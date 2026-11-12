import React, { useEffect, useState } from 'react'
import { ComposedChart, LineChart, Line, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, LabelList } from 'recharts'
import { api, inr, pct } from './api'
import { Card, Loading, COLORS, tip, pnlFill, pnlTone } from './ui'

const cr = (v) => `₹${(v / 1e7).toFixed(1)}Cr`

export default function Risk({ settings }) {
  const [front, setFront] = useState(null)
  const [curve, setCurve] = useState(null)
  useEffect(() => {
    api.post('frontier', settings).then(setFront)
    api.post('budget-curve', settings).then(setCurve)
  }, [settings])

  return (
    <div className="stack">
      <p className="lead">Budget {inr(settings.budget, 0)} · max {Math.round(settings.max_dest_share * 100)}% per destination. Change these on the Budget Optimizer tab.</p>
      <div className="row2">
        <Card title="Risk–return frontier" sub="Each point is an optimal plan for a different risk appetite (λ). Moving right protects the downside; moving up earns more on average.">
          {!front ? <Loading text="Solving 6 plans…" /> : (
            <ResponsiveContainer width="100%" height={340}>
              <LineChart data={front} margin={{ left: 10, right: 30, top: 20, bottom: 10 }}>
                <CartesianGrid stroke={COLORS.grid} />
                <XAxis dataKey="cvar10" type="number" domain={['auto', 'auto']} tickFormatter={cr} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid}
                  label={{ value: 'Worst-10% average profit', position: 'insideBottom', offset: -5, fontSize: 12 }} />
                <YAxis dataKey="expected_profit" type="number" domain={['auto', 'auto']} tickFormatter={cr} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
                <Tooltip {...tip()} formatter={(v, n) => [inr(v), n]} labelFormatter={(v) => `Worst-10%: ${inr(v)}`} />
                <Line dataKey="expected_profit" name="Expected profit" stroke={COLORS.teal} strokeWidth={2} dot={{ r: 5, fill: COLORS.teal }}>
                  <LabelList dataKey="risk_aversion" position="top" formatter={(v) => `λ=${v}`} style={{ fontSize: 11 }} />
                </Line>
              </LineChart>
            </ResponsiveContainer>)}
          {front && <table className="mini"><thead><tr><th>λ</th><th className="r">Invested</th><th className="r">Expected</th><th className="r">Worst-10%</th><th className="r">ROI</th></tr></thead>
            <tbody>{front.map((f) => <tr key={f.risk_aversion} className="nohover"><td>{f.risk_aversion}</td><td className="r">{inr(f.invested)}</td><td className={`r ${pnlTone(f.expected_profit)}`}>{inr(f.expected_profit)}</td><td className={`r ${pnlTone(f.cvar10)}`}>{inr(f.cvar10)}</td><td className={`r ${pnlTone(f.roi)}`}>{pct(f.roi)}</td></tr>)}</tbody></table>}
        </Card>
        <Card title="How much budget is worth deploying?" sub="Optimal expected profit and ROI as the budget grows — returns diminish once the best opportunities are used up">
          {!curve ? <Loading text="Solving 7 budgets…" /> : (
            <ResponsiveContainer width="100%" height={400}>
              <ComposedChart data={curve} margin={{ left: 10, right: 10, top: 20 }}>
                <CartesianGrid vertical={false} stroke={COLORS.grid} />
                <XAxis dataKey="budget" tickFormatter={(v) => `₹${(v / 1e7).toFixed(0)}Cr`} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
                <YAxis yAxisId="l" tickFormatter={cr} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
                <YAxis yAxisId="r" orientation="right" tickFormatter={(v) => pct(v, 0)} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} domain={[0, 'auto']} />
                <Tooltip {...tip()} formatter={(v, n) => (n === 'ROI' ? pct(v) : inr(v))} labelFormatter={(v) => `Budget ${inr(v, 0)}`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar yAxisId="l" dataKey="invested" name="Capital deployed" fill={COLORS.light} radius={[4, 4, 0, 0]} />
                <Bar yAxisId="l" dataKey="expected_profit" name="Expected profit" fill={COLORS.teal} radius={[4, 4, 0, 0]}>
                  {curve.map((c) => <Cell key={c.budget} fill={pnlFill(c.expected_profit)} />)}
                </Bar>
                <Line yAxisId="r" dataKey="roi" name="ROI" stroke={COLORS.navy} strokeWidth={2} dot={{ r: 4 }} />
              </ComposedChart>
            </ResponsiveContainer>)}
        </Card>
      </div>
    </div>
  )
}
