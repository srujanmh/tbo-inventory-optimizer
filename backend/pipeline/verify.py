"""Independent verification of the numbers the product shows.

Every check recomputes a figure from first principles (not by calling the code that produced it)
and compares. Used by tests/test_math.py, by the training pipeline (stored in summary.json) and
by the /api/verify endpoint, which re-checks a live plan.
"""
import numpy as np

from .config import COMPETITIVE_ELASTICITY
from .simulate import lognormal_draws
from . import models as M


def _check(name, passed, detail, group):
    return dict(name=name, passed=bool(passed), detail=detail, group=group)


def plan_checks(opt, res, budget, lam, share):
    out = []
    plan, st = res["plan"], res["stats"]
    tol_rupees = 1.0 * len(plan) + 1

    inv_rows = sum(r["investment"] for r in plan)
    blk = {c: b for c, b in zip(opt.cands.cand_id, opt.blocks)}
    inv_blocks = 0.0
    for r in plan:
        b = blk[r["cand_id"]]
        k = int(np.searchsorted(b["levels"], r["units"]))
        inv_blocks += float(b["block_cost"][:k].sum())
    out.append(_check("Budget respected", st["invested"] <= budget * (1 + 1e-9),
                      f"invested {st['invested']:,.0f} <= budget {budget:,.0f}", "Budget"))
    out.append(_check("Investment adds up", abs(inv_blocks - st["invested"]) <= tol_rupees and
                      abs(inv_rows - st["invested"]) <= 0.5 * st["units"] + tol_rupees,
                      f"sum of positions {inv_rows:,.0f} vs total {st['invested']:,.0f}", "Budget"))
    by_dest = {}
    for r in plan:
        by_dest[r["destination"]] = by_dest.get(r["destination"], 0.0) + r["investment"]
    worst = max(by_dest.values()) if by_dest else 0
    out.append(_check("Destination cap respected", worst <= share * budget + tol_rupees + 0.5 * st["units"],
                      f"largest destination {worst:,.0f} <= cap {share * budget:,.0f}", "Budget"))
    if "unused_budget" in res:
        u = res["unused_budget"]["unused"]
        out.append(_check("Unused budget = budget - invested", abs(u - (budget - st["invested"])) <= 1,
                          f"{u:,.0f}", "Budget"))

    # independent profit recomputation from the raw scenario inputs
    total = np.zeros(opt.n_scen)
    worst_rel = 0.0
    sold = units = 0.0
    for r in plan:
        b = blk[r["cand_id"]]
        c = opt.cands.set_index("cand_id").loc[r["cand_id"]]
        Q = float(r["units"])
        if "z" in b:
            e = b["econ"]
            o = next(x for x in b["options"] if x["supplier_id"] == c.supplier_id)
            D = lognormal_draws(e["median"], e["sigma"], b["z"].astype(float)) * float(c.price_mult) ** (-(e["elasticity"] + COMPETITIVE_ELASTICITY))
            p, cost, salv, cr = e["market_price"] * float(c.price_mult), o["_unit_cost"], o["_salvage"], e["cancel_rate"]
        else:
            D, p, cost, salv, cr = b["D"].astype(float), float(c.sell_price), float(c.unit_cost), float(c.salvage_rate), float(c.cancel_rate)
        S = np.minimum(Q, D)
        prof = p * (S - S * cr) + salv * cost * (Q - S) - cost * Q        # textbook newsvendor P&L
        k = int(np.searchsorted(b["levels"], Q))
        stored = b["profit_levels"][:, k].astype(float)
        rel = abs(prof.mean() - stored.mean()) / max(abs(stored.mean()), 1.0)
        worst_rel = max(worst_rel, rel)
        total += prof
        sold += S.mean()
        units += Q
    out.append(_check("Position profits recomputed from scratch", worst_rel < 1e-3,
                      f"max relative difference {worst_rel:.2e} over {len(plan)} positions", "Profit"))
    exp_sum = sum(r["expected_profit"] for r in plan)
    out.append(_check("Expected profit = sum of positions", abs(exp_sum - st["expected_profit"]) <= max(tol_rupees, 2e-4 * abs(exp_sum)),
                      f"{exp_sum:,.0f} vs {st['expected_profit']:,.0f}", "Profit"))
    out.append(_check("Portfolio expected profit (independent)", abs(total.mean() - st["expected_profit"]) <= 1e-3 * abs(st["expected_profit"]) + 1,
                      f"{total.mean():,.0f} vs {st['expected_profit']:,.0f}", "Profit"))
    out.append(_check("ROI = profit / investment", abs(st["roi"] - st["expected_profit"] / st["invested"]) < 1e-3 if st["invested"] else True,
                      f"{st['roi']:.4f}", "Profit"))

    srt = np.sort(total)
    n10, n5 = max(1, int(0.1 * opt.n_scen)), max(1, int(0.05 * opt.n_scen))
    cvar, p5, pl = srt[:n10].mean(), srt[n5 - 1], (total < 0).mean()
    tol = 2e-3 * abs(st["expected_profit"]) + 1
    out.append(_check("Worst-10% profit (CVaR) recomputed", abs(cvar - st["cvar10"]) <= tol, f"{cvar:,.0f} vs {st['cvar10']:,.0f}", "Risk"))
    out.append(_check("5th-percentile profit recomputed", abs(p5 - st["p5"]) <= tol, f"{p5:,.0f} vs {st['p5']:,.0f}", "Risk"))
    out.append(_check("Probability of loss recomputed", abs(pl - st["prob_loss"]) <= 0.002, f"{pl:.4f} vs {st['prob_loss']:.4f}", "Risk"))
    out.append(_check("Profit spread (std) recomputed", abs(total.std() - st["profit_std"]) <= tol, f"{total.std():,.0f}", "Risk"))

    out.append(_check("Units add up", sum(r["units"] for r in plan) == st["units"], f"{st['units']:,} units", "Inventory"))
    ok_st = all(r["expected_sold"] <= r["units"] + 1e-6 and 0 <= r["sell_through"] <= 1 for r in plan)
    out.append(_check("Expected sales never exceed units bought", ok_st, "sell-through within 0-100% for every position", "Inventory"))
    out.append(_check("Portfolio sell-through recomputed", abs(sold / units - st["sell_through"]) < 2e-3 if units else True,
                      f"{sold / units if units else 0:.4f} vs {st['sell_through']:.4f}", "Inventory"))
    ok_blocks = all(np.all(np.diff(b["levels"]) > 0) and np.allclose(b["block_cost"], np.diff(b["levels"]) * b["block_cost"][0] / max(b["levels"][1], 1))
                    for b in opt.blocks)
    out.append(_check("Quantity blocks consistent", ok_blocks, "levels increase; block cost = units x unit cost", "Inventory"))

    # newsvendor quantity: Q* is the critical-ratio quantile of demand at the chosen price
    nv_err = 0.0
    for c, b in list(zip(opt.cands.itertuples(), opt.blocks))[:200]:
        if c.q_star >= c.max_allotment - 0.6 or "D" not in b:
            continue
        Dd = b["D"].astype(float)   # critical ratio is stored to 3 decimals: compare with the bracket it rounds from
        lo = float(np.quantile(Dd, max(c.critical_ratio - 0.0005, 0)))
        hi = float(np.quantile(Dd, min(c.critical_ratio + 0.0005, 1)))
        err = 0.0 if lo * 0.99 <= c.q_star <= hi * 1.01 else min(abs(c.q_star - lo), abs(c.q_star - hi)) / max(c.q_star, 1)
        nv_err = max(nv_err, err)
    out.append(_check("Newsvendor quantities (critical-ratio quantile)", nv_err < 0.01, f"max relative error {nv_err:.2e}", "Inventory"))

    # optimality: the MILP must beat greedy on its own objective and sit close to the LP bound
    scores = opt.risk_scores(lam)
    k_sel = np.zeros(len(opt.cands), int)
    idx = {c: i for i, c in enumerate(opt.cands.cand_id)}
    for r in plan:
        i = idx[r["cand_id"]]
        k_sel[i] = int(np.searchsorted(opt.blocks[i]["levels"], r["units"]))
    obj = sum(float(scores[i][:k].sum()) for i, k in enumerate(k_sel) if k > 0)
    opt.greedy(budget)
    g_obj = sum(float(scores[i][:k].sum()) for i, k in enumerate(opt.last_k) if k > 0)
    out.append(_check("Optimizer beats greedy on its objective", obj >= g_obj - 1, f"{obj:,.0f} vs greedy {g_obj:,.0f}", "Optimality"))
    lp = opt.solve(budget, lam=lam, max_dest_share=share, relax=True, time_limit=20)
    gap = (lp["objective"] - obj) / max(abs(lp["objective"]), 1)
    out.append(_check("Within 1% of the theoretical best (LP bound)", gap <= 0.01, f"gap {gap:.3%}", "Optimality"))
    return out


