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
  return <ol className="lifecycle" aria-label={`Run state ${state}`}>
    {phases.map(([label], index) => <li key={label} className={index < active ? 'done' : index === active ? 'current' : ''}>
      <span>{index < active ? '✓' : index + 1}</span><div><strong>{label}</strong><small>{index === active ? state.replaceAll('_', ' ').toLowerCase() : index < active ? 'Complete' : 'Pending'}</small></div>
    </li>)}
  </ol>
}

