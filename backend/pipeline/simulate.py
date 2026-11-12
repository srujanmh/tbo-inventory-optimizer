"""Monte Carlo demand simulation + newsvendor economics for every candidate
(item x travel-week). Produces per-candidate quantity *blocks* that the MILP chooses from.

Economics of pre-buying Q units at unit cost c and selling at price p:
    sold       S = min(Q, D)
    cancelled  C = S * cancel_rate            (cancelled units are not re-sold)
    profit     = p * (S - C) + salvage * c * (Q - S) - c * Q
where salvage = refundable share if unsold allotment is released back to the supplier.
"""
import numpy as np
import pandas as pd

from .config import N_SCENARIOS, N_BLOCKS, PRICE_GRID, CVAR_ALPHA, SEED, COMPETITIVE_ELASTICITY


def lognormal_draws(median, sigma, z):
    """Weekly demand draws: lognormal with the forecast median and calibrated log-spread sigma."""
    return max(median, 0.1) * np.exp(sigma * z)


def common_shocks(destinations, n=N_SCENARIOS, seed=SEED):
    """Shared demand shocks so portfolio risk is realistic: one global factor
    (macro/economy) + one per destination (local events, weather, disruptions)."""
    rng = np.random.default_rng(seed + 1)
    g = rng.standard_normal(n)
    dest = {d: rng.standard_normal(n) for d in destinations}
    return g, dest


def profit_matrix(D, Q_levels, price, cost, salvage, cancel_rate):
    """profit[s, k] for scenario s and quantity level k."""
    Q = Q_levels[None, :]
    S = np.minimum(Q, D[:, None])
    C = S * cancel_rate
    return price * (S - C) + salvage * cost * (Q - S) - cost * Q


def build_candidate(row, z, price_grid=PRICE_GRID, n_blocks=N_BLOCKS):
    """row: dict with median, sigma, market_price, unit_cost, salvage_rate, cancel_rate,
    elasticity, max_allotment. z: standard-normal draws (already correlated)."""
    D0 = lognormal_draws(row["median"], row["sigma"], z)
    best = None
    for g in price_grid:
        p = row["market_price"] * g
        D = D0 * g ** (-(row["elasticity"] + COMPETITIVE_ELASTICITY))
        # newsvendor critical ratio -> Q*
        under = p * (1 - row["cancel_rate"]) - row["unit_cost"]          # margin lost per unit short
        over = row["unit_cost"] * (1 - row["salvage_rate"])              # loss per unsold unit
        if under <= 0:
            continue
        cr = under / (under + over)
        q_star = float(np.quantile(D, cr))
        q_star = min(q_star, row["max_allotment"])
        if q_star < 1:
            continue
        pm = profit_matrix(D, np.array([q_star]), p, row["unit_cost"], row["salvage_rate"], row["cancel_rate"])
        ep = pm.mean()
        if best is None or ep > best["exp_profit_qstar"]:
            best = dict(price_mult=g, sell_price=p, q_star=q_star, critical_ratio=cr,
                        exp_profit_qstar=ep, D=D)
    if best is None or best["exp_profit_qstar"] <= 0:
        return None

    # quantity blocks up to a bit beyond Q* (MILP may stop earlier when risk-averse)
    q_max = min(row["max_allotment"], np.quantile(best["D"], 0.97))
    q_max = max(q_max, best["q_star"])
    block = max(1, int(np.ceil(q_max / n_blocks)))
    levels = np.arange(0, n_blocks + 1) * block
    levels = levels[levels <= q_max + block - 1]
    pm = profit_matrix(best["D"], levels.astype(float), best["sell_price"], row["unit_cost"],
                       row["salvage_rate"], row["cancel_rate"])
    deltas = np.diff(pm, axis=1)                    # scenario x block marginal profit
    k = max(1, int(CVAR_ALPHA * deltas.shape[0]))
    tail = np.sort(deltas, axis=0)[:k].mean(axis=0)  # CVaR of each block's marginal profit
    sold_exp = np.minimum(levels[None, :], best["D"][:, None]).mean(axis=0)
    return dict(
        sell_price=best["sell_price"], price_mult=best["price_mult"], q_star=best["q_star"],
        critical_ratio=best["critical_ratio"], block_size=block, levels=levels,
        block_exp=deltas.mean(axis=0), block_cvar=tail, block_cost=np.full(len(levels) - 1, block * row["unit_cost"]),
        profit_levels=pm.astype(np.float32), exp_sold_levels=sold_exp,
        demand_mean_at_price=float(best["D"].mean()),
    )
