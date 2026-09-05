import { Activity, Beaker, BarChart3, ScrollText, TriangleAlert } from 'lucide-react'
import type { Run } from '../types'
import { RunsTable } from './RunsTable'

type Section = 'Runs' | 'Experiments' | 'Baselines' | 'Incidents' | 'Audit'

const copy: Record<Section, { title: string; description: string }> = {
  Runs: { title: 'Test runs', description: 'Every planned and executed performance test in this workspace.' },
  Experiments: { title: 'Experiments', description: 'Compare proposed load profiles before sending traffic.' },
  Baselines: { title: 'Baselines', description: 'Reference performance targets derived from completed runs.' },
  Incidents: { title: 'Incidents', description: 'Runs that need investigation because execution or thresholds failed.' },
  Audit: { title: 'Audit trail', description: 'Lifecycle activity retained for accountability and review.' },
}

export function WorkspaceSection({ section, runs, selected, onSelect }: { section: Section; runs: Run[]; selected?: string; onSelect: (id: string) => void }) {
  const meta = copy[section]
  const completed = runs.filter((run) => run.state === 'COMPLETED')
  const incidents = runs.filter((run) => ['FAILED', 'TIMED_OUT', 'CANCELED'].includes(run.state))
  const icon = section === 'Experiments' ? <Beaker /> : section === 'Baselines' ? <BarChart3 /> : section === 'Incidents' ? <TriangleAlert /> : section === 'Audit' ? <ScrollText /> : <Activity />

  return <div className="section-page">
    <header className="section-heading"><div><span className="section-icon">{icon}</span><h1>{meta.title}</h1><p>{meta.description}</p></div><span className="section-count">{section === 'Baselines' ? completed.length : section === 'Incidents' ? incidents.length : runs.length} records</span></header>
    {section === 'Runs' && <RunsTable runs={runs} selected={selected} onSelect={onSelect} />}
    {section === 'Experiments' && <div className="section-cards">{runs.map((run) => <article className="section-card" key={run.id}><span>LOAD EXPERIMENT</span><strong>{run.id.slice(0, 8)}</strong><p>{run.state.replaceAll('_', ' ').toLowerCase()} · {run.execution_backend.toLowerCase()} backend</p><button className="button secondary" onClick={() => onSelect(run.id)}>Open run</button></article>)}{!runs.length && <Empty label="Create a test to begin an experiment." />}</div>}
    {section === 'Baselines' && <div className="section-cards">{completed.map((run) => <article className="section-card" key={run.id}><span>COMPLETED BASELINE</span><strong>{run.metrics['http_req_duration.p(95)'] ? `${Math.round(run.metrics['http_req_duration.p(95)'])} ms p95` : 'Metrics pending'}</strong><p>Run {run.id.slice(0, 8)} · error rate {((run.metrics['http_req_failed.rate'] ?? 0) * 100).toFixed(2)}%</p><button className="button secondary" onClick={() => onSelect(run.id)}>View evidence</button></article>)}{!completed.length && <Empty label="Completed runs will appear here as candidate baselines." />}</div>}
    {section === 'Incidents' && <div className="section-cards">{incidents.map((run) => <article className="section-card incident" key={run.id}><span>NEEDS REVIEW</span><strong>{run.state.replaceAll('_', ' ')}</strong><p>{run.error ?? `Run ${run.id.slice(0, 8)} requires follow-up.`}</p><button className="button secondary" onClick={() => onSelect(run.id)}>Inspect run</button></article>)}{!incidents.length && <Empty label="No failed, timed-out, or canceled runs. Everything is clear." />}</div>}
    {section === 'Audit' && <div className="audit-list">{runs.map((run) => <article key={run.id}><ScrollText size={16} /><div><strong>Run {run.id.slice(0, 8)} is {run.state.replaceAll('_', ' ').toLowerCase()}</strong><p>Recorded {new Date(run.created_at).toLocaleString()} · {run.execution_backend.toLowerCase()} backend</p></div><button className="button secondary" onClick={() => onSelect(run.id)}>Open</button></article>)}{!runs.length && <Empty label="Audit events appear as tests are created and updated." />}</div>}
  </div>
}

function Empty({ label }: { label: string }) { return <div className="section-empty">{label}</div> }
