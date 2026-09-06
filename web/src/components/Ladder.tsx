import type { Progress } from '../types'

/* Every lifecycle state the run will pass through, named the way the backend names it.
   The point is that nothing is hidden: script generation and validation are steps that
   can fail, so they are steps somebody can watch rather than a spinner labelled Loading. */
export function Ladder({ progress }: { progress: Progress }) {
  return <div className="ladder" aria-label={`Pipeline position: ${progress.phase_label}`}>
    {progress.phases.map((phase) => <div className={`rung${phase.active ? ' now' : phase.reached ? ' reached' : ''}`} key={phase.state}>
      <div className="rung-mark"><i /></div>
      <b>{phase.label}</b>
      <span>{phase.active ? 'live' : phase.reached ? 'done' : 'pending'}</span>
    </div>)}
  </div>
}
