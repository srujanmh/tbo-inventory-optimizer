// In-browser engine for the static website build.
// Loads precomputed model outputs (site/data.json + site/scen.json) and re-runs the budget
// optimization locally: marginal-value allocation over newsvendor quantity blocks with a
// mean–tail risk objective, budget and destination caps. Verified against the HiGHS MILP
// in the Python backend (within 0.2% on every tested budget / risk setting).

let D = null, S = null, viable = [], tailIdx = null, tailMean = null

async function load() {
  if (D) return
  const base = './site/'
  const [data, scen] = await Promise.all([fetch(base + 'data.json').then((r) => r.json()), fetch(base + 'scen.json').then((r) => r.json())])
  D = data
  const bin = atob(scen.b64), bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  S = new Int16Array(bytes.buffer)
  const ns = D.summary.n_scenarios_web
  viable = D.cands.filter((c) => c.viable).map((c) => ({ ...c, blk: D.blocks[c.cand_id] }))
  // profit (₹) for candidate c at level k, scenario s
  viable.forEach((c) => { c.prof = (k) => S.subarray(c.blk.offset + k * ns, c.blk.offset + (k + 1) * ns) })
  // stress scenarios: worst 10% for a reference portfolio (every candidate near Q*)
  const ref = new Float64Array(ns)
  viable.forEach((c) => {
    let k = 1, best = Infinity
    c.blk.levels.forEach((l, i) => { if (i > 0 && Math.abs(l - c.q_star) < best) { best = Math.abs(l - c.q_star); k = i } })
    const p = c.prof(k); for (let s = 0; s < ns; s++) ref[s] += p[s]
  })
  tailIdx = [...ref.keys()].sort((a, b) => ref[a] - ref[b]).slice(0, Math.max(1, Math.floor(0.1 * ns)))
  // per-block expected and tail marginal profit
  viable.forEach((c) => {
    const L = c.blk.levels.length
    c.bexp = []; c.btail = []
    for (let k = 1; k < L; k++) {
      const a = c.prof(k - 1), b = c.prof(k)
      let e = 0, t = 0
      for (let s = 0; s < ns; s++) e += b[s] - a[s]
      tailIdx.forEach((s) => { t += b[s] - a[s] })
      c.bexp.push((e / ns) * 1000); c.btail.push((t / tailIdx.length) * 1000)
    }
  })
}

const sum = (a) => a.reduce((x, y) => x + y, 0)

function filtered(st) {
  return viable.map((c, i) => [c, i]).filter(([c]) => st.item_types.includes(c.item_type) && (!st.destinations || st.destinations.includes(c.destination)))
}

function evaluate(ksel) {
  const ns = D.summary.n_scenarios_web
  const tot = new Float64Array(ns)
  let invested = 0, units = 0, sold = 0
  viable.forEach((c, i) => {
    const k = ksel[i]; if (!k) return
    const p = c.prof(k); for (let s = 0; s < ns; s++) tot[s] += p[s] * 1000
    invested += k * c.blk.cost; units += c.blk.levels[k]; sold += c.blk.sold[k]
  })
  const srt = Array.from(tot).sort((a, b) => a - b)
  const n5 = Math.max(1, Math.floor(0.05 * ns)), n10 = Math.max(1, Math.floor(0.1 * ns))
  const exp = sum(srt) / ns
  const lo = srt[0], hi = srt[ns - 1], nb = 30, w = (hi - lo) / nb || 1
  const hist = Array.from({ length: nb }, (_, j) => ({ x0: lo + j * w, x1: lo + (j + 1) * w, count: 0 }))
  srt.forEach((v) => { hist[Math.min(nb - 1, Math.floor((v - lo) / w))].count++ })
  return {
    invested, expected_profit: exp, roi: invested ? exp / invested : 0,
    p5: srt[n5 - 1], cvar10: sum(srt.slice(0, n10)) / n10, prob_loss: srt.filter((v) => v < 0).length / ns,
    units, expected_units_sold: sold, sell_through: units ? sold / units : 0, histogram: hist,
  }
}

