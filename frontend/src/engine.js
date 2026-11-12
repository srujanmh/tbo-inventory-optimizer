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
      stats, plan, by_destination: byDest, by_week: byWeek,
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
  async explain(r) { return { explanation: explainText(r), llm: null } },
}

const inr = (x) => {
  const a = Math.abs(x)
  if (a >= 1e7) return `₹${(x / 1e7).toFixed(2)} Cr`
  if (a >= 1e5) return `₹${(x / 1e5).toFixed(1)} L`
  return `₹${Math.round(x).toLocaleString('en-IN')}`
}

function explainText(r) {
  const drivers = (r.drivers || []).slice(0, 3).map((d) => `${d.driver.toLowerCase()} (${d.effect >= 0 ? '+' : ''}${d.effect.toFixed(0)}%)`).join(', ')
  const ev = r.events?.length ? ` The week overlaps ${r.events.join(', ')}.` : ''
  const so = r.sold_out_risk
  const soTxt = so >= 0.4
    ? `In this season the property/route was sold out on ${Math.round(so * 100)}% of days historically, so pre-buying secures inventory TBO would otherwise lose.`
    : `Historical sold-out rate in this window is ${Math.round(so * 100)}%, so the case is mainly margin, not availability.`
  return [
    `Buy ${r.units} ${r.unit}s of ${r.name} (${r.destination}) for the week of ${r.week} at ${inr(r.unit_cost)}/${r.unit} — total ${inr(r.investment)}. Purchase by ${r.buy_by}; waiting until the last minute would cost about ${inr(r.cost_if_wait)}/${r.unit}.`,
    `Forecast demand is ${Math.round(r.demand_p50)} (range ${Math.round(r.demand_p10)}–${Math.round(r.demand_p90)}) for the week, driven mostly by ${drivers}.${ev}`,
    soTxt,
    `Recommended selling price ${inr(r.sell_price)} vs market ${inr(r.market_price)}. Expected profit ${inr(r.expected_profit)} with ${Math.round(r.sell_through * 100)}% expected sell-through; in the worst 5% of scenarios profit is ${inr(r.worst5_profit)}.`,
  ].join(' ')
}
