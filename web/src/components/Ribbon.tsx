import type { Stage } from '../types'

/* The load profile drawn the way k6 will execute it: every stage ramps linearly from the
   previous target to its own, starting from zero. The same component draws the planned
   profile in the composer and the traversed profile during a run, so what somebody
   approved and what is executing are literally the same picture. */
const W = 900
const H = 132
const PAD_L = 34
const PAD_R = 12
const TOP = 16
const FLOOR = H - 26

export function Ribbon({ stages, elapsed, planned, stageIndex }: { stages: Stage[]; elapsed?: number; planned?: number; stageIndex?: number }) {
  const total = planned && planned > 0 ? planned : stages.reduce((sum, stage) => sum + stage.duration_seconds, 0)
  const open = stages.some((stage) => stage.target_rps != null)
  const value = (stage: Stage) => (open ? stage.target_rps ?? 0 : stage.target_vus ?? 0)
  const peak = Math.max(1, ...stages.map(value))
  const x = (second: number) => PAD_L + (total > 0 ? second / total : 0) * (W - PAD_L - PAD_R)
  const y = (level: number) => FLOOR - (level / (peak * 1.14)) * (FLOOR - TOP)

  let cursor = 0
  let previous = 0
  const points: Array<[number, number]> = [[x(0), y(0)]]
  const ticks: number[] = []
  for (const stage of stages) {
    const start = cursor
    cursor += stage.duration_seconds
    /* A hold stage keeps its level; only a changed target draws a ramp. */
    points.push([x(start), y(previous)], [x(cursor), y(value(stage))])
    previous = value(stage)
    ticks.push(cursor)
  }
  points.push([x(cursor), y(0)])
  const edge = points.slice(0, -1).map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(' ')
  const area = `M ${points.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(' L ')} Z`
  const head = elapsed !== undefined && total > 0 ? x(Math.min(elapsed, total)) : undefined

  return <div className="ribbon">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Load profile reaching ${peak} ${open ? 'requests per second' : 'virtual users'} over ${Math.round(total)} seconds`}>
      <defs><linearGradient id="lp-ribbon" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#00fb96" stopOpacity=".16" /><stop offset="100%" stopColor="#00fb96" stopOpacity="0" />
      </linearGradient></defs>
      <line className="track" x1={PAD_L} x2={W - PAD_R} y1={FLOOR} y2={FLOOR} />
      <line className="track" x1={PAD_L} x2={W - PAD_R} y1={TOP} y2={TOP} />
      {ticks.slice(0, -1).map((tick) => <line key={tick} className="tick" x1={x(tick)} x2={x(tick)} y1={TOP} y2={FLOOR} />)}
      <path className="fill" d={area} />
      <polyline className={head !== undefined ? 'edge done' : 'edge'} points={edge} />
      <text x={4} y={TOP + 4}>{Math.round(peak)}</text>
      <text x={14} y={FLOOR + 4}>0</text>
      <text x={PAD_L} y={H - 6}>{open ? 'requests per second' : 'virtual users'}</text>
      <text x={W - PAD_R} y={H - 6} textAnchor="end">{Math.round(total)}s</text>
      {head !== undefined && <>
        <line className="play" x1={head} x2={head} y1={TOP - 6} y2={FLOOR} />
        <circle className="cap" cx={head} cy={TOP - 6} r="2.6" />
      </>}
    </svg>
    <div className="ribbon-legend">
      {stages.map((stage, index) => <div key={`${stage.name}-${index}`} className={stageIndex === index ? 'now' : ''}>
        <b>{value(stage)}{open ? ' rps' : ' vu'} · {stage.duration_seconds}s</b>
        <span>{stage.name.replaceAll('_', ' ')}{stage.measurement === false ? ' · warm-up' : ''}</span>
      </div>)}
    </div>
  </div>
}
