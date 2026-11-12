"""Budget allocation.

MILP (solved with HiGHS through PuLP):
    x[i,k] in {0,1}  -> buy quantity block k of candidate i (item x travel week)
    maximize   sum  [(1-lam) * E[dProfit_ik] + lam * Tail[dProfit_ik]] * x[i,k]
               Tail = average marginal profit over a fixed set T of portfolio stress scenarios
               (the worst 10% of scenarios for a reference "buy everything at Q*" portfolio).
               Because T is shared by all candidates, sum(Tail * x) is exactly the plan's average
               profit in those stress scenarios -> a linear, scenario-consistent CVaR proxy.
    s.t.       sum cost_ik * x[i,k]                  <= Budget
               sum_{i in dest d} cost_ik * x[i,k]    <= max_dest_share * Budget   (diversification)
               x[i,k] <= x[i,k-1]                                                  (blocks in order)

Baselines for comparison:
  * greedy      - rank by ROI at the newsvendor quantity, buy Q* until budget runs out
  * last_year   - split budget in proportion to last year's revenue in the same week
"""
import numpy as np
import pandas as pd
import pulp


def _solver(time_limit):
    """Prefer HiGHS (pip install highspy); fall back to the CBC binary bundled with PuLP."""
    if "HiGHS" in pulp.listSolvers(onlyAvailable=True):
        return pulp.HiGHS(msg=False, timeLimit=time_limit, gapRel=0.002)
    return pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit, gapRel=0.002)


