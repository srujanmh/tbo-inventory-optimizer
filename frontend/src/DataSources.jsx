import React, { useEffect, useState } from 'react'
import { api, STATIC, LIVE_URL, num } from './api'
import { Card, Kpi, KpiRow, Pill, Loading } from './ui'

const templateCsv = (t) => t.columns.map((c) => c.name).join(',') + '\n'
const download = (name, text) => {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

function Validator({ tables }) {
  const [kind, setKind] = useState(tables[0].kind)
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)

  const run = async () => {
    if (!file) return
    setBusy(true); setErr(null); setRes(null)
    try {
      const csv = await file.text()
      setRes(await api.post('data/validate', { kind, csv }))
    } catch (e) {
      setErr(e.message === 'server-only'
        ? 'File checks run on the server. Open the full app to check a file.'
        : `Could not check the file: ${e.message}`)
    } finally { setBusy(false) }
  }

  return (
    <Card title="Check a data file" sub="Upload an export before retraining. Nothing is stored; the file is only checked against the contract below.">
      <div className="validator">
        <label>Table
          <select value={kind} onChange={(e) => { setKind(e.target.value); setRes(null) }}>
            {tables.map((t) => <option key={t.kind} value={t.kind}>{t.file}</option>)}
          </select>
        </label>
        <label>CSV file
          <input type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] || null); setRes(null) }} />
        </label>
        <button className="run" disabled={!file || busy} onClick={run}>{busy ? 'Checking…' : 'Check file'}</button>
      </div>
      {STATIC && <p className="note">This copy runs entirely in your browser, so file checks are not available here. Use the full app at <a href={LIVE_URL} target="_blank" rel="noreferrer">{LIVE_URL.replace('https://', '')}</a>.</p>}
      {err && <p className="note txt-bad" role="alert">{err}</p>}
      {res && (
        <div className="val-result" role="status">
          <p className="lead">{res.ok ? <Pill tone="green">Passes</Pill> : <Pill tone="red">Needs fixing</Pill>}{' '}
            {num(res.rows)} rows{res.items != null && <> · {num(res.items)} items</>}{res.date_range && <> · {res.date_range[0]} → {res.date_range[1]}</>}</p>
          {res.issues.length > 0 && <ul className="issues">{res.issues.map((i) => <li key={i} className="txt-bad">{i}</li>)}</ul>}
          {res.warnings.length > 0 && <ul className="issues">{res.warnings.map((w) => <li key={w} className="muted">{w}</li>)}</ul>}
          {res.ok && res.issues.length === 0 && <p className="note">This file can be loaded. Load the full set of tables, then retrain (steps on the right).</p>}
        </div>
      )}
    </Card>
  )
}

export default function DataSources() {
  const [d, setD] = useState(null)
  const [open, setOpen] = useState(null)
  useEffect(() => { api.get('data/contract').then(setD) }, [])
  if (!d) return <Loading text="Loading data contract…" />
  const synthetic = d.source !== 'real'
  const totalCols = d.tables.reduce((a, t) => a + t.columns.length, 0)

  return (
    <div className="stack">
      <KpiRow>
        <Kpi label="Data in use now" value={synthetic ? 'Synthetic demo' : 'Real TBO data'} hint={synthetic ? 'every figure is simulated, not actual TBO results' : 'loaded through the data contract'} tone={synthetic ? 'warn' : 'good'} />
        <Kpi label="Tables in the contract" value={num(d.tables.length)} hint={`${totalCols} columns in total`} />
        <Kpi label="Models retrained from these files" value="6" hint="demand, cancellations, supplier rates, market price, elasticity, supplier scorecard" />
      </KpiRow>

      {synthetic && (
        <Card title="Why the numbers are simulated" className="sim-card">
          <p className="lead">The challenge did not include TBO data, so the prototype runs on a synthetic dataset that behaves like TBO's business: seasonality, holidays and events, sold-out days, cancellations, supplier quotes by lead time and six suppliers with different terms. Profit, savings and back-test results therefore show how the method performs, <b>not</b> what TBO has earned or saved.</p>
          <p className="note">No model depends on the synthetic generator. Every model reads only the six files below, so replacing them with an authorized export from TBO's systems and retraining moves the whole product onto real data.</p>
        </Card>
      )}

      <div className="row2">
        <Validator tables={d.tables} />
        <Card title="Moving to real data" sub="Three steps, run by the data team">
          <ol className="ol-steps">
            <li><b>Export</b> the six tables below from the booking engine, search logs, supplier contracting and procurement systems (at least 15 months of history).</li>
            <li><b>Validate and load</b>: <code>python -m pipeline.ingest --source /path/to/export</code>. Nothing is copied unless every table passes.</li>
            <li><b>Retrain</b>: <code>python -m pipeline.train</code> (about 2 minutes). It rebuilds every model, re-runs the accuracy back-test and the plan back-test, and re-checks the optimizer's maths.</li>
          </ol>
          <p className="note">Live feeds (search volumes, competitor rates, supplier availability) plug into the What-if &amp; Re-planning page, which re-optimises the plan when a signal changes demand, prices or availability.</p>
        </Card>
      </div>

      <Card title="Data contract" sub="The exact files and columns the system needs. Click a table to see its columns, or download an empty template.">
        <div className="tbl-wrap"><table>
          <thead><tr><th>File</th><th>What it holds</th><th>Comes from</th><th className="r">Columns</th><th className="r">Template</th></tr></thead>
          <tbody>{d.tables.map((t) => (
            <React.Fragment key={t.kind}>
              <tr onClick={() => setOpen(open === t.kind ? null : t.kind)} aria-expanded={open === t.kind} tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(open === t.kind ? null : t.kind) } }}>
                <td><b>{t.file}</b></td><td>{t.description}</td><td className="muted">{t.source}</td>
                <td className="r">{t.columns.length}</td>
                <td className="r"><button className="link" onClick={(e) => { e.stopPropagation(); download(t.file, templateCsv(t)) }}>Download</button></td>
              </tr>
              {open === t.kind && (
                <tr className="nohover detail"><td colSpan={5}>
                  <table className="inner"><thead><tr><th>Column</th><th>Type</th><th>Required</th><th>Rule</th></tr></thead>
                    <tbody>{t.columns.map((c) => (
                      <tr key={c.name} className="nohover"><td><code>{c.name}</code></td><td>{c.type}</td><td>{c.required ? 'yes' : 'optional'}</td><td className="muted">{c.rule || '–'}</td></tr>
                    ))}</tbody></table>
                  {t.key && <p className="note">Unique key: {t.key.join(' + ')}</p>}
                </td></tr>
              )}
            </React.Fragment>
          ))}</tbody>
        </table></div>
      </Card>
    </div>
  )
}
