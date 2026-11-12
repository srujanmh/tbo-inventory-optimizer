import React, { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, Cell } from 'recharts'
import { api, inr, pct, num, shortWeek } from './api'
import { Card, Kpi, KpiRow, Pill, RiskPill, Loading, COLORS, DEST_COLORS, EASE, tip, pnlTone, pnlFill, Pnl } from './ui'
import { STATIC, DEFAULT_SETTINGS } from './api'

const crore = (v) => `₹${(v / 1e7).toFixed(0)}Cr`

function Controls({ summary, s, set, onRun, busy }) {
  const toggle = (arr, v) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])
  const dests = s.destinations || summary.destinations
  const riskLabel = s.risk_aversion < 0.2 ? 'Profit-seeking' : s.risk_aversion < 0.6 ? 'Balanced' : 'Conservative'
  return (
    <Card title="Planning inputs" className="controls">
      <div className="ctl">
        <label className="ctl-t" htmlFor="budget-cr">Maximum budget</label>
        <div className="budget-in">
          <b aria-hidden="true">₹</b>
          <input id="budget-cr" type="number" min="1" step="5" value={Math.round(s.budget / 1e7)} aria-describedby="budget-hint"
            onChange={(e) => set({ ...s, budget: Math.max(1, +e.target.value) * 1e7 })} />
          <b aria-hidden="true">Cr</b>
        </div>
        <input type="range" min="5" max="200" step="5" value={Math.min(200, s.budget / 1e7)} aria-label="Budget in crore"
          aria-valuetext={`${Math.round(s.budget / 1e7)} crore rupees`} onChange={(e) => set({ ...s, budget: +e.target.value * 1e7 })} />
        <small id="budget-hint">Full opportunity pool ≈ {inr(summary.full_plan_cost, 0)} · plans update automatically</small>
      </div>
      <label className="ctl">
        <span>Risk appetite <Pill tone="blue">{riskLabel} · λ={s.risk_aversion.toFixed(2)}</Pill></span>
        <input type="range" min="0" max="1" step="0.05" value={s.risk_aversion} aria-label="Risk aversion lambda"
          aria-valuetext={`${riskLabel}, lambda ${s.risk_aversion.toFixed(2)}`} onChange={(e) => set({ ...s, risk_aversion: +e.target.value })} />
        <div className="ends"><small>Max expected profit</small><small>Protect downside</small></div>
      </label>
      <label className="ctl">
        <span>Max share per destination: <b>{Math.round(s.max_dest_share * 100)}%</b></span>
        <input type="range" min="0.1" max="1" step="0.05" value={s.max_dest_share} aria-label="Maximum share of budget per destination"
          aria-valuetext={`${Math.round(s.max_dest_share * 100)} percent`} onChange={(e) => set({ ...s, max_dest_share: +e.target.value })} />
      </label>
      <div className="ctl" role="group" aria-labelledby="types-l">
        <span id="types-l">Inventory types</span>
        <div className="chips">
          {['Hotel', 'Flight'].map((t) => (
            <button key={t} className={`chip ${s.item_types.includes(t) ? 'on' : ''}`} aria-pressed={s.item_types.includes(t)}
              onClick={() => { const v = toggle(s.item_types, t); if (v.length) set({ ...s, item_types: v }) }}>{t === 'Hotel' ? '🏨 Hotels' : '✈️ Flights'}</button>
          ))}
        </div>
      </div>
      <div className="ctl" role="group" aria-labelledby="dest-l">
        <span id="dest-l">Destinations <small>{s.destinations ? `${dests.length} of ${summary.destinations.length}` : 'all'}</small></span>
        <div className="chips">
          {summary.destinations.map((d) => (
            <button key={d} className={`chip sm ${dests.includes(d) ? 'on' : ''}`} aria-pressed={dests.includes(d)}
              onClick={() => { const v = toggle(dests, d); if (v.length) set({ ...s, destinations: v.length === summary.destinations.length ? null : v }) }}>{d}</button>
          ))}
        </div>
      </div>
      <motion.button className="run" onClick={onRun} disabled={busy} whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}>{busy ? 'Optimizing…' : 'Run optimization'}</motion.button>
      <button className="reset" onClick={() => set(DEFAULT_SETTINGS)}>Reset to defaults</button>
    </Card>
  )
}