function solve(st, lam = st.risk_aversion) {
  const B = st.budget
  const cand = filtered(st)
  const nDest = new Set(cand.map(([c]) => c.destination)).size
  const cap = Math.max(st.max_dest_share, 1 / Math.max(nDest, 1)) * B
  const ksel = new Array(viable.length).fill(0)
  const spent = {}
  let left = B
  const score = (c, k) => (1 - lam) * c.bexp[k] + lam * c.btail[k]
  // priority queue (simple binary heap) on value per rupee of each candidate's next block
  const heap = []
  const push = (r, i) => { heap.push([r, i]); let j = heap.length - 1; while (j > 0) { const p = (j - 1) >> 1; if (heap[p][0] >= heap[j][0]) break;[heap[p], heap[j]] = [heap[j], heap[p]]; j = p } }
  const pop = () => { const top = heap[0], last = heap.pop(); if (heap.length) { heap[0] = last; let j = 0; for (;;) { const l = 2 * j + 1, r = l + 1; let m = j; if (l < heap.length && heap[l][0] > heap[m][0]) m = l; if (r < heap.length && heap[r][0] > heap[m][0]) m = r; if (m === j) break;[heap[m], heap[j]] = [heap[j], heap[m]]; j = m } } return top }
  cand.forEach(([c, i]) => { const s = score(c, 0); if (s > 0) push(s / c.blk.cost, i) })
  while (heap.length) {
    const [, i] = pop(); const c = viable[i], k = ksel[i], cost = c.blk.cost, d = c.destination
    if (cost > left || (spent[d] || 0) + cost > cap) continue
    ksel[i]++; left -= cost; spent[d] = (spent[d] || 0) + cost
    if (ksel[i] < c.bexp.length && score(c, ksel[i]) > 0) push(score(c, ksel[i]) / cost, i)
  }
  return ksel
}

function planRows(ksel) {
  const ns = D.summary.n_scenarios_web, n5 = Math.max(1, Math.floor(ns / 20))
  const rows = []
  viable.forEach((c, i) => {
    const k = ksel[i]; if (!k) return
    const p = Array.from(c.prof(k), (v) => v * 1000)
    const q = c.blk.levels[k], sold = c.blk.sold[k]
    rows.push({
      ...c, blk: undefined, prof: undefined, bexp: undefined, btail: undefined,
      units: q, investment: q * c.unit_cost, saving_vs_wait: q * (c.cost_if_wait - c.unit_cost),
      expected_profit: sum(p) / ns, worst5_profit: sum(p.sort((a, b) => a - b).slice(0, n5)) / n5,
      expected_sold: sold, sell_through: sold / q,
    })
  })
  return rows.sort((a, b) => b.expected_profit - a.expected_profit)
}

function group(rows, key, extra = []) {
  const m = {}
  rows.forEach((r) => {
    const g = (m[r[key]] ||= { [key]: r[key], investment: 0, expected_profit: 0, units: 0 })
    g.investment += r.investment; g.expected_profit += r.expected_profit; g.units += r.units
  })
  return Object.values(m)
}

function greedyRoi(st) {
  const ksel = new Array(viable.length).fill(0)
  let left = st.budget
  filtered(st).sort((a, b) => (b[0].roi_at_qstar || 0) - (a[0].roi_at_qstar || 0)).forEach(([c, i]) => {
    if (left <= 0) return
    let kt = 1, best = Infinity
    c.blk.levels.forEach((l, j) => { if (j > 0 && Math.abs(l - c.q_star) < best) { best = Math.abs(l - c.q_star); kt = j } })
    const kf = Math.min(kt, Math.floor(left / c.blk.cost))
    if (kf > 0) { ksel[i] = kf; left -= kf * c.blk.cost }
  })
  return ksel
}

function lastYear(st) {
  const f = filtered(st)
  const tot = sum(f.map(([c]) => c.last_year_revenue || 0))
  const ksel = new Array(viable.length).fill(0)
  f.forEach(([c, i]) => {
    const w = tot > 0 ? (c.last_year_revenue || 0) / tot : 1 / f.length
    ksel[i] = Math.min(c.blk.levels.length - 1, Math.floor((w * st.budget) / c.blk.cost))
  })
  return ksel
}

const strip = (s) => { const { histogram, ...r } = s; return r }

