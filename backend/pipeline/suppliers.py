"""Supplier intelligence.

Each hotel or flight can be sourced from several suppliers (direct contract, bed banks,
consolidators, ...). They differ in price, how much they can supply, how reliably they confirm
allotments, how much they refund when unsold stock is released, and how far ahead you must book.

* `generate_supplier_data` writes a synthetic supplier master and ~3 years of allotment-request
  history (what was asked, offered, confirmed, released and refunded). The hidden "true" supplier
  parameters go to `_supplier_truth.csv` and are only used to score the estimates and replay the
  back-test, never by the models.
* `supplier_scorecard` estimates every supplier's behaviour from that history alone.
* `effective_terms` turns a scorecard row into the numbers the optimizer needs: an effective unit
  cost that includes the expected cost of re-buying units the supplier fails to confirm, a
  refund (salvage) rate for unsold stock, and an availability cap.
"""
import numpy as np
import pandas as pd

from .config import DATA_DIR, SEED, HIST_START, HIST_END

# name, item_type, price index vs benchmark rate, availability share, reliability (confirm rate),
# refund adjustment vs the item's base release refund, minimum lead time (days), free-release window (days)
SUPPLIER_PROFILES = [
    ("S-HDIR", "Direct hotel contract", "Hotel", 1.00, 0.60, 0.97, +0.00, 30, 21),
    ("S-HBBA", "BedBank Alpha", "Hotel", 1.045, 1.00, 0.93, +0.15, 7, 7),
    ("S-HBBN", "BedBank Nova", "Hotel", 0.965, 0.70, 0.84, -0.10, 21, 30),
    ("S-FGRP", "Airline group desk", "Flight", 1.00, 0.65, 0.98, +0.00, 45, 30),
    ("S-FCON", "Consolidator SkyLink", "Flight", 1.035, 1.00, 0.94, +0.10, 7, 7),
    ("S-FCHR", "Charter block Aero", "Flight", 0.95, 0.50, 0.87, -0.08, 60, 45),
]


def generate_supplier_data(items: pd.DataFrame, data_dir=DATA_DIR, seed=SEED):
    rng = np.random.default_rng(seed + 101)
    sup = pd.DataFrame(SUPPLIER_PROFILES, columns=["supplier_id", "supplier", "item_type", "price_index", "availability",
                                                   "reliability", "refund_adj", "min_lead_days", "free_release_days"])
    # true per item x supplier parameters (suppliers behave a bit differently per property / route)
    truth = []
    for it in items.itertuples():
        for s in sup[sup.item_type == it.item_type].itertuples():
            truth.append(dict(
                item_id=it.item_id, supplier_id=s.supplier_id,
                price_index=round(s.price_index * rng.normal(1, 0.012), 4),
                availability=round(float(np.clip(s.availability * rng.normal(1, 0.08), 0.2, 1.0)), 3),
                reliability=round(float(np.clip(s.reliability + rng.normal(0, 0.015), 0.6, 0.995)), 3),
                refund_rate=round(float(np.clip(it.salvage_rate + s.refund_adj + rng.normal(0, 0.02), 0.0, 0.9)), 3),
                min_lead_days=s.min_lead_days))
    truth = pd.DataFrame(truth)

    # allotment-request history: ~2 requests per item-supplier per month
    hist = []
    months = pd.date_range(HIST_START, HIST_END - pd.Timedelta(days=60), freq="MS")
    it_idx = items.set_index("item_id")
    for t in truth.itertuples():
        base_need = it_idx.loc[t.item_id, "base_demand"] * 7 * 0.6
        for m in months:
            for _ in range(2):
                req_date = m + pd.Timedelta(days=int(rng.integers(0, 28)))
                lead = int(rng.choice([t.min_lead_days, t.min_lead_days + 15, t.min_lead_days + 45]))
                desired = max(5, int(base_need * rng.uniform(0.6, 1.4)))
                offered = int(min(desired, round(desired * t.availability * rng.uniform(0.8, 1.2))))
                confirmed = int(rng.binomial(offered, t.reliability))
                bench = it_idx.loc[t.item_id, "ref_price"] * (1 - it_idx.loc[t.item_id, "prebuy_discount"])
                quoted = bench * t.price_index * rng.normal(1, 0.025)
                released = int(rng.binomial(confirmed, 0.12))
                refund = released * quoted * float(np.clip(t.refund_rate + rng.normal(0, 0.03), 0, 1))
                hist.append((str(req_date.date()), t.item_id, t.supplier_id, lead, desired, offered, confirmed,
                             round(quoted, 0), round(bench, 0), released, round(refund, 0)))
    hist = pd.DataFrame(hist, columns=["request_date", "item_id", "supplier_id", "lead_days", "units_requested",
                                       "units_offered", "units_confirmed", "quoted_unit_cost", "benchmark_unit_cost",
                                       "units_released", "refund_amount"])
    sup.drop(columns=["price_index", "availability", "reliability", "refund_adj"]).to_csv(data_dir / "suppliers.csv", index=False)
    hist.to_csv(data_dir / "supplier_history.csv", index=False)
    truth.to_csv(data_dir / "_supplier_truth.csv", index=False)
    return sup, hist, truth


