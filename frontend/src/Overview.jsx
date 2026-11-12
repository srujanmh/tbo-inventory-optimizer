import React, { useEffect, useMemo, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { api, inr, pct, num, shortWeek } from './api'
import { Card, Kpi, KpiRow, Pill, RiskPill, Loading, COLORS, tip, pnlTone } from './ui'

const METRICS = {
  demand: { label: 'Forecast demand (P50 units)', fmt: (v) => num(v), },
  sold_out_risk: { label: 'Sold-out risk', fmt: (v) => pct(v, 0), },
  opportunity: { label: 'Opportunity score', fmt: (v) => v.toFixed(0), },
}

function Heatmap({ summary }) {
  const [m, setM] = useState('sold_out_risk')
  const grid = useMemo(() => {
    const g = {}
    summary.heatmap.forEach((r) => { (g[r.destination] ||= {})[r.week] = r })
    return g
  }, [summary])
  const vals = summary.heatmap.map((r) => r[m])
  const max = Math.max(...vals), min = Math.min(...vals)
  const [r, gg, b] = COLORS.heat[m]
  return (
    <Card title="Where & when demand outruns supply" sub="Destination × travel week, next 13 weeks"
      right={<div className="seg" role="group" aria-label="Heatmap metric">{Object.entries(METRICS).map(([k, v]) => <button key={k} className={m === k ? 'on' : ''} aria-pressed={m === k} onClick={() => setM(k)}>{v.label.split(' (')[0]}</button>)}</div>}>
      <div className="heat-wrap"><div className="heat" style={{ gridTemplateColumns: `110px repeat(${summary.weeks.length}, 1fr)` }}>
        <div />
        {summary.weeks.map((w) => <div key={w} className="hx">{shortWeek(w)}</div>)}
        {summary.destinations.map((d) => (
          <React.Fragment key={d}>
            <div className="hy">{d}</div>
            {summary.weeks.map((w) => {
              const v = grid[d]?.[w]?.[m] ?? 0
              const a = (v - min) / (max - min || 1)
              return <div key={w} className="hc" title={`${d} · ${w}: ${METRICS[m].fmt(v)}`}
                style={{ background: `rgba(${r},${gg},${b},${0.06 + 0.9 * a})`, color: a > 0.55 ? COLORS.heatInk[m] : 'var(--text)' }}>{METRICS[m].fmt(v)}</div>
            })}
          </React.Fragment>
        ))}
      </div></div>
    </Card>
  )
}

export default function Overview({ summary, openForecast }) {
  const [opps, setOpps] = useState(null)
  useEffect(() => { api.opportunities(15).then(setOpps) }, [])
  const bt = summary.forecast_backtest, un = summary.unconstraining
  const imp = Object.entries(summary.driver_importance).map(([k, v]) => ({ k, v }))

  return (
    <div className="stack">
      <KpiRow>
        <Kpi label="Forecast accuracy (weekly)" num={1 - bt.weekly_wape} fmt={(v) => pct(v)} hint={`= 1 − WAPE · naive ${pct(1 - bt.weekly_wape_naive)} · details in Accuracy & Validation`} tone="good" />
        <Kpi label="P10–P90 interval coverage" value={pct(bt.coverage_p10_p90, 0)} hint={`target 80% · holdout ${bt.holdout_start} → ${bt.holdout_end}`} />
        <Kpi label="Hidden demand on sold-out days" num={un.hidden_demand_recovered} fmt={num} hint={`error ${pct(un.sold_out_day_error_bookings, 0)} → ${pct(un.sold_out_day_error_unconstrained, 0)} after unconstraining`} tone="warn" />
        <Kpi label="High sold-out-risk windows" num={summary.high_risk_windows} fmt={num} hint={`of ${summary.n_candidates} item-weeks ahead`} tone="warn" />
        <Kpi label="Opportunity pool" value={inr(summary.full_plan_cost, 0)} hint={`${summary.n_viable} profitable item-weeks · avg ROI ${pct(summary.avg_roi)}`} />
      </KpiRow>
      <Heatmap summary={summary} />
      <div className="row2 wide-left">
        <Card title="Top pre-buy opportunities" sub="Ranked by ROI at the optimal quantity, sold-out pressure and forecast confidence">
          {!opps ? <Loading /> : (
            <div className="tbl-wrap"><table>
              <thead><tr><th>Inventory</th><th>Week</th><th className="r">Demand (P10–P90)</th><th className="r">Buy at</th><th className="r">Sell at</th><th className="r">ROI</th><th className="r">Sold-out</th><th className="r">Score</th></tr></thead>
              <tbody>{opps.map((o) => (
                <tr key={o.cand_id} onClick={() => openForecast(o.item_id)} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') openForecast(o.item_id) }}>
                  <td><div className="nm"><span className={`ic ${o.item_type}`}>{o.item_type === 'Hotel' ? 'H' : 'F'}</span><div><b>{o.name}</b><small>{o.destination}{o.events?.length ? ` · ${o.events[0]}` : ''}</small></div></div></td>
                  <td>{shortWeek(o.week)}</td>
                  <td className="r">{num(o.demand_p50)} <small>({num(o.demand_p10)}–{num(o.demand_p90)})</small></td>
                  <td className="r">{inr(o.unit_cost)}</td>
                  <td className="r">{inr(o.sell_price)}</td>
                  <td className={`r ${pnlTone(o.roi_at_qstar)}`}>{pct(o.roi_at_qstar)}</td>
                  <td className="r"><RiskPill v={o.sold_out_risk} /></td>
                  <td className="r"><Pill tone="blue">{o.opportunity_score.toFixed(0)}</Pill></td>
                </tr>))}
              </tbody></table></div>)}
        </Card>
        <Card title="What drives demand" sub="Share of forecast model gain by signal group">
          <ResponsiveContainer width="100%" height={330}>
            <BarChart data={imp} layout="vertical" margin={{ left: 10, right: 30 }}>
              <CartesianGrid horizontal={false} stroke={COLORS.grid} />
              <XAxis type="number" tickFormatter={(v) => pct(v, 0)} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
              <YAxis type="category" dataKey="k" width={150} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
              <Tooltip {...tip()} formatter={(v) => pct(v)} />
              <Bar isAnimationActive={false} dataKey="v" fill={COLORS.purple} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <p className="note">All lagged signals (search momentum, last year's demand, recent level) are older than the 13-week horizon, so they are always known at planning time.</p>
        </Card>
      </div>
    </div>
  )
}
