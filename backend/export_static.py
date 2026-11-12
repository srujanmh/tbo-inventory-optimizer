"""Export everything the static website needs (no Python server required).

Run after training:   python export_static.py
Writes frontend/public/site/data.json   (summary, items, forecasts, candidates, quantity blocks)
       frontend/public/site/scen.json   (base64 Int16 scenario profits in ₹ thousands, per candidate x level x scenario)
The browser re-runs the budget optimization itself (see frontend/src/engine.js).
"""
import base64
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.config import ART_DIR
from pipeline.optimizer import Optimizer
from pipeline.suppliers import supplier_summary, validation_payload
from pipeline import verify, ingest

N_SCEN_WEB = 300   # scenario subset shipped to the browser
OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "site"


def clean(o):
    return json.loads(json.dumps(o, default=lambda x: x.item() if hasattr(x, "item") else
                                 (x.tolist() if hasattr(x, "tolist") else str(x))), parse_constant=lambda c: None)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    c = pickle.load(open(ART_DIR / "candidates.pkl", "rb"))
    cands, blocks = c["cands"], c["blocks"]
    series = pickle.load(open(ART_DIR / "series.pkl", "rb"))
    summary = json.loads((ART_DIR / "summary.json").read_text())
    items = pd.read_csv(ART_DIR / "items_enriched.csv").fillna({"origin": ""})

    heat = (cands.groupby(["destination", "week"]).agg(demand=("demand_p50", "sum"), sold_out_risk=("sold_out_risk", "mean"),
            opportunity=("opportunity_score", "mean")).reset_index())
    v = cands[cands.viable]
    summary.update(destinations=sorted(cands.destination.unique().tolist()), weeks=sorted(cands.week.unique().tolist()),
                   heatmap=heat.round(3).to_dict("records"), avg_roi=float(v.roi_at_qstar.mean()),
                   full_plan_cost=float(sum(b["block_cost"].sum() for b in blocks if b.get("viable", True))),
                   high_risk_windows=int((cands.sold_out_risk >= 0.5).sum()), n_scenarios_web=N_SCEN_WEB)

    # forecasts: compact per item
    h, f = series["history"].copy(), series["forecast"].copy()
    h = h[h.date > h.date.max() - pd.Timedelta(days=120)]
    fc = {}
    for iid in items.item_id:
        hh, ff = h[h.item_id == iid], f[f.item_id == iid]
        fc[iid] = dict(
            history=[[d.strftime("%Y-%m-%d"), int(b), round(float(e), 1), int(s)] for d, b, e, s in
                     zip(hh.date, hh.bookings, hh.demand_est, hh.sold_out)],
            forecast=[[d.strftime("%Y-%m-%d"), round(float(a), 1), round(float(b), 1), round(float(c_), 1), round(float(r), 3)]
                      for d, a, b, c_, r in zip(ff.date, ff.p10, ff.p50, ff.p90, ff.cancel_rate)])

    # quantity blocks + scenario profits (int16, ₹ thousands)
    bmap = {b["cand_id"]: b for b in blocks}
    blk, chunks, offset = {}, [], 0
    for cid in v.cand_id:
        b = bmap[cid]
        pl = b["profit_levels"][:N_SCEN_WEB, :]                      # scen x levels
        q = np.clip(np.round(pl / 1000.0), -32767, 32767).astype("<i2").T  # levels x scen
        chunks.append(q.tobytes())
        blk[cid] = dict(levels=b["levels"].astype(int).tolist(), cost=float(b["block_cost"][0]),
                        sold=[round(float(x), 1) for x in b["exp_sold_levels"]], offset=offset)
        offset += q.size
    # shipped as base64 inside JSON so any static host / artifact server will serve it
    (OUT / "scen.json").write_text(json.dumps({"dtype": "int16-le", "unit": 1000, "b64": base64.b64encode(b"".join(chunks)).decode()}))
    (OUT / "scen.bin").unlink(missing_ok=True)

    keep = ["cand_id", "item_id", "name", "item_type", "destination", "tier", "unit", "week", "demand_p10", "demand_p50",
            "demand_p90", "market_price", "sell_price", "unit_cost", "cost_if_wait", "buy_by", "q_star", "sold_out_risk",
            "cancel_rate", "roi_at_qstar", "opportunity_score", "last_year_revenue", "events", "drivers", "viable",
            "supplier", "supplier_id", "supplier_cost", "supplier_reliability", "suppliers", "price_mult", "critical_ratio",
            "salvage_rate", "elasticity", "buy_lead_days", "max_allotment"]
    # read-only extras for the Suppliers, Accuracy and Data tabs; verification is run on the server MILP plan
    opt = Optimizer(cands, blocks)
    res = opt.solve(75e7, lam=0.3, max_dest_share=0.3)
    ver = verify.run_all(opt, res, 75e7, 0.3, 0.3, summary["forecast_backtest"].get("table"), series.get("validation"))
    ver["note"] = "Checked on the server-side MILP plan at the default settings (₹75 Cr, balanced risk, 30% cap)."
    sc = pd.read_csv(ART_DIR / "supplier_scorecard.csv")
    extra = dict(suppliers=dict(supplier_summary(sc, cands), model=summary.get("supplier_scorecard_model")),
                 validation=validation_payload(summary, series.get("validation")),
                 contract=dict(source=summary.get("data_source", "synthetic"), tables=ingest.contract()), verification=ver)
    data = dict(summary=summary, items=items.to_dict("records"), forecasts=fc,
                cands=cands[keep].to_dict("records"), blocks=blk, extra=extra)
    (OUT / "data.json").write_text(json.dumps(clean(data), separators=(",", ":")))
    print(f"data.json {(OUT / 'data.json').stat().st_size / 1e6:.2f} MB, scen.json {(OUT / 'scen.json').stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
