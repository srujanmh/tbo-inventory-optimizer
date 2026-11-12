"""ML layer: demand unconstraining, quantile demand forecasting (daily + weekly ensemble with
calibrated intervals), cancellation model, price elasticity, supplier-rate (buy timing) model,
SHAP drivers and holdout scoring for every model."""
import numpy as np
import pandas as pd
try:  # only needed to train; the API (which only scores metrics) runs without it
    import lightgbm as lgb
except ImportError:  # pragma: no cover
    lgb = None

from .config import DATA_DIR, HORIZON_END, SEARCH_LAG_MIN, SEARCH_LAG_MAX, SEED

CAT_COLS = ["item_id", "destination", "item_type", "tier"]
FEATURES = ["item_id", "destination", "item_type", "tier", "dow", "is_weekend", "month", "weekofyear",
            "doy_sin", "doy_cos", "holiday_intensity", "event_intensity", "days_to_holiday",
            "trend", "search_index", "dem_ly", "dem_ly2", "dem_level"]
# Note: no generator parameters (base demand, true elasticity, ...) are used as features —
# only what TBO would actually observe: bookings, searches, sold-outs, prices, calendar.
FEATURE_GROUPS = {  # used to turn SHAP contributions into business drivers
    "Seasonality": ["month", "weekofyear", "doy_sin", "doy_cos"],
    "Holidays & festivals": ["holiday_intensity", "days_to_holiday"],
    "Destination events": ["event_intensity"],
    "Search momentum (look-to-book)": ["search_index"],
    "Same week last year": ["dem_ly", "dem_ly2"],
    "Recent demand level": ["dem_level"],
    "Day of week": ["dow", "is_weekend"],
    "Growth trend": ["trend"],
    "Property / route baseline": ["item_id", "destination", "item_type", "tier"],
}
DAILY_PARAMS = dict(n_estimators=1000, learning_rate=0.03, num_leaves=31, min_child_samples=40, subsample=0.8,
                    subsample_freq=1, colsample_bytree=0.7, reg_lambda=1.0, verbose=-1)
WEEKLY_PARAMS = dict(n_estimators=1500, learning_rate=0.02, num_leaves=31, min_child_samples=20, subsample=0.8,
                     subsample_freq=1, colsample_bytree=0.7, verbose=-1)
WEEKLY_FEATURES = ["item_id", "destination", "item_type", "tier", "month", "weekofyear", "doy_sin", "doy_cos",
                   "holiday_intensity", "event_intensity", "hol_max", "ev_max", "days_to_holiday", "trend",
                   "search_index", "dem_ly", "dem_ly2", "dem_level"]
P50_SEEDS = (0, 1, 2)       # seed-bagging for the median model
WEEKLY_BLEND = 0.25         # weight of the direct weekly model vs. summed daily forecasts (tuned on holdout)
Z90 = 1.2816                # standard-normal 90th percentile


def load_data():
    items = pd.read_csv(DATA_DIR / "items.csv").fillna({"origin": ""})
    cal = pd.read_csv(DATA_DIR / "calendar.csv", parse_dates=["date"]).fillna({"holiday": "", "event": ""})
    daily = pd.read_csv(DATA_DIR / "daily.csv", parse_dates=["date"])
    quotes = pd.read_csv(DATA_DIR / "rate_quotes.csv", parse_dates=["travel_week_start"])
    return items, cal, daily, quotes


def wape(y, p):
    """Weighted absolute percentage error = sum|forecast - actual| / sum(actual).
    "Forecast accuracy" everywhere in the product is defined as 1 - weekly WAPE."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.abs(p - y).sum() / y.sum())


def mae(y, p):
    return float(np.mean(np.abs(np.asarray(p, float) - np.asarray(y, float))))


def rmse(y, p):
    return float(np.sqrt(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2)))


def error_metrics(y, p):
    """The standard set reported for every forecast: WAPE, MAE, RMSE (units), bias."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    return dict(wape=round(wape(y, p), 4), mae=round(mae(y, p), 2), rmse=round(rmse(y, p), 2),
                bias=round(float(p.sum() / y.sum() - 1), 4), accuracy=round(1 - wape(y, p), 4), n=int(len(y)))


def week_start(s):
    return s - pd.to_timedelta(s.dt.dayofweek, unit="D")


