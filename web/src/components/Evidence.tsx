import { useEffect, useState } from 'react'
import { count, errorTone, millis, percent } from '../format'
import type { Capabilities, Investigation, Plan, Run } from '../types'

/* The case the run makes, in the order an argument is made: the claim, the evidence, what
   the claim does not cover, and the next experiment. The figures beside it are the ones
   the analysis actually cites, and the artifacts are the raw material, so nothing here
   asks to be taken on trust. */
interface Correlation { received_notifications: number; distinct_alerts: number; duplicates_removed: number; incident_count: number; excluded_unrelated_notifications: number; incidents: Array<{ id: string; title: string; signals: string[] }> }
interface Report { report?: { correlation?: Correlation }; investigation?: { likely_root_cause?: string } }

const FIGURES: Array<[string, string]> = [
  ['http_req_duration.p(95)', 'p95 latency'],
  ['http_req_duration.p(99)', 'p99 latency'],
  ['http_req_duration.avg', 'mean latency'],
  ['http_req_failed.rate', 'error rate'],
  ['http_reqs.count', 'requests sent'],
  ['http_reqs.rate', 'throughput'],
  ['vus.max', 'peak virtual users'],
  ['iterations.count', 'journeys completed'],
  ['db_pool_utilization', 'target pool utilisation'],
  ['db_wait_ms', 'target pool wait'],
  ['db_pool_saturation_events', 'pool saturation events'],
]

function figure(key: string, value: number) {
  if (key.endsWith('.rate') && key.startsWith('http_req_failed')) return { text: percent(value), tone: errorTone(value) }
  if (key.endsWith('utilization')) return { text: percent(value, 1), tone: '' }
  if (key.endsWith('_ms') || key.includes('duration')) return { text: `${millis(value)} ms`, tone: '' }
  if (key === 'http_reqs.rate') return { text: `${value.toFixed(1)} /s`, tone: '' }
  return { text: count(value), tone: '' }
}

export function Evidence({ run, plan, investigation, capabilities, onSelect }: { run: Run; plan?: Plan | null; investigation?: Investigation | null; capabilities?: Capabilities; onSelect: (id: string) => void }) {
  const [report, setReport] = useState<Report>()
  const [comparison, setComparison] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    setReport(undefined); setComparison(undefined); setError('')
    if (run.state !== 'COMPLETED') return
    void fetch(`/api/runs/${run.id}/report`).then((response) => response.json()).then((data: Report) => { if (live) setReport(data) }).catch(() => {})
    if (run.parent_run_id) void fetch(`/api/runs/${run.id}/compare/${run.parent_run_id}`).then((response) => response.json()).then((data) => {
      const p95 = data.metrics?.['http_req_duration.p(95)']
      /* A comparison across different workloads is not a regression verdict, and saying
         so is the difference between evidence and a number with an arrow on it. */
      if (live && p95) setComparison(`Against its parent run, p95 moved ${millis(p95.baseline)} → ${millis(p95.current)} ms. ${data.same_workload ? 'Same workload, so this is comparable.' : 'Different workloads, so this is not a regression verdict.'}`)
    }).catch(() => {})
    return () => { live = false }
  }, [run.id, run.state, run.parent_run_id])

  async function act(path: string, body?: unknown) {
    setBusy(true); setError('')
    try {
      const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail ?? 'The action was refused')
      onSelect(data.verification_run_id ?? data.id)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  const correlation = report?.report?.correlation
  const remediable = capabilities?.remediation_enabled && report?.investigation?.likely_root_cause === 'Modeled connection-pool contention'
  const headline = investigation?.likely_root_cause ?? investigation?.summary
  /* The backend often repeats one sentence across summary, ai_summary and evidence.
     Collapsing the repeats makes this read as an argument rather than an echo. */
  const body = investigation
    ? [investigation.ai_summary ?? investigation.summary, ...investigation.evidence, ...(investigation.limitations ?? [])].filter((item, index, all) => item && item !== headline && all.indexOf(item) === index)
    : []
  const present = FIGURES.filter(([key]) => run.metrics[key] !== undefined)

  return <div className="evidence">
    <div className="finding">
      {headline ? <>
        <p className="finding-lead">{headline}</p>
        <span className="cite">evidence assessment {Math.round((investigation?.confidence ?? 0) * 100)} / 100 · heuristic, not a proof</span>
        {body.map((item) => <p key={item}>{item}</p>)}
        {comparison && <p>{comparison}</p>}
        {investigation?.recommended_next_experiment && <p className="next"><b>Next experiment.</b> {investigation.recommended_next_experiment}</p>}
      </> : <div className="hollow"><strong>no claim yet</strong>No root cause will be asserted without time-correlated evidence. Run the plan and the analysis will appear here with its own confidence.</div>}

      {correlation && <>
        <span className="cite">alert correlation</span>
        <p>{correlation.received_notifications} notifications reduced to {correlation.distinct_alerts} distinct alerts and {correlation.incident_count} incident{correlation.incident_count === 1 ? '' : 's'}; {correlation.duplicates_removed} duplicates removed and {correlation.excluded_unrelated_notifications} unrelated notifications excluded.</p>
        {correlation.incidents.map((incident) => <p key={incident.id}><b>{incident.title}</b> — {incident.signals.join(', ')}</p>)}
      </>}

      <div className="artifacts">
        <a className="act small" href={`/api/runs/${run.id}/report`} target="_blank" rel="noreferrer">evidence json</a>
        <a className="act small" href={`/api/runs/${run.id}/script`} target="_blank" rel="noreferrer">generated k6 script</a>
        {run.state === 'COMPLETED' && <button className="act small" disabled={busy} onClick={() => void act(`/api/runs/${run.id}/rerun`)}>repeat this workload</button>}
        {run.state === 'COMPLETED' && !run.parent_run_id && <button className="act small" disabled={busy} onClick={() => void act(`/api/runs/${run.id}/follow-up`)}>narrow the boundary</button>}
        {remediable && <button className="act small key" disabled={busy} onClick={() => void act(`/api/runs/${run.id}/remediate`, { pool_size: 12 })}>raise the pool to 12 and verify</button>}
      </div>
      {error && <span className="cite" style={{ color: 'var(--rose)' }}>{error}</span>}
    </div>

    <div className="instrument-side">
      {present.length > 0 ? <dl className="figures">
        {present.map(([key, label]) => { const shown = figure(key, run.metrics[key]); return <div className="figure" key={key}><dt>{label}</dt><dd className={shown.tone}>{shown.text}</dd></div> })}
      </dl> : <div className="hollow"><strong>awaiting signals</strong>k6 writes its summary when the run finishes. Live samples appear in the trace above while it executes.</div>}

      {plan && plan.thresholds.length > 0 && <div className="limits">
        {plan.thresholds.map((threshold) => <div className="limit" key={threshold.metric + threshold.expression}><span>{threshold.metric}</span><b>{threshold.expression}</b></div>)}
      </div>}
      {run.slo_passed !== null && run.slo_passed !== undefined && <span className="cite">declared limits {run.slo_passed ? 'held' : 'were breached'} for this run</span>}
    </div>
  </div>
}
