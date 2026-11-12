import React, { useEffect, useMemo, useState } from 'react'
import { ComposedChart, LineChart, Line, Bar, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'
import { api, pct, num, shortWeek, STATIC } from './api'
import { Card, Loading, COLORS, tip, Defs, Sim, Pill } from './ui'
import Backtest from './Backtest'

const f2 = (v) => (v === null || v === undefined ? '–' : v.toLocaleString('en-IN', { maximumFractionDigits: 1 }))

/** The single definition used everywhere in the product */
export function MetricDefs({ summary }) {
  const bt = summary.forecast_backtest
  return (
    <Defs items={[
      ['Forecast accuracy (headline)', pct(1 - bt.weekly_wape), `= 1 − WAPE of weekly demand per hotel/route, on the ${bt.holdout_start} → ${bt.holdout_end} holdout the model never saw. This is the only "accuracy" figure quoted in the product.`],
      ['WAPE', pct(bt.weekly_wape), 'Weighted absolute percentage error = Σ|forecast − actual| ÷ Σ actual. Robust when some weeks are small, unlike plain MAPE.'],
      ['MAE · RMSE', `${f2(bt.table?.weekly_model.mae)} · ${f2(bt.table?.weekly_model.rmse)}`, 'Average and root-mean-square error in units (rooms or seats) per item-week. RMSE punishes large misses more.'],
      ['Bias', `${bt.bias >= 0 ? '+' : ''}${pct(bt.bias)}`, 'Total forecast ÷ total actual − 1. Near zero means the model neither over- nor under-buys systematically.'],
    ]} />
  )
}

function MetricsTable({ t }) {
  const rows = [
    ['Weekly · our model', t.weekly_model, 'headline'],
    ['Weekly · naive (same week last year)', t.weekly_naive],
    ['Weekly · best possible (noise floor)', t.weekly_ceiling, 'sim'],
    ['Weekly · hotels', t.by_type?.Hotel],
    ['Weekly · flights', t.by_type?.Flight],
    ['Weekly · vs true demand (incl. hidden demand)', t.weekly_vs_true_demand, 'sim'],
    ['Daily · our model', t.daily_model],
    ['Daily · naive (same weekday last year)', t.daily_naive],
  ].filter((r) => r[1])
  return (
    <div className="tbl-wrap"><table>
      <thead><tr><th>Forecast</th><th className="r">Accuracy (1 − WAPE)</th><th className="r">WAPE</th><th className="r">MAE (units)</th><th className="r">RMSE (units)</th><th className="r">Bias</th><th className="r">Points</th></tr></thead>
      <tbody>{rows.map(([n, m, tag]) => (
        <tr key={n} className="nohover"><td><b>{n}</b>{tag === 'headline' && <Pill tone="green">headline</Pill>}{tag === 'sim' && <Sim title="Only measurable because the data is synthetic and the true demand is known" />}</td>
          <td className="r"><b>{pct(m.accuracy)}</b></td><td className="r">{pct(m.wape)}</td><td className="r">{f2(m.mae)}</td><td className="r">{f2(m.rmse)}</td>
          <td className="r">{m.bias >= 0 ? '+' : ''}{pct(m.bias)}</td><td className="r">{num(m.n)}</td></tr>))}</tbody>
    </table></div>
  )
}

export function Scorecard({ summary }) {
  const bt = summary.forecast_backtest, un = summary.unconstraining, el = summary.elasticity
  const cm = summary.cancellation_model, rm = summary.supplier_rate_model, prm = summary.price_model, sm = summary.supplier_scorecard_model
  const rows = [
    ['Forecast intervals', 'P10–P90 coverage (target 80%)', `${pct(bt.coverage_p10_p90, 0)} daily · ${pct(bt.weekly_coverage_p10_p90, 0)} weekly`, '74%', 'Uncalibrated model'],
    ['Sold-out demand recovery', 'Error on sold-out days (WAPE)', pct(un.sold_out_day_error_unconstrained), pct(un.sold_out_day_error_bookings), 'Raw bookings'],
    ...(el ? [['Price elasticity', 'Mean absolute error', el.mae.toFixed(3), el.mae_previous_method.toFixed(3), 'Open-days-only regression']] : []),
    ['Supplier rates (buy timing)', 'Cost error (MAPE)', pct(rm.mape), pct(rm.mape_baseline), 'Item × lead-time average'],
    ...(prm ? [['Market selling price', 'Weekly price error (MAPE)', `${pct(prm.weekly_mape)} · peaks ${pct(prm.peak_day_mape)}`, `${pct(prm.weekly_mape_monthly_avg)} · peaks ${pct(prm.peak_day_mape_monthly_avg)}`, 'Monthly average price']] : []),
    ['Cancellations', 'Weekly count error (WAPE)', pct(cm.weekly_wape), pct(cm.weekly_wape_baseline), "Item's historical rate"],
    ...(sm ? [['Supplier reliability', 'Confirmation-rate error (MAE)', pct(sm.reliability_mae, 2), '–', 'Estimated from request history']] : []),
  ]
  return (
    <Card title="Supporting models" sub={`Each model scored out-of-sample (${bt.holdout_start} → ${bt.holdout_end}). Lower error is better. These are errors, not "accuracy", so they are not mixed with the headline forecast accuracy.`}>
      <div className="tbl-wrap"><table>
        <thead><tr><th>Model</th><th>Error metric</th><th className="r">Ours</th><th className="r">Baseline</th><th>Baseline method</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r[0]} className="nohover"><td><b>{r[0]}</b></td><td>{r[1]}</td><td className="r good">{r[2]}</td><td className="r">{r[3]}</td><td><small>{r[4]}</small></td></tr>
        ))}</tbody>
      </table></div>
    </Card>
  )
}