function Explain({ row, onClose, openForecast }) {
  const [txt, setTxt] = useState(null)
  const closeRef = useRef(null)
  useEffect(() => { setTxt(null); api.post('explain', row).then(setTxt) }, [row])
  useEffect(() => {
    const prev = document.activeElement
    closeRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); prev?.focus?.() }
  }, [])
  return (
    <motion.div className="drawer-bg" onClick={onClose} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
      <motion.aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" onClick={(e) => e.stopPropagation()} initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
        transition={{ type: 'spring', stiffness: 320, damping: 34 }}>
        <button className="x" ref={closeRef} onClick={onClose} aria-label="Close explanation">×</button>
        <div className="eyebrow">{row.item_type} · {row.destination} · week of {row.week}</div>
        <h2 id="drawer-title">{row.name}</h2>
        <KpiRow className="three">
          <Kpi label="Buy" value={`${num(row.units)} ${row.unit}s`} hint={`by ${row.buy_by}`} />
          <Kpi label="Investment" value={inr(row.investment)} hint={`${inr(row.unit_cost)} / ${row.unit}`} />
          <Kpi label="Expected profit" value={inr(row.expected_profit)} hint={<>worst 5%: <Pnl v={row.worst5_profit}>{inr(row.worst5_profit)}</Pnl></>} tone={pnlTone(row.expected_profit)} />
        </KpiRow>
        <h4>Why this recommendation</h4>
        {!txt ? <Loading text="Writing explanation…" /> : <>
          <p className="explain">{txt.explanation}</p>
          {txt.llm && <><h4>AI analyst note</h4><p className="explain ai">{txt.llm}</p></>}
        </>}
        <h4>Demand drivers this week (SHAP, vs. an average day)</h4>
        <div className="drivers">
          {row.drivers.map((d) => (
            <div key={d.driver} className="drv">
              <span>{d.driver}</span>
              <div className="bar"><motion.i className={d.effect >= 0 ? 'pos' : 'neg'} initial={{ width: 0 }} animate={{ width: `${Math.min(100, Math.abs(d.effect) / Math.max(...row.drivers.map((x) => Math.abs(x.effect))) * 100)}%` }} transition={{ duration: 0.7, ease: EASE, delay: 0.25 }} /></div>
              <b>{d.effect >= 0 ? '+' : ''}{d.effect.toFixed(0)}%</b>
            </div>
          ))}
        </div>
        {row.events?.length > 0 && <><h4>Events in window</h4><div className="chips">{row.events.map((e) => <Pill key={e} tone="amber">{e}</Pill>)}</div></>}
        <button className="link" onClick={() => openForecast(row.item_id)}>Open forecast for this item →</button>
      </motion.aside>
    </motion.div>
  )
}

const CSV_COLS = ['name', 'item_type', 'destination', 'week', 'units', 'unit', 'unit_cost', 'investment', 'buy_by', 'sell_price', 'market_price', 'expected_profit', 'worst5_profit', 'sell_through', 'sold_out_risk', 'demand_p50']
const toCsv = (plan) => [CSV_COLS.join(','), ...plan.map((r) => CSV_COLS.map((c) => JSON.stringify(typeof r[c] === 'number' ? Math.round(r[c] * 1000) / 1000 : (r[c] ?? ''))).join(','))].join('\n')

function downloadCsv(plan) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([toCsv(plan)], { type: 'text/csv' }))
  a.download = 'tbo_prebuy_plan.csv'
  document.body.appendChild(a); a.click(); a.remove()
}