class Optimizer:
    def __init__(self, cands: pd.DataFrame, blocks: list):
        self.cands = cands[cands.viable].reset_index(drop=True)
        bmap = {b["cand_id"]: b for b in blocks}
        self.blocks = [bmap[c] for c in self.cands.cand_id]
        self.n_scen = self.blocks[0]["profit_levels"].shape[0]
        # stress scenarios T: worst 10% for a reference portfolio (every candidate at ~Q*)
        ref = np.zeros(self.n_scen)
        for c, b in zip(self.cands.itertuples(), self.blocks):
            k = max(1, int(np.argmin(np.abs(b["levels"] - c.q_star))))
            ref += b["profit_levels"][:, k]
        self.tail_idx = np.argsort(ref)[: max(1, int(0.10 * self.n_scen))]
        self.block_tail = [np.diff(b["profit_levels"][self.tail_idx], axis=1).mean(axis=0) for b in self.blocks]

    # ------------------------------------------------------------------ helpers
    def _mask(self, item_types, destinations):
        m = self.cands.item_type.isin(item_types)
        if destinations:
            m &= self.cands.destination.isin(destinations)
        return m.values

    def evaluate(self, k_sel: np.ndarray) -> dict:
        """Portfolio statistics for a chosen block count per candidate (scenario-consistent)."""
        total = np.zeros(self.n_scen)
        invested = units = exp_sold = 0.0
        for i, k in enumerate(k_sel):
            if k <= 0:
                continue
            b = self.blocks[i]
            total += b["profit_levels"][:, k]
            invested += b["block_cost"][:k].sum()
            units += b["levels"][k]
            exp_sold += b["exp_sold_levels"][k]
        srt = np.sort(total)
        n5 = max(1, int(0.05 * self.n_scen))
        n10 = max(1, int(0.10 * self.n_scen))
        hist, edges = np.histogram(total, bins=30)
        exp_profit = float(total.mean())
        return dict(
            invested=round(invested, 0), expected_profit=round(exp_profit, 0),
            roi=round(exp_profit / invested, 4) if invested else 0.0,
            profit_std=round(float(total.std()), 0), p5=round(float(srt[n5 - 1]), 0),
            p95=round(float(srt[int(0.95 * self.n_scen)]), 0),
            cvar10=round(float(srt[:n10].mean()), 0), prob_loss=round(float((total < 0).mean()), 4),
            units=int(round(units)), expected_units_sold=int(round(exp_sold)),
            sell_through=round(exp_sold / units, 4) if units else 0.0,
            histogram=[dict(x0=round(float(edges[j]), 0), x1=round(float(edges[j + 1]), 0), count=int(hist[j]))
                       for j in range(len(hist))],
        )

    def _plan_rows(self, k_sel):
        rows = []
        for i, k in enumerate(k_sel):
            if k <= 0:
                continue
            c, b = self.cands.iloc[i], self.blocks[i]
            pl = b["profit_levels"][:, k]
            q = int(b["levels"][k])
            rows.append(dict(
                cand_id=c.cand_id, item_id=c.item_id, name=c["name"], item_type=c.item_type, destination=c.destination,
                tier=c.tier, unit=c.unit, week=c.week, units=q, unit_cost=c.unit_cost, investment=round(q * c.unit_cost, 0),
                sell_price=c.sell_price, market_price=c.market_price, buy_by=c.buy_by,
                cost_if_wait=c.cost_if_wait, saving_vs_wait=round(q * (c.cost_if_wait - c.unit_cost), 0),
                demand_p10=c.demand_p10, demand_p50=c.demand_p50, demand_p90=c.demand_p90,
                expected_profit=round(float(pl.mean()), 0), worst5_profit=round(float(np.sort(pl)[: max(1, len(pl) // 20)].mean()), 0),
                expected_sold=round(float(b["exp_sold_levels"][k]), 1), sell_through=round(float(b["exp_sold_levels"][k]) / q, 3),
                sold_out_risk=c.sold_out_risk, cancel_rate=c.cancel_rate, opportunity_score=c.opportunity_score,
                events=c.events, drivers=c.drivers,
            ))
        return sorted(rows, key=lambda r: -r["expected_profit"])

    # ------------------------------------------------------------------ MILP
    def solve(self, budget, lam=0.3, max_dest_share=0.30, item_types=("Hotel", "Flight"),
              destinations=None, time_limit=20):
        mask = self._mask(item_types, destinations)
        prob = pulp.LpProblem("tbo_prebuy", pulp.LpMaximize)
        x, obj, cost_terms, dest_terms = {}, [], [], {}
        for i in np.where(mask)[0]:
            b = self.blocks[i]
            score = (1 - lam) * b["block_exp"] + lam * self.block_tail[i]
            pos = np.where(score > 0)[0]
            if len(pos) == 0:
                continue
            last = pos.max()
            d = self.cands.destination.iat[i]
            for k in range(last + 1):
                v = pulp.LpVariable(f"x_{i}_{k}", cat="Binary")
                x[(i, k)] = v
                obj.append(float(score[k]) * v)
                ct = float(b["block_cost"][k]) * v
                cost_terms.append(ct)
                dest_terms.setdefault(d, []).append(ct)
                if k > 0:
                    prob += v <= x[(i, k - 1)]
        if not x:
            return self._result(np.zeros(len(self.cands), int), budget, lam, "no_candidates")
        prob += pulp.lpSum(obj)
        prob += pulp.lpSum(cost_terms) <= budget
        n_dest = len(dest_terms)
        share = max(max_dest_share, 1.0 / max(n_dest, 1))   # keep feasible when few destinations selected
        for d, terms in dest_terms.items():
            prob += pulp.lpSum(terms) <= share * budget
        prob.solve(_solver(time_limit))
        status = pulp.LpStatus[prob.status]
        k_sel = np.zeros(len(self.cands), int)
        for (i, k), v in x.items():
            if v.value() is not None and v.value() > 0.5:
                k_sel[i] = max(k_sel[i], k + 1)
        return self._result(k_sel, budget, lam, status)

    def _result(self, k_sel, budget, lam, status):
        stats = self.evaluate(k_sel)
        plan = self._plan_rows(k_sel)
        by_dest = (pd.DataFrame(plan).groupby("destination").agg(investment=("investment", "sum"),
                   expected_profit=("expected_profit", "sum"), units=("units", "sum")).reset_index()
                   .sort_values("investment", ascending=False).to_dict("records")) if plan else []
        by_type = (pd.DataFrame(plan).groupby("item_type").agg(investment=("investment", "sum"),
                   expected_profit=("expected_profit", "sum")).reset_index().to_dict("records")) if plan else []
        by_week = (pd.DataFrame(plan).groupby("week").agg(investment=("investment", "sum"),
                   expected_profit=("expected_profit", "sum"), units=("units", "sum")).reset_index()
                   .sort_values("week").to_dict("records")) if plan else []
        stats.update(budget=budget, budget_used=round(stats["invested"] / budget, 4) if budget else 0,
                     risk_aversion=lam, status=status, n_positions=len(plan),
                     saving_vs_wait=round(sum(r["saving_vs_wait"] for r in plan), 0),
                     units_in_soldout_windows=int(sum(r["expected_sold"] for r in plan if r["sold_out_risk"] >= 0.5)))
        return dict(stats=stats, plan=plan, by_destination=by_dest, by_type=by_type, by_week=by_week, k_sel=k_sel)

    # ------------------------------------------------------------------ baselines
    def greedy(self, budget, item_types=("Hotel", "Flight"), destinations=None):
        mask = self._mask(item_types, destinations)
        roi = self.cands.roi_at_qstar.fillna(0).values
        order = [i for i in np.argsort(-roi) if mask[i]]
        k_sel = np.zeros(len(self.cands), int)
        left = budget
        for i in order:
            b = self.blocks[i]
            k_target = max(1, int(np.argmin(np.abs(b["levels"] - self.cands.q_star.iat[i]))))
            cum = np.cumsum(b["block_cost"][:k_target])
            k_fit = int(np.searchsorted(cum, left, side="right"))
            if k_fit > 0:
                k_sel[i] = k_fit
                left -= cum[k_fit - 1]
            if left <= 0:
                break
        self.last_k = k_sel
        return self.evaluate(k_sel)

    def last_year(self, budget, item_types=("Hotel", "Flight"), destinations=None):
        mask = self._mask(item_types, destinations)
        w = self.cands.last_year_revenue.fillna(0).values * mask
        w = w / w.sum() if w.sum() > 0 else mask / mask.sum()
        k_sel = np.zeros(len(self.cands), int)
        for i in np.where(w > 0)[0]:
            b = self.blocks[i]
            cum = np.cumsum(b["block_cost"])
            k_sel[i] = int(np.searchsorted(cum, w[i] * budget, side="right"))
        self.last_k = k_sel
        return self.evaluate(k_sel)

    def frontier(self, budget, lams=(0.0, 0.2, 0.4, 0.6, 0.8, 0.95), **kw):
        out = []
        for lam in lams:
            r = self.solve(budget, lam=lam, time_limit=8, **kw)["stats"]
            out.append(dict(risk_aversion=lam, expected_profit=r["expected_profit"],
                            cvar10=r["cvar10"], p5=r["p5"], prob_loss=r["prob_loss"], invested=r["invested"], roi=r["roi"]))
        return out

    def budget_curve(self, budgets, lam=0.3, **kw):
        out = []
        for B in budgets:
            r = self.solve(B, lam=lam, time_limit=8, **kw)["stats"]
            out.append(dict(budget=B, expected_profit=r["expected_profit"], invested=r["invested"],
                            roi=r["roi"], cvar10=r["cvar10"]))
        return out
