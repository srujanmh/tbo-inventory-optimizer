"""Synthetic but realistic TBO.com data generator.

Produces (in backend/data/):
  items.csv          hotel & flight inventory master
  calendar.csv       holidays, festivals and destination events per date (external signals)
  daily.csv          per item per day: searches, bookings, sold-out flag, price, cancellations
  rate_quotes.csv    historical supplier pre-buy quotes by lead time
  suppliers.csv / supplier_history.csv   supplier master + allotment-request history (see suppliers.py)
  _ground_truth.csv  true (unconstrained) demand - used ONLY to evaluate the unconstraining step

The demand process deliberately contains the effects the real problem talks about:
seasonality, holidays, destination events, growth, price elasticity, supply shrinking in
peaks (=> sold-outs that hide true demand), searches that reflect true demand
(look-to-book), cancellations and lead-time-dependent supplier rates.
"""
import numpy as np
import pandas as pd

from .suppliers import generate_supplier_data
from .config import DATA_DIR, SEED, HIST_START, HIST_END, HORIZON_END, LEAD_OPTIONS

rng = np.random.default_rng(SEED)

# ----------------------------------------------------------------------------------
# Destinations: popularity + monthly seasonality (Jan..Dec)
# ----------------------------------------------------------------------------------
DESTINATIONS = {
    "Goa":       dict(pop=1.30, intl=False, season=[1.3, 1.1, 0.9, 0.75, 0.7, 0.5, 0.45, 0.5, 0.55, 0.8, 1.3, 1.7]),
    "Jaipur":    dict(pop=1.00, intl=False, season=[1.4, 1.2, 1.0, 0.7, 0.55, 0.5, 0.6, 0.65, 0.75, 1.1, 1.3, 1.4]),
    "Udaipur":   dict(pop=0.80, intl=False, season=[1.3, 1.2, 1.0, 0.7, 0.55, 0.5, 0.65, 0.75, 0.8, 1.1, 1.3, 1.45]),
    "Kochi":     dict(pop=0.85, intl=False, season=[1.3, 1.2, 1.0, 0.8, 0.65, 0.55, 0.6, 0.85, 0.8, 0.95, 1.2, 1.45]),
    "Manali":    dict(pop=0.90, intl=False, season=[1.2, 0.9, 0.8, 1.0, 1.5, 1.6, 0.8, 0.6, 0.8, 1.0, 0.9, 1.4]),
    "Dubai":     dict(pop=1.20, intl=True,  season=[1.4, 1.3, 1.2, 0.9, 0.7, 0.55, 0.55, 0.6, 0.8, 1.0, 1.25, 1.5]),
    "Bangkok":   dict(pop=1.10, intl=True,  season=[1.3, 1.2, 1.05, 1.2, 0.85, 0.75, 0.8, 0.8, 0.75, 0.95, 1.2, 1.4]),
    "Singapore": dict(pop=1.00, intl=True,  season=[1.0, 0.95, 1.0, 0.95, 1.05, 1.25, 1.05, 0.95, 0.95, 1.05, 1.0, 1.35]),
    "Bali":      dict(pop=0.90, intl=True,  season=[1.0, 0.85, 0.85, 0.9, 1.0, 1.15, 1.4, 1.45, 1.05, 0.95, 0.9, 1.35]),
    "London":    dict(pop=0.75, intl=True,  season=[0.7, 0.7, 0.8, 0.95, 1.1, 1.35, 1.45, 1.35, 1.05, 0.9, 0.85, 1.25]),
}

