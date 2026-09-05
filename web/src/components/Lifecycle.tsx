import type { RunState } from '../types'

const phases = [
  ['Intent', ['CREATED']],
  ['Discover', ['DISCOVERING_APPLICATION', 'GENERATING_DATA']],
  ['Plan', ['PLANNING', 'GENERATING_SCRIPT', 'VALIDATING']],
  ['Execute', ['SCHEDULED', 'QUEUED', 'INITIALIZING', 'RUNNING']],
  ['Analysis', ['COLLECTING_TELEMETRY', 'ANALYZING', 'COMPLETED']],
] as const

export function Lifecycle({ state }: { state: RunState }) {
  const active = phases.findIndex(([, states]) => (states as readonly string[]).includes(state))
  /* A finished run has finished every phase, including the one COMPLETED lives in. */
  const settled = state === 'COMPLETED'
  return <ol className="lifecycle" aria-label={`Run state ${state}`}>
    {phases.map(([label], index) => {
      const done = index < active || settled
      return <li key={label} className={done ? 'done' : index === active ? 'current' : ''}>
        <span>{done ? '✓' : index + 1}</span><div><strong>{label}</strong><small>{index === active ? state.replaceAll('_', ' ').toLowerCase() : done ? 'Complete' : 'Pending'}</small></div>
      </li>
    })}
  </ol>
}