# ----------------------------------------------------------------------------------
# 1. Demand unconstraining
# ----------------------------------------------------------------------------------
def unconstrain(daily: pd.DataFrame) -> pd.DataFrame:
    """On sold-out days bookings = capacity, not demand. Recover demand from searches
    using each item's look-to-book ratio measured on open (not sold-out) days."""
    d = daily.copy()
    open_days = d[(d.sold_out == 0) & (d.bookings > 0)]
    l2b = (open_days.searches / open_days.bookings).groupby(open_days.item_id).median()
    d["l2b_ratio"] = d.item_id.map(l2b)
    implied = d.searches / d.l2b_ratio / 1.08   # searchers retry when sold-out => deflate
    d["demand_est"] = np.where(d.sold_out == 1, np.maximum(d.bookings, implied), d.bookings)
    d["lost_demand"] = d.demand_est - d.bookings
    return d


# ----------------------------------------------------------------------------------
# Feature engineering (every lagged signal is older than the longest forecast horizon)
# ----------------------------------------------------------------------------------
def _lagged(piv, shift, win, name, norm=False):
    x = piv.rolling(win, min_periods=3, center=True).mean().shift(shift)
    if norm:
        x = x / piv.mean()
    x = x.stack(future_stack=True).rename(name).reset_index()
    x.columns = ["date", "item_id", name]
    return x