def forecast_checks(table, validation):
    out = []
    if not validation:
        return out
    y = np.array([r["y"] for r in validation], float)
    p = np.array([r["median"] for r in validation], float)
    wm = table["weekly_model"]
    w = np.abs(p - y).sum() / y.sum()
    out.append(_check("Weekly WAPE recomputed", abs(w - wm["wape"]) < 1e-3, f"{w:.4f} vs {wm['wape']:.4f}", "Forecast"))
    out.append(_check("Weekly MAE recomputed", abs(np.abs(p - y).mean() - wm["mae"]) < 0.05, f"{np.abs(p - y).mean():.2f}", "Forecast"))
    out.append(_check("Weekly RMSE recomputed", abs(np.sqrt(((p - y) ** 2).mean()) - wm["rmse"]) < 0.05,
                      f"{np.sqrt(((p - y) ** 2).mean()):.2f}", "Forecast"))
    out.append(_check("Accuracy = 1 - WAPE", abs(wm["accuracy"] - (1 - wm["wape"])) < 1e-4, f"{wm['accuracy']:.4f}", "Forecast"))
    n = np.array([r["naive"] for r in validation], float)
    out.append(_check("Model beats the naive baseline", w < np.abs(n - y).sum() / y.sum(),
                      f"{w:.3f} vs naive {np.abs(n - y).sum() / y.sum():.3f}", "Forecast"))
    return out


def run_all(opt, res, budget, lam, share, table=None, validation=None):
    checks = plan_checks(opt, res, budget, lam, share)
    if table is not None:
        checks += forecast_checks(table, validation)
    return dict(passed=sum(c["passed"] for c in checks), total=len(checks), checks=checks)
