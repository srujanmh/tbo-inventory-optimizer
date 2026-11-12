"""End-to-end training pipeline. Run:  python -m pipeline.train
Writes everything the API needs into backend/artifacts/."""
import json
import pickle
import time

import numpy as np
import pandas as pd

from .config import (ART_DIR, DATA_DIR, TODAY, HIST_END, HORIZON_START, HORIZON_END, HORIZON_WEEKS,
                     LEAD_OPTIONS, N_SCENARIOS, SEED)
from . import models as M
from .candidates import build_candidates, season_proxy_from
from .plan_backtest import run_plan_backtest


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:6.1f}s] {msg}", flush=True)


def run():
    ART_DIR.mkdir(parents=True, exist_ok=True)
    items, cal, daily, quotes = M.load_data()
    log(f"loaded {len(items)} items, {len(daily):,} daily rows")

    # ---------------- 1. Unconstrain demand ----------------
    d = M.unconstrain(daily)
    truth = pd.read_csv(DATA_DIR / "_ground_truth.csv", parse_dates=["date"])
    chk = d.merge(truth, on=["date", "item_id"])
    so = chk[chk.sold_out == 1]
    unconstrain_metrics = dict(
        sold_out_day_share=round(float(d.sold_out.mean()), 4),
        hidden_demand_true=int((so.true_demand - so.bookings).sum()),
        hidden_demand_recovered=int((so.demand_est - so.bookings).sum()),
        sold_out_day_error_bookings=round(float(np.abs(so.bookings - so.true_demand).sum() / so.true_demand.sum()), 4),
        sold_out_day_error_unconstrained=round(float(np.abs(so.demand_est - so.true_demand).sum() / so.true_demand.sum()), 4),
    )
    log(f"unconstrained demand: {unconstrain_metrics}")

    # ---------------- 2. Features + forecast ----------------
    feat = M.build_features(d, items, cal, d)
    metrics, calib, fc_holdout = M.backtest(feat, HIST_END, truth)
    log(f"forecast backtest: {metrics}")
    fc = M.DemandForecaster().fit(feat)
    fc.s_daily, fc.k_weekly = calib["s_daily"], calib["k_weekly"]
    log("fitted daily + weekly forecasters on full history")

    # ---------------- 3. Cancellation model ----------------
    cut = HIST_END - pd.Timedelta(days=91)
    cancel_metrics = M.score_cancel_model(feat, cut)
    log(f"cancellation model: {cancel_metrics}")
    cmodel = M.fit_cancel_model(feat)

    # ---------------- 4. Elasticity & price index ----------------
    el, price_idx = M.estimate_elasticity(feat, items)
    el_chk = el.merge(items[["item_id", "elasticity"]])
    elasticity_metrics = dict(mae=round(float(np.abs(el_chk.elasticity_est - el_chk.elasticity).mean()), 3),
                              bias=round(float((el_chk.elasticity_est - el_chk.elasticity).mean()), 3),
                              corr=round(float(np.corrcoef(el_chk.elasticity_est, el_chk.elasticity)[0, 1]), 3),
                              mae_previous_method=0.308)
    log(f"elasticity: {elasticity_metrics}")
    season_proxy = season_proxy_from(feat)

    # ---------------- 5. Supplier-rate model (buy timing) ----------------
    qf = M.rate_frame(quotes, items, cal, season_proxy)
    rate_metrics = M.score_rate_model(qf, cut)
    log(f"supplier-rate model: {rate_metrics}")
    rmodel = M.fit_rate_model(qf)

    # ---------------- 5b. Market price model ----------------
    price_metrics = M.score_price_model(feat, cut)
    log(f"price model: {price_metrics}")
    pmodel = M.fit_price_model(feat)

    # ---------------- 6. Build candidates (item x week) for the live plan ----------------
    cands, blocks, hz = build_candidates(items, cal, d, feat, fc, cmodel, rmodel, el, price_idx, season_proxy,
                                         TODAY, HORIZON_START, HORIZON_WEEKS, pmodel=pmodel)
    log(f"built {len(cands)} candidates ({int(cands.viable.sum())} viable)")

    # ---------------- 6b. Back-dated plan test ----------------
    plan_bt = run_plan_backtest(items, cal, d, feat, quotes, truth, daily, fc_holdout,
                                as_of=cut + pd.Timedelta(days=1), n_weeks=12, log=log)

    # ---------------- 7. Persist ----------------
    feat["item_id_s"] = feat.item_id.astype(str)
    hist_out = feat[feat.date > HIST_END - pd.Timedelta(days=200)][
        ["date", "item_id_s", "bookings", "demand_est", "sold_out", "searches", "avg_sell_price"]].rename(columns={"item_id_s": "item_id"})
    fc_out = hz[["date", "item_id_s", "p10", "p50", "p90", "cancel_rate"]].rename(columns={"item_id_s": "item_id"})
    importance = fc.importance()

    with open(ART_DIR / "candidates.pkl", "wb") as f:
        pickle.dump(dict(cands=cands, blocks=blocks), f)
    with open(ART_DIR / "series.pkl", "wb") as f:
        pickle.dump(dict(history=hist_out, forecast=fc_out), f)
    items.merge(el, on="item_id", how="left").to_csv(ART_DIR / "items_enriched.csv", index=False)
    summary = dict(
        generated_at=str(pd.Timestamp.now().round("s")), today=str(TODAY.date()),
        history=dict(start=str(feat.date.min().date()), end=str(HIST_END.date()), rows=int(len(feat))),
        horizon=dict(start=str(HORIZON_START.date()), end=str(HORIZON_END.date()), weeks=HORIZON_WEEKS),
        n_items=int(len(items)), n_candidates=int(len(cands)), n_viable=int(cands.viable.sum()),
        forecast_backtest=metrics, unconstraining=unconstrain_metrics,
        cancellation_model=cancel_metrics, supplier_rate_model=rate_metrics, price_model=price_metrics,
        elasticity=elasticity_metrics, elasticity_mae=elasticity_metrics["mae"], driver_importance=importance,
        total_capacity_cost=float(sum(b["block_cost"].sum() for b in blocks)),
        plan_backtest=plan_bt,
    )
    with open(ART_DIR / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    log("artifacts written")


if __name__ == "__main__":
    run()