function Validation({ v }) {
  const items = useMemo(() => [...new Set(v.rows.map((r) => r.item_id))].sort(), [v])
  const [item, setItem] = useState(items.find((i) => i === 'H-GOA-M') || items[0])
  const rows = v.rows.filter((r) => r.item_id === item).map((r) => ({ ...r, band: [r.p10, r.p90] }))
  const inBand = rows.filter((r) => r.y >= r.p10 && r.y <= r.p90).length
  return (
    <div className="row2">
      <Card title="Forecast vs actual demand, all items" sub="Weekly totals across the 45 hotels and routes during the holdout quarter (forecast made before it started)">
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={v.weekly} margin={{ left: 0, right: 10, top: 10 }}>
            <CartesianGrid vertical={false} stroke={COLORS.grid} />
            <XAxis dataKey="week" tickFormatter={shortWeek} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
            <YAxis tickFormatter={(x) => num(x)} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} width={60} />
            <Tooltip {...tip()} formatter={(x) => num(x)} labelFormatter={(w) => `Week of ${w}`} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line dataKey="actual" name="Actual demand" stroke={COLORS.navy} strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} />
            <Line dataKey="forecast" name="Our forecast" stroke={COLORS.teal} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="naive" name="Naive (last year)" stroke={COLORS.slate} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </Card>
      <Card title="One item, week by week" sub={`Actual demand vs forecast and its P10–P90 range · ${inBand} of ${rows.length} weeks inside the range`}
        right={<select className="sel" value={item} onChange={(e) => setItem(e.target.value)} aria-label="Choose an item">{items.map((i) => <option key={i}>{i}</option>)}</select>}>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={rows} margin={{ left: 0, right: 10, top: 10 }}>
            <CartesianGrid vertical={false} stroke={COLORS.grid} />
            <XAxis dataKey="week" tickFormatter={shortWeek} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
            <YAxis tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} width={50} />
            <Tooltip {...tip()} formatter={(x) => (Array.isArray(x) ? `${num(x[0])} – ${num(x[1])}` : num(x))} labelFormatter={(w) => `Week of ${w}`} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Area dataKey="band" name="P10–P90 range" fill={COLORS.teal} fillOpacity={0.15} stroke="none" isAnimationActive={false} />
            <Bar dataKey="y" name="Actual" fill={COLORS.navy} fillOpacity={0.75} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            <Line dataKey="median" name="Forecast (P50)" stroke={COLORS.teal} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </Card>
    </div>
  )
}

function Verification({ settings }) {
  const [v, setV] = useState(null)
  useEffect(() => { setV(null); api.post('verify', settings).then(setV).catch(() => setV({ error: true })) }, [settings])
  if (!v) return <Card title="Mathematical verification"><Loading text="Re-checking every number independently…" /></Card>
  if (v.error) return null
  const groups = [...new Set(v.checks.map((c) => c.group))]
  return (
    <Card title={`Mathematical verification · ${v.passed} of ${v.total} checks passed`}
      sub={STATIC ? v.note : 'Run live on the plan for your current Budget Optimizer settings. Each check recomputes a figure from first principles and compares it with what the dashboard shows.'}>
      {groups.map((g) => (
        <div key={g}><h4 className="mini-h">{g}</h4>
          <div className="checks">{v.checks.filter((c) => c.group === g).map((c) => (
            <div className="check" key={c.name}><span className={c.passed ? 'ok' : 'no'} aria-label={c.passed ? 'passed' : 'failed'}>{c.passed ? '✓' : '✗'}</span>
              <div>{c.name}<small>{c.detail}</small></div></div>))}</div>
        </div>))}
      <p className="note">Also run as automated tests: <code>cd backend && python -m pytest tests</code> (plans at four budget/risk settings, what-if directions, unused-budget logic, metric definitions).</p>
    </Card>
  )
}

export default function Accuracy({ summary, settings }) {
  const [v, setV] = useState(null)
  useEffect(() => { api.get('validation').then(setV) }, [])
  const bt = summary.forecast_backtest
  return (
    <div className="stack">
      <Card title="How accuracy is measured" sub="One definition, used everywhere in the product">
        <MetricDefs summary={summary} />
        <p className="note">Daily accuracy ({pct(1 - bt.daily_wape)}) is lower than weekly because single days are noisier; pre-buying is decided per travel week, so weekly accuracy is the relevant headline. The best achievable weekly accuracy on this data is about {pct(1 - bt.weekly_wape_ceiling)} — the rest is randomness no model can predict. We tested adding more recent demand signals (up to the planning date): forecast errors did not depend on them (correlation 0.02) and did not grow with how far ahead the week is, so the remaining gap is noise, not a missing signal.</p>
      </Card>
      {!v ? <Loading text="Loading validation data…" /> : <>
        <Card title="Forecast error table" sub={`Holdout ${bt.holdout_start} → ${bt.holdout_end}: forecasts made with data up to the day before, compared with what actually happened`}>
          <MetricsTable t={v.table} />
        </Card>
        <Validation v={v} />
      </>}
      <Backtest summary={summary} />
      <Scorecard summary={summary} />
      <Verification settings={settings} />
    </div>
  )
}
