import type { Run } from '../types'

function count(run: Run, key: string) {
  const metric = run.metrics[key]
  return metric === undefined ? '—' : Math.round(metric).toLocaleString()
}

function millis(run: Run, key: string) {
  const metric = run.metrics[key]
  return metric === undefined ? '—' : `${metric < 10 ? metric.toFixed(2) : Math.round(metric).toLocaleString()} ms`
}

export function MetricStrip({ run }: { run: Run }) {
  const failed = run.metrics['http_req_failed.rate']
  /* Colour is spent only on the number that has an unambiguous direction. Throughput
     and latency mean nothing without the target's own SLOs, so they stay neutral and
     a healthy run reads calm rather than alarmed. */
  const errorTone = failed === undefined ? '' : failed === 0 ? ' tone-good' : failed <= 0.01 ? ' tone-warn' : ' tone-bad'
  const metrics: Array<[string, string, string]> = [
    [run.state === 'RUNNING' ? 'Active virtual users' : 'Peak virtual users', count(run, run.state === 'RUNNING' ? 'vus' : 'vus.max'), ''],
    ['Requests', count(run, 'http_reqs.count'), ''],
    ['p95 latency', millis(run, 'http_req_duration.p(95)'), ''],
    ['Error rate', failed === undefined ? '—' : `${(failed * 100).toFixed(2)}%`, errorTone],
  ]
  return <div className="metric-strip">{metrics.map(([label, metric, tone], index) => <div key={label} className={`metric metric-${index}${tone}`}><strong>{metric}</strong><span>{label}</span></div>)}</div>
}
