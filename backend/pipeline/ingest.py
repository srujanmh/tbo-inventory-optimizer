"""Data contract and ingestion for real (authorized) TBO data.

The prototype ships with a synthetic dataset. To run it on real data, export the tables below
from TBO's booking, supplier and pricing systems, validate them, and retrain:

    python -m pipeline.ingest --source /path/to/export      # validates and copies into backend/data/
    python -m pipeline.train                                  # retrains every model on the new data

The API exposes the same validation at POST /api/data/validate so a file can be checked from the
dashboard before anyone retrains. Nothing in the models depends on the synthetic generator: they
only read these files.
"""
import argparse
import io
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA_DIR, ART_DIR

# column: (type, required, rule)  type in {str, int, float, date, flag}
SCHEMAS = {
    "items": dict(
        file="items.csv", description="Inventory master: one row per hotel or flight route TBO can pre-buy",
        key=["item_id"], source="Product / content catalogue",
        columns=dict(item_id=("str", True, "unique id"), name=("str", True, ""), item_type=("str", True, "Hotel or Flight"),
                     destination=("str", True, ""), tier=("str", True, "e.g. Budget / Midscale / Luxury / Economy"),
                     origin=("str", False, "flights only"), unit=("str", True, "room-night or seat"),
                     ref_price=("float", True, "> 0, typical selling rate in INR"),
                     salvage_rate=("float", True, "0-1, refund share when unsold stock is released"))),
    "daily": dict(
        file="daily.csv", description="Daily demand signals per item: searches, bookings, sold-out flag, price, cancellations",
        key=["date", "item_id"], source="Booking engine + search logs",
        columns=dict(date=("date", True, "YYYY-MM-DD"), item_id=("str", True, "must exist in items"),
                     searches=("int", True, ">= 0"), bookings=("int", True, ">= 0"), sold_out=("flag", True, "0 or 1"),
                     avg_sell_price=("float", True, "> 0, INR"), cancellations=("int", True, "0 to bookings"))),
    "calendar": dict(
        file="calendar.csv", description="Holidays, festivals and destination events (external demand drivers)",
        key=["date", "destination"], source="Public holiday calendars + events feed",
        columns=dict(date=("date", True, ""), destination=("str", True, ""), holiday=("str", False, "name or blank"),
                     holiday_intensity=("float", True, "0 = none, 1 = major"), event=("str", False, "name or blank"),
                     event_intensity=("float", True, "0 = none, 1 = major"))),
    "rate_quotes": dict(
        file="rate_quotes.csv", description="Historical supplier pre-buy quotes by lead time",
        key=["item_id", "travel_week_start", "lead_days"], source="Contracting / supplier rate feeds",
        columns=dict(item_id=("str", True, ""), travel_week_start=("date", True, "Monday of travel week"),
                     lead_days=("int", True, "days before travel"), cost_multiplier=("float", True, "> 0, quote / ref_price"),
                     quoted_unit_cost=("float", True, "> 0, INR"))),
    "suppliers": dict(
        file="suppliers.csv", description="Supplier master", key=["supplier_id"], source="Supplier management",
        columns=dict(supplier_id=("str", True, ""), supplier=("str", True, ""), item_type=("str", True, "Hotel or Flight"),
                     min_lead_days=("int", True, ">= 0"), free_release_days=("int", True, ">= 0"))),
    "supplier_history": dict(
        file="supplier_history.csv", description="Allotment requests and what each supplier offered, confirmed and refunded",
        key=None, source="Procurement / allotment system",
        columns=dict(request_date=("date", True, ""), item_id=("str", True, ""), supplier_id=("str", True, ""),
                     lead_days=("int", True, ""), units_requested=("int", True, "> 0"), units_offered=("int", True, "<= requested"),
                     units_confirmed=("int", True, "<= offered"), quoted_unit_cost=("float", True, "> 0"),
                     benchmark_unit_cost=("float", True, "> 0"), units_released=("int", True, "<= confirmed"),
                     refund_amount=("float", True, ">= 0"))),
}


def contract():
    return [dict(kind=k, file=v["file"], description=v["description"], source=v["source"], key=v["key"],
                 columns=[dict(name=c, type=t, required=r, rule=rule) for c, (t, r, rule) in v["columns"].items()])
            for k, v in SCHEMAS.items()]


