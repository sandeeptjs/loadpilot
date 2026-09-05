import { useEffect, useState } from 'react'
import type { Run } from '../types'

interface Correlation { received_notifications: number; distinct_alerts: number; duplicates_removed: number; incident_count: number; notification_reduction_pct: number; excluded_unrelated_notifications: number; incidents: Array<{ id: string; title: string; signals: string[] }> }
interface Report { report: { correlation: Correlation }; investigation: { likely_root_cause?: string } }

export function DemoEvidence({ run, onSelect }: { run: Run; onSelect: (id: string) => void }) {
  const [report, setReport] = useState<Report>()
  const [enabled, setEnabled] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [comparison, setComparison] = useState<string>()
  useEffect(() => {
    let active = true
    setReport(undefined); setError(''); setComparison(undefined)
    if (run.state === 'COMPLETED') {
      void fetch(`/api/runs/${run.id}/report`).then(r => r.json()).then(data => { if (active && data.report) setReport(data) })
      void fetch('/api/capabilities').then(r => r.json()).then(data => { if (active) setEnabled(data.remediation_enabled) })
      if (run.parent_run_id) void fetch(`/api/runs/${run.id}/compare/${run.parent_run_id}`).then(r => r.json()).then(data => {
        const p95 = data.metrics?.['http_req_duration.p(95)']
        if (active && p95) setComparison(`p95: ${p95.baseline.toFixed(1)} → ${p95.current.toFixed(1)} ms. ${data.same_workload ? 'Same workload.' : 'Different workloads; not a regression verdict.'}`)
      })
    }
    return () => { active = false }
  }, [run.id, run.state, run.parent_run_id])
  async function action(path: string, body?: unknown) {
    setBusy(true); setError('')
    try {
      const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail ?? 'Action failed')
      onSelect(data.verification_run_id ?? data.id)
    } catch (reason) { setError(String(reason)) }
    finally { setBusy(false) }
  }
  if (!report) return null
  const c = report.report.correlation
  return <section className="demo-evidence">
    <h2>Alert correlation and next experiment</h2>
    <p>{c.received_notifications} notifications → {c.distinct_alerts} distinct alerts → {c.incident_count} incidents. {c.duplicates_removed} duplicates removed; {c.excluded_unrelated_notifications} unrelated notifications excluded.</p>
    {c.incidents.map(incident => <p key={incident.id}><strong>{incident.title}</strong> · {incident.signals.join(', ')}</p>)}
    {comparison && <p className="comparison">{comparison}</p>}
    <div className="run-actions">
      <a className="button secondary" href={`/api/runs/${run.id}/report`} target="_blank" rel="noreferrer">Full evidence JSON</a>
      <a className="button secondary" href={`/api/runs/${run.id}/script`} target="_blank" rel="noreferrer">Generated script</a>
      <button className="button secondary" disabled={busy} onClick={() => void action(`/api/runs/${run.id}/rerun`)}>Repeat workload</button>
      {!run.parent_run_id && <button className="button secondary" disabled={busy} onClick={() => void action(`/api/runs/${run.id}/follow-up`)}>Narrow the load boundary</button>}
      {enabled && report.investigation.likely_root_cause === 'Modeled connection-pool contention' && <button className="button primary" disabled={busy} onClick={() => void action(`/api/runs/${run.id}/remediate`, { pool_size: 12 })}>Increase sandbox pool to 12 and verify</button>}
    </div>
    <p>Sandbox actions use a fixed target, an allow-listed setting, a maximum pool size, and recorded rollback values.</p>
    {error && <p className="form-error">{error}</p>}
  </section>
}