HOTEL_TIERS = {  # tier: (base room-nights/day, ref price INR, elasticity range, salvage range)
    "Budget":  (26, 3200, (1.4, 2.0), (0.45, 0.60)),
    "Midscale": (18, 6500, (1.0, 1.5), (0.35, 0.50)),
    "Luxury":  (8, 17500, (0.6, 1.0), (0.25, 0.40)),
}
HOTEL_NAMES = {
    "Goa": ["Calangute Bay Inn", "Baga Palms Resort", "Taj Fort Aguada Grand"],
    "Jaipur": ["Pink City Residency", "Amer View Hotel", "Rambagh Heritage Palace"],
    "Udaipur": ["Lakeside Haveli Stay", "Fateh Garden Hotel", "Pichola Lake Palace"],
    "Kochi": ["Fort Kochi Homestay", "Marine Drive Suites", "Backwater Grand Resort"],
    "Manali": ["Old Manali Lodge", "Solang Valley Retreat", "Himalayan Spa Resort"],
    "Dubai": ["Deira City Hotel", "Marina Bay Suites", "Palm Jumeirah Royal"],
    "Bangkok": ["Khao San Budget Inn", "Sukhumvit Central", "Chao Phraya Riverside"],
    "Singapore": ["Little India Pod Hotel", "Orchard Plaza Hotel", "Marina Skyline Grand"],
    "Bali": ["Kuta Surf Lodge", "Seminyak Garden Villas", "Ubud Jungle Retreat"],
    "London": ["Paddington Budget Rooms", "Kensington Park Hotel", "Mayfair Grand"],
}
ROUTES = [  # (origin, destination, base seats/day, ref fare INR)
    ("DEL", "Goa", 70, 6200), ("BOM", "Goa", 85, 4200), ("BLR", "Goa", 60, 4100),
    ("DEL", "Jaipur", 45, 3300), ("BOM", "Udaipur", 40, 4800), ("DEL", "Kochi", 40, 7200),
    ("DEL", "Manali", 30, 7800), ("DEL", "Dubai", 80, 16500), ("BOM", "Dubai", 90, 14500),
    ("DEL", "Bangkok", 65, 17500), ("BOM", "Singapore", 55, 21000), ("BLR", "Singapore", 45, 19500),
    ("DEL", "Bali", 35, 29000), ("BOM", "London", 35, 52000), ("DEL", "London", 40, 50000),
]

