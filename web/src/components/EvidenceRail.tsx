import type { Investigation, Plan, Run } from '../types'

const preferred = ['db_pool_utilization', 'db_wait_ms', 'db_pool_saturation_events', 'http_req_duration.p(95)', 'http_req_failed.rate', 'http_reqs.count']
const labels: Record<string, string> = { db_pool_utilization: 'DB pool utilization', db_wait_ms: 'Average DB wait', db_pool_saturation_events: 'Pool saturation events', 'http_req_duration.p(95)': 'Overall p95 latency', 'http_req_failed.rate': 'HTTP error rate', 'http_reqs.count': 'HTTP requests' }
function format(key: string, value: number) {
  if (key.endsWith('utilization') || key.endsWith('.rate')) return `${(value * 100).toFixed(1)}%`
  if (key.endsWith('_ms') || key.includes('duration')) return `${value.toFixed(1)} ms`
  return value.toFixed(0)
}

export function EvidenceRail({ run, plan, investigation }: { run: Run; plan: Plan; investigation?: Investigation }) {
  const evidence = Object.keys(run.metrics).length > 0
  return <aside className="evidence-rail">
    <section><h2>Run evidence</h2>
      {evidence ? <dl>{preferred.filter((key) => run.metrics[key] !== undefined).map((key) => <div key={key}><dt>{labels[key]}</dt><dd>{format(key, run.metrics[key])}</dd></div>)}</dl> : <div className="rail-empty"><strong>Awaiting signals</strong><span>No root cause will be claimed without time-correlated evidence.</span></div>}
    </section>
    {investigation && <section className="finding"><h2>Analysis</h2><strong>{investigation.likely_root_cause ?? investigation.summary}</strong><p>{investigation.ai_summary ?? investigation.summary}</p><span>Evidence assessment: {Math.round(investigation.confidence * 100)} / 100, heuristic</span>{investigation.evidence.map((item) => <p key={item}>{item}</p>)}{investigation.limitations?.map((item) => <p key={item}>{item}</p>)}{investigation.recommended_next_experiment && <p className="next"><b>Next:</b> {investigation.recommended_next_experiment}</p>}</section>}
    <section><h2>Thresholds</h2><ul className="threshold-list">{plan.thresholds.map((threshold) => <li key={threshold.metric}><span>{threshold.metric}</span><strong>{threshold.expression}</strong></li>)}</ul></section>
    <section><h2>Journey</h2><ol className="journey">{plan.journeys.flatMap((journey) => journey.steps).map((step, index) => <li key={`${step.operation_id}-${index}`}><span>{index + 1}</span>{step.operation_id}</li>)}</ol></section>
  </aside>
}
