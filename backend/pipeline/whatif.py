"""What-if simulation and automated re-planning.

A *shock* changes one input of the decision model for part of the portfolio:

    kind          effect                                                         scope keys
    demand        forecast demand x (1 + change)                                 destination, item_type, item_id
    market_price  market rate x (1 + change); TBO's price follows the market,    destination, item_type, item_id
                  and market demand reacts with the item's own elasticity
    supplier_cost supplier rates x (1 + change)                                  + supplier_id
    availability  supplier availability x (1 + change)  (-1 = supplier out)      + supplier_id
    cancellation  cancellation rate x (1 + change)                               destination, item_type, item_id

For every affected candidate the same logic used at training time is re-run on the SAME demand
scenarios (stored standard-normal draws): supplier choice, price, newsvendor quantity and quantity
blocks. Untouched candidates keep their blocks, so a what-if with no shocks reproduces the base
plan exactly. The optimizer is then rebuilt and re-solved.

`replan` compares the plan re-optimised for the new conditions with simply keeping the current
plan (same units, same supplier) under the new conditions, and recommends re-planning when the
gain is material.
"""
import copy

import numpy as np
import pandas as pd

from .config import COMPETITIVE_ELASTICITY, TODAY
from .simulate import choose_supplier, lognormal_draws, profit_matrix
from .optimizer import Optimizer

KINDS = ("demand", "market_price", "supplier_cost", "availability", "cancellation")
SCOPE_KEYS = ("destination", "item_type", "item_id")


def _matches(sh, cand):
    return all(sh.get(k) in (None, "", "all") or sh.get(k) == cand[k] for k in SCOPE_KEYS)


def _shocked_inputs(sim, cand, shocks):
    econ = dict(sim["econ"])
    opts = copy.deepcopy(sim["options"])
    for sh in shocks:
        if not _matches(sh, cand):
            continue
        ch = float(sh["change"])
        k = sh["kind"]
        if k == "demand":
            econ["median"] *= max(1 + ch, 0.01)
        elif k == "market_price":
            econ["market_price"] *= max(1 + ch, 0.01)
            econ["median"] *= max(1 + ch, 0.01) ** (-econ["elasticity"])
        elif k == "cancellation":
            econ["cancel_rate"] = float(np.clip(econ["cancel_rate"] * (1 + ch), 0, 0.9))
        elif k in ("supplier_cost", "availability"):
            for o in opts:
                if not o.get("eligible") or (sh.get("supplier_id") not in (None, "", "all") and sh["supplier_id"] != o["supplier_id"]):
                    continue
                if k == "supplier_cost":
                    o["_unit_cost"] *= max(1 + ch, 0.01)
                    o["effective_cost"] = round(o["_unit_cost"], 0)
                    if o.get("supplier_cost") is not None:
                        o["supplier_cost"] = round(o["supplier_cost"] * (1 + ch), 0)
                else:
                    o["_cap"] *= max(1 + ch, 0.0)
                    o["cap_units"] = round(o["_cap"], 0)
                    if o["_cap"] < 1:
                        o["eligible"], o["reason"] = False, "no availability"
    return econ, opts


def apply_shocks(cands: pd.DataFrame, blocks: list, shocks: list):
    """Return (cands', blocks', changed_ids) with every affected candidate re-optimised."""
    shocks = [s for s in (shocks or []) if s.get("kind") in KINDS and abs(float(s.get("change", 0))) > 1e-9]
    if not shocks:
        return cands, blocks, set()
    bmap = {b["cand_id"]: b for b in blocks}
    new_c = cands.copy()
    new_c["suppliers"] = new_c["suppliers"].astype(object)
    new_blocks, changed = [], set()
    for idx, cand in cands.iterrows():
        sim = bmap.get(cand.cand_id)
        if sim is None or "z" not in sim or not any(_matches(s, cand) for s in shocks):
            if sim is not None:
                new_blocks.append(sim)
            continue
        econ, opts = _shocked_inputs(sim, cand, shocks)
        c, chosen, row = choose_supplier(econ, opts, sim["z"], sim["max_allot"])
        changed.add(cand.cand_id)
        f = econ["median"] / max(sim["econ"]["median"], 1e-9)
        upd = dict(demand_p50=round(cand.demand_p50 * f, 1), demand_p10=round(cand.demand_p10 * f, 1),
                   demand_p90=round(cand.demand_p90 * f, 1), market_price=round(econ["market_price"], 0),
                   cancel_rate=round(econ["cancel_rate"], 4),
                   suppliers=[{k: v for k, v in o.items() if not k.startswith("_")} for o in opts])
        sim2 = dict(sim, econ=econ, options=opts)
        for k in ("levels", "block_exp", "block_cvar", "block_cost", "profit_levels", "exp_sold_levels", "D"):
            sim2.pop(k, None)
        if c is None:
            upd.update(viable=False)
            sim2["viable"] = False
        else:
            week = pd.Timestamp(cand.week)
            upd.update(viable=True, sell_price=round(c["sell_price"], 0), price_mult=c["price_mult"],
                       q_star=round(c["q_star"], 1), critical_ratio=round(c["critical_ratio"], 3), block_size=c["block_size"],
                       unit_cost=round(chosen["_unit_cost"], 0), salvage_rate=round(row["salvage_rate"], 4),
                       supplier=chosen["supplier"], supplier_id=chosen["supplier_id"], supplier_cost=chosen.get("supplier_cost"),
                       supplier_reliability=chosen.get("reliability"), buy_lead_days=int(chosen["buy_lead_days"]),
                       buy_by=str(max(week - pd.Timedelta(days=int(chosen["buy_lead_days"])), TODAY).date()))
            sim2.update(viable=True, **{k: c[k] for k in ("levels", "block_exp", "block_cvar", "block_cost",
                                                          "profit_levels", "exp_sold_levels", "D")})
            k = max(int(np.argmin(np.abs(c["levels"] - c["q_star"]))), 1)
            upd["roi_at_qstar"] = round(float(c["profit_levels"][:, k].mean() / (c["levels"][k] * chosen["_unit_cost"])), 4)
        for k, v in upd.items():
            new_c.at[idx, k] = v
        new_blocks.append(sim2)
    new_c["viable"] = new_c["viable"].astype(bool)
    return new_c, new_blocks, changed


