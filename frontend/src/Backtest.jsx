import React from 'react'
import { ComposedChart, Bar, Cell, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'
import { inr, pct, num, shortWeek } from './api'
import { Card, Kpi, KpiRow, COLORS, tip, pnlTone, pnlFill } from './ui'

const cr = (v) => `₹${(v / 1e7).toFixed(1)}Cr`

/** Back-dated plan test: plan made with data available on `as_of`, replayed against what really happened. */
export default function Backtest({ summary }) {
  const bt = summary.plan_backtest
  if (!bt) return null
  const ai = bt.ai, gr = bt.greedy, ly = bt.last_year
  const rows = [
    ['AI optimizer (MILP)', ai], ['Greedy ROI ranking', gr], ["Last year's mix", ly],
  ]
  return (
    <Card title="Back-test: would the plan have made money?"
      sub={`Plan built as of ${bt.as_of} using only data available that day, then replayed against what really happened in the next ${bt.weeks} travel weeks (${bt.horizon_start} → ${bt.horizon_end}): real demand, real cancellations and the supplier's real quotes.`}>
      <KpiRow className="four">
        <Kpi label="Realised profit" num={ai.realised_profit} fmt={(v) => inr(v)} hint={`predicted ${inr(ai.predicted_profit)} · ${pct(ai.prediction_gap)} gap`} tone={pnlTone(ai.realised_profit)} />
        <Kpi label="Realised ROI" num={ai.realised_roi} fmt={(v) => pct(v)} hint={`on ${inr(ai.invested)} invested`} tone={pnlTone(ai.realised_roi)} />
        <Kpi label="vs last year's mix" num={ai.realised_profit / ly.realised_profit - 1} fmt={(v) => `${v >= 0 ? '+' : ''}${pct(v)}`} hint={`${inr(ai.realised_profit - ly.realised_profit)} difference`} tone={pnlTone(ai.realised_profit - ly.realised_profit)} />
        <Kpi label="Loss-making positions" num={ai.loss_making_positions} fmt={num} hint={`of ${ai.positions} · last year's mix: ${ly.loss_making_positions}`} tone="bad" />
      </KpiRow>
      <div className="row2" style={{ marginBottom: 0 }}>
        <div>
          <h4 className="mini-h">Predicted vs realised profit by travel week (AI plan)</h4>
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={bt.weekly} margin={{ left: 0, right: 10, top: 10 }}>
              <CartesianGrid vertical={false} stroke={COLORS.grid} />
              <XAxis dataKey="week" tickFormatter={shortWeek} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
              <YAxis tickFormatter={cr} tick={{ fontSize: 11, fill: COLORS.muted }} stroke={COLORS.grid} />
              <Tooltip {...tip()} formatter={(v) => inr(v)} labelFormatter={(w) => `Week of ${w}`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="realised_profit" name="Realised profit" fill={COLORS.teal} radius={[4, 4, 0, 0]}>
                {bt.weekly.map((w) => <Cell key={w.week} fill={pnlFill(w.realised_profit)} />)}
              </Bar>
              <Line dataKey="predicted_profit" name="Predicted profit" stroke={COLORS.blue} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div>
          <h4 className="mini-h">Same budget, three strategies, real outcomes</h4>
          <div className="tbl-wrap"><table>
            <thead><tr><th>Strategy</th><th className="r">Invested</th><th className="r">Predicted</th><th className="r">Realised</th><th className="r">ROI</th><th className="r">Sell-through</th><th className="r">Losses</th></tr></thead>
            <tbody>{rows.map(([n, s]) => (
              <tr key={n} className="nohover"><td><b>{n}</b></td><td className="r">{inr(s.invested)}</td><td className={`r ${pnlTone(s.predicted_profit)}`}>{inr(s.predicted_profit)}</td>
                <td className={`r ${pnlTone(s.realised_profit)}`}>{inr(s.realised_profit)}</td><td className={`r ${pnlTone(s.realised_roi)}`}>{pct(s.realised_roi)}</td><td className="r">{pct(s.sell_through, 0)}</td><td className={`r ${s.loss_making_positions > 0 ? 'bad' : ''}`}>{s.loss_making_positions}</td></tr>
            ))}</tbody>
          </table></div>
          <p className="note">Realised profit landed within {pct(Math.abs(ai.prediction_gap))} of the prediction, so the risk model is well calibrated. Copying last year's mix tied money up in {ly.loss_making_positions} positions that lost money.</p>
        </div>
      </div>
    </Card>
  )
}
