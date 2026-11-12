"""FastAPI backend for the TBO Inventory Optimization platform.

Run:  uvicorn app:app --reload --port 8000     (from the backend/ folder)
If frontend/dist exists (npm run build), the dashboard is also served at http://localhost:8000
"""
import json
import pickle
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipeline.config import ART_DIR
from pipeline.optimizer import Optimizer
from pipeline.explain import template_explanation, explanation_sections, llm_explanation
from pipeline import whatif, verify, ingest
from pipeline.suppliers import supplier_summary, validation_payload

if not (ART_DIR / "candidates.pkl").exists():
    raise SystemExit("Artifacts missing. Run:  python -m pipeline.generate_data && python -m pipeline.train")

with open(ART_DIR / "candidates.pkl", "rb") as f:
    _c = pickle.load(f)
with open(ART_DIR / "series.pkl", "rb") as f:
    SERIES = pickle.load(f)
SUMMARY = json.loads((ART_DIR / "summary.json").read_text())
ITEMS = pd.read_csv(ART_DIR / "items_enriched.csv").fillna({"origin": ""})
CANDS: pd.DataFrame = _c["cands"]
BLOCKS = _c["blocks"]
OPT = Optimizer(CANDS, BLOCKS)
SCORECARD = pd.read_csv(ART_DIR / "supplier_scorecard.csv")
SUPPLIERS = SCORECARD.drop_duplicates("supplier_id")[["supplier_id", "supplier", "item_type"]].reset_index(drop=True)
_BASE_CACHE = {}


def clean(o):
    """Make numpy / pandas values JSON serialisable."""
    return json.loads(json.dumps(o, default=lambda x: x.item() if hasattr(x, "item") else
                                 (x.tolist() if hasattr(x, "tolist") else str(x))),
                      parse_constant=lambda c: None)   # NaN / inf -> null


