"""Plain-English explanations of a recommendation.

Always produces a deterministic template explanation (works offline). If ANTHROPIC_API_KEY
is set, also asks Claude to write a short analyst-style rationale from the same facts."""
import json
import os
import urllib.request


def _inr(x):
    x = float(x)
    if abs(x) >= 1e7:
        return f"₹{x / 1e7:.2f} Cr"
    if abs(x) >= 1e5:
        return f"₹{x / 1e5:.1f} L"
    return f"₹{x:,.0f}"


def template_explanation(r: dict) -> str:
    drivers = ", ".join(f"{d['driver'].lower()} ({'+' if d['effect'] >= 0 else ''}{d['effect']:.0f}%)"
                        for d in r.get("drivers", [])[:3])
    ev = f" The week overlaps {', '.join(r['events'])}." if r.get("events") else ""
    so = r.get("sold_out_risk", 0)
    so_txt = (f"In this season the property/route was sold out on {so:.0%} of days historically, so pre-buying "
              f"secures inventory TBO would otherwise lose." if so >= 0.4 else
              f"Historical sold-out rate in this window is {so:.0%}, so the case is mainly margin, not availability.")
    lines = [
        f"Buy {r['units']} {r['unit']}s of {r['name']} ({r['destination']}) for the week of {r['week']} "
        f"at {_inr(r['unit_cost'])}/{r['unit']} — total {_inr(r['investment'])}. Purchase by {r['buy_by']}; "
        f"waiting until the last minute would cost about {_inr(r['cost_if_wait'])}/{r['unit']}.",
        f"Forecast demand is {r['demand_p50']:.0f} (range {r['demand_p10']:.0f}–{r['demand_p90']:.0f}) for the week, "
        f"driven mostly by {drivers}.{ev}",
        so_txt,
        f"Recommended selling price {_inr(r['sell_price'])} vs market {_inr(r['market_price'])}. Expected profit "
        f"{_inr(r['expected_profit'])} with {r['sell_through']:.0%} expected sell-through; in the worst 5% of "
        f"scenarios profit is {_inr(r['worst5_profit'])}.",
    ]
    return " ".join(lines)


def llm_explanation(r: dict) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    facts = {k: r[k] for k in ["name", "destination", "item_type", "week", "units", "unit", "unit_cost", "investment",
                               "buy_by", "cost_if_wait", "sell_price", "market_price", "demand_p10", "demand_p50",
                               "demand_p90", "expected_profit", "worst5_profit", "sell_through", "sold_out_risk",
                               "cancel_rate", "events", "drivers"] if k in r}
    prompt = ("You are an inventory analyst at TBO.com, a B2B travel distributor. In at most 90 words, explain to a "
              "procurement manager why the system recommends this pre-buy, and name the single biggest risk. "
              "Use INR (crore/lakh). Facts (JSON):\n" + json.dumps(facts, default=str))
    body = json.dumps({"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 300,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return "".join(b.get("text", "") for b in data.get("content", []))
    except Exception as e:  # never break the dashboard because of the LLM
        return f"(LLM explanation unavailable: {e})"