# ----------------------------------------------------------------------------------
# External signals: national holidays/festivals and destination events
# ----------------------------------------------------------------------------------
NATIONAL = [  # (name, start, end, intensity)
    ("Holi", "2024-03-23", "2024-03-26", 0.35), ("Holi", "2025-03-13", "2025-03-16", 0.35), ("Holi", "2026-03-03", "2026-03-05", 0.35),
    ("Summer Vacation", "2024-05-15", "2024-06-15", 0.30), ("Summer Vacation", "2025-05-15", "2025-06-15", 0.30), ("Summer Vacation", "2026-05-15", "2026-06-15", 0.30),
    ("Independence Day Weekend", "2024-08-15", "2024-08-18", 0.30), ("Independence Day Weekend", "2025-08-15", "2025-08-17", 0.30), ("Independence Day Weekend", "2026-08-14", "2026-08-16", 0.30),
    ("Dussehra / Puja", "2024-10-10", "2024-10-13", 0.40), ("Dussehra / Puja", "2025-09-29", "2025-10-02", 0.40), ("Dussehra / Puja", "2026-10-17", "2026-10-20", 0.40),
    ("Diwali", "2024-10-30", "2024-11-03", 0.55), ("Diwali", "2025-10-18", "2025-10-23", 0.55), ("Diwali", "2026-11-06", "2026-11-10", 0.55),
    ("Christmas - New Year", "2024-12-21", "2025-01-01", 0.70), ("Christmas - New Year", "2025-12-20", "2026-01-01", 0.70), ("Christmas - New Year", "2026-12-19", "2027-01-01", 0.70),
    ("Republic Day Weekend", "2024-01-26", "2024-01-28", 0.30), ("Republic Day Weekend", "2025-01-24", "2025-01-26", 0.30), ("Republic Day Weekend", "2026-01-24", "2026-01-26", 0.30), ("Republic Day Weekend", "2027-01-23", "2027-01-26", 0.30),
]
EVENTS = [  # (destination, name, start, end, intensity)
    ("Goa", "Sunburn Festival", "2024-12-28", "2024-12-30", 0.9), ("Goa", "Sunburn Festival", "2025-12-27", "2025-12-30", 0.9), ("Goa", "Sunburn Festival", "2026-12-27", "2026-12-30", 0.9),
    ("Goa", "Goa Carnival", "2024-02-10", "2024-02-13", 0.5), ("Goa", "Goa Carnival", "2025-03-01", "2025-03-04", 0.5), ("Goa", "Goa Carnival", "2026-02-14", "2026-02-17", 0.5), ("Goa", "Goa Carnival", "2027-02-06", "2027-02-09", 0.5),
    ("Jaipur", "Jaipur Literature Festival", "2024-02-01", "2024-02-05", 0.7), ("Jaipur", "Jaipur Literature Festival", "2025-01-30", "2025-02-03", 0.7), ("Jaipur", "Jaipur Literature Festival", "2026-01-15", "2026-01-19", 0.7), ("Jaipur", "Jaipur Literature Festival", "2027-01-21", "2027-01-25", 0.7),
    ("Udaipur", "Wedding Season Peak", "2024-11-20", "2024-12-10", 0.45), ("Udaipur", "Wedding Season Peak", "2025-11-20", "2025-12-10", 0.45), ("Udaipur", "Wedding Season Peak", "2026-11-20", "2026-12-10", 0.45),
    ("Kochi", "Kochi-Muziris Biennale", "2024-12-12", "2025-03-31", 0.20), ("Kochi", "Kochi-Muziris Biennale", "2026-12-12", "2027-03-31", 0.20),
    ("Manali", "Winter Carnival", "2024-01-02", "2024-01-06", 0.6), ("Manali", "Winter Carnival", "2025-01-02", "2025-01-06", 0.6), ("Manali", "Winter Carnival", "2026-01-02", "2026-01-06", 0.6), ("Manali", "Winter Carnival", "2027-01-02", "2027-01-06", 0.6),
    ("Dubai", "Dubai Shopping Festival", "2024-12-15", "2025-01-29", 0.35), ("Dubai", "Dubai Shopping Festival", "2025-12-05", "2026-01-11", 0.35), ("Dubai", "Dubai Shopping Festival", "2026-12-04", "2027-01-17", 0.35),
    ("Dubai", "Dubai Shopping Festival", "2024-01-01", "2024-01-14", 0.35),
    ("Bangkok", "Songkran", "2024-04-12", "2024-04-16", 0.8), ("Bangkok", "Songkran", "2025-04-12", "2025-04-16", 0.8), ("Bangkok", "Songkran", "2026-04-12", "2026-04-16", 0.8),
    ("Singapore", "Singapore Grand Prix", "2024-09-19", "2024-09-22", 0.9), ("Singapore", "Singapore Grand Prix", "2025-10-02", "2025-10-05", 0.9), ("Singapore", "Singapore Grand Prix", "2026-10-08", "2026-10-11", 0.9),
    ("Bali", "Nyepi & Galungan", "2024-03-09", "2024-03-13", 0.3), ("Bali", "Nyepi & Galungan", "2025-03-27", "2025-03-31", 0.3), ("Bali", "Nyepi & Galungan", "2026-03-17", "2026-03-21", 0.3),
    ("London", "Wimbledon", "2024-07-01", "2024-07-14", 0.5), ("London", "Wimbledon", "2025-06-30", "2025-07-13", 0.5), ("London", "Wimbledon", "2026-06-29", "2026-07-12", 0.5),
    ("London", "Winter Wonderland & Boxing Day Sales", "2024-12-20", "2025-01-02", 0.3), ("London", "Winter Wonderland & Boxing Day Sales", "2025-12-19", "2026-01-02", 0.3), ("London", "Winter Wonderland & Boxing Day Sales", "2026-12-18", "2027-01-02", 0.3),
]