// Same logic as Optimizer.unused_budget on the server: why part of the budget stays uninvested
function unusedBudget(st, ksel, lam = st.risk_aversion) {
  const B = st.budget
  const inFilter = new Set(filtered(st).map(([, i]) => i))
  const nDest = new Set(filtered(st).map(([c]) => c.destination)).size
  const share = Math.max(st.max_dest_share, 1 / Math.max(nDest, 1)), cap = share * B
  const score = (c, k) => (1 - lam) * c.bexp[k] + lam * c.btail[k]
  const destInv = {}
  let invested = 0
  viable.forEach((c, i) => { if (ksel[i]) { const v = ksel[i] * c.blk.cost; invested += v; destInv[c.destination] = (destInv[c.destination] || 0) + v } })
  const left = B - invested
  const buckets = {}
  viable.forEach((c, i) => {
    let nGood = 0
    for (let k = 0; k < c.bexp.length; k++) if (score(c, k) > 0) nGood = k + 1
    const k0 = ksel[i]
    if (k0 >= nGood) return
    const r = !inFilter.has(i) ? 'filtered' : (destInv[c.destination] || 0) + c.blk.cost > cap + 1e-6 ? 'dest_cap' : c.blk.cost > left + 1e-6 ? 'too_big' : 'other'
    const b = (buckets[r] ||= { cost: 0, positions: 0 })
    b.cost += (nGood - k0) * c.blk.cost; b.positions++
  })
  const capped = Object.entries(destInv).filter(([, v]) => v >= cap * 0.995).map(([d]) => d).sort()
  const labels = {
    dest_cap: `Destination limit: ${capped.length ? capped.join(', ') : 'some destinations'} already hold the maximum ${Math.round(share * 100)}% of the budget, so more profitable stock there is not bought (diversification rule)`,
    too_big: 'Leftover is smaller than the next quantity block of any remaining profitable position',
    filtered: 'Profitable options exist but are excluded by the inventory-type or destination filters',
    other: 'Allocation granularity: the in-browser allocator buys whole quantity blocks',
  }
  const reasons = Object.entries(buckets).map(([code, b]) => ({ code, label: labels[code], blocked_cost: b.cost, positions: b.positions }))
    .sort((a, b) => b.blocked_cost - a.blocked_cost)
  let summary
  if (left <= 0.01 * B) summary = 'The budget is fully used.'
  else if (!reasons.some((r) => r.code !== 'filtered')) {
    const f = reasons.find((r) => r.code === 'filtered')
    summary = f ? `Every option inside your filters is already bought up to its profitable limit. Another ₹${(f.blocked_cost / 1e7).toFixed(1)} Cr of profitable inventory exists outside the selected inventory types or destinations; widen the filters to use the rest of the budget.`
      : 'Every available position is already bought up to the point where one more unit stops paying: past that point the expected profit after cancellations, unsold-stock losses and the risk penalty is zero or negative, so investing the rest would lower profit. Keeping it uninvested is the optimal decision.'
  } else summary = reasons[0].label + '.'
  return { unused: left, unused_share: left / B, summary, reasons, capped_destinations: capped, destination_cap: cap }
}

export const engine = {
  async summary() { await load(); return D.summary },
  async items() { await load(); return D.items },
  async opportunities(limit = 15) {
    await load()
    return D.cands.filter((c) => c.viable).sort((a, b) => b.opportunity_score - a.opportunity_score).slice(0, limit)
  },
  async forecast(id) {
    await load()
    const f = D.forecasts[id]
    return {
      item: D.items.find((i) => i.item_id === id),
      history: f.history.map(([date, bookings, demand_est, sold_out]) => ({ date, bookings, demand_est, sold_out })),
      forecast: f.forecast.map(([date, p10, p50, p90, cancel_rate]) => ({ date, p10, p50, p90, cancel_rate })),
      weeks: D.cands.filter((c) => c.item_id === id),
    }
  },
  async optimize(st) {
    await load()
    const ksel = solve(st)
    const stats = evaluate(ksel)
    const plan = planRows(ksel)
    const byDest = group(plan, 'destination').sort((a, b) => b.investment - a.investment)
    const byWeek = group(plan, 'week').sort((a, b) => (a.week < b.week ? -1 : 1))
    Object.assign(stats, {
      budget: st.budget, budget_used: stats.invested / st.budget, risk_aversion: st.risk_aversion, status: 'Optimal (in-browser)',
      n_positions: plan.length, saving_vs_wait: sum(plan.map((r) => r.saving_vs_wait)),
      units_in_soldout_windows: sum(plan.filter((r) => r.sold_out_risk >= 0.5).map((r) => r.expected_sold)),
    })
    return {
      stats, plan, by_destination: byDest, by_week: byWeek, unused_budget: unusedBudget(st, ksel),
      baselines: { greedy_roi_ranking: strip(evaluate(greedyRoi(st))), last_year_proportional: strip(evaluate(lastYear(st))) },
    }
  },
  async frontier(st) {
    await load()
    return [0, 0.2, 0.4, 0.6, 0.8, 0.95].map((lam) => {
      const s = evaluate(solve(st, lam))
      return { risk_aversion: lam, expected_profit: s.expected_profit, cvar10: s.cvar10, p5: s.p5, prob_loss: s.prob_loss, invested: s.invested, roi: s.roi }
    })
  },
  async budgetCurve(st) {
    await load()
    return [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2].map((f) => {
      const B = st.budget * f, s = evaluate(solve({ ...st, budget: B }))
      return { budget: B, expected_profit: s.expected_profit, invested: s.invested, roi: s.roi, cvar10: s.cvar10 }
    })
  },
  async explain(r) { const sections = explainSections(r); return { explanation: sections.map((x) => x.text).join(' '), sections, llm: null } },
  async suppliers() { await load(); return D.extra.suppliers },
  async validation() { await load(); return D.extra.validation },
  async contract() { await load(); return D.extra.contract },
  async verification() { await load(); return D.extra.verification },
}

