"""Back-dated plan test: "would the plan actually have made money?"

1. Pretend today is the day after the forecast holdout starts (e.g. 11 Aug 2026).
2. Re-fit every model using ONLY data available before that date, build candidates for the
   next 12 travel weeks and solve the same budget allocation (plus the two baselines).
3. Replay the plans against what really happened in those weeks:
     - real demand (ground-truth demand, adjusted for the plan's own selling price),
     - real cancellation rates,
     - the supplier's real quote at the chosen lead time.
   and compare realised profit with what the plan predicted.
"""
import numpy as np
import pandas as pd

from .config import COMPETITIVE_ELASTICITY, LEAD_OPTIONS
from . import models as M
from .candidates import build_candidates, season_proxy_from
from .optimizer import Optimizer
from .suppliers import supplier_scorecard


def _realise(opt: Optimizer, k_sel, items, truth, daily, quotes, sup_truth=None):
    it = items.set_index("item_id")
    tw = truth.assign(week=truth.date - pd.to_timedelta(truth.date.dt.dayofweek, unit="D")) \
        .groupby(["item_id", "week"]).true_demand.sum()
    dw = daily.assign(week=daily.date - pd.to_timedelta(daily.date.dt.dayofweek, unit="D")) \
        .groupby(["item_id", "week"])[["bookings", "cancellations"]].sum()
    q = quotes.set_index(["item_id", "travel_week_start", "lead_days"]).cost_multiplier
    st = sup_truth.set_index(["item_id", "supplier_id"]) if sup_truth is not None else None
    rows = []
    for i, k in enumerate(k_sel):
        if k <= 0:
            continue
        c, b = opt.cands.iloc[i], opt.blocks[i]
        week = pd.Timestamp(c.week)
        Q = float(b["levels"][k])
        p = float(c.sell_price)
        e_true = float(it.loc[c.item_id, "elasticity"]) if "elasticity" in it else float(c.elasticity)
        D = float(tw.get((c.item_id, week), 0.0)) * float(c.price_mult) ** (-(e_true + COMPETITIVE_ELASTICITY))
        bk = dw.loc[(c.item_id, week)] if (c.item_id, week) in dw.index else None
        cr = float(bk.cancellations / bk.bookings) if bk is not None and bk.bookings > 0 else float(c.cancel_rate)
        lead = min(LEAD_OPTIONS, key=lambda l: abs(l - int(c.buy_lead_days)))
        ref = float(it.loc[c.item_id, "ref_price"])
        mult = q.get((c.item_id, week, lead), np.nan)
        bench = float(mult * ref) if not np.isnan(mult) else float(c.unit_cost)
        late = q.get((c.item_id, week, min(LEAD_OPTIONS)), np.nan)
        c_wait = float(late * ref) if not np.isnan(late) else bench
        if st is not None and isinstance(c.get("supplier_id"), str) and (c.item_id, c.supplier_id) in st.index:
            tr = st.loc[(c.item_id, c.supplier_id)]       # the supplier's TRUE behaviour, unknown to the planner
            c_s, rel, refund = bench * float(tr.price_index), float(tr.reliability), float(tr.refund_rate)
        else:
            c_s, rel, refund = bench, 1.0, float(c.salvage_rate)
        cost_total = c_s * Q + (1 - rel) * Q * max(c_wait - c_s, 0.0)   # unconfirmed units re-bought late
        cost = cost_total / Q
        S = min(Q, D)
        realised = p * (S - S * cr) + refund * c_s * (Q - S) - cost_total
        rows.append(dict(cand_id=c.cand_id, item_id=c.item_id, name=c["name"], destination=c.destination, week=c.week,
                         units=Q, invested_planned=Q * float(c.unit_cost), invested_actual=Q * cost,
                         predicted_profit=float(b["profit_levels"][:, k].mean()), realised_profit=realised,
                         predicted_demand=float(c.demand_p50), actual_demand=D, sold=S, cancel_rate_actual=cr))
    return pd.DataFrame(rows)


def _summ(df):
    if df.empty:
        return dict(positions=0)
    return dict(
        positions=int(len(df)), invested=round(float(df.invested_actual.sum()), 0),
        predicted_profit=round(float(df.predicted_profit.sum()), 0), realised_profit=round(float(df.realised_profit.sum()), 0),
        realised_roi=round(float(df.realised_profit.sum() / df.invested_actual.sum()), 4),
        units=int(df.units.sum()), units_sold=int(round(df.sold.sum())),
        sell_through=round(float(df.sold.sum() / df.units.sum()), 4),
        loss_making_positions=int((df.realised_profit < 0).sum()),
        prediction_gap=round(float(df.realised_profit.sum() / df.predicted_profit.sum() - 1), 4),
    )


def run_plan_backtest(items, cal, d, feat, quotes, truth, daily, fc_holdout, as_of, n_weeks=12,
                      budget=75e7, lam=0.3, max_dest_share=0.30, sup=None, sup_hist=None, sup_truth=None, log=print):
    as_of = pd.Timestamp(as_of)
    d_hist = d[d.date < as_of]
    feat_hist = feat[feat.date < as_of]
    horizon_start = as_of + pd.Timedelta(days=(7 - as_of.dayofweek) % 7 or 7)

    el, price_idx = M.estimate_elasticity(feat_hist, items)
    sp = season_proxy_from(feat_hist)
    cmodel = M.fit_cancel_model(feat_hist)
    qf = M.rate_frame(quotes, items, cal, sp)
    rmodel = M.fit_rate_model(qf[qf.week < as_of])
    pmodel = M.fit_price_model(feat_hist)

    cands, blocks, _ = build_candidates(items, cal, d_hist, feat_hist, fc_holdout, cmodel, rmodel, el, price_idx, sp,
                                        as_of, horizon_start, n_weeks, pmodel=pmodel,
                                        scorecard=supplier_scorecard(sup, sup_hist, as_of) if sup is not None else None)
    opt = Optimizer(cands, blocks)
    log(f"plan back-test: {int(cands.viable.sum())} viable candidates as of {as_of.date()}")

    res = opt.solve(budget, lam=lam, max_dest_share=max_dest_share)
    ai = _realise(opt, res["k_sel"], items, truth, daily, quotes, sup_truth)
    opt.greedy(budget)
    gr = _realise(opt, opt.last_k, items, truth, daily, quotes, sup_truth)
    opt.last_year(budget)
    ly = _realise(opt, opt.last_k, items, truth, daily, quotes, sup_truth)

    weekly = ai.groupby("week").agg(predicted_profit=("predicted_profit", "sum"), realised_profit=("realised_profit", "sum"),
                                    invested=("invested_actual", "sum")).reset_index()
    out = dict(
        as_of=str(as_of.date()), horizon_start=str(horizon_start.date()),
        horizon_end=str((horizon_start + pd.Timedelta(weeks=n_weeks) - pd.Timedelta(days=1)).date()),
        weeks=n_weeks, budget=budget, risk_aversion=lam,
        ai=_summ(ai), greedy=_summ(gr), last_year=_summ(ly),
        weekly=weekly.round(0).to_dict("records"),
        top_positions=ai.sort_values("realised_profit", ascending=False).head(8).round(1).to_dict("records"),
        worst_positions=ai.sort_values("realised_profit").head(5).round(1).to_dict("records"),
    )
    log(f"plan back-test result: AI {out['ai']} | greedy {out['greedy']} | last-year {out['last_year']}")
    return out