export default function Optimizer({ summary, settings, setSettings, openForecast }) {
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [sel, setSel] = useState(null)
  const [sort, setSort] = useState(['expected_profit', -1])
  const [filter, setFilter] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [toast, setToast] = useState('')
  const reqId = useRef(0)

  const run = () => {
    const id = ++reqId.current
    setBusy(true)
    api.post('optimize', settings).then((r) => { if (id === reqId.current) setRes(r) })
      .finally(() => { if (id === reqId.current) setBusy(false) })
  }
  // re-plan automatically whenever an input changes (debounced)
  useEffect(() => { const t = setTimeout(run, res ? 350 : 0); return () => clearTimeout(t) }, [settings])

  const flash = (m) => { setToast(m); setTimeout(() => setToast(''), 2500) }
  const copyCsv = async () => {
    try { await navigator.clipboard.writeText(toCsv(res.plan)); flash(`Copied ${res.plan.length} rows — paste into Excel or Sheets`) }
    catch { flash('Copy was blocked by the browser — use Download instead') }
  }

  const plan = useMemo(() => {
    if (!res) return []
    const f = filter.toLowerCase()
    return [...res.plan].filter((r) => !f || `${r.name} ${r.destination}`.toLowerCase().includes(f))
      .sort((a, b) => (a[sort[0]] > b[sort[0]] ? 1 : -1) * sort[1])
  }, [res, sort, filter])

  const s = res?.stats
  const cmp = res && [
    { name: 'AI optimizer (MILP)', expected: s.expected_profit, worst: s.cvar10 },
    { name: 'Greedy ROI ranking', expected: res.baselines.greedy_roi_ranking.expected_profit, worst: res.baselines.greedy_roi_ranking.cvar10 },
    { name: "Last year's mix", expected: res.baselines.last_year_proportional.expected_profit, worst: res.baselines.last_year_proportional.cvar10 },
  ]
  const lyProfit = res && res.baselines.last_year_proportional.expected_profit
  const gain = res && s.expected_profit - lyProfit
  // a % uplift is meaningless when the baseline loses money: show the rupee difference instead
  const uplift = res && (lyProfit > 0 ? s.expected_profit / lyProfit - 1 : null)
  const th = (k, l, cls = '') => <th className={`${cls} sortable`} onClick={() => setSort([k, sort[0] === k ? -sort[1] : -1])}>{l}{sort[0] === k ? (sort[1] < 0 ? ' ↓' : ' ↑') : ''}</th>

  return (
    <div className="opt-grid">
      <Controls summary={summary} s={settings} set={setSettings} onRun={run} busy={busy} />
      <div className="opt-main">
        {!res ? <Loading text="Solving allocation…" /> : <>
          <KpiRow className={`four ${busy ? 'dim' : ''}`}>
            <Kpi label="Capital deployed" num={s.invested} fmt={(v) => inr(v)} hint={`${pct(s.budget_used, 0)} of ${inr(s.budget, 0)} budget`} />
            <Kpi label="Expected profit" num={s.expected_profit} fmt={(v) => inr(v)} hint={`ROI ${pct(s.roi)}`} tone={pnlTone(s.expected_profit)} />
            <Kpi label="Worst-10% profit" num={s.cvar10} fmt={(v) => inr(v)} hint={`P(loss) ${pct(s.prob_loss)}`} tone={pnlTone(s.cvar10)} />
            {uplift !== null
              ? <Kpi label="vs last year's mix" num={uplift} fmt={(v) => `${v >= 0 ? '+' : ''}${pct(v)}`} hint={`${gain >= 0 ? '+' : ''}${inr(gain)} expected profit`} tone={pnlTone(uplift)} />
              : <Kpi label="vs last year's mix" num={gain} fmt={(v) => `${v >= 0 ? '+' : ''}${inr(v)}`} hint={<>last year's mix would <span className="txt-bad">lose {inr(-lyProfit)}</span></>} tone={pnlTone(gain)} />}
            <Kpi label="Inventory secured" num={s.units} fmt={num} hint={`${pct(s.sell_through, 0)} expected sell-through`} />
            <Kpi label="In sold-out windows" num={s.units_in_soldout_windows} fmt={num} hint="bookable units where supply usually runs out" tone="warn" />
            <Kpi label="Saved by buying early" num={s.saving_vs_wait} fmt={(v) => inr(v)} hint="vs last-minute supplier rates" />
            <Kpi label="Positions" num={s.n_positions} fmt={num} hint={`solver: ${s.status}`} />
          </KpiRow>

          <div className="row2">
            <Card title="Strategy comparison" sub={`Same budget, three ways to spend it (Monte Carlo, ${STATIC ? 300 : '1,000'} scenarios)`}>
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={cmp} margin={{ left: 10, right: 10, top: 10 }}>
                  <CartesianGrid vertical={false} stroke={COLORS.grid} />
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: COLORS.muted }} stroke={COLORS.grid} />
                  <YAxis tickFormatter={crore} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
                  <Tooltip {...tip()} formatter={(v) => inr(v)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="expected" name="Expected profit" fill={COLORS.teal} radius={[4, 4, 0, 0]}>
                    {cmp.map((d) => <Cell key={d.name} fill={pnlFill(d.expected)} />)}
                  </Bar>
                  <Bar dataKey="worst" name="Worst-10% profit" fill={COLORS.teal} fillOpacity={0.45} radius={[4, 4, 0, 0]}>
                    {cmp.map((d) => <Cell key={d.name} fill={pnlFill(d.worst)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>
            <Card title="Profit distribution" sub="Portfolio profit across simulated demand scenarios · green = profit, red = loss">
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={s.histogram} margin={{ left: 0, right: 10, top: 10 }} barCategoryGap={1}>
                  <CartesianGrid vertical={false} stroke={COLORS.grid} />
                  <XAxis dataKey="x0" tickFormatter={(v) => `₹${(v / 1e7).toFixed(1)}Cr`} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} minTickGap={30} />
                  <YAxis tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
                  <Tooltip {...tip()} formatter={(v) => [v, 'scenarios']} labelFormatter={(v) => `from ${inr(v)}`} />
                  <Bar dataKey="count">
                    {s.histogram.map((h, i) => <Cell key={i} fill={pnlFill((h.x0 + h.x1) / 2)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>
          </div>

          <div className="row2">
            <Card title="Allocation by destination">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={res.by_destination} layout="vertical" margin={{ left: 20, right: 20 }}>
                  <CartesianGrid horizontal={false} stroke={COLORS.grid} />
                  <XAxis type="number" tickFormatter={crore} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
                  <YAxis type="category" dataKey="destination" width={80} tick={{ fontSize: 12, fill: COLORS.muted }} stroke={COLORS.grid} />
                  <Tooltip {...tip()} formatter={(v) => inr(v)} />
                  <Bar dataKey="investment" name="Investment" radius={[0, 4, 4, 0]}>
                    {res.by_destination.map((d, i) => <Cell key={d.destination} fill={DEST_COLORS[i % DEST_COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>
            <Card title="Allocation by travel week">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={res.by_week} margin={{ left: 0, right: 10, top: 10 }}>
                  <CartesianGrid vertical={false} stroke={COLORS.grid} />
                  <XAxis dataKey="week" tickFormatter={shortWeek} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
                  <YAxis tickFormatter={crore} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
                  <Tooltip {...tip()} formatter={(v) => inr(v)} labelFormatter={(w) => `Week of ${w}`} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="investment" name="Investment" fill={COLORS.navy} radius={[4, 4, 0, 0]} />
                  <Bar dataKey="expected_profit" name="Expected profit" fill={COLORS.teal} radius={[4, 4, 0, 0]}>
                    {res.by_week.map((w) => <Cell key={w.week} fill={pnlFill(w.expected_profit)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>
          </div>

          <Card title={`Buy plan · ${plan.length} positions`} sub="What to buy, how many, when, and at what selling price. Click a row for the reasoning."
            right={<div className="tbl-tools">{toast && <span className="toast" role="status">{toast}</span>}
              <input placeholder="Filter hotel / route / city…" aria-label="Filter the buy plan" value={filter} onChange={(e) => setFilter(e.target.value)} />
              <button className="ghost" onClick={copyCsv} disabled={!res.plan.length}>Copy CSV</button>
              <button className="ghost" onClick={() => downloadCsv(res.plan)} disabled={!res.plan.length}>Download CSV</button></div>}>
            {res.plan.length === 0 ? (
              <div className="empty"><b>Nothing worth buying under these settings</b>No item-week earns a positive risk-adjusted return within this budget and filter set. Try a larger budget, a lower risk aversion, or more destinations.</div>
            ) : plan.length === 0 ? (
              <div className="empty"><b>No positions match “{filter}”</b>Clear the filter to see all {res.plan.length} positions.</div>
            ) : <>
            <div className="tbl-wrap">
              <table>
                <thead><tr>
                  {th('name', 'Inventory')}{th('week', 'Travel week')}{th('units', 'Units', 'r')}{th('unit_cost', 'Unit cost', 'r')}
                  {th('investment', 'Investment', 'r')}{th('buy_by', 'Buy by')}{th('sell_price', 'Sell price', 'r')}
                  {th('demand_p50', 'Demand P50', 'r')}{th('expected_profit', 'Exp. profit', 'r')}{th('sell_through', 'Sell-through', 'r')}{th('sold_out_risk', 'Sold-out risk', 'r')}
                </tr></thead>
                <tbody>
                  {plan.slice(0, showAll ? plan.length : 150).map((r) => (
                    <tr key={r.cand_id} onClick={() => setSel(r)} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(r) } }}
                      aria-label={`${r.name}, week of ${r.week}: buy ${r.units} ${r.unit}s. Open explanation`}>
                      <td><div className="nm"><span className={`ic ${r.item_type}`}>{r.item_type === 'Hotel' ? 'H' : 'F'}</span><div><b>{r.name}</b><small>{r.destination} · {r.tier}</small></div></div></td>
                      <td>{shortWeek(r.week)}{r.events?.length > 0 && <span className="evt" title={r.events.join(', ')}>★</span>}</td>
                      <td className="r">{num(r.units)}</td>
                      <td className="r">{inr(r.unit_cost)}</td>
                      <td className="r"><b>{inr(r.investment)}</b></td>
                      <td>{r.buy_by}</td>
                      <td className="r">{inr(r.sell_price)} <small className={r.sell_price >= r.market_price ? 'up' : 'down'}>{r.sell_price >= r.market_price ? '+' : ''}{pct(r.sell_price / r.market_price - 1, 0)}</small></td>
                      <td className="r">{num(r.demand_p50)}</td>
                      <td className={`r ${pnlTone(r.expected_profit)}`}>{inr(r.expected_profit)}</td>
                      <td className="r">{pct(r.sell_through, 0)}</td>
                      <td className="r"><RiskPill v={r.sold_out_risk} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="tbl-foot">
              <span>Showing {Math.min(plan.length, showAll ? plan.length : 150)} of {plan.length} positions · totals and charts always include all {res.plan.length}</span>
              {plan.length > 150 && <button className="ghost" onClick={() => setShowAll(!showAll)}>{showAll ? 'Show top 150' : `Show all ${plan.length}`}</button>}
            </div>
            </>}
          </Card>
        </>}
      </div>
      <AnimatePresence>{sel && <Explain key={sel.cand_id} row={sel} onClose={() => setSel(null)} openForecast={openForecast} />}</AnimatePresence>
    </div>
  )
}