app = FastAPI(title="TBO Inventory Optimizer API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=2000)


class OptimizeReq(BaseModel):
    budget: float = Field(75e7, gt=0, description="Maximum budget in INR")
    risk_aversion: float = Field(0.3, ge=0, le=1, description="0 = maximise expected profit, 1 = maximise worst-case")
    max_dest_share: float = Field(0.30, gt=0, le=1, description="Max share of budget in one destination")
    item_types: List[str] = ["Hotel", "Flight"]
    destinations: Optional[List[str]] = None


class ScenarioReq(OptimizeReq):
    shocks: List[dict] = Field(default_factory=list, description="list of {kind, change, destination?, item_type?, item_id?, supplier_id?}")
    current_plan: Optional[List[dict]] = Field(None, description="plan currently in force (rows from a previous response); "
                                                                 "defaults to the plan optimised before any shock")
    min_gain_share: float = Field(0.005, ge=0, le=0.5, description="re-plan only if expected profit improves by this share")


def _kw(req):
    return dict(item_types=tuple(req.item_types), destinations=req.destinations)


def _base(req):
    """Base plan for these settings (cached): the plan before any shock."""
    key = (req.budget, req.risk_aversion, req.max_dest_share, tuple(req.item_types), tuple(req.destinations or ()))
    if key not in _BASE_CACHE:
        if len(_BASE_CACHE) > 32:
            _BASE_CACHE.clear()
        _BASE_CACHE[key] = OPT.solve(req.budget, lam=req.risk_aversion, max_dest_share=req.max_dest_share, **_kw(req))
    return _BASE_CACHE[key]


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/summary")
def summary():
    v = CANDS[CANDS.viable]
    heat = (CANDS.groupby(["destination", "week"]).agg(demand=("demand_p50", "sum"), sold_out_risk=("sold_out_risk", "mean"),
            opportunity=("opportunity_score", "mean")).reset_index())
    return clean(dict(
        **SUMMARY,
        destinations=sorted(CANDS.destination.unique().tolist()),
        weeks=sorted(CANDS.week.unique().tolist()),
        heatmap=heat.round(3).to_dict("records"),
        full_plan_cost=float(sum(b["block_cost"].sum() for b in OPT.blocks)),
        avg_roi=float(v.roi_at_qstar.mean()),
        high_risk_windows=int((CANDS.sold_out_risk >= 0.5).sum()),
    ))


@app.get("/api/items")
def items():
    return clean(ITEMS.to_dict("records"))


@app.get("/api/opportunities")
def opportunities(limit: int = 40, item_type: Optional[str] = None, destination: Optional[str] = None):
    v = CANDS[CANDS.viable]
    if item_type:
        v = v[v.item_type == item_type]
    if destination:
        v = v[v.destination == destination]
    cols = ["cand_id", "item_id", "name", "item_type", "destination", "tier", "week", "demand_p10", "demand_p50", "demand_p90",
            "market_price", "sell_price", "unit_cost", "cost_if_wait", "buy_by", "q_star", "sold_out_risk", "cancel_rate",
            "roi_at_qstar", "opportunity_score", "events", "drivers"]
    return clean(v.sort_values("opportunity_score", ascending=False).head(limit)[cols].to_dict("records"))


@app.post("/api/optimize")
def optimize(req: OptimizeReq):
    kw = dict(item_types=tuple(req.item_types), destinations=req.destinations)
    res = OPT.solve(req.budget, lam=req.risk_aversion, max_dest_share=req.max_dest_share, **kw)
    res.pop("k_sel")
    greedy = OPT.greedy(req.budget, **kw)
    last = OPT.last_year(req.budget, **kw)
    for s in (greedy, last):
        s.pop("histogram")
    res["baselines"] = dict(greedy_roi_ranking=greedy, last_year_proportional=last)
    return clean(res)


@app.post("/api/scenario")
def scenario(req: ScenarioReq):
    """What-if simulation / re-planning: apply shocks, re-optimise, compare with keeping the current plan."""
    base = _base(req)
    solve_kw = dict(budget=req.budget, lam=req.risk_aversion, max_dest_share=req.max_dest_share, **_kw(req))
    current = req.current_plan or base["plan"]
    known = set(CANDS.cand_id)
    current = [r for r in current if r.get("cand_id") in known and r.get("units", 0) > 0]
    rp = whatif.replan(CANDS, BLOCKS, current, req.shocks, solve_kw, min_gain_share=req.min_gain_share)
    rp.pop("optimizer")
    res = rp.pop("result")
    return clean(dict(rp, stats=res["stats"], plan=res["plan"], by_destination=res["by_destination"],
                      by_type=res["by_type"], by_week=res["by_week"], unused_budget=res.get("unused_budget"),
                      base_stats=base["stats"], shocks=req.shocks))


@app.get("/api/signals/next")
def next_signal(seq: int = 0):
    """Next incoming market signal for the automated re-planning demo (simulated)."""
    return clean(whatif.sample_signal(seq, CANDS.destination.unique(), SUPPLIERS))


@app.get("/api/suppliers")
def suppliers():
    return clean(dict(supplier_summary(SCORECARD, CANDS), model=SUMMARY.get("supplier_scorecard_model")))


@app.get("/api/validation")
def validation():
    return clean(validation_payload(SUMMARY, SERIES.get("validation")))


@app.post("/api/verify")
def verify_plan(req: OptimizeReq):
    res = OPT.solve(req.budget, lam=req.risk_aversion, max_dest_share=req.max_dest_share, **_kw(req))
    share = max(req.max_dest_share, 1.0 / max(len(req.destinations or CANDS.destination.unique()), 1))
    return clean(verify.run_all(OPT, res, req.budget, req.risk_aversion, share,
                                SUMMARY["forecast_backtest"].get("table"), SERIES.get("validation")))


@app.get("/api/data/contract")
def data_contract():
    return clean(dict(source=SUMMARY.get("data_source", "synthetic"), tables=ingest.contract()))


class ValidateReq(BaseModel):
    kind: str
    csv: str = Field(..., max_length=8_000_000)


@app.post("/api/data/validate")
def data_validate(req: ValidateReq):
    if req.kind not in ingest.SCHEMAS:
        raise HTTPException(400, f"kind must be one of {list(ingest.SCHEMAS)}")
    return clean(ingest.validate_csv_text(req.csv, req.kind))


@app.post("/api/frontier")
def frontier(req: OptimizeReq):
    kw = dict(item_types=tuple(req.item_types), destinations=req.destinations, max_dest_share=req.max_dest_share)
    return clean(OPT.frontier(req.budget, **kw))


@app.post("/api/budget-curve")
def budget_curve(req: OptimizeReq):
    kw = dict(item_types=tuple(req.item_types), destinations=req.destinations, max_dest_share=req.max_dest_share)
    budgets = [req.budget * f for f in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)]
    return clean(OPT.budget_curve(budgets, lam=req.risk_aversion, **kw))


@app.get("/api/forecast/{item_id}")
def forecast(item_id: str):
    if item_id not in set(ITEMS.item_id):
        raise HTTPException(404, "unknown item")
    h = SERIES["history"]
    h = h[h.item_id == item_id].copy()
    f = SERIES["forecast"]
    f = f[f.item_id == item_id].copy()
    h["date"], f["date"] = h.date.dt.strftime("%Y-%m-%d"), f.date.dt.strftime("%Y-%m-%d")
    weeks = CANDS[CANDS.item_id == item_id]
    item = ITEMS[ITEMS.item_id == item_id].iloc[0].to_dict()
    return clean(dict(item=item, history=h.round(2).to_dict("records"), forecast=f.round(2).to_dict("records"),
                      weeks=weeks.drop(columns=[c for c in ["price_mult"] if c in weeks]).to_dict("records")))


@app.post("/api/explain")
def explain(row: dict):
    try:
        text = template_explanation(row)
    except KeyError as e:
        raise HTTPException(400, f"missing field {e}")
    return {"explanation": text, "sections": explanation_sections(row), "llm": llm_explanation(row)}


# ---------------- serve the built dashboard ----------------
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST.resolve() in f.parents:   # favicon, architecture.png, site data, ...
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