def scenario_profit_fixed(sim, cand_new, position, shocks_applied_sim):
    """Profit per scenario of KEEPING an existing position (same units and supplier) under new conditions.
    TBO keeps its price policy relative to the market (same price multiplier)."""
    econ, opts = shocks_applied_sim
    o = next((x for x in opts if x["supplier_id"] == position["supplier_id"]), None)
    if o is None or "_unit_cost" not in o:
        o = dict(_unit_cost=position["unit_cost"], _salvage=position.get("salvage_rate", 0.3))
    g = float(position["price_mult"])
    D = lognormal_draws(econ["median"], econ["sigma"], sim["z"].astype(float)) * g ** (-(econ["elasticity"] + COMPETITIVE_ELASTICITY))
    Q = float(position["units"])
    if "_cap" in o:                      # supplier can no longer deliver more than its (new) availability
        Q = min(Q, float(o["_cap"])) if o.get("eligible", True) else 0.0
    pm = profit_matrix(D, np.array([Q]), econ["market_price"] * g, o["_unit_cost"], o["_salvage"], econ["cancel_rate"])[:, 0]
    sold = np.minimum(Q, D).mean()
    return pm, Q * o["_unit_cost"], sold, Q


def keep_plan_stats(base_blocks, base_cands, plan_rows, shocks, n_scen):
    """Stats of the unchanged plan when the world changes."""
    bmap = {b["cand_id"]: b for b in base_blocks}
    cidx = base_cands.set_index("cand_id")
    total = np.zeros(n_scen)
    invested = units = sold = 0.0
    for r in plan_rows:
        sim = bmap[r["cand_id"]]
        cand = cidx.loc[r["cand_id"]]
        econ, opts = _shocked_inputs(sim, dict(cand, cand_id=r["cand_id"]), shocks)
        sid = r.get("supplier_id") or cand.supplier_id      # the plan in force may use another supplier / price
        pos = dict(r, supplier_id=sid, price_mult=r.get("price_mult") or cand.price_mult, salvage_rate=sim_salvage(sim, sid, cand))
        pm, inv, s, q = scenario_profit_fixed(sim, cand, pos, (econ, opts))
        total += pm
        invested += inv
        units += q
        sold += s
    srt = np.sort(total)
    n10 = max(1, int(0.1 * n_scen))
    n5 = max(1, int(0.05 * n_scen))
    return dict(expected_profit=round(float(total.mean()), 0), cvar10=round(float(srt[:n10].mean()), 0),
                p5=round(float(srt[n5 - 1]), 0), prob_loss=round(float((total < 0).mean()), 4),
                invested=round(invested, 0), units=int(units), sell_through=round(sold / units, 4) if units else 0)


def sim_salvage(sim, supplier_id, cand):
    o = next((x for x in sim["options"] if x["supplier_id"] == supplier_id), None)
    return o["_salvage"] if o and "_salvage" in o else float(cand.salvage_rate)


