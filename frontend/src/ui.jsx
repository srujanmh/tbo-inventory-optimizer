import React, { useEffect, useRef, useState } from 'react'
import { motion, animate } from 'motion/react'

export const EASE = [0.22, 1, 0.36, 1]
export const fadeUp = { hidden: { opacity: 0, y: 14 }, show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } } }
export const stagger = (gap = 0.06, delay = 0) => ({ hidden: {}, show: { transition: { staggerChildren: gap, delayChildren: delay } } })

/** Animated number: tweens from the previous value to the new one. */
export function CountUp({ value, format = (v) => Math.round(v).toLocaleString('en-IN'), duration = 0.9 }) {
  const [v, setV] = useState(0)
  const prev = useRef(0)
  useEffect(() => {
    if (value === null || value === undefined || isNaN(value)) return
    const ctl = animate(prev.current, value, { duration, ease: EASE, onUpdate: setV })
    prev.current = value
    return () => ctl.stop()
  }, [value])
  return <>{format(v)}</>
}

/** Row of KPI cards that stagger in. */
export const KpiRow = ({ className = '', children }) => (
  <motion.div className={`kpis ${className}`} variants={stagger(0.05)} initial="hidden" animate="show">{children}</motion.div>
)

export const Card = ({ title, sub, right, children, className = '' }) => (
  <motion.section className={`card ${className}`} initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }}
    viewport={{ once: true, margin: '-40px' }} transition={{ duration: 0.5, ease: EASE }}>
    {(title || right) && (
      <header className="card-h">
        <div>
          <h3>{title}</h3>
          {sub && <p className="sub">{sub}</p>}
        </div>
        {right}
      </header>
    )}
    {children}
  </motion.section>
)

export const Kpi = ({ label, value, num, fmt, hint, tone }) => (
  <motion.div className={`kpi ${tone || ''}`} variants={fadeUp} whileHover={{ y: -3 }}>
    <div className="kpi-l">{label}</div>
    <div className="kpi-v">{num !== undefined ? <CountUp value={num} format={fmt} /> : value}</div>
    {hint && <div className="kpi-h">{hint}</div>}
  </motion.div>
)

export const Pill = ({ children, tone = '' }) => <span className={`pill ${tone}`}>{children}</span>

export const RiskPill = ({ v }) => {
  const tone = v >= 0.6 ? 'red' : v >= 0.35 ? 'amber' : 'green'
  return <Pill tone={tone}>{Math.round(v * 100)}%</Pill>
}

export const Loading = ({ text = 'Loading…' }) => <div className="loading"><span className="spin" />{text}</div>

// Theme palettes for charts (CSS handles everything else through variables)
export const PALETTES = {
  light: {
    navy: '#18181B', blue: '#18181B', teal: '#15803D', amber: '#B45309', red: '#DC2626', slate: '#A1A1AA',
    grid: '#ECECEA', purple: '#52525B', light: '#D4D4D8', text: '#18181B', muted: '#6B6B73', surface: '#FFFFFF',
    dest: ['#18181B', '#2E2E33', '#3F3F46', '#52525B', '#63636B', '#71717A', '#8B8B93', '#A1A1AA', '#B8B8BE', '#D4D4D8'],
    heat: { demand: [24, 24, 27], sold_out_risk: [220, 38, 38], opportunity: [21, 128, 61] },
    heatInk: { demand: '#FFFFFF', sold_out_risk: '#FFFFFF', opportunity: '#FFFFFF' },
  },
  dark: {
    navy: '#F2F2F2', blue: '#F2F2F2', teal: '#4ADE80', amber: '#FBBF24', red: '#F87171', slate: '#A1A1AA',
    grid: '#2E2E2E', purple: '#D4D4D8', light: '#55555C', text: '#EDEDED', muted: '#A1A1AA', surface: '#1B1B1B',
    dest: ['#FAFAFA', '#E4E4E7', '#D4D4D8', '#C4C4C8', '#A1A1AA', '#8B8B93', '#71717A', '#5E5E66', '#52525B', '#3F3F46'],
    heat: { demand: [250, 250, 250], sold_out_risk: [248, 113, 113], opportunity: [74, 222, 128] },
    heatInk: { demand: '#0A0A0A', sold_out_risk: '#0A0A0A', opportunity: '#0A0A0A' },
  },
}
// Mutable palette objects: App calls setPalette() before rendering, so every chart re-renders in the new theme.
export const COLORS = { ...PALETTES.light }
export const DEST_COLORS = [...PALETTES.light.dest]
export function setPalette(theme) {
  Object.assign(COLORS, PALETTES[theme])
  DEST_COLORS.splice(0, DEST_COLORS.length, ...PALETTES[theme].dest)
}

/** Profit / loss colouring: green for >= 0, red for < 0 — used everywhere money is shown */
export const pnlTone = (v) => (v < 0 ? 'bad' : 'good')          // Kpi tone + table cell class
export const pnlFill = (v) => (v < 0 ? COLORS.red : COLORS.teal)  // chart fills
export const Pnl = ({ v, children }) => <span className={v < 0 ? 'txt-bad' : 'txt-good'}>{children}</span>

/** Shared Recharts tooltip styling */
export const tip = () => ({
  contentStyle: { background: COLORS.surface, border: `1px solid ${COLORS.grid}`, borderRadius: 10, color: COLORS.text, fontSize: 12 },
  labelStyle: { color: COLORS.muted }, itemStyle: { color: COLORS.text }, cursor: { fill: 'rgba(128,128,128,0.08)' },
})
export const axis = () => ({ tick: { fontSize: 11, fill: COLORS.muted }, stroke: COLORS.grid })

/** Small amber tag marking figures that come from simulated (synthetic) data */
export const Sim = ({ title = 'Computed on the synthetic demo dataset, not actual TBO results' }) => <span className="sim-tag" title={title}>simulated</span>

/** Collapsible definitions / explanations */
export const Defs = ({ items }) => (
  <div className="defs">{items.map(([k, v, d]) => <div className="def" key={k}><div className="k">{k}</div><b>{v}</b><p>{d}</p></div>)}</div>
)