def build_items() -> pd.DataFrame:
    rows = []
    for dest, dinfo in DESTINATIONS.items():
        for (tier, (base, price, e_rng, s_rng)), name in zip(HOTEL_TIERS.items(), HOTEL_NAMES[dest]):
            intl_mult = 1.35 if dinfo["intl"] else 1.0
            rows.append(dict(
                item_id=f"H-{dest[:3].upper()}-{tier[0]}", name=name, item_type="Hotel", destination=dest,
                tier=tier, origin="", unit="room-night",
                base_demand=round(base * dinfo["pop"] * rng.uniform(0.85, 1.15), 2),
                ref_price=round(price * intl_mult * rng.uniform(0.9, 1.1), -1),
                elasticity=round(rng.uniform(*e_rng), 2),
                salvage_rate=round(rng.uniform(*s_rng), 2),
                cancel_base=round(rng.uniform(0.09, 0.16), 3),
                l2b=round(rng.uniform(18, 32), 1),
                prebuy_discount=round(rng.uniform(0.20, 0.30), 3),
            ))
    for org, dest, base, fare in ROUTES:
        rows.append(dict(
            item_id=f"F-{org}-{dest[:3].upper()}", name=f"{org} → {dest} (group seats)", item_type="Flight",
            destination=dest, tier="Economy", origin=org, unit="seat",
            base_demand=round(base * rng.uniform(0.9, 1.1), 2),
            ref_price=round(fare * rng.uniform(0.92, 1.08), -1),
            elasticity=round(rng.uniform(0.9, 1.6), 2),
            salvage_rate=round(rng.uniform(0.15, 0.35), 2),
            cancel_base=round(rng.uniform(0.04, 0.08), 3),
            l2b=round(rng.uniform(9, 16), 1),
            prebuy_discount=round(rng.uniform(0.14, 0.22), 3),
        ))
    return pd.DataFrame(rows)


