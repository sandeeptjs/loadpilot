import type { Run } from '../types'

function value(run: Run, key: string, suffix = '') {
  const metric = run.metrics[key]
  return metric === undefined ? '—' : `${metric < 10 ? metric.toFixed(2) : Math.round(metric)}${suffix}`
}

export function MetricStrip({ run }: { run: Run }) {
  const metrics = [
    [run.state === 'RUNNING' ? 'Active virtual users' : 'Peak virtual users', value(run, run.state === 'RUNNING' ? 'vus' : 'vus.max')],
    ['Requests', value(run, 'http_reqs.count')],
    ['p95 latency', value(run, 'http_req_duration.p(95)', ' ms')],
    ['Error rate', run.metrics['http_req_failed.rate'] === undefined ? '—' : `${(run.metrics['http_req_failed.rate'] * 100).toFixed(2)}%`],
  ]
  return <div className="metric-strip">{metrics.map(([label, metric], index) => <div key={label} className={`metric metric-${index}`}><strong>{metric}</strong><span>{label}</span></div>)}</div>
}

