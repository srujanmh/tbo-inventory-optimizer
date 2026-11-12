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


def explanation_sections(r: dict) -> list:
    """Structured reasoning for one recommendation: why this item, how much, which supplier,
    what price, and what profit / risk to expect. Every number comes from the plan row."""
    drivers = ", ".join(f"{d['driver'].lower()} ({'+' if d['effect'] >= 0 else ''}{d['effect']:.0f}%)"
                        for d in r.get("drivers", [])[:3])
    ev = f" The week overlaps {', '.join(r['events'])}." if r.get("events") else ""
    so = r.get("sold_out_risk", 0) or 0
    so_txt = (f" It was sold out on {so:.0%} of days in this season in past years, so pre-buying secures stock TBO "
              f"would otherwise lose." if so >= 0.4 else f" Past sold-out rate in this season is {so:.0%}, so the case "
              f"is mainly margin rather than availability.")
    out = [dict(title="Why this item and week",
                text=f"Forecast demand is {r['demand_p50']:.0f} {r['unit']}s (80% range {r['demand_p10']:.0f}–"
                     f"{r['demand_p90']:.0f}), driven mostly by {drivers or 'its normal baseline'}.{ev}{so_txt}")]
    cr = r.get("critical_ratio")
    if cr:
        side = ("an unsold unit loses more than a sold unit earns, so the plan buys cautiously"
                if cr < 0.5 else "a sold unit earns more than an unsold unit loses, so the plan buys generously")
        qty = (f"Buy {r['units']} {r['unit']}s ({_inr(r['investment'])}). Here {side}: the profit-maximising quantity is the "
               f"level that demand exceeds in {1 - cr:.0%} of scenarios (newsvendor critical ratio {cr:.2f})")
    else:
        qty = f"Buy {r['units']} {r['unit']}s ({_inr(r['investment'])})"
    qs = r.get("q_star")
    if qs and r["units"] < qs * 0.95:
        qty += f"; the plan buys less than that level ({qs:.0f}) because the risk setting or budget favours other positions"
    out.append(dict(title="How much", text=qty + f". Expected sell-through is {r['sell_through']:.0%}."))
    sups = [o for o in (r.get("suppliers") or [])]
    if r.get("supplier") and sups:
        others = [o for o in sups if o.get("supplier_id") != r.get("supplier_id")]
        me = next((o for o in sups if o.get("supplier_id") == r.get("supplier_id")), None)
        alt = []
        for o in others:
            if not o.get("eligible"):
                alt.append(f"{o['supplier']} is not eligible ({o.get('reason', 'unavailable')})")
            elif not o.get("viable"):
                alt.append(f"{o['supplier']} would not be profitable (effective cost {_inr(o['effective_cost'])})")
            else:
                alt.append(f"{o['supplier']} would earn {_inr(o.get('exp_profit', 0))} at the best quantity "
                           f"(effective cost {_inr(o['effective_cost'])}, {o['reliability']:.0%} confirmation)")
        rel = r.get("supplier_reliability")
        out.append(dict(title="Which supplier",
                        text=f"{r['supplier']} gives the highest expected profit"
                             + (f" ({_inr(me['exp_profit'])} at its best quantity)" if me and me.get('exp_profit') is not None else "")
                             + f": quoted {_inr(r.get('supplier_cost') or r['unit_cost'])}, "
                             f"{rel:.0%} of allotments confirmed historically, so the effective cost including re-buying "
                             f"unconfirmed units late is {_inr(r['unit_cost'])}/{r['unit']}. " + ("; ".join(alt) + "." if alt else "")))
    pm = r.get("price_mult")
    ptxt = f"Sell at {_inr(r['sell_price'])} vs a market rate of {_inr(r['market_price'])}"
    if pm is not None:
        if pm > 1.001:
            ptxt += f" (+{pm - 1:.0%}): demand is strong enough that the higher margin outweighs the agents lost to cheaper wholesalers"
        elif pm < 0.999:
            ptxt += f" ({pm - 1:.0%}): pricing below market sells more of the pre-bought stock, which pays more than the lost margin"
        else:
            ptxt += " (at market): moving the price either way lowers expected profit"
    out.append(dict(title="Selling price", text=ptxt + "."))
    out.append(dict(title="Timing",
                    text=f"Buy by {r['buy_by']} ({r.get('buy_lead_days', '?')} days before travel). Waiting until the last "
                         f"minute would cost about {_inr(r['cost_if_wait'])}/{r['unit']}, i.e. {_inr(r.get('saving_vs_wait', 0))} more for this position."))
    out.append(dict(title="Profit and risk",
                    text=f"Expected profit {_inr(r['expected_profit'])}. About {r.get('cancel_rate', 0):.0%} of sold units are "
                         f"expected to cancel (cancelled units are not resold) and unsold units are released for a "
                         f"{(r.get('salvage_rate') or 0):.0%} refund — both are already in the profit figure. In the worst 5% of "
                         f"simulated demand scenarios the position makes {_inr(r['worst5_profit'])}."))
    return out


def template_explanation(r: dict) -> str:
    return " ".join(s["text"] for s in explanation_sections(r))


def llm_explanation(r: dict) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    facts = {k: r[k] for k in ["name", "destination", "item_type", "week", "units", "unit", "unit_cost", "investment",
                               "buy_by", "cost_if_wait", "sell_price", "market_price", "demand_p10", "demand_p50",
                               "demand_p90", "expected_profit", "worst5_profit", "sell_through", "sold_out_risk",
                               "cancel_rate", "events", "drivers", "supplier", "supplier_reliability", "price_mult"] if k in r}
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