def load_supplier_data(data_dir=DATA_DIR):
    sup = pd.read_csv(data_dir / "suppliers.csv")
    hist = pd.read_csv(data_dir / "supplier_history.csv", parse_dates=["request_date"])
    return sup, hist


def supplier_scorecard(sup: pd.DataFrame, hist: pd.DataFrame, as_of=None) -> pd.DataFrame:
    """Estimate supplier behaviour per item from the request history (only rows before `as_of`)."""
    h = hist if as_of is None else hist[hist.request_date < pd.Timestamp(as_of)]
    g = h.groupby(["item_id", "supplier_id"])
    sc = pd.DataFrame(dict(
        n_requests=g.size(),
        price_index=g.apply(lambda x: (x.quoted_unit_cost / x.benchmark_unit_cost).median(), include_groups=False),
        availability=g.apply(lambda x: (x.units_offered / x.units_requested).mean(), include_groups=False),
        reliability=g.apply(lambda x: x.units_confirmed.sum() / max(x.units_offered.sum(), 1), include_groups=False),
        refund_rate=g.apply(lambda x: x.refund_amount.sum() / max((x.units_released * x.quoted_unit_cost).sum(), 1),
                            include_groups=False),
        min_lead_days=g.lead_days.min(),
    )).reset_index()
    sc = sc.merge(sup[["supplier_id", "supplier", "item_type", "free_release_days"]], on="supplier_id")
    return sc.round(4)


def effective_terms(base_cost, cost_if_wait, sc_row, max_allotment):
    """Economics of sourcing one candidate from one supplier.

    Units the supplier fails to confirm must be bought again close to travel at the last-minute
    rate, so the effective cost per planned unit is
        c_eff = c_s + (1 - reliability) * max(c_wait - c_s, 0)
    Refunds on released stock are paid on c_s, so the salvage rate relative to c_eff is
    refund_rate * c_s / c_eff."""
    c_s = float(base_cost) * float(sc_row["price_index"])
    c_eff = c_s + (1 - float(sc_row["reliability"])) * max(float(cost_if_wait) - c_s, 0.0)
    salvage = float(sc_row["refund_rate"]) * c_s / c_eff
    cap = float(sc_row["availability"]) * float(max_allotment)
    return dict(supplier_cost=c_s, unit_cost=c_eff, salvage_rate=salvage, cap=cap)


def score_scorecard(sc: pd.DataFrame, truth: pd.DataFrame) -> dict:
    """How well the history-based estimates recover the hidden supplier parameters."""
    m = sc.merge(truth, on=["item_id", "supplier_id"], suffixes=("_est", "_true"))
    out = {}
    for k in ["price_index", "availability", "reliability", "refund_rate"]:
        out[f"{k}_mae"] = round(float(np.abs(m[f"{k}_est"] - m[f"{k}_true"]).mean()), 4)
    return out


def supplier_summary(scorecard: pd.DataFrame, cands: pd.DataFrame) -> dict:
    """Supplier comparison table for the dashboard (shared by the API and the static export)."""
    v = cands[cands.viable]
    chosen = v.groupby("supplier_id").agg(positions=("cand_id", "count")).reset_index()
    agg = (scorecard.groupby(["supplier_id", "supplier", "item_type"]).agg(
        price_index=("price_index", "mean"), availability=("availability", "mean"), reliability=("reliability", "mean"),
        refund_rate=("refund_rate", "mean"), min_lead_days=("min_lead_days", "min"),
        free_release_days=("free_release_days", "first"), items=("item_id", "nunique"), requests=("n_requests", "sum"))
        .reset_index().merge(chosen, on="supplier_id", how="left").fillna({"positions": 0}))
    return dict(suppliers=agg.round(4).to_dict("records"),
                by_item=scorecard.merge(chosen, on="supplier_id", how="left").round(4).to_dict("records"))


def validation_payload(summary: dict, validation: list) -> dict:
    v = pd.DataFrame(validation or [])
    weekly = (v.groupby("week").agg(actual=("y", "sum"), forecast=("median", "sum"), naive=("naive", "sum")).reset_index()
              .round(1).to_dict("records")) if len(v) else []
    return dict(table=summary["forecast_backtest"].get("table"), weekly=weekly, rows=v.to_dict("records"))
