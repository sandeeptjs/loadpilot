import type { Progress } from '../types'
import { stopwatch } from '../format'

/* The progress instrument, drawn as one ring because the landing page is built on discs
   and this is the same object. Before execution the ring tracks the pipeline; once k6 is
   running it tracks the planned load profile, with a tick at every stage boundary, so the
   ring always answers the question actually being asked at that moment. */
const SIZE = 240
const MID = SIZE / 2
const R = 104
const CIRC = 2 * Math.PI * R

function polar(fraction: number, radius: number) {
  const angle = fraction * Math.PI * 2
  return [MID + Math.cos(angle) * radius, MID + Math.sin(angle) * radius] as const
}

export function Gauge({ progress, breached }: { progress: Progress; breached?: boolean }) {
  const executing = progress.planned_seconds > 0 && (progress.elapsed_seconds > 0 || progress.terminal)
  const reached = progress.phases.filter((phase) => phase.reached || phase.active).length
  const fraction = executing
    ? Math.max(0, Math.min(1, progress.fraction))
    : progress.phases.length ? Math.max(0, (reached - 0.5) / progress.phases.length) : 0
  const tone = breached ? ' bad' : executing || fraction > 0 ? '' : ' idle'
  const [hx, hy] = polar(fraction, R)

  return <div className="gauge">
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={`${Math.round(fraction * 100)} percent complete, phase ${progress.phase_label}`}>
      <circle className="track" cx={MID} cy={MID} r={R} />
      <circle className="track" cx={MID} cy={MID} r={R - 13} />
      <circle
        className={`arc${tone}`}
        cx={MID}
        cy={MID}
        r={R}
        strokeDasharray={`${(CIRC * fraction).toFixed(2)} ${CIRC.toFixed(2)}`}
      />
      {executing && progress.stages.map((stage) => {
        const at = (stage.offset_seconds ?? 0) / Math.max(1, progress.planned_seconds)
        const [x1, y1] = polar(at, R - 7)
        const [x2, y2] = polar(at, R + 7)
        return at > 0 ? <line className="stagetick" key={stage.name + String(stage.offset_seconds)} x1={x1} y1={y1} x2={x2} y2={y2} /> : null
      })}
      {fraction > 0 && fraction < 1 && <circle className="head" cx={hx} cy={hy} r="3.4" />}
    </svg>
    <div className="gauge-core">
      <span className="phase">{progress.phase_label}</span>
      <b>{Math.round(fraction * 100)}<i>%</i></b>
      <span className="m">{executing ? 'of planned profile' : 'through the pipeline'}</span>
      {executing && <span className="gauge-elapsed">{stopwatch(progress.elapsed_seconds)} / {stopwatch(progress.planned_seconds)}</span>}
    </div>
  </div>
}
