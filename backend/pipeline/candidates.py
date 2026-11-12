"""Turn forecasts + price / cost / cancellation models into decision candidates
(item x travel-week) with Monte Carlo quantity blocks for the optimizer.

Written as a function of the planning date (`as_of`) so the exact same logic runs both
for the live plan and for the back-dated plan back-test."""
import numpy as np
import pandas as pd

from .config import LEAD_OPTIONS, N_SCENARIOS, SEED
from . import models as M
from .simulate import common_shocks, build_candidate, choose_supplier
from .suppliers import effective_terms

W_G, W_D = 0.30, 0.40                      # weight of global / destination shocks in demand scenarios
W_E = np.sqrt(1 - W_G ** 2 - W_D ** 2)


def build_candidates(items, cal, d_hist, feat_hist, fc, cmodel, rmodel, el, price_idx, season_proxy,
                     as_of, horizon_start, n_weeks, pmodel=None, scorecard=None, seed=SEED):
    """d_hist / feat_hist must only contain data before `as_of`."""
    as_of = pd.Timestamp(as_of)
    horizon_start = pd.Timestamp(horizon_start)
    hdates = pd.date_range(horizon_start, horizon_start + pd.Timedelta(weeks=n_weeks) - pd.Timedelta(days=1), freq="D")
    hz = pd.DataFrame([(dt, i) for i in items.item_id for dt in hdates], columns=["date", "item_id"])
    hz = M.build_features(hz, items, cal, d_hist)
    hz["p10"], hz["p50"], hz["p90"] = fc.predict_daily(hz)
    hz = pd.concat([hz, fc.shap_drivers(hz).add_prefix("drv_")], axis=1)
    wk_fc = fc.predict_weekly(hz).set_index(["item_id", "week"])
    hz["cancel_rate"] = np.clip(cmodel.predict(hz[M.CANCEL_FEATURES]), 0, 0.6)
    if pmodel is not None:
        hz["mkt_price"] = M.predict_price(pmodel, hz)      # holiday/event-aware weekly market price

    hz["week"] = hz.date - pd.to_timedelta(hz.date.dt.dayofweek, unit="D")
    hz["item_id_s"] = hz.item_id.astype(str)
    weeks = sorted(hz.week.unique())
    wk_sig = M._week_signals(cal, pd.Series(np.repeat(weeks, len(items))),
                             pd.Series(np.tile(items.destination.values, len(weeks))))
    fh = feat_hist.copy()
    fh["iso_week"] = fh.date.dt.isocalendar().week.astype(int).clip(upper=52)
    fh["item_id_s"] = fh.item_id.astype(str)
    last_year = fh[fh.date > as_of - pd.Timedelta(days=366)]
    avg_week_dem = last_year.groupby("item_id_s").demand_est.mean() * 7
    el_map = el.set_index("item_id").elasticity_est

    g_shock, d_shock = common_shocks(items.destination.unique(), seed=seed)
    rng = np.random.default_rng(seed + 7)

    meta, blocks = [], []
    it_idx = items.set_index("item_id")
    for (item_id, week), g in hz.groupby(["item_id_s", "week"], sort=True):
        it = it_idx.loc[item_id]
        wrow = wk_fc.loc[(item_id, week)]
        median, sigma = float(wrow["median"]), float(wrow["sigma"])
        month = pd.Timestamp(week + pd.Timedelta(days=3)).month
        if pmodel is not None:
            market_price = float(g.mkt_price.mean())
        else:
            mp = price_idx[(price_idx.item_id == item_id) & (price_idx.month == month)].month_price
            market_price = float(mp.iloc[0]) if len(mp) else float(it.ref_price)

        # --- buy timing: predicted supplier cost for each feasible lead time
        days_until = (pd.Timestamp(week) - as_of).days
        leads = sorted({l for l in LEAD_OPTIONS if l <= days_until} | {max(days_until, 1)}, reverse=True)
        sig = wk_sig[(wk_sig.destination == it.destination) & (wk_sig.week == week)].iloc[0]
        sprox = season_proxy[(season_proxy.item_id == item_id) & (season_proxy.month == month)].season_proxy
        rx = pd.DataFrame(dict(item_id=item_id, destination=it.destination, item_type=it.item_type, tier=it.tier,
                               weekofyear=min(pd.Timestamp(week).isocalendar()[1], 52), holiday_intensity=sig.holiday_intensity,
                               event_intensity=sig.event_intensity, lead_days=leads,
                               season_proxy=float(sprox.iloc[0]) if len(sprox) else 1.0))
        for col in M.CAT_COLS:
            rx[col] = pd.Categorical(rx[col].astype(str), categories=sorted(items[col].astype(str).unique()))
        mults = rmodel.predict(rx[M.RATE_FEATURES])
        cost_if_wait = float(mults[-1]) * float(it.ref_price)

        def timing(min_lead):
            """Cheapest predicted rate among lead times the supplier accepts; buy at the latest
            lead time within 1.5% of that rate (keeps flexibility without paying more)."""
            ok_idx = [j for j, l in enumerate(leads) if l >= min_lead]
            if not ok_idx:
                return None
            best_mult = float(min(mults[j] for j in ok_idx))
            lead = int(min(leads[j] for j in ok_idx if mults[j] <= best_mult * 1.015))
            return best_mult, lead
        # --- historical sold-out risk in the same season window (ISO week +-1, prior years)
        wk_no = min(pd.Timestamp(week).isocalendar()[1], 52)
        hist = fh[(fh.item_id_s == item_id) & (fh.iso_week.between(wk_no - 1, wk_no + 1))]
        sold_out_risk = float(hist.sold_out.mean()) if len(hist) else 0.0
        hist_lost = float(hist.lost_demand.sum() / max(hist.date.dt.year.nunique(), 1))
        ly = fh[(fh.item_id_s == item_id) & (fh.date >= pd.Timestamp(week) - pd.Timedelta(days=364))
                & (fh.date < pd.Timestamp(week) - pd.Timedelta(days=357))]
        ly_rev = float((ly.bookings * ly.avg_sell_price).sum())

        max_allot = float(max(1.6 * avg_week_dem.get(item_id, median), 5))
        econ = dict(median=median, sigma=sigma, market_price=market_price,
                    cancel_rate=float(g.cancel_rate.mean()), elasticity=float(el_map.get(item_id, 1.2)))
        z = W_G * g_shock + W_D * d_shock[it.destination] + W_E * rng.standard_normal(N_SCENARIOS)

        # --- supplier choice: evaluate every supplier on the same demand scenarios, keep the best
        if scorecard is not None:
            sups = scorecard[scorecard.item_id == item_id].to_dict("records")
        else:   # single implicit supplier (the benchmark rate)
            sups = [dict(supplier_id="S-BENCH", supplier="Benchmark rate", price_index=1.0, availability=1.0,
                         reliability=1.0, refund_rate=float(it.salvage_rate), min_lead_days=0, free_release_days=0)]
        options = []
        for sp in sups:
            tm = timing(int(sp["min_lead_days"]))
            opt = dict(supplier_id=sp["supplier_id"], supplier=sp["supplier"], reliability=round(float(sp["reliability"]), 3),
                       refund_rate=round(float(sp["refund_rate"]), 3), availability=round(float(sp["availability"]), 3),
                       min_lead_days=int(sp["min_lead_days"]), price_index=round(float(sp["price_index"]), 4))
            if tm is None:
                opt.update(eligible=False, reason=f"needs {int(sp['min_lead_days'])} days notice; only {days_until} left")
            else:
                mult, lead = tm
                t = effective_terms(mult * float(it.ref_price), cost_if_wait, sp, max_allot)
                opt.update(eligible=True, supplier_cost=round(t["supplier_cost"], 0), effective_cost=round(t["unit_cost"], 0),
                           cap_units=round(t["cap"], 0), buy_lead_days=lead,
                           _unit_cost=t["unit_cost"], _salvage=t["salvage_rate"], _cap=t["cap"])
            options.append(opt)
        c, chosen, row = choose_supplier(econ, options, z, max_allot)
        if chosen is None:          # nothing profitable: describe the cheapest eligible option
            el_opts = [o for o in options if o.get("eligible")]
            chosen = min(el_opts, key=lambda o: o["_unit_cost"]) if el_opts else dict(
                _unit_cost=float(mults.min()) * float(it.ref_price), _salvage=float(it.salvage_rate), _cap=max_allot,
                buy_lead_days=int(min(leads)), supplier=None, supplier_id=None, reliability=None, supplier_cost=None)
            row = dict(econ, unit_cost=chosen["_unit_cost"], salvage_rate=chosen["_salvage"],
                       max_allotment=min(max_allot, chosen["_cap"]))
        unit_cost = float(chosen["_unit_cost"])
        buy_by_lead = int(chosen["buy_lead_days"])
        buy_by = max(pd.Timestamp(week) - pd.Timedelta(days=buy_by_lead), as_of)
        sim = dict(cand_id=f"{item_id}|{pd.Timestamp(week).date()}", z=z.astype(np.float32), econ=econ,
                   max_allot=max_allot, options=options, days_until=days_until, cost_if_wait=cost_if_wait)
        public_options = [{k: v for k, v in o.items() if not k.startswith("_")} for o in options]

        drv = g[[col for col in g.columns if col.startswith("drv_")]].mean()   # avg log-contribution over the week
        drv = drv.drop(["drv_Property / route baseline"]).sort_values(key=np.abs, ascending=False)
        top = [dict(driver=k.replace("drv_", ""), effect=round(float(np.expm1(v) * 100), 1)) for k, v in drv.head(4).items()]
        evt = cal[(cal.destination == it.destination) & (cal.date >= week) & (cal.date < week + pd.Timedelta(days=7))]
        events = sorted(set([e for e in evt.event if e]) | set([h for h in evt.holiday if h]))

        base = dict(
            cand_id=f"{item_id}|{pd.Timestamp(week).date()}", item_id=item_id, name=it["name"], item_type=it.item_type,
            destination=it.destination, tier=it.tier, unit=it.unit, week=str(pd.Timestamp(week).date()),
            demand_p50=round(median, 1), demand_p10=round(float(wrow.p10), 1), demand_p90=round(float(wrow.p90), 1),
            demand_sd=round(float(median * np.sqrt(np.exp(sigma ** 2) - 1) * np.exp(sigma ** 2 / 2)), 1),
            market_price=round(market_price, 0), unit_cost=round(unit_cost, 0), cost_if_wait=round(cost_if_wait, 0),
            buy_by=str(buy_by.date()), buy_lead_days=buy_by_lead, salvage_rate=round(row["salvage_rate"], 4),
            supplier=chosen.get("supplier"), supplier_id=chosen.get("supplier_id"), supplier_cost=chosen.get("supplier_cost"),
            supplier_reliability=chosen.get("reliability"), suppliers=public_options,
            cancel_rate=round(row["cancel_rate"], 4), elasticity=round(row["elasticity"], 2),
            max_allotment=round(row["max_allotment"], 0), sold_out_risk=round(sold_out_risk, 3),
            hist_lost_demand=round(hist_lost, 1), last_year_revenue=round(ly_rev, 0),
            events=events, drivers=top,
        )
        if c is None:
            base.update(viable=False)
            meta.append(base)
            blocks.append(dict(sim, viable=False))
            continue
        base.update(viable=True, sell_price=round(c["sell_price"], 0), price_mult=c["price_mult"],
                    q_star=round(c["q_star"], 1), critical_ratio=round(c["critical_ratio"], 3),
                    block_size=c["block_size"])
        meta.append(base)
        blocks.append(dict(sim, viable=True, **{k: c[k] for k in
                      ["levels", "block_exp", "block_cvar", "block_cost", "profit_levels", "exp_sold_levels", "D"]}))

    cands = pd.DataFrame(meta)
    v = cands[cands.viable]
    bmap = {b["cand_id"]: b for b in blocks if b.get("viable")}
    roi = []
    for r in v.itertuples():
        b = bmap[r.cand_id]
        k = max(int(np.argmin(np.abs(b["levels"] - r.q_star))), 1)
        roi.append(b["profit_levels"][:, k].mean() / (b["levels"][k] * r.unit_cost))
    cands.loc[v.index, "roi_at_qstar"] = np.round(roi, 4)
    conf = 1 - np.clip(cands.demand_sd / cands.demand_p50.clip(lower=1), 0, 1)
    score = (0.5 * cands.roi_at_qstar.rank(pct=True) + 0.3 * cands.sold_out_risk.rank(pct=True) + 0.2 * conf.rank(pct=True))
    cands["opportunity_score"] = np.where(cands.viable, np.round(100 * score, 1), 0.0)
    return cands, blocks, hz


def season_proxy_from(feat):
    sp = feat.groupby(["item_id", "month"], observed=True).demand_est.mean().rename("m").reset_index()
    sp["item_id"] = sp.item_id.astype(str)
    sp["season_proxy"] = sp.m / sp.groupby("item_id").m.transform("mean")
    return sp[["item_id", "month", "season_proxy"]]
