import { useEffect, useState } from 'react'
import { clock, millis, percent } from '../format'
import type { Run } from '../types'
import { Band } from './Band'
import { Log } from './Log'
import type { View } from './Rail'

/* The register pages. Each one is a different question asked of the same run history, so
   each one answers in its own shape: the log is a log, candidate baselines are figures,
   and the audit trail is a stream of what the system did and why. */
interface AuditEvent { id: string; action: string; timestamp: string; reason: string; related_test_id?: string }

const P95 = 'http_req_duration.p(95)'
const ERR = 'http_req_failed.rate'
const FLAGGED = ['FAILED', 'TIMED_OUT', 'CANCELED']

export function Sections({ view, runs, selected, onSelect }: { view: View; runs: Run[]; selected?: string; onSelect: (id: string) => void }) {
  const [events, setEvents] = useState<AuditEvent[]>([])
  useEffect(() => {
    if (view !== 'audit') return
    let live = true
    void fetch('/api/audit?limit=200').then((response) => response.json()).then((data: AuditEvent[]) => { if (live) setEvents(data) }).catch(() => { if (live) setEvents([]) })
    return () => { live = false }
  }, [view])

  const completed = runs.filter((run) => run.state === 'COMPLETED' && run.slo_passed !== false)
  const flagged = runs.filter((run) => FLAGGED.includes(run.state) || run.slo_passed === false)

  if (view === 'log') return <Band index="—" title="Flight log" lead="Every requirement this workspace has planned or executed, newest first." note={`${runs.length} recorded`}>
    <Log runs={runs} selected={selected} onSelect={onSelect} />
  </Band>

  if (view === 'experiments') return <Band index="—" title="Experiments" lead="Compiled plans, each one a question put to the target. Open one to see the profile it will execute." note={`${runs.length} compiled`}>
    <div className="cards">
      {runs.map((run) => <article className="card" key={run.id}>
        <b>{run.execution_backend.toLowerCase()} · {run.state.replaceAll('_', ' ').toLowerCase()}</b>
        <strong>{run.id.slice(0, 8)}</strong>
        <p>Planned {clock(run.created_at)}{run.scheduled_at ? `, scheduled for ${clock(run.scheduled_at)}` : ''}{run.parent_run_id ? `, following ${run.parent_run_id.slice(0, 8)}` : ''}.</p>
        <button className="act small" onClick={() => onSelect(run.id)}>open</button>
      </article>)}
      {runs.length === 0 && <article className="card"><b>empty</b><p>Write a requirement in the brief and the first experiment appears here.</p></article>}
    </div>
  </Band>

  if (view === 'baselines') return <Band index="—" title="Candidate baselines" lead="Completed runs whose declared limits held. These are the figures a later run is worth comparing against." note={`${completed.length} eligible`}>
    <div className="cards">
      {completed.map((run) => <article className="card" key={run.id}>
        <b>held its limits</b>
        <strong>{run.metrics[P95] === undefined ? 'no summary' : `${millis(run.metrics[P95])} ms p95`}</strong>
        <p>Run {run.id.slice(0, 8)} · error rate {percent(run.metrics[ERR] ?? 0)} · {clock(run.finished_at ?? run.created_at)}</p>
        <button className="act small" onClick={() => onSelect(run.id)}>view evidence</button>
      </article>)}
      {completed.length === 0 && <article className="card"><b>empty</b><p>A run that completes within its declared limits becomes a candidate baseline here.</p></article>}
    </div>
  </Band>

  if (view === 'incidents') return <Band index="—" title="Flags" lead="Runs that ended badly or breached the limits the requirement declared. Each one needs a person to read it." note={`${flagged.length} to review`}>
    <div className="cards">
      {flagged.map((run) => <article className="card flag" key={run.id}>
        <b>{run.state.replaceAll('_', ' ').toLowerCase()}{run.slo_passed === false ? ' · limits breached' : ''}</b>
        <strong>{run.id.slice(0, 8)}</strong>
        <p>{run.error ?? (run.slo_passed === false ? 'Execution finished, but the declared limits did not hold. The evidence is worth reading before rerunning.' : `The run ended as ${run.state.replaceAll('_', ' ').toLowerCase()}.`)}</p>
        <button className="act small" onClick={() => onSelect(run.id)}>inspect</button>
      </article>)}
      {flagged.length === 0 && <article className="card"><b>clear</b><p>No failed, timed-out or canceled runs, and no breached limits.</p></article>}
    </div>
  </Band>

  return <Band index="—" title="Audit trail" lead="What the system did, when, and the reason it recorded for doing it." note={`${events.length} events`}>
    <div className="stream">
      {events.map((event) => <div className="stream-row" key={event.id}>
        <div><b>{event.action}</b><p>{new Date(event.timestamp).toLocaleString()} · {event.reason}</p></div>
        {event.related_test_id && <button className="act small" onClick={() => onSelect(event.related_test_id!)}>open run</button>}
      </div>)}
      {events.length === 0 && <div className="hollow"><strong>nothing recorded</strong>Lifecycle events are appended as runs are planned, executed and analysed.</div>}
    </div>
  </Band>
}
