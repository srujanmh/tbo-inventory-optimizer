import React, { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { api, inr, pct, num, shortWeek, STATIC, LIVE_URL } from './api'
import { Card, Kpi, KpiRow, Pill, Loading, Sim, pnlTone } from './ui'

const KINDS = {
  demand: { label: 'Demand', hint: 'forecast demand changes (search surge, new flight route, event cancelled…)', min: -50, max: 50 },
  market_price: { label: 'Market price', hint: 'competitor rates move; TBO keeps its price position vs the market', min: -30, max: 30 },
  supplier_cost: { label: 'Supplier cost', hint: 'supplier rates change (fuel surcharge, contract renegotiation…)', min: -30, max: 30 },
  availability: { label: 'Supplier availability', hint: 'allotment a supplier can offer (−100% = supplier unavailable)', min: -100, max: 50 },
  cancellation: { label: 'Cancellations', hint: 'cancellation rate changes (travel advisory, weather…)', min: -50, max: 100 },
}
const PRESETS = [
  ['Goa demand +20%', [{ kind: 'demand', destination: 'Goa', change: 0.2 }]],
  ['Fuel surcharge: flight suppliers +8%', [{ kind: 'supplier_cost', item_type: 'Flight', change: 0.08 }]],
  ['BedBank Nova goes offline', [{ kind: 'availability', supplier_id: 'S-HBBN', change: -1 }]],
  ['Competitors cut Dubai hotel rates 10%', [{ kind: 'market_price', destination: 'Dubai', item_type: 'Hotel', change: -0.1 }]],
  ['Monsoon advisory: Kochi cancellations +50%', [{ kind: 'cancellation', destination: 'Kochi', change: 0.5 }]],
  ['Recession: all demand −15%', [{ kind: 'demand', change: -0.15 }]],
]
const describe = (sh, sups) => {
  const k = KINDS[sh.kind]?.label || sh.kind
  const scope = [sh.destination, sh.item_type && `${sh.item_type.toLowerCase()}s`, sh.supplier_id && sups.find((x) => x.supplier_id === sh.supplier_id)?.supplier].filter(Boolean).join(' · ') || 'everything'
  return `${k} ${sh.change >= 0 ? '+' : ''}${Math.round(sh.change * 100)}% · ${scope}`
}
const slim = (plan) => plan.map(({ cand_id, units, name, destination, item_type, week, investment, sell_price, supplier, supplier_id, price_mult, unit_cost }) =>
  ({ cand_id, units, name, destination, item_type, week, investment, sell_price, supplier, supplier_id, price_mult, unit_cost }))

function ShockEditor({ sh, i, set, remove, summary, sups }) {
  const k = KINDS[sh.kind]
  const up = (patch) => set(i, { ...sh, ...patch })
  const supplierKind = sh.kind === 'supplier_cost' || sh.kind === 'availability'
  return (
    <div className="shock">
      <div className="shock-h">
        <select value={sh.kind} aria-label="What changes" onChange={(e) => up({ kind: e.target.value, change: 0.1, supplier_id: undefined })}>
          {Object.entries(KINDS).map(([v, o]) => <option key={v} value={v}>{o.label}</option>)}
        </select>
        <b className={sh.change >= 0 ? 'txt-good' : 'txt-bad'}>{sh.change >= 0 ? '+' : ''}{Math.round(sh.change * 100)}%</b>
        <button className="x-sm ghost" onClick={() => remove(i)} aria-label="Remove this change">Remove</button>
      </div>
      <input type="range" min={k.min} max={k.max} step="1" value={Math.round(sh.change * 100)} aria-label={`${k.label} change in percent`}
        onChange={(e) => up({ change: +e.target.value / 100 })} />
      <div className="shock-row">
        <select value={sh.destination || ''} aria-label="Destination" onChange={(e) => up({ destination: e.target.value || undefined })}>
          <option value="">All destinations</option>{summary.destinations.map((d) => <option key={d}>{d}</option>)}
        </select>
        <select value={sh.item_type || ''} aria-label="Inventory type" onChange={(e) => up({ item_type: e.target.value || undefined })}>
          <option value="">Hotels & flights</option><option>Hotel</option><option>Flight</option>
        </select>
        {supplierKind && <select value={sh.supplier_id || ''} aria-label="Supplier" onChange={(e) => up({ supplier_id: e.target.value || undefined })}>
          <option value="">All suppliers</option>{sups.map((x) => <option key={x.supplier_id} value={x.supplier_id}>{x.supplier}</option>)}
        </select>}
      </div>
      <small className="muted">{k.hint}</small>
    </div>
  )
}

function Outcome({ r, title }) {
  const d = r.diff
  return (
    <>
      <div className={`decision ${r.replan_recommended ? 'yes' : 'no'}`} role="status">
        <b>{r.replan_recommended ? 'Re-plan recommended' : 'Keep the current plan'}</b> — {r.reason}. {r.affected_candidates} item-weeks affected by the change.
      </div>
      <KpiRow className="four">
        <Kpi label={<>Plan before the change<Sim /></>} value={inr(r.base_stats.expected_profit)} hint={`invested ${inr(r.base_stats.invested)}`} />
        <Kpi label={<>Keep plan, new conditions<Sim /></>} value={inr(r.keep_plan.expected_profit)} hint={`worst-10% ${inr(r.keep_plan.cvar10)}${r.keep_plan.invested > r.stats.budget ? ' · over budget' : ''}`} tone={pnlTone(r.keep_plan.expected_profit)} />
        <Kpi label={<>Re-planned<Sim /></>} value={inr(r.stats.expected_profit)} hint={`worst-10% ${inr(r.stats.cvar10)} · invested ${inr(r.stats.invested)}`} tone={pnlTone(r.stats.expected_profit)} />
        <Kpi label="Gain from re-planning" value={`${r.gain >= 0 ? '+' : ''}${inr(r.gain)}`} hint={`worst-10% ${r.tail_gain >= 0 ? '+' : ''}${inr(r.tail_gain)}`} tone={pnlTone(r.gain)} />
      </KpiRow>
      <Card title={title || `What changes in the plan · ${d.n_changes} positions`} sub={`${d.counts.add} added · ${d.counts.remove} dropped · ${d.counts.increase} increased · ${d.counts.decrease} reduced · ${d.counts.reprice} re-priced. Largest changes first.`}>
        {d.n_changes === 0 ? <div className="empty"><b>No change needed</b>The current plan is already optimal under these conditions.</div> : (
          <div className="tbl-wrap"><table>
            <thead><tr><th>Action</th><th>Inventory</th><th>Week</th><th className="r">Units</th><th className="r">Investment</th><th className="r">Sell price</th><th>Supplier</th></tr></thead>
            <tbody>{d.changes.map((c) => (
              <tr key={c.cand_id} className="nohover">
                <td><span className={`act ${c.action}`}>{c.action}</span></td>
                <td><b>{c.name}</b><br /><small className="muted">{c.destination}</small></td>
                <td>{shortWeek(c.week)}</td>
                <td className="r">{num(c.units_before)} → <b>{num(c.units_after)}</b></td>
                <td className="r">{inr(c.investment_before)} → <b>{inr(c.investment_after)}</b></td>
                <td className="r">{c.price_before ? inr(c.price_before) : '–'} → {c.price_after ? inr(c.price_after) : '–'}</td>
                <td><small>{c.supplier_before === c.supplier_after || !c.supplier_before || !c.supplier_after ? (c.supplier_after || c.supplier_before) : `${c.supplier_before} → ${c.supplier_after}`}</small></td>
              </tr>))}</tbody>
          </table></div>)}
      </Card>
    </>
  )
}

function LiveReplanning({ settings, sups }) {
  const [running, setRunning] = useState(false)
  const [events, setEvents] = useState([])
  const [current, setCurrent] = useState(null)       // plan in force (rows + stats)
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)
  const active = useRef([])
  const plan = useRef(null)

  const reset = () => { setRunning(false); setEvents([]); setCurrent(null); active.current = []; plan.current = null; seq.current = 0 }
  useEffect(reset, [settings])

  const busyRef = useRef(false)
  const tick = async () => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    try {
      const sig = await api.get(`signals/next?seq=${seq.current++}`)
      active.current = [...active.current, sig].slice(-6)             // signals stay in force for the last 6 updates
      const r = await api.post('scenario', { ...settings, shocks: active.current, current_plan: plan.current ? slim(plan.current) : null })
      if (r.replan_recommended) { plan.current = r.plan; setCurrent({ stats: r.stats, n: r.plan.length }) }
      else setCurrent({ stats: r.keep_plan, n: plan.current ? plan.current.length : r.base_stats.n_positions })
      setEvents((e) => [{ sig, at: new Date().toLocaleTimeString(), adopted: r.replan_recommended, gain: r.gain, reason: r.reason,
        changes: r.diff.n_changes, counts: r.diff.counts, profit: r.replan_recommended ? r.stats.expected_profit : r.keep_plan.expected_profit }, ...e].slice(0, 30))
    } catch (e) {
      setEvents((ev) => [{ sig: { id: `err-${Date.now()}`, text: 'Update failed — will retry with the next signal' }, at: new Date().toLocaleTimeString(), adopted: false, reason: e.message, gain: 0, changes: 0, counts: {}, profit: null }, ...ev])
    } finally { busyRef.current = false; setBusy(false) }
  }
  useEffect(() => {
    if (!running) return
    tick()
    const t = setInterval(tick, 9000)
    return () => clearInterval(t)
  }, [running])

  return (
    <Card title="Automated re-planning (live feed)" sub="Market signals stream in; after each one the system re-optimises and adopts the new plan only if it beats keeping the current one by at least 0.5% of expected profit (or the current plan no longer fits the budget)."
      right={<div className="tbl-tools">
        <button className="run" style={{ margin: 0, width: 'auto' }} onClick={() => setRunning(!running)}>{running ? 'Pause feed' : events.length ? 'Resume feed' : 'Start live feed'}</button>
        {events.length > 0 && <button className="ghost" onClick={reset}>Reset</button>}
      </div>}>
      <p className="note" style={{ marginTop: 0 }}>Signals are <b>simulated</b> for the demo. In production they come from search logs, competitor rate feeds and supplier APIs (see Data Sources). A new signal arrives about every 9 seconds; each stays in force for the next 6 updates.</p>
      {current && <KpiRow className="three">
        <Kpi label={<>Plan in force<Sim /></>} value={inr(current.stats.expected_profit)} hint={`expected profit · ${num(current.n)} positions`} tone={pnlTone(current.stats.expected_profit)} />
        <Kpi label="Signals processed" value={num(events.length)} hint={`${events.filter((e) => e.adopted).length} re-plans adopted`} />
        <Kpi label="Active signals" value={num(active.current.length)} hint={busy ? 'updating…' : 'waiting for next signal'} />
      </KpiRow>}
      {events.length === 0 ? <div className="empty"><b>Feed not started</b>Press “Start live feed” to watch the plan react to incoming market changes.</div> : (
        <div className="feed" aria-live="polite">
          <AnimatePresence initial={false}>{events.map((e) => (
            <motion.div key={e.sig.id} className="sig" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
              <div className="t"><b>{e.sig.text}</b><small>{e.at}</small></div>
              <div>{e.adopted
                ? <><Pill tone="green">re-planned</Pill> {e.changes} positions changed ({e.counts.add} added, {e.counts.remove} dropped, {e.counts.increase} up, {e.counts.decrease} down) · gain <span className={e.gain >= 0 ? 'txt-good' : 'txt-bad'}>{inr(e.gain)}</span></>
                : <><Pill>kept plan</Pill> <small>{e.reason}</small></>}
                {e.profit !== null && <small> · expected profit now {inr(e.profit)}</small>}</div>
            </motion.div>))}</AnimatePresence>
        </div>)}
    </Card>
  )
}

