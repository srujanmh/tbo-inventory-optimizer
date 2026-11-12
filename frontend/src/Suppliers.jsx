import React, { useEffect, useMemo, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts'
import { api, pct, num } from './api'
import { Card, Kpi, KpiRow, Pill, Loading, COLORS, DEST_COLORS, tip, Sim } from './ui'

const signed = (v) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`

export default function Suppliers({ summary }) {
  const [d, setD] = useState(null)
  const [item, setItem] = useState('')
  useEffect(() => { api.get('suppliers').then(setD) }, [])
  const items = useMemo(() => (d ? [...new Set(d.by_item.map((r) => r.item_id))].sort() : []), [d])
  useEffect(() => { if (items.length && !item) setItem(items.find((x) => x.startsWith('H-GOA')) || items[0]) }, [items])
  if (!d) return <Loading text="Loading supplier scorecard…" />
  const rows = d.by_item.filter((r) => r.item_id === item)
  const m = d.model
  const total = d.suppliers.reduce((a, s) => a + s.positions, 0)
  return (
    <div className="stack">
      <KpiRow>
        <Kpi label="Suppliers compared" value={num(d.suppliers.length)} hint={`${d.by_item.length} item × supplier pairs`} />
        <Kpi label="Allotment requests analysed" value={num(d.suppliers.reduce((a, s) => a + s.requests, 0))} hint="history used to score each supplier" />
        <Kpi label="Item-weeks sourced" value={num(total)} hint="each profitable item-week gets its best supplier" />
        {m && <Kpi label="Reliability estimate error" value={pct(m.reliability_mae)} hint={<>vs hidden true value<Sim /></>} tone="good" />}
      </KpiRow>

      <Card title="Supplier scorecard" sub="Estimated from each supplier's own history of allotment requests: what was asked for, offered, confirmed, released and refunded">
        <div className="tbl-wrap"><table>
          <thead><tr><th>Supplier</th><th>Type</th><th className="r">Price vs benchmark</th><th className="r">Availability</th><th className="r">Confirms</th>
            <th className="r">Refund on release</th><th className="r">Min. notice</th><th className="r">Free release</th><th className="r">Item-weeks won</th></tr></thead>
          <tbody>{d.suppliers.map((s) => (
            <tr key={s.supplier_id} className="nohover">
              <td><b>{s.supplier}</b><br /><small className="muted">{s.items} {s.item_type === 'Hotel' ? 'hotels' : 'routes'} · {num(s.requests)} requests</small></td>
              <td>{s.item_type}</td>
              <td className={`r ${s.price_index < 1 ? 'good' : s.price_index > 1.01 ? 'bad' : ''}`}>{signed(s.price_index - 1)}</td>
              <td className="r">{pct(s.availability, 0)}</td>
              <td className={`r ${s.reliability < 0.9 ? 'bad' : 'good'}`}>{pct(s.reliability, 1)}</td>
              <td className="r">{pct(s.refund_rate, 0)}</td>
              <td className="r">{s.min_lead_days} days</td>
              <td className="r">{s.free_release_days} days</td>
              <td className="r"><b>{num(s.positions)}</b></td>
            </tr>))}</tbody>
        </table></div>
        <p className="note">Availability = share of requested units the supplier could offer. Confirms = share of offered units actually confirmed. Refund = share of the cost returned when unsold stock is released.</p>
      </Card>

      <div className="row2">
        <Card title="How a supplier is chosen" sub="For every item and travel week, each eligible supplier is evaluated on the same 1,000 demand scenarios">
          <p className="lead">The cheapest quote does not always win. A supplier that fails to confirm allotments forces TBO to re-buy those units close to travel at the last-minute rate, and a supplier with a poor refund policy makes every unsold unit more expensive. The system prices both in:</p>
          <div className="formula">{`effective cost = quote + (1 − confirmation rate) × (last-minute rate − quote)
salvage        = refund rate × quote   (per unsold unit released)
eligible       = supplier's minimum notice ≤ days left before travel
capacity       = availability × typical weekly demand`}</div>
          <p className="note">Each supplier is then run through the same price and newsvendor-quantity optimisation, and the one with the highest expected profit is used. Open any position in the Budget Optimizer to see the side-by-side comparison for that item-week.</p>
        </Card>
        <Card title="Who wins the business" sub="Number of profitable item-weeks sourced from each supplier">
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={d.suppliers} layout="vertical" margin={{ left: 20, right: 20 }}>
              <CartesianGrid horizontal={false} stroke={COLORS.grid} />
              <XAxis type="number" tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
              <YAxis type="category" dataKey="supplier" width={150} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
              <Tooltip {...tip()} formatter={(v) => [v, 'item-weeks']} />
              <Bar dataKey="positions" radius={[0, 4, 4, 0]}>{d.suppliers.map((s, i) => <Cell key={s.supplier_id} fill={DEST_COLORS[(i * 2) % DEST_COLORS.length]} />)}</Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card title="Compare suppliers for one item" right={
        <select value={item} onChange={(e) => setItem(e.target.value)} aria-label="Choose an item" className="sel">
          {items.map((i) => <option key={i} value={i}>{i}</option>)}
        </select>}>
        <div className="tbl-wrap"><table>
          <thead><tr><th>Supplier</th><th className="r">Price vs benchmark</th><th className="r">Availability</th><th className="r">Confirms</th><th className="r">Refund</th><th className="r">Min. notice</th><th className="r">Requests</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.supplier_id} className="nohover"><td><b>{r.supplier}</b></td><td className="r">{signed(r.price_index - 1)}</td><td className="r">{pct(r.availability, 0)}</td>
              <td className="r">{pct(r.reliability, 1)}</td><td className="r">{pct(r.refund_rate, 0)}</td><td className="r">{r.min_lead_days} d</td><td className="r">{r.n_requests}</td></tr>))}</tbody>
        </table></div>
        {m && <p className="note">How well the history recovers each supplier's true behaviour (synthetic data lets us check): price ±{pct(m.price_index_mae, 2)}, availability ±{pct(m.availability_mae, 1)}, confirmation rate ±{pct(m.reliability_mae, 2)}, refund rate ±{pct(m.refund_rate_mae, 2)} (mean absolute error).</p>}
      </Card>
    </div>
  )
}