def validate(df: pd.DataFrame, kind: str, known_items=None) -> dict:
    sch = SCHEMAS[kind]
    issues, warnings = [], []
    cols = sch["columns"]
    missing = [c for c, (_, req, _) in cols.items() if req and c not in df.columns]
    if missing:
        issues.append(f"missing required columns: {', '.join(missing)}")
    extra = [c for c in df.columns if c not in cols]
    if extra:
        warnings.append(f"ignored extra columns: {', '.join(extra[:8])}")
    for c, (t, req, _) in cols.items():
        if c not in df.columns:
            continue
        s = df[c]
        nulls = int(s.isna().sum()) if t != "str" else int((s.isna() | (s.astype(str).str.strip() == "")).sum())
        if req and nulls and t != "str" or (req and t == "str" and nulls):
            issues.append(f"{c}: {nulls} empty values")
        if t == "date":
            bad = int(pd.to_datetime(s, errors="coerce").isna().sum() - s.isna().sum())
            if bad:
                issues.append(f"{c}: {bad} values are not dates")
        elif t in ("int", "float", "flag"):
            num = pd.to_numeric(s, errors="coerce")
            bad = int(num.isna().sum() - s.isna().sum())
            if bad:
                issues.append(f"{c}: {bad} values are not numbers")
            if (num < 0).any():
                issues.append(f"{c}: {int((num < 0).sum())} negative values")
            if t == "flag" and not num.dropna().isin([0, 1]).all():
                issues.append(f"{c}: must be 0 or 1")
    if not issues:
        if sch["key"] and df.duplicated(sch["key"]).any():
            issues.append(f"{int(df.duplicated(sch['key']).sum())} duplicate rows on key {sch['key']}")
        if kind == "daily":
            if (df.cancellations > df.bookings).any():
                issues.append("cancellations exceed bookings on some rows")
            if (df.bookings > df.searches).mean() > 0.05:
                warnings.append("bookings exceed searches on >5% of rows - check the search log join")
            dates = pd.to_datetime(df.date)
            span = (dates.max() - dates.min()).days
            if span < 365 + 91:
                warnings.append(f"only {span} days of history; at least 15 months are needed for year-over-year features")
        if kind == "supplier_history":
            if (df.units_confirmed > df.units_offered).any() or (df.units_offered > df.units_requested).any():
                issues.append("confirmed <= offered <= requested is violated on some rows")
        if known_items is not None and "item_id" in df.columns and kind != "items":
            unknown = sorted(set(df.item_id.astype(str)) - set(map(str, known_items)))
            if unknown:
                issues.append(f"{len(unknown)} item_ids not in the items master (e.g. {', '.join(unknown[:3])})")
    out = dict(kind=kind, rows=int(len(df)), columns=list(df.columns), ok=not issues, issues=issues, warnings=warnings)
    for c, (t, _, _) in cols.items():
        if t == "date" and c in df.columns:
            d = pd.to_datetime(df[c], errors="coerce")
            out["date_range"] = [str(d.min().date()) if d.notna().any() else None, str(d.max().date()) if d.notna().any() else None]
            break
    if "item_id" in df.columns:
        out["items"] = int(df.item_id.nunique())
    return out


def validate_csv_text(text: str, kind: str) -> dict:
    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception as e:  # malformed CSV
        return dict(kind=kind, ok=False, rows=0, issues=[f"could not parse CSV: {e}"], warnings=[])
    src = DATA_DIR / "items.csv" if (DATA_DIR / "items.csv").exists() else ART_DIR / "items_enriched.csv"
    known = pd.read_csv(src).item_id if src.exists() and kind != "items" else None
    return validate(df, kind, known)


def ingest(source: Path, dest: Path = DATA_DIR) -> list:
    reports = []
    items = pd.read_csv(source / SCHEMAS["items"]["file"]) if (source / SCHEMAS["items"]["file"]).exists() else None
    for kind, sch in SCHEMAS.items():
        f = source / sch["file"]
        if not f.exists():
            reports.append(dict(kind=kind, ok=False, issues=[f"{sch['file']} not found"], warnings=[]))
            continue
        reports.append(validate(pd.read_csv(f), kind, None if items is None else items.item_id))
    if all(r["ok"] for r in reports):
        dest.mkdir(parents=True, exist_ok=True)
        for sch in SCHEMAS.values():
            shutil.copy(source / sch["file"], dest / sch["file"])
    return reports


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Validate and load a TBO data export")
    ap.add_argument("--source", required=True, type=Path)
    args = ap.parse_args()
    rep = ingest(args.source)
    for r in rep:
        print(("OK   " if r["ok"] else "FAIL ") + r["kind"], "; ".join(r["issues"] + r["warnings"]))
    print("Copied into backend/data/. Now run: python -m pipeline.train" if all(r["ok"] for r in rep)
          else "Fix the issues above; nothing was copied.")
