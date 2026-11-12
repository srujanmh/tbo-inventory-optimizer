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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipeline.config import ART_DIR
from pipeline.optimizer import Optimizer
from pipeline.explain import template_explanation, llm_explanation

if not (ART_DIR / "candidates.pkl").exists():
    raise SystemExit("Artifacts missing. Run:  python -m pipeline.generate_data && python -m pipeline.train")

with open(ART_DIR / "candidates.pkl", "rb") as f:
    _c = pickle.load(f)
with open(ART_DIR / "series.pkl", "rb") as f:
    SERIES = pickle.load(f)
SUMMARY = json.loads((ART_DIR / "summary.json").read_text())
ITEMS = pd.read_csv(ART_DIR / "items_enriched.csv").fillna({"origin": ""})
CANDS: pd.DataFrame = _c["cands"]
OPT = Optimizer(CANDS, _c["blocks"])


def clean(o):
    """Make numpy / pandas values JSON serialisable."""
    return json.loads(json.dumps(o, default=lambda x: x.item() if hasattr(x, "item") else
                                 (x.tolist() if hasattr(x, "tolist") else str(x))),
                      parse_constant=lambda c: None)   # NaN / inf -> null


app = FastAPI(title="TBO Inventory Optimizer API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class OptimizeReq(BaseModel):
    budget: float = Field(75e7, gt=0, description="Maximum budget in INR")
    risk_aversion: float = Field(0.3, ge=0, le=1, description="0 = maximise expected profit, 1 = maximise worst-case")
    max_dest_share: float = Field(0.30, gt=0, le=1, description="Max share of budget in one destination")
    item_types: List[str] = ["Hotel", "Flight"]
    destinations: Optional[List[str]] = None


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
    return {"explanation": text, "llm": llm_explanation(row)}


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
