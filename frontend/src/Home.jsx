import React from 'react'
import { inr, pct, num } from './api'
import { motion } from 'motion/react'
import { Card, CountUp, fadeUp, stagger } from './ui'
import { Scorecard } from './Overview'
import Backtest from './Backtest'

const STEPS = [
  ['01', 'Recover true demand', 'Sold-out days hide demand: bookings stop at capacity. Searches ÷ look-to-book ratio recover what customers actually wanted.', 'Demand unconstraining'],
  ['02', 'Forecast with uncertainty', 'Quantile gradient-boosting models predict P10 / P50 / P90 demand for every hotel and route, for each of the next 13 travel weeks.', 'LightGBM quantile ensemble'],
  ['03', 'Price, cancel & cost models', 'Price elasticity sets the selling price, a cancellation model nets out drop-offs, and a supplier-rate model finds the cheapest moment to buy.', 'Elasticity · cancellations · buy timing'],
  ['04', 'Simulate 1,000 futures', 'Monte Carlo scenarios with shared market, destination and item shocks turn each option into a full profit distribution.', 'Monte Carlo + newsvendor'],
  ['05', 'Allocate the budget', 'An optimizer picks how many units of which item-week to buy, maximising expected profit while protecting the worst case.', 'Mean–CVaR optimization'],
]

export default function Home({ summary, go }) {
  const bt = summary.forecast_backtest, un = summary.unconstraining
  return (
    <div className="home">
      <section className="hero">
        <motion.div className="hero-txt" variants={stagger(0.1, 0.05)} initial="hidden" animate="show">
          <motion.div variants={fadeUp} className="eyebrow light">Hackathon · Inventory Optimization for TBO.com</motion.div>
          <motion.h1 variants={fadeUp}>Buy the right travel inventory, at the right time, within the right budget.</motion.h1>
          <motion.p variants={fadeUp}>
            An AI decision-support platform that turns bookings, searches, sold-outs, seasonality and events into a
            pre-buy plan for hotel rooms and flight seats. It says what to buy, how many, when, and at what price,
            to maximise risk-adjusted profit for a given budget.
          </motion.p>
          <motion.div variants={fadeUp} className="cta">
            <motion.button className="run big" onClick={() => go('optimizer')} whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}>Try the budget optimizer →</motion.button>
            <motion.button className="ghost big" onClick={() => go('overview')} whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}>Explore demand & accuracy</motion.button>
          </motion.div>
        </motion.div>
        <motion.div className="hero-stats" variants={stagger(0.09, 0.35)} initial="hidden" animate="show">
          <motion.div variants={fadeUp} whileHover={{ y: -4 }}><b><CountUp value={1 - bt.weekly_wape} format={(v) => pct(v)} duration={1.4} /></b><span>weekly forecast accuracy<br /><small>vs {pct(1 - bt.weekly_wape_naive)} naive</small></span></motion.div>
          <motion.div variants={fadeUp} whileHover={{ y: -4 }}><b><CountUp value={un.hidden_demand_recovered} format={num} duration={1.6} /></b><span>hidden demand recovered<br /><small>on sold-out days</small></span></motion.div>
          <motion.div variants={fadeUp} whileHover={{ y: -4 }}><b>{summary.n_items} × {summary.horizon.weeks}</b><span>items × travel weeks<br /><small>{summary.n_viable} profitable options</small></span></motion.div>
          <motion.div variants={fadeUp} whileHover={{ y: -4 }}><b>&lt; 1 s</b><span>to re-plan any budget<br /><small>runs in your browser</small></span></motion.div>
        </motion.div>
      </section>

      <div className="problem">
        {[
          ['Sold-outs hide demand', 'In peak weeks supply runs out, so historical bookings understate what customers wanted, and naive plans under-buy exactly where it matters.'],
          ['Every rupee competes', 'A fixed budget has to be split across hotels, flights, destinations and travel weeks, each with different margin, demand and risk.'],
          ['Unsold stock is a loss', 'Pre-bought rooms and seats that do not sell are only partly refundable, so demand uncertainty and cancellations must be priced in.'],
        ].map(([t, d]) => <Card key={t} title={t}><p className="muted">{d}</p></Card>)}
      </div>

      <h2 className="sec">How it works</h2>
      <motion.div className="steps" variants={stagger(0.1)} initial="hidden" whileInView="show" viewport={{ once: true, margin: '-60px' }}>
        {STEPS.map(([n, t, d, tag]) => (
          <motion.div className="step" key={n} variants={fadeUp} whileHover={{ y: -4, boxShadow: '0 10px 24px rgba(15,23,42,.08)' }}>
            <div className="num">{n}</div><h4>{t}</h4><p>{d}</p><span className="pill blue">{tag}</span>
          </motion.div>
        ))}
      </motion.div>


      <h2 className="sec">Is it accurate?</h2>
      <Backtest summary={summary} />
      <Scorecard summary={summary} />

      <p className="muted small-note">
        Data note: the challenge did not include a dataset, so the platform runs on a realistic synthetic dataset
        ({summary.history.start} → {summary.history.end}, {summary.n_items} hotels & routes across {summary.destinations.length} destinations)
        with seasonality, Indian holidays, destination events, promotions, supply shortages, cancellations and lead-time-dependent supplier rates.
        Swap in real TBO data with the same columns and retrain.
      </p>
    </div>
  )
}