export default function Scenarios({ summary, settings }) {
  const [sups, setSups] = useState([])
  const [shocks, setShocks] = useState(PRESETS[0][1])
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const id = useRef(0)
  useEffect(() => { if (!STATIC) api.get('suppliers').then((d) => setSups(d.suppliers)) }, [])
  useEffect(() => {
    if (STATIC) return
    const my = ++id.current
    setBusy(true); setErr(null)
    const t = setTimeout(() => api.post('scenario', { ...settings, shocks }).then((r) => { if (my === id.current) setRes(r) })
      .catch((e) => { if (my === id.current) setErr(e.message) }).finally(() => { if (my === id.current) setBusy(false) }), 450)
    return () => clearTimeout(t)
  }, [shocks, settings])

  if (STATIC) return (
    <Card title="What-if simulation and automated re-planning">
      <div className="empty"><b>Needs the optimization server</b>This copy runs entirely in your browser, so it cannot re-run the supplier, pricing and MILP models.
        Open the live version at <a href={LIVE_URL} target="_blank" rel="noreferrer">{LIVE_URL.replace('https://', '')}</a> to change demand, prices, supplier costs, availability and cancellations and watch the plan re-optimise.</div>
    </Card>)

  const setOne = (i, v) => setShocks(shocks.map((x, j) => (j === i ? v : x)))
  return (
    <div className="stack">
      <div className="opt-grid">
        <Card title="What-if inputs" className="controls" sub={`Budget ${inr(settings.budget, 0)}, risk λ=${settings.risk_aversion.toFixed(2)} and filters come from the Budget Optimizer tab.`}>
          <div className="ctl"><span>Quick scenarios</span>
            <div className="chips">{PRESETS.map(([l, v]) => <button key={l} className="chip sm" onClick={() => setShocks(v)}>{l}</button>)}</div>
          </div>
          {shocks.map((sh, i) => <ShockEditor key={i} sh={sh} i={i} set={setOne} remove={(j) => setShocks(shocks.filter((_, k) => k !== j))} summary={summary} sups={sups} />)}
          <button className="ghost" style={{ marginTop: 10 }} onClick={() => setShocks([...shocks, { kind: 'demand', change: 0.1 }])}>+ Add a change</button>
          {shocks.length > 0 && <p className="note">{shocks.map((s) => describe(s, sups)).join(' · ')}</p>}
        </Card>
        <div className="opt-main">
          {err ? <div className="empty"><b>Could not run the scenario</b>{err}</div>
            : !res ? <Loading text="Re-optimising under the new conditions…" />
              : <div className={busy ? 'dim-wrap' : ''} style={{ opacity: busy ? 0.55 : 1, transition: 'opacity .2s' }}>
                {shocks.length === 0 ? <div className="empty"><b>No changes applied</b>Add a change or pick a quick scenario to see how profit and the plan react.</div>
                  : <Outcome r={res} />}
              </div>}
        </div>
      </div>
      <LiveReplanning settings={settings} sups={sups} />
    </div>
  )
}
