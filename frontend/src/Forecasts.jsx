import React, { useEffect, useMemo, useState } from 'react'
import { ComposedChart, Area, Line, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, ReferenceLine } from 'recharts'
import { api, inr, pct, num, shortWeek } from './api'
import { Card, Kpi, KpiRow, Pill, RiskPill, Loading, COLORS, tip } from './ui'

export default function Forecasts({ itemId, setItemId }) {
  const [items, setItems] = useState([])
  const [d, setD] = useState(null)
  useEffect(() => { api.items().then(setItems) }, [])
  useEffect(() => { setD(null); api.forecast(itemId).then(setD) }, [itemId])

  const data = useMemo(() => {
    if (!d) return []
    const h = d.history.slice(-120).map((r) => ({ date: r.date, bookings: r.bookings, demand: Math.round(r.demand_est), soldout: r.sold_out ? r.bookings : null }))
    const f = d.forecast.map((r) => ({ date: r.date, p50: r.p50, base: r.p10, band: r.p90 - r.p10 }))
    return [...h, ...f]
  }, [d])

  const grouped = useMemo(() => {
    const g = {}
    items.forEach((i) => { (g[i.destination] ||= []).push(i) })
    return g
  }, [items])

  return (
    <div className="stack">
      <Card title="Forecast explorer" right={
        <select aria-label="Choose hotel or flight route" value={itemId} onChange={(e) => setItemId(e.target.value)}>
          {Object.entries(grouped).map(([dest, arr]) => (
            <optgroup key={dest} label={dest}>{arr.map((i) => <option key={i.item_id} value={i.item_id}>{i.name} ({i.item_type === 'Hotel' ? i.tier : 'Flight'})</option>)}</optgroup>
          ))}
        </select>}>
        {!d ? <Loading /> : <>
          <KpiRow>
            <Kpi label="Item" value={d.item.name} hint={`${d.item.item_type} · ${d.item.destination} · ${d.item.tier}`} />
            <Kpi label="Reference price" value={inr(d.item.ref_price)} hint={`per ${d.item.unit}`} />
            <Kpi label="Price elasticity (est.)" value={d.item.elasticity_est?.toFixed(2)} hint={`market-level · true ${d.item.elasticity}`} />
            <Kpi label="Look-to-book" value={`${d.item.l2b} : 1`} hint="searches per booking" />
            <Kpi label="Unsold-allotment refund" value={pct(d.item.salvage_rate, 0)} hint="salvage if released back" />
          </KpiRow>
          <ResponsiveContainer width="100%" height={360}>
            <ComposedChart data={data} margin={{ left: 0, right: 20, top: 10 }}>
              <CartesianGrid vertical={false} stroke={COLORS.grid} />
              <XAxis dataKey="date" tickFormatter={(v) => shortWeek(v)} minTickGap={40} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
              <YAxis tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
              <Tooltip {...tip()} labelFormatter={(v) => v} formatter={(v, n) => (n === 'P10–P90 band' ? null : [typeof v === 'number' ? v.toFixed(0) : v, n])} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area isAnimationActive={false} dataKey="base" stackId="b" stroke="none" fill="transparent" legendType="none" name="base" />
              <Area isAnimationActive={false} dataKey="band" stackId="b" stroke="none" fill={COLORS.blue} fillOpacity={0.15} name="P10–P90 band" />
              <Line isAnimationActive={false} dataKey="bookings" stroke={COLORS.slate} dot={false} strokeWidth={1.2} name="Actual bookings" />
              <Line isAnimationActive={false} dataKey="demand" stroke={COLORS.amber} dot={false} strokeWidth={1.4} strokeDasharray="4 3" name="Unconstrained demand" />
              <Scatter isAnimationActive={false} dataKey="soldout" fill={COLORS.red} name="Sold-out day" shape={(p) => p.payload.soldout != null ? <circle cx={p.cx} cy={p.cy} r={2.6} fill={COLORS.red} /> : null} />
              <Line isAnimationActive={false} dataKey="p50" stroke={COLORS.blue} dot={false} strokeWidth={2} name="Forecast P50" />
              <ReferenceLine x={d.forecast[0]?.date} stroke={COLORS.navy} strokeDasharray="3 3" label={{ value: 'forecast →', fontSize: 11, position: 'insideTopLeft' }} />
            </ComposedChart>
          </ResponsiveContainer>
        </>}
      </Card>
      {d && (
        <Card title="Weekly plan inputs" sub="Aggregated forecast, predicted costs and the drivers behind each week">
          <div className="tbl-wrap"><table>
            <thead><tr><th>Week</th><th className="r">Demand P10 / P50 / P90</th><th className="r">Unit cost</th><th className="r">Last-minute cost</th><th>Buy by</th><th className="r">Sell price</th><th className="r">Cancel</th><th className="r">Sold-out</th><th>Top drivers</th><th>Events</th></tr></thead>
            <tbody>{d.weeks.map((w) => (
              <tr key={w.week} className="nohover">
                <td>{shortWeek(w.week)}</td>
                <td className="r">{num(w.demand_p10)} / <b>{num(w.demand_p50)}</b> / {num(w.demand_p90)}</td>
                <td className="r">{inr(w.unit_cost)}</td>
                <td className="r">{inr(w.cost_if_wait)}</td>
                <td>{w.buy_by}</td>
                <td className="r">{w.sell_price ? inr(w.sell_price) : '–'}</td>
                <td className="r">{pct(w.cancel_rate, 0)}</td>
                <td className="r"><RiskPill v={w.sold_out_risk} /></td>
                <td className="small">{w.drivers.slice(0, 2).map((x) => `${x.driver} ${x.effect >= 0 ? '+' : ''}${x.effect.toFixed(0)}%`).join(' · ')}</td>
                <td>{w.events.map((e) => <Pill key={e} tone="amber">{e}</Pill>)}</td>
              </tr>))}
            </tbody></table></div>
        </Card>
      )}
    </div>
  )
}