def plan_diff(old_rows, new_rows, limit=25):
    old = {r["cand_id"]: r for r in old_rows}
    new = {r["cand_id"]: r for r in new_rows}
    out = []
    for cid in set(old) | set(new):
        o, n = old.get(cid), new.get(cid)
        ou, nu = (o["units"] if o else 0), (n["units"] if n else 0)
        if ou == nu and (not o or not n or o.get("sell_price") == n.get("sell_price")):
            continue
        r = n or o
        action = "add" if not o else "remove" if not n else "increase" if nu > ou else "decrease" if nu < ou else "reprice"
        out.append(dict(cand_id=cid, name=r["name"], destination=r["destination"], item_type=r["item_type"], week=r["week"],
                        action=action, units_before=ou, units_after=nu,
                        investment_before=o["investment"] if o else 0, investment_after=n["investment"] if n else 0,
                        price_before=o["sell_price"] if o else None, price_after=n["sell_price"] if n else None,
                        supplier_before=o.get("supplier") if o else None, supplier_after=n.get("supplier") if n else None))
    out.sort(key=lambda x: -abs(x["investment_after"] - x["investment_before"]))
    counts = {a: sum(1 for x in out if x["action"] == a) for a in ("add", "remove", "increase", "decrease", "reprice")}
    return dict(changes=out[:limit], n_changes=len(out), counts=counts)


def replan(base_cands, base_blocks, base_plan_rows, shocks, solve_kw, min_gain_share=0.005, min_gain_abs=10e5):
    cands2, blocks2, changed = apply_shocks(base_cands, base_blocks, shocks)
    opt2 = Optimizer(cands2, blocks2)
    res = opt2.solve(**solve_kw)
    res.pop("k_sel", None)
    keep = keep_plan_stats(base_blocks, base_cands, base_plan_rows, shocks, opt2.n_scen)
    new = res["stats"]
    gain = new["expected_profit"] - keep["expected_profit"]
    tail_gain = new["cvar10"] - keep["cvar10"]
    over_budget = keep["invested"] > solve_kw["budget"] * 1.0001
    threshold = max(min_gain_share * abs(keep["expected_profit"]), min_gain_abs)
    if over_budget:
        decision, why = True, "the current plan would now cost more than the budget"
    elif gain >= threshold:
        decision, why = True, f"re-planning adds {gain / 1e7:.2f} Cr expected profit (threshold {threshold / 1e7:.2f} Cr)"
    elif tail_gain >= threshold:
        decision, why = True, f"re-planning improves worst-10% profit by {tail_gain / 1e7:.2f} Cr"
    else:
        decision, why = False, f"gain of {gain / 1e7:.2f} Cr is below the {threshold / 1e7:.2f} Cr threshold; keep the current plan"
    return dict(result=res, keep_plan=keep, gain=round(gain, 0), tail_gain=round(tail_gain, 0),
                replan_recommended=decision, reason=why, affected_candidates=len(changed),
                diff=plan_diff(base_plan_rows, res["plan"]), optimizer=opt2)


SIGNAL_TEMPLATES = [
    ("demand", "Search volume for {dest} {dir} {pct} vs forecast over the last 48 h", (0.08, 0.28)),
    ("market_price", "Competitor {type} rates in {dest} {dir} {pct}", (0.04, 0.12)),
    ("supplier_cost", "{sup} {dir} its {type} rates by {pct}", (0.03, 0.10)),
    ("availability", "{sup} cuts {dest} allotments by {pct}", (0.30, 0.70)),
    ("cancellation", "Travel advisory for {dest}: cancellations {dir} {pct}", (0.20, 0.60)),
]


def sample_signal(seq: int, destinations, suppliers: pd.DataFrame):
    """A plausible incoming market signal for the live re-planning demo (SIMULATED, not real data)."""
    rng = np.random.default_rng(1000 + int(seq))
    kind, text, (lo, hi) = SIGNAL_TEMPLATES[int(rng.integers(len(SIGNAL_TEMPLATES)))]
    mag = float(np.round(rng.uniform(lo, hi), 2))
    dest = str(rng.choice(sorted(destinations)))
    sh = dict(kind=kind, destination=dest)
    if kind == "availability":
        change = -mag
    elif kind == "cancellation":
        change = mag
    else:
        change = mag if rng.random() < 0.55 else -mag
    if kind in ("supplier_cost", "availability"):
        s = suppliers.iloc[int(rng.integers(len(suppliers)))]
        sh.update(supplier_id=s.supplier_id, item_type=s.item_type)
        sup_name = s.supplier
    else:
        sup_name = ""
    if kind == "market_price":
        sh["item_type"] = str(rng.choice(["Hotel", "Flight"]))
    if kind == "supplier_cost":
        sh.pop("destination")
    sh["change"] = round(change, 2)
    pct = f"{abs(change):.0%}"
    word = ("rises" if kind == "supplier_cost" else "up") if change > 0 else ("cuts" if kind == "supplier_cost" else "down")
    sh["text"] = text.format(dest=dest, dir=word, pct=pct, sup=sup_name, type=(sh.get("item_type") or "").lower() or "hotel")
    sh["id"] = int(seq)
    sh["simulated"] = True
    return sh
