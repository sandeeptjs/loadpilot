import type { Plan, Run } from '../types'
import { useEffect, useState } from 'react'

export function RunTimeline({ run, plan }: { run: Run; plan: Plan }) {
  const [points, setPoints] = useState<Array<{ timestamp: string; metrics: Record<string, number> }>>([])
  useEffect(() => {
    let active = true
    setPoints([])
    const load = () => { void fetch(`/api/runs/${run.id}/samples?limit=10000`).then(r => r.json()).then(data => { if (active) setPoints(data.samples ?? []) }).catch(() => {}) }
    load()
    const timer = window.setInterval(load, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [run.id])
  const total = plan.stages.reduce((sum, stage) => sum + stage.duration_seconds, 0)
  const durationLabel = total < 60 ? `${total} seconds` : `${Math.round(total / 60)} minutes`
  const hasMetrics = Object.keys(run.metrics).length > 0
  const measured = points.filter(point => point.metrics['http_req_duration.p(95)'] !== undefined)
  const max = Math.max(100, ...measured.map(point => point.metrics['http_req_duration.p(95)']))
  const start = measured.length ? Date.parse(measured[0].timestamp) : 0
  const span = measured.length > 1 ? Date.parse(measured[measured.length - 1].timestamp) - start : 1
  const line = measured.map(point => `${45 + (Date.parse(point.timestamp) - start) / Math.max(span, 1) * 530},${210 - point.metrics['http_req_duration.p(95)'] / max * 170}`).join(' ')
  return <section className="timeline-panel">
    <header><div><h2>Load profile</h2><p>Planned stages and collected k6 evidence</p></div><span className="live-dot">{run.state === 'RUNNING' ? 'Live' : run.state}</span></header>
    <div className="stage-rail">{plan.stages.map((stage) => <div key={stage.name} style={{ flex: stage.duration_seconds }}><strong>{stage.name}</strong><small>{stage.target_vus ?? 0} VUs · {stage.duration_seconds}s</small></div>)}</div>
    <div className={hasMetrics ? 'chart has-data' : 'chart'}>
      {hasMetrics ? <>
        <svg className="telemetry-plot" viewBox="0 0 620 250" role="img" aria-label="Measured rolling p95 latency over time">
          <text x="45" y="20" fill="#81909b" fontSize="11">Rolling p95 latency, ms</text>
          <text x="4" y="45" fill="#81909b" fontSize="10">{Math.round(max)}</text>
          <text x="25" y="215" fill="#81909b" fontSize="10">0</text>
          <text x="45" y="238" fill="#81909b" fontSize="10">First sample</text>
          <text x="495" y="238" fill="#81909b" fontSize="10">{Math.round(span / 1000)}s elapsed</text>
          <polyline points={line} fill="none" stroke="#ffb72e" strokeWidth="2.5" />
        </svg>
        <div className="chart-note">Real k6 samples. Rolling p95 is an estimate; final summary metrics are authoritative.</div>
      </> : <div className="empty-chart"><ActivityMark /><strong>No telemetry collected yet</strong><span>The run must pass k6 validation and start before real metrics appear.</span></div>}
    </div>
    <footer><span>Executor <strong>{plan.executor}</strong></span><span>Duration <strong>{durationLabel}</strong></span><span>Source <strong>k6 + target metrics</strong></span></footer>
  </section>
}

function ActivityMark() {
  return <svg width="54" height="30" viewBox="0 0 54 30" aria-hidden="true"><path d="M1 18h10l4-12 8 22 7-17 5 7h18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
}
