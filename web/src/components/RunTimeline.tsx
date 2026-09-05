import type { Plan, Run } from '../types'

export function RunTimeline({ run, plan }: { run: Run; plan: Plan }) {
  const total = plan.stages.reduce((sum, stage) => sum + stage.duration_seconds, 0)
  const durationLabel = total < 60 ? `${total} seconds` : `${Math.round(total / 60)} minutes`
  const hasMetrics = Object.keys(run.metrics).length > 0
  return <section className="timeline-panel">
    <header><div><h2>Load profile</h2><p>Planned stages and collected k6 evidence</p></div><span className="live-dot">{run.state === 'RUNNING' ? 'Live' : run.state}</span></header>
    <div className="stage-rail">{plan.stages.map((stage) => <div key={stage.name} style={{ flex: stage.duration_seconds }}><strong>{stage.name}</strong><small>{stage.target_vus ?? 0} VUs · {Math.round(stage.duration_seconds / 60)}m</small></div>)}</div>
    <div className={hasMetrics ? 'chart has-data' : 'chart'}>
      {hasMetrics ? <>
        <div className="bar latency" style={{ height: `${Math.min(88, (run.metrics['http_req_duration.p(95)'] ?? 0) / 10)}%` }}><span>p95</span></div>
        <div className="bar requests" style={{ height: `${Math.min(88, (run.metrics['http_reqs.count'] ?? 0) / 20)}%` }}><span>requests</span></div>
        <div className="chart-note">Aggregated summary received. Time-series detail is queried from Prometheus for the run window.</div>
      </> : <div className="empty-chart"><ActivityMark /><strong>No telemetry collected yet</strong><span>The run must pass k6 validation and start before real metrics appear.</span></div>}
    </div>
    <footer><span>Executor <strong>{plan.executor}</strong></span><span>Duration <strong>{durationLabel}</strong></span><span>Source <strong>k6 + Prometheus</strong></span></footer>
  </section>
}

function ActivityMark() {
  return <svg width="54" height="30" viewBox="0 0 54 30" aria-hidden="true"><path d="M1 18h10l4-12 8 22 7-17 5 7h18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
}
