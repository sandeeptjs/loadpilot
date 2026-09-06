import type { Sample } from '../types'
import { millis, percent } from '../format'

/* Real k6 samples, nothing smoothed or invented. Two series share the box because the
   only interesting question during a run is whether latency climbed before errors did:
   latency against the left scale in white, error rate against the right scale in rose. */
const W = 960
const H = 250
const L = 46
const RGT = 52
const TOP = 30
const BOT = H - 34
const P95 = 'http_req_duration.p(95)'
const ERR = 'http_req_failed.rate'

/* A fixed ceiling flattens every fast run onto the baseline. Round up to the next
   1 / 2 / 5 step above the peak so the trace always uses the height of the plot. */
function ceiling(peak: number) {
  if (!(peak > 0)) return 10
  const headroom = peak * 1.25
  const magnitude = 10 ** Math.floor(Math.log10(headroom))
  const scaled = headroom / magnitude
  return (scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10) * magnitude
}

export function Trace({ samples, live }: { samples: Sample[]; live: boolean }) {
  const measured = samples.filter((sample) => sample.metrics[P95] !== undefined)
  if (measured.length === 0) {
    return <div className="trace-empty">
      <strong>{live ? 'Instrument warming' : 'No telemetry collected'}</strong>
      <span>{live ? 'k6 emits its first aggregate a moment after the ramp begins.' : 'The plan must pass k6 validation and execute before measured samples exist.'}</span>
    </div>
  }
  const start = Date.parse(measured[0].timestamp)
  const span = Math.max(1, Date.parse(measured[measured.length - 1].timestamp) - start)
  const top = ceiling(Math.max(...measured.map((sample) => sample.metrics[P95])))
  const errPeak = Math.max(0.02, ...measured.map((sample) => sample.metrics[ERR] ?? 0))
  const errTop = ceiling(errPeak * 100) / 100
  const x = (sample: Sample) => L + ((Date.parse(sample.timestamp) - start) / span) * (W - L - RGT)
  const y = (value: number, scale: number) => BOT - Math.min(1, value / scale) * (BOT - TOP)

  const latency = measured.map((sample) => [x(sample), y(sample.metrics[P95], top)] as const)
  const errors = measured.filter((sample) => sample.metrics[ERR] !== undefined).map((sample) => [x(sample), y(sample.metrics[ERR], errTop)] as const)
  const line = latency.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(' ')
  const area = `M ${latency[0][0].toFixed(1)},${BOT} L ${line.replaceAll(' ', ' L ')} L ${latency[latency.length - 1][0].toFixed(1)},${BOT} Z`
  const head = latency[latency.length - 1]
  const last = measured[measured.length - 1].metrics

  return <div className="trace-panel">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Rolling p95 latency peaking near ${Math.round(top)} milliseconds across ${Math.round(span / 1000)} seconds`}>
      <defs><linearGradient id="lp-trace" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#00fb96" stopOpacity=".2" /><stop offset="100%" stopColor="#00fb96" stopOpacity="0" />
      </linearGradient></defs>
      {[0, 0.25, 0.5, 0.75, 1].map((step) => <line className="grid" key={step} x1={L} x2={W - RGT} y1={TOP + step * (BOT - TOP)} y2={TOP + step * (BOT - TOP)} />)}
      <path className="area" d={area} />
      <polyline className="line" points={line} />
      {errors.length > 1 && <polyline className="line err" points={errors.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(' ')} />}
      <circle className="halo" cx={head[0]} cy={head[1]} r="7" />
      <circle className="pip" cx={head[0]} cy={head[1]} r="3" />
      <text x={4} y={TOP + 4}>{Math.round(top)}</text>
      <text x={26} y={BOT + 4}>0</text>
      <text x={L} y={16}>p95 latency, ms</text>
      <text x={W - RGT + 8} y={TOP + 4}>{(errTop * 100).toFixed(errTop < 0.1 ? 1 : 0)}%</text>
      <text x={W - RGT + 8} y={16}>errors</text>
      <text x={L} y={H - 8}>first sample</text>
      <text x={W - RGT} y={H - 8} textAnchor="end">{Math.round(span / 1000)}s of samples</text>
    </svg>
    <div className="ribbon-legend">
      <div className={live ? 'now' : ''}><b>{millis(last[P95])} ms</b><span>latest rolling p95</span></div>
      <div><b>{percent(last[ERR] ?? 0)}</b><span>latest error rate</span></div>
      <div><b>{measured.length}</b><span>samples collected</span></div>
      <div><b>{millis(Math.max(...measured.map((sample) => sample.metrics[P95])))} ms</b><span>worst sample</span></div>
    </div>
  </div>
}