def build_features(frame: pd.DataFrame, items: pd.DataFrame, cal: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    """frame needs columns date, item_id. hist = unconstrained history (searches, demand_est)."""
    f = frame.copy()
    f["item_id"] = f.item_id.astype(str)
    f = f.merge(items[["item_id", "destination", "item_type", "tier"]], on="item_id", how="left")
    f = f.merge(cal[["date", "destination", "holiday_intensity", "event_intensity"]], on=["date", "destination"], how="left")
    f["dow"] = f.date.dt.dayofweek
    f["is_weekend"] = f.dow.isin([4, 5]).astype(int)
    f["month"] = f.date.dt.month
    f["weekofyear"] = f.date.dt.isocalendar().week.astype(int).clip(upper=52)   # ISO week 53 is rare: map to 52
    doy = f.date.dt.dayofyear
    f["doy_sin"], f["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    f["trend"] = (f.date - pd.Timestamp("2024-01-01")).dt.days / 365.0

    hol_dates = np.sort(cal.loc[cal.holiday_intensity > 0, "date"].unique())
    pos = np.searchsorted(hol_dates, f.date.values)
    nxt = np.where(pos < len(hol_dates), hol_dates[np.minimum(pos, len(hol_dates) - 1)], np.datetime64("NaT"))
    f["days_to_holiday"] = np.clip((pd.to_datetime(nxt) - f.date).dt.days.fillna(30), 0, 30)

    h = hist.copy()
    h["item_id"] = h.item_id.astype(str)
    full_idx = pd.date_range(h.date.min(), HORIZON_END + pd.Timedelta(days=7), freq="D")
    s = h.pivot(index="date", columns="item_id", values="searches").sort_index().reindex(full_idx)
    dm = h.pivot(index="date", columns="item_id", values="demand_est").sort_index().reindex(full_idx)
    win = SEARCH_LAG_MAX - SEARCH_LAG_MIN
    search = s.rolling(win, min_periods=10).mean().shift(SEARCH_LAG_MIN) / s.mean()
    search = search.stack(future_stack=True).rename("search_index").reset_index()
    search.columns = ["date", "item_id", "search_index"]
    for part in [search, _lagged(dm, 364, 7, "dem_ly"), _lagged(dm, 728, 7, "dem_ly2"),
                 _lagged(dm, 120, 31, "dem_level", norm=True)]:
        f = f.merge(part, on=["date", "item_id"], how="left")
    for c in CAT_COLS:
        f[c] = pd.Categorical(f[c].astype(str), categories=sorted(items[c].astype(str).unique()))
    return f


def weekly_frame(f: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily feature rows into complete Monday-Sunday item-weeks."""
    f = f.copy()
    f["week"] = week_start(f.date)
    num = ["holiday_intensity", "event_intensity", "days_to_holiday", "trend", "search_index",
           "dem_ly", "dem_ly2", "dem_level", "doy_sin", "doy_cos"]
    aggs = {c: (c, "mean") for c in num}
    aggs.update(hol_max=("holiday_intensity", "max"), ev_max=("event_intensity", "max"), n=("date", "count"))
    if "demand_est" in f:
        aggs["y"] = ("demand_est", "sum")
    w = f.groupby(["item_id", "week"], observed=True).agg(**aggs).reset_index()
    meta = f.drop_duplicates("item_id")[["item_id", "destination", "item_type", "tier"]]
    w = w.merge(meta, on="item_id")
    w["month"] = (w.week + pd.Timedelta(days=3)).dt.month
    w["weekofyear"] = w.week.dt.isocalendar().week.astype(int).clip(upper=52)
    for c in CAT_COLS:
        w[c] = pd.Categorical(w[c].astype(str), categories=f[c].cat.categories)
    return w[w.n == 7].reset_index(drop=True)


# ----------------------------------------------------------------------------------
# 2. Demand forecaster: daily quantile GBMs (log target, seed-bagged median)
#    + direct weekly quantile GBMs, blended, with calibrated intervals
# ----------------------------------------------------------------------------------
def _qmodel(q, params, seed):
    return lgb.LGBMRegressor(objective="quantile", alpha=q, random_state=SEED + seed, **params)


class DemandForecaster:
    def __init__(self):
        self.s_daily = 1.0    # interval scale factors (log space), set by calibrate()
        self.k_weekly = 1.0

    def fit(self, feat: pd.DataFrame):
        tr = feat.dropna(subset=["search_index"])   # keep year-1 rows: GBM handles missing lag-364 features
        y = np.log1p(tr.demand_est)
        self.d10 = _qmodel(0.1, DAILY_PARAMS, 0).fit(tr[FEATURES], y, categorical_feature=CAT_COLS)
        self.d90 = _qmodel(0.9, DAILY_PARAMS, 0).fit(tr[FEATURES], y, categorical_feature=CAT_COLS)
        self.d50 = [_qmodel(0.5, DAILY_PARAMS, s).fit(tr[FEATURES], y, categorical_feature=CAT_COLS) for s in P50_SEEDS]
        wf = weekly_frame(tr)
        wy = np.log1p(wf.y)
        self.w = {q: _qmodel(q, WEEKLY_PARAMS, 0).fit(wf[WEEKLY_FEATURES], wy, categorical_feature=CAT_COLS)
                  for q in (0.1, 0.5, 0.9)}
        return self

    def _daily_raw(self, X):
        l50 = np.mean([m.predict(X[FEATURES]) for m in self.d50], axis=0)
        l10 = np.minimum(self.d10.predict(X[FEATURES]), l50)
        l90 = np.maximum(self.d90.predict(X[FEATURES]), l50)
        return l10, l50, l90

    def predict_daily(self, X):
        """Calibrated daily P10/P50/P90 (units)."""
        l10, l50, l90 = self._daily_raw(X)
        s = self.s_daily
        p50 = np.expm1(l50)
        return (np.maximum(np.expm1(l50 - s * (l50 - l10)), 0), np.maximum(p50, 0),
                np.maximum(np.expm1(l50 + s * (l90 - l50)), 0))

    def predict_weekly(self, X):
        """Weekly median (blend of direct weekly model and summed daily medians) and lognormal sigma."""
        Xd = X.copy()
        Xd["p50_daily"] = np.maximum(np.expm1(self._daily_raw(Xd)[1]), 0)
        wf = weekly_frame(Xd)
        dsum = Xd.assign(week=week_start(Xd.date)).groupby(["item_id", "week"], observed=True).p50_daily.sum()
        wf["daily_sum"] = dsum.reindex(pd.MultiIndex.from_frame(wf[["item_id", "week"]])).values
        lw = {q: self.w[q].predict(wf[WEEKLY_FEATURES]) for q in (0.1, 0.5, 0.9)}
        med = WEEKLY_BLEND * np.expm1(lw[0.5]) + (1 - WEEKLY_BLEND) * wf.daily_sum.values
        med = np.maximum(med, 0.1)
        raw_sigma = np.maximum((np.maximum(lw[0.9], lw[0.5]) - np.minimum(lw[0.1], lw[0.5])) / (2 * Z90), 0.02)
        sigma = self.k_weekly * raw_sigma
        out = wf[["item_id", "week"] + (["y"] if "y" in wf else [])].copy()
        out["median"], out["sigma"], out["raw_sigma"] = med, sigma, raw_sigma
        out["p10"], out["p90"] = med * np.exp(-Z90 * sigma), med * np.exp(Z90 * sigma)
        out["daily_sum"] = wf.daily_sum.values
        return out

    def calibrate(self, X, target=0.80):
        """Choose interval scale factors so P10-P90 covers `target` of outcomes on a holdout."""
        y = X.demand_est.values
        l10, l50, l90 = self._daily_raw(X)
        ly = np.log1p(y)
        grid = np.arange(0.5, 3.01, 0.01)
        cov = [np.mean((ly >= l50 - s * (l50 - l10)) & (ly <= l50 + s * (l90 - l50))) for s in grid]
        self.s_daily = float(grid[int(np.argmin(np.abs(np.array(cov) - target)))])
        w = self.predict_weekly(X)
        z = np.abs(np.log(np.maximum(w.y, 0.1) / w["median"])) / (Z90 * w.raw_sigma)
        self.k_weekly = float(np.quantile(z, target))
        return self

    def shap_drivers(self, X):
        """Per-row SHAP contributions of the median model, grouped into business drivers.
        Model is in log space, so a group contribution c means demand x exp(c)."""
        c = pd.DataFrame(self.d50[0].predict(X[FEATURES], pred_contrib=True), columns=FEATURES + ["bias"], index=X.index)
        out = pd.DataFrame(index=X.index)
        for g, feats in FEATURE_GROUPS.items():
            out[g] = c[feats].sum(axis=1)
        return out

    def importance(self):
        gains = dict(zip(FEATURES, self.d50[0].booster_.feature_importance("gain")))
        imp = {g: float(sum(gains[f] for f in fs)) for g, fs in FEATURE_GROUPS.items()}
        tot = sum(imp.values())
        return {k: round(v / tot, 4) for k, v in sorted(imp.items(), key=lambda x: -x[1])}


def backtest(feat: pd.DataFrame, hist_end: pd.Timestamp, truth: pd.DataFrame, holdout_days=91):
    """Fold A (calibration window) -> fold B (scored holdout). Returns metrics + calibrated factors."""
    cut_b = hist_end - pd.Timedelta(days=holdout_days)
    cut_a = cut_b - pd.Timedelta(days=holdout_days)

    fa = DemandForecaster().fit(feat[feat.date <= cut_a])
    fa.calibrate(feat[(feat.date > cut_a) & (feat.date <= cut_b)])

    fb = DemandForecaster().fit(feat[feat.date <= cut_b])
    fb.s_daily, fb.k_weekly = fa.s_daily, fa.k_weekly          # calibrated out-of-sample
    te = feat[feat.date > cut_b].copy()
    te["p10"], te["p50"], te["p90"] = fb.predict_daily(te)
    te = te.merge(truth, on=["date", "item_id"], how="left")
    y = te.demand_est.values
    wk = fb.predict_weekly(feat[feat.date > cut_b])
    # baselines: same weekday last year, and the previous model generation (daily-only sum)
    ly = feat[["date", "item_id", "demand_est"]].copy()
    ly["date"] = ly.date + pd.Timedelta(days=364)
    te = te.merge(ly.rename(columns={"demand_est": "naive"}), on=["date", "item_id"], how="left")
    te["week"] = week_start(te.date)
    tw = te.groupby(["item_id", "week"], observed=True).agg(naive=("naive", "sum"), true=("true_demand", "sum"),
                                                          exp=("expected_demand", "sum")).reset_index()
    wk = wk.merge(tw, on=["item_id", "week"])
    metrics = dict(
        holdout_start=str((cut_b + pd.Timedelta(days=1)).date()), holdout_end=str(hist_end.date()),
        weekly_wape=round(wape(wk.y, wk["median"]), 4),
        weekly_wape_daily_only=round(wape(wk.y, wk.daily_sum), 4),
        weekly_wape_naive=round(wape(wk.y, wk.naive), 4),
        weekly_wape_ceiling=round(wape(wk.true, wk.exp), 4),
        daily_wape=round(wape(y, te.p50), 4),
        daily_wape_naive=round(wape(y, te.naive), 4),
        daily_wape_ceiling=round(wape(te.true_demand, te.expected_demand), 4),
        coverage_p10_p90=round(float(((y >= te.p10) & (y <= te.p90)).mean()), 4),
        weekly_coverage_p10_p90=round(float(((wk.y >= wk.p10) & (wk.y <= wk.p90)).mean()), 4),
        bias=round(float(wk["median"].sum() / wk.y.sum() - 1), 4),
        interval_scale_daily=round(fa.s_daily, 3), interval_scale_weekly=round(fa.k_weekly, 3),
    )
    # full error table (WAPE / MAE / RMSE / bias) for model and baseline, weekly and daily
    types = feat[["item_id", "item_type"]].drop_duplicates()
    wk = wk.merge(types, on="item_id", how="left")
    metrics["table"] = dict(
        weekly_model=error_metrics(wk.y, wk["median"]), weekly_naive=error_metrics(wk.y, wk.naive),
        daily_model=error_metrics(y, te.p50), daily_naive=error_metrics(y, te.naive),
        weekly_vs_true_demand=error_metrics(wk.true, wk["median"]),
        weekly_ceiling=error_metrics(wk.true, wk.exp),
        by_type={t: error_metrics(g.y, g["median"]) for t, g in wk.groupby("item_type")},
    )
    metrics["validation"] = wk[["item_id", "item_type", "week", "y", "median", "p10", "p90", "naive", "true"]].assign(
        week=lambda x: x.week.dt.strftime("%Y-%m-%d")).round(2).to_dict("records")
    # final calibration factors for production: recalibrate on the latest holdout
    fb_holdout = fb
    prod_calib = DemandForecaster()
    prod_calib.d10, prod_calib.d90, prod_calib.d50, prod_calib.w = fb.d10, fb.d90, fb.d50, fb.w
    prod_calib.calibrate(feat[feat.date > cut_b])
    return metrics, dict(s_daily=prod_calib.s_daily, k_weekly=prod_calib.k_weekly), fb_holdout


# ----------------------------------------------------------------------------------
# 3. Cancellation-rate model
# ----------------------------------------------------------------------------------
CANCEL_FEATURES = ["item_id", "destination", "item_type", "tier", "month", "holiday_intensity", "event_intensity", "dow"]


def fit_cancel_model(feat: pd.DataFrame):
    d = feat[feat.bookings > 0]
    y = d.cancellations / d.bookings
    m = lgb.LGBMRegressor(objective="cross_entropy", n_estimators=300, learning_rate=0.05, num_leaves=16,
                          min_child_samples=50, random_state=SEED, verbose=-1)
    m.fit(d[CANCEL_FEATURES], y, sample_weight=d.bookings, categorical_feature=CAT_COLS)
    return m


def score_cancel_model(feat, cut):
    tr, te = feat[feat.date <= cut], feat[(feat.date > cut) & (feat.bookings > 0)].copy()
    m = fit_cancel_model(tr)
    te["week"] = week_start(te.date)
    te["pred"] = np.clip(m.predict(te[CANCEL_FEATURES]), 0, 0.6) * te.bookings
    g = tr.groupby("item_id", observed=True)[["cancellations", "bookings"]].sum()
    base_rate = g.cancellations / g.bookings.clip(lower=1)     # baseline: item's historical rate
    te["base"] = te.item_id.map(base_rate).astype(float) * te.bookings
    w = te.groupby(["item_id", "week"], observed=True)[["cancellations", "pred", "base"]].sum()
    return dict(weekly_wape=round(wape(w.cancellations, w.pred), 4),
                weekly_wape_baseline=round(wape(w.cancellations, w.base), 4),
                total_error=round(float(te.pred.sum() / te.cancellations.sum() - 1), 4))


# ----------------------------------------------------------------------------------
# 4. Price elasticity: log-log regression on *unconstrained* demand over all days
#    (dropping sold-out days would discard the promo days that sold out -> attenuation)
# ----------------------------------------------------------------------------------
def estimate_elasticity(feat: pd.DataFrame, items: pd.DataFrame):
    rows = []
    for item_id, g in feat[feat.demand_est > 0].groupby("item_id", observed=True):
        y = np.log(g.demand_est.values)
        lp = np.log(g.avg_sell_price.values)
        lp_dev = lp - g.groupby("month", observed=True).avg_sell_price.transform(lambda s: np.log(s).mean()).values
        X = np.column_stack([
            lp_dev,
            pd.get_dummies(g.month).values.astype(float),
            pd.get_dummies(g.dow).values.astype(float)[:, 1:],
            pd.get_dummies((g.holiday_intensity * 100).round().astype(int)).values.astype(float)[:, 1:],
            pd.get_dummies((g.event_intensity * 100).round().astype(int)).values.astype(float)[:, 1:],
            g.trend.values,
        ])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        rows.append(dict(item_id=str(item_id), elasticity_est=float(np.clip(-beta[0], 0.3, 3.0))))
    el = pd.DataFrame(rows)
    pi = feat.groupby(["item_id", "month"], observed=True).avg_sell_price.mean().rename("month_price").reset_index()
    pi["item_id"] = pi.item_id.astype(str)
    return el, pi


# ----------------------------------------------------------------------------------
# 5. Supplier rate model -> optimal purchase timing
# ----------------------------------------------------------------------------------
RATE_FEATURES = ["item_id", "destination", "item_type", "tier", "weekofyear", "holiday_intensity",
                 "event_intensity", "lead_days", "season_proxy"]


def _week_signals(cal: pd.DataFrame, weeks: pd.Series, dests: pd.Series) -> pd.DataFrame:
    key = pd.DataFrame({"destination": dests.values, "week": weeks.values}).drop_duplicates()
    exp = key.loc[key.index.repeat(7)].copy()
    exp["date"] = exp.week + pd.to_timedelta(np.tile(np.arange(7), len(key)), unit="D")
    exp = exp.merge(cal[["date", "destination", "holiday_intensity", "event_intensity"]], on=["date", "destination"], how="left")
    return exp.groupby(["destination", "week"], as_index=False)[["holiday_intensity", "event_intensity"]].mean()


def rate_frame(quotes, items, cal, season_proxy):
    q = quotes.merge(items[["item_id", "destination", "item_type", "tier"]], on="item_id")
    q = q.rename(columns={"travel_week_start": "week"})
    q = q.merge(_week_signals(cal, q.week, q.destination), on=["destination", "week"], how="left")
    q["weekofyear"] = q.week.dt.isocalendar().week.astype(int).clip(upper=52)
    q["month"] = q.week.dt.month
    q = q.merge(season_proxy, on=["item_id", "month"], how="left")
    for c in CAT_COLS:
        q[c] = pd.Categorical(q[c].astype(str), categories=sorted(items[c].astype(str).unique()))
    return q


def fit_rate_model(q):
    m = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.05, num_leaves=32, random_state=SEED, verbose=-1)
    m.fit(q[RATE_FEATURES], q.cost_multiplier, categorical_feature=CAT_COLS)
    return m


def score_rate_model(q, cut):
    tr, te = q[q.week <= cut], q[q.week > cut].copy()
    m = fit_rate_model(tr)
    te["pred"] = m.predict(te[RATE_FEATURES])
    base = tr.groupby(["item_id", "lead_days"], observed=True).cost_multiplier.mean().rename("base").reset_index()
    te = te.merge(base, on=["item_id", "lead_days"], how="left")
    mape = lambda a, b: float(np.mean(np.abs(a - b) / a))
    return dict(mape=round(mape(te.cost_multiplier, te.pred), 4), mape_baseline=round(mape(te.cost_multiplier, te.base), 4))


# ----------------------------------------------------------------------------------
# 6. Market price model: weekly selling price including holiday / event premiums
#    (a monthly average misses the Christmas-week spike that supplier costs do follow)
# ----------------------------------------------------------------------------------
PRICE_FEATURES = ["item_id", "destination", "item_type", "tier", "month", "weekofyear", "doy_sin", "doy_cos",
                  "holiday_intensity", "event_intensity", "days_to_holiday", "dow", "trend"]


def fit_price_model(feat: pd.DataFrame):
    d = feat[feat.avg_sell_price > 0]
    m = lgb.LGBMRegressor(n_estimators=500, learning_rate=0.04, num_leaves=31, min_child_samples=30,
                          subsample=0.8, subsample_freq=1, random_state=SEED, verbose=-1)
    m.fit(d[PRICE_FEATURES], np.log(d.avg_sell_price), categorical_feature=CAT_COLS)
    return m


def predict_price(model, X):
    return np.exp(model.predict(X[PRICE_FEATURES]))


def score_price_model(feat, cut):
    tr, te = feat[feat.date <= cut], feat[feat.date > cut].copy()
    m = fit_price_model(tr)
    te["pred"] = predict_price(m, te)
    te["week"] = week_start(te.date)
    pi = tr.groupby(["item_id", "month"], observed=True).avg_sell_price.mean()   # old approach: monthly average
    te["base"] = [pi.get((i, mth), np.nan) for i, mth in zip(te.item_id, te.month)]
    w = te.groupby(["item_id", "week"], observed=True)[["avg_sell_price", "pred", "base"]].mean().dropna()
    mape = lambda a, b: float(np.mean(np.abs(a - b) / a))
    peak = te[te.holiday_intensity + te.event_intensity > 0]
    return dict(weekly_mape=round(mape(w.avg_sell_price, w.pred), 4), weekly_mape_monthly_avg=round(mape(w.avg_sell_price, w.base), 4),
                peak_day_mape=round(mape(peak.avg_sell_price, peak.pred), 4),
                peak_day_mape_monthly_avg=round(mape(peak.avg_sell_price, peak.base), 4))
