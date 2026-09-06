import type { Run } from '../types'
import { clock, errorTone, millis, percent } from '../format'

/* Every run in the workspace as one line, the way a flight log is kept: newest first, one
   glyph for state, and the figures that decide whether the line is worth opening. The last
   column compares this run's p95 against the slowest run in the log — real comparative
   data, drawn rather than tabulated, so an outlier is visible without reading numbers. */
const P95 = 'http_req_duration.p(95)'
const ERR = 'http_req_failed.rate'

function tone(run: Run) {
  if (run.state === 'RUNNING' || run.state === 'INITIALIZING' || run.state === 'COLLECTING_TELEMETRY') return 'live'
  if (run.state === 'COMPLETED') return run.slo_passed === false ? 'bad' : 'good'
  if (['FAILED', 'TIMED_OUT', 'CANCELED'].includes(run.state)) return 'bad'
  return 'wait'
}

export function Log({ runs, selected, onSelect }: { runs: Run[]; selected?: string; onSelect: (id: string) => void }) {
  const worst = Math.max(1, ...runs.map((run) => run.metrics[P95] ?? 0))
  return <div className="log">
    <div className="log-row head">
      <span />
      <span>run</span>
      <span>state</span>
      <span>p95</span>
      <span className="hide-thin">errors</span>
      <span className="hide-thin">created</span>
      <span className="hide-thin">p95 against log</span>
    </div>
    {runs.map((run) => {
      const rate = run.metrics[ERR]
      const share = (run.metrics[P95] ?? 0) / worst
      return <button className={`log-row${selected === run.id ? ' on' : ''}`} key={run.id} onClick={() => onSelect(run.id)}>
        <span className={`dot ${tone(run)}`} />
        <span className="log-id">{run.id.slice(0, 8)}</span>
        <span className="log-state">{run.state.replaceAll('_', ' ').toLowerCase()}{run.slo_passed === false ? ' · breached' : ''}</span>
        <span className="log-figure">{run.metrics[P95] === undefined ? '—' : `${millis(run.metrics[P95])} ms`}</span>
        <span className={`log-figure hide-thin ${errorTone(rate)}`}>{rate === undefined ? '—' : percent(rate)}</span>
        <span className="log-when hide-thin">{clock(run.created_at)}</span>
        <span className="log-spark hide-thin">{run.metrics[P95] !== undefined && <svg viewBox="0 0 100 16" preserveAspectRatio="none" aria-hidden="true"><path d={`M 0 8 H ${Math.max(2, share * 100).toFixed(1)}`} /></svg>}</span>
      </button>
    })}
    {runs.length === 0 && <div className="hollow"><strong>log empty</strong>Nothing has been planned in this workspace yet.</div>}
  </div>
}