def build_calendar(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Long-format calendar: one row per date x destination with holiday & event intensity."""
    cal = pd.DataFrame({"date": dates})
    cal["holiday"] = ""
    cal["holiday_intensity"] = 0.0
    for name, s, e, inten in NATIONAL:
        m = (cal.date >= s) & (cal.date <= e)
        cal.loc[m, "holiday"] = name
        cal.loc[m, "holiday_intensity"] = np.maximum(cal.loc[m, "holiday_intensity"], inten)
    out = []
    for dest in DESTINATIONS:
        c = cal.copy()
        c["destination"] = dest
        c["event"] = ""
        c["event_intensity"] = 0.0
        for d, name, s, e, inten in EVENTS:
            if d != dest:
                continue
            m = (c.date >= s) & (c.date <= e)
            c.loc[m, "event"] = name
            c.loc[m, "event_intensity"] = np.maximum(c.loc[m, "event_intensity"], inten)
        out.append(c)
    return pd.concat(out, ignore_index=True)


def generate():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    items = build_items()
    all_dates = pd.date_range(HIST_START, HORIZON_END + pd.Timedelta(days=7), freq="D")
    calendar = build_calendar(all_dates)
    hist_dates = pd.date_range(HIST_START, HIST_END, freq="D")

    cal_h = calendar[calendar.date.isin(hist_dates)].set_index(["destination", "date"])
    t_years = ((hist_dates - HIST_START).days / 365.0).values
    month_idx = hist_dates.month.values - 1
    dow = hist_dates.dayofweek.values

    # common macro shocks (e.g. airfare/fuel, economy) shared by everything
    macro = np.exp(np.cumsum(rng.normal(0, 0.012, len(hist_dates))))
    macro = macro / macro.mean()

    daily, truth = [], []
    for it in items.itertuples():
        d = DESTINATIONS[it.destination]
        season = np.array(d["season"])[month_idx]
        c = cal_h.loc[it.destination]
        hol = c["holiday_intensity"].reindex(hist_dates).values
        ev = c["event_intensity"].reindex(hist_dates).values
        hol_eff = hol * (0.7 if d["intl"] and it.item_type == "Hotel" else 1.0)
        if it.item_type == "Hotel":
            dow_f = np.array([0.85, 0.85, 0.9, 0.95, 1.15, 1.3, 1.0])[dow]
        else:
            dow_f = np.array([1.0, 0.85, 0.85, 0.95, 1.2, 1.05, 1.15])[dow]
        trend = 1.0 + 0.14 * t_years  # business growth ~14%/yr
        peak = season * (1 + hol_eff) * (1 + ev)

        # Price: rises with peak (yield mgmt) + random promos (exogenous variation)
        promo = rng.choice([1.0, 0.9, 0.85, 1.08], size=len(hist_dates), p=[0.7, 0.12, 0.06, 0.12])
        price = it.ref_price * (1 + 0.22 * (peak - 1)) * promo * rng.normal(1, 0.03, len(hist_dates))
        if it.item_type == "Flight":
            price = price * (0.85 + 0.15 * macro)
        price = np.clip(price, it.ref_price * 0.6, None)
        price_ratio = price / (it.ref_price * (1 + 0.22 * (peak - 1)))  # vs "typical" price for that peak

        mean_dem = it.base_demand * peak * dow_f * trend * price_ratio ** (-it.elasticity)
        # negative-binomial-ish noise
        lam = mean_dem * rng.gamma(shape=12, scale=1 / 12, size=len(hist_dates))
        true_dem = rng.poisson(lam)

        # Supply available to TBO via normal (dynamic) sourcing shrinks in peaks
        supply = it.base_demand * trend * 1.45 * (1 - 0.32 * np.clip(peak - 1, 0, 1.6)) * rng.normal(1, 0.08, len(hist_dates))
        supply = np.maximum(np.round(supply), 1)
        bookings = np.minimum(true_dem, supply)
        sold_out = (true_dem >= supply).astype(int)

        # Searches reflect *true* demand (people search even when sold out; retries)
        searches = true_dem * it.l2b * rng.lognormal(0, 0.12, len(hist_dates)) * np.where(sold_out == 1, 1.08, 1.0)
        searches = np.round(searches + rng.poisson(it.l2b * 0.5, len(hist_dates)))

        cancel_rate = np.clip(it.cancel_base * (1 + 0.35 * hol_eff + 0.2 * ev) * (0.8 if d["intl"] else 1.0), 0, 0.5)
        cancels = rng.binomial(bookings.astype(int), cancel_rate)

        daily.append(pd.DataFrame(dict(
            date=hist_dates, item_id=it.item_id, searches=searches.astype(int), bookings=bookings.astype(int),
            sold_out=sold_out, avg_sell_price=np.round(price, 0), cancellations=cancels,
        )))
        truth.append(pd.DataFrame(dict(date=hist_dates, item_id=it.item_id, true_demand=true_dem,
                                       expected_demand=np.round(mean_dem, 3))))

    daily = pd.concat(daily, ignore_index=True)
    truth = pd.concat(truth, ignore_index=True)

    # ---------------- Supplier pre-buy rate quotes (historical) -------------------
    # For each item, travel week and lead time: quoted cost as a multiple of ref price.
    weeks = pd.date_range(HIST_START + pd.Timedelta(days=(7 - HIST_START.dayofweek) % 7), HIST_END, freq="7D")
    cal_idx = calendar.set_index(["destination", "date"])
    quotes = []
    for it in items.itertuples():
        d = DESTINATIONS[it.destination]
        c = cal_idx.loc[it.destination]
        for w in weeks:
            wd = pd.date_range(w, periods=7)
            season = d["season"][w.month - 1]
            hol = c.loc[wd, "holiday_intensity"].mean()
            ev = c.loc[wd, "event_intensity"].mean()
            peak = season * (1 + hol) * (1 + ev)
            base_mult = (1 - it.prebuy_discount) * (1 + 0.18 * (peak - 1))
            for lead in LEAD_OPTIONS:
                urgency = (1 - lead / 120) ** 1.6 * (0.10 + 0.22 * max(peak - 1, 0))
                mult = base_mult * (1 + urgency) * rng.normal(1, 0.02)
                quotes.append((it.item_id, w, lead, round(mult, 4), round(mult * it.ref_price, 0)))
    quotes = pd.DataFrame(quotes, columns=["item_id", "travel_week_start", "lead_days", "cost_multiplier", "quoted_unit_cost"])

    items.to_csv(DATA_DIR / "items.csv", index=False)
    calendar.to_csv(DATA_DIR / "calendar.csv", index=False)
    daily.to_csv(DATA_DIR / "daily.csv", index=False)
    quotes.to_csv(DATA_DIR / "rate_quotes.csv", index=False)
    truth.to_csv(DATA_DIR / "_ground_truth.csv", index=False)
    generate_supplier_data(items)
    print(f"items={len(items)} daily_rows={len(daily):,} quotes={len(quotes):,} "
          f"sold_out_rate={daily.sold_out.mean():.1%}")


if __name__ == "__main__":
    generate()