const inr = (x) => {
  const a = Math.abs(x)
  if (a >= 1e7) return `₹${(x / 1e7).toFixed(2)} Cr`
  if (a >= 1e5) return `₹${(x / 1e5).toFixed(1)} L`
  return `₹${Math.round(x).toLocaleString('en-IN')}`
}

// JS port of pipeline/explain.py explanation_sections (keeps the static site self-contained)
function explainSections(r) {
  const pctS = (v) => `${Math.round(v * 100)}%`
  const drivers = (r.drivers || []).slice(0, 3).map((d) => `${d.driver.toLowerCase()} (${d.effect >= 0 ? '+' : ''}${d.effect.toFixed(0)}%)`).join(', ')
  const ev = r.events?.length ? ` The week overlaps ${r.events.join(', ')}.` : ''
  const so = r.sold_out_risk || 0
  const soTxt = so >= 0.4 ? ` It was sold out on ${pctS(so)} of days in this season in past years, so pre-buying secures stock TBO would otherwise lose.`
    : ` Past sold-out rate in this season is ${pctS(so)}, so the case is mainly margin rather than availability.`
  const out = [{ title: 'Why this item and week', text: `Forecast demand is ${Math.round(r.demand_p50)} ${r.unit}s (80% range ${Math.round(r.demand_p10)}–${Math.round(r.demand_p90)}), driven mostly by ${drivers || 'its normal baseline'}.${ev}${soTxt}` }]
  const cr = r.critical_ratio
  let qty = `Buy ${r.units} ${r.unit}s (${inr(r.investment)})`
  if (cr) qty += `. Here ${cr < 0.5 ? 'an unsold unit loses more than a sold unit earns, so the plan buys cautiously' : 'a sold unit earns more than an unsold unit loses, so the plan buys generously'}: the profit-maximising quantity is the level that demand exceeds in ${pctS(1 - cr)} of scenarios (newsvendor critical ratio ${cr.toFixed(2)})`
  if (r.q_star && r.units < r.q_star * 0.95) qty += `; the plan buys less than that level (${Math.round(r.q_star)}) because the risk setting or budget favours other positions`
  out.push({ title: 'How much', text: `${qty}. Expected sell-through is ${pctS(r.sell_through)}.` })
  const sups = r.suppliers || []
  if (r.supplier && sups.length) {
    const me = sups.find((o) => o.supplier_id === r.supplier_id)
    const alt = sups.filter((o) => o.supplier_id !== r.supplier_id).map((o) => !o.eligible ? `${o.supplier} is not eligible (${o.reason || 'unavailable'})`
      : !o.viable ? `${o.supplier} would not be profitable (effective cost ${inr(o.effective_cost)})`
        : `${o.supplier} would earn ${inr(o.exp_profit || 0)} at the best quantity (effective cost ${inr(o.effective_cost)}, ${pctS(o.reliability)} confirmation)`)
    out.push({ title: 'Which supplier', text: `${r.supplier} gives the highest expected profit${me?.exp_profit != null ? ` (${inr(me.exp_profit)} at its best quantity)` : ''}: quoted ${inr(r.supplier_cost || r.unit_cost)}, ${pctS(r.supplier_reliability)} of allotments confirmed historically, so the effective cost including re-buying unconfirmed units late is ${inr(r.unit_cost)}/${r.unit}. ${alt.length ? alt.join('; ') + '.' : ''}` })
  }
  const pm = r.price_mult
  let pt = `Sell at ${inr(r.sell_price)} vs a market rate of ${inr(r.market_price)}`
  if (pm > 1.001) pt += ` (+${pctS(pm - 1)}): demand is strong enough that the higher margin outweighs the agents lost to cheaper wholesalers`
  else if (pm < 0.999) pt += ` (${pctS(pm - 1)}): pricing below market sells more of the pre-bought stock, which pays more than the lost margin`
  else if (pm) pt += ' (at market): moving the price either way lowers expected profit'
  out.push({ title: 'Selling price', text: pt + '.' })
  out.push({ title: 'Timing', text: `Buy by ${r.buy_by}. Waiting until the last minute would cost about ${inr(r.cost_if_wait)}/${r.unit}, i.e. ${inr(r.saving_vs_wait || 0)} more for this position.` })
  out.push({ title: 'Profit and risk', text: `Expected profit ${inr(r.expected_profit)}. About ${pctS(r.cancel_rate || 0)} of sold units are expected to cancel (cancelled units are not resold) and unsold units are released for a ${pctS(r.salvage_rate || 0)} refund — both are already in the profit figure. In the worst 5% of simulated demand scenarios the position makes ${inr(r.worst5_profit)}.` })
  return out
}
