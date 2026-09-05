import type { Plan, Run } from '../types'
import { useEffect, useState } from 'react'

/* Plot geometry. The measured series is mapped into this box; the numbers are the
   same ones the previous polyline used, kept here as constants so the axis, the
   area fill and the trace cannot drift apart. */
const X0 = 45
const X1 = 575
const Y0 = 210
const Y1 = 40

/* A fixed 100 ms ceiling flattened every fast run into a line along the baseline.
   Round up to the next 1 / 2 / 5 step above the peak instead, so the trace always
   uses the height of the plot and the axis label stays a readable number. */
function ceiling(peak: number) {
  if (!(peak > 0)) return 10
  const headroom = peak * 1.25
  const magnitude = 10 ** Math.floor(Math.log10(headroom))
  const scaled = headroom / magnitude
  return (scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10) * magnitude
}

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
  const live = run.state === 'RUNNING'
  const measured = points.filter(point => point.metrics['http_req_duration.p(95)'] !== undefined)
  const max = ceiling(measured.length ? Math.max(...measured.map(point => point.metrics['http_req_duration.p(95)'])) : 0)
  const start = measured.length ? Date.parse(measured[0].timestamp) : 0
  const span = measured.length > 1 ? Date.parse(measured[measured.length - 1].timestamp) - start : 1
  const plotted = measured.map(point => ({
    x: X0 + (Date.parse(point.timestamp) - start) / Math.max(span, 1) * (X1 - X0),
    y: Y0 - point.metrics['http_req_duration.p(95)'] / max * (Y0 - Y1),
  }))
  const line = plotted.map(point => `${point.x},${point.y}`).join(' ')
  const area = plotted.length ? `M ${plotted[0].x},${Y0} ${plotted.map(point => `L ${point.x},${point.y}`).join(' ')} L ${plotted[plotted.length - 1].x},${Y0} Z` : ''
  const head = plotted[plotted.length - 1]
  return <section className="timeline-panel">
    <header><div><h2>Load profile</h2><p>Planned stages and collected k6 evidence</p></div><span className={live ? 'live-dot live' : 'live-dot'}>{live ? 'Live' : run.state}</span></header>
    <div className="stage-rail">{plan.stages.map((stage) => <div key={stage.name} style={{ flex: stage.duration_seconds }}><strong>{stage.name}</strong><small>{stage.target_vus ?? 0} VUs · {stage.duration_seconds}s</small></div>)}</div>
    <div className={hasMetrics ? 'chart has-data' : 'chart'}>
      {hasMetrics ? <>
        <svg className="telemetry-plot" viewBox="0 0 620 250" role="img" aria-label="Measured rolling p95 latency over time">
          <defs>
            <linearGradient id="lp-trace-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#00fb96" stopOpacity=".22" />
              <stop offset="100%" stopColor="#00fb96" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0, 0.25, 0.5, 0.75, 1].map((step) => <line key={step} className="axis" x1={X0} x2={X1} y1={Y1 + step * (Y0 - Y1)} y2={Y1 + step * (Y0 - Y1)} />)}
          <text x={X0} y="20" fontSize="11">Rolling p95 latency, ms</text>
          <text x="4" y={Y1 + 5} fontSize="10">{Math.round(max)}</text>
          <text x="25" y={Y0 + 5} fontSize="10">0</text>
          <text x={X0} y="238" fontSize="10">First sample</text>
          <text x="495" y="238" fontSize="10">{Math.round(span / 1000)}s elapsed</text>
          {area && <path className="area" d={area} fill="url(#lp-trace-area)" />}
          <polyline className="glow" points={line} />
          <polyline className="trace" points={line} />
          {head && <><circle className="halo" cx={head.x} cy={head.y} r="7" /><circle className="head" cx={head.x} cy={head.y} r="3" /></>}
        </svg>
      </> : <div className="empty-chart"><ActivityMark /><strong>No telemetry collected yet</strong><span>The run must pass k6 validation and start before real metrics appear.</span></div>}
    </div>
    {hasMetrics && <div className="chart-note">Real k6 samples. Rolling p95 is an estimate; final summary metrics are authoritative.</div>}
    <footer><span>Executor <strong>{plan.executor}</strong></span><span>Duration <strong>{durationLabel}</strong></span><span>Source <strong>k6 + target metrics</strong></span></footer>
  </section>
}

function ActivityMark() {
  return <svg width="54" height="30" viewBox="0 0 54 30" aria-hidden="true"><path d="M1 18h10l4-12 8 22 7-17 5 7h18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
}
