import { useCallback, useEffect, useState } from 'react'
import { Plus, RefreshCw, Square } from 'lucide-react'
import { api } from './api'
import { EvidenceRail } from './components/EvidenceRail'
import { Lifecycle } from './components/Lifecycle'
import { MetricStrip } from './components/MetricStrip'
import { NewTestDialog } from './components/NewTestDialog'
import { RunTimeline } from './components/RunTimeline'
import { RunsTable } from './components/RunsTable'
import { Sidebar } from './components/Sidebar'
import { WorkspaceSection } from './components/WorkspaceSection'
import type { Investigation, Plan, Run } from './types'
import './styles.css'

export default function App() {
  const [runs, setRuns] = useState<Run[]>([])
  const [selected, setSelected] = useState<Run>()
  const [plan, setPlan] = useState<Plan>()
  const [investigation, setInvestigation] = useState<Investigation>()
  const [active, setActive] = useState('Dashboard')
  const [dialog, setDialog] = useState(false)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await api.runs(); setRuns(data)
      const target = selected?.id ?? data[0]?.id
      if (target) { const detail = await api.run(target); setSelected(detail.run); setPlan(detail.plan); setInvestigation(detail.investigation) }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
  }, [selected?.id])
  useEffect(() => { void load() }, [load])

  async function choose(id: string) { const detail = await api.run(id); setSelected(detail.run); setPlan(detail.plan); setInvestigation(detail.investigation); setActive('Dashboard') }
  function navigate(item: string) { if (item === 'New test') setDialog(true); else setActive(item) }
  async function cancel() { if (selected) { await api.cancel(selected.id, 'Stopped from live run view'); await load() } }
  async function start() {
    if (!selected) return
    setStarting(true); setError('')
    setSelected((current) => current ? { ...current, state: 'RUNNING', started_at: new Date().toISOString() } : current)
    try { await api.start(selected.id); await load() }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setStarting(false) }
  }

  return <div className="app-shell">
    <Sidebar active={active} onNavigate={navigate} />
    <main>
      <header className="topbar"><div><span>Workspace</span><strong>{active}</strong></div><div className="top-actions"><button className="icon-button" onClick={() => void load()} aria-label="Refresh"><RefreshCw size={17} /></button><button className="button primary" onClick={() => setDialog(true)}><Plus size={17} />New test</button></div></header>
      {error && <div className="global-error">API unavailable: {error}</div>}
      {active !== 'Dashboard' && active !== 'New test' ? <WorkspaceSection section={active as 'Runs' | 'Experiments' | 'Baselines' | 'Incidents' | 'Audit'} runs={runs} selected={selected?.id} onSelect={(id) => void choose(id)} /> : selected && plan ? <div className="workspace-content">
        <div className="run-heading"><div><span className="crumb">Runs / {selected.id.slice(0, 8)}</span><h1>{plan.test_type.toLowerCase()} performance run</h1><p>Validated plan · {selected.execution_backend.toLowerCase()} backend · created {new Date(selected.created_at).toLocaleTimeString()}</p></div>
          <div className="run-actions">
            {selected.state === 'VALIDATING' && <button className="button primary" onClick={() => void start()} disabled={starting}>{starting ? 'Running…' : 'Start test'}</button>}
            {!['COMPLETED', 'FAILED', 'CANCELED', 'TIMED_OUT'].includes(selected.state) && <button className="button danger" onClick={() => void cancel()}><Square size={14} fill="currentColor" />Stop test</button>}
          </div>
        </div>
        <Lifecycle state={selected.state} />
        <MetricStrip run={selected} />
        <div className="primary-grid"><RunTimeline run={selected} plan={plan} /><EvidenceRail run={selected} plan={plan} investigation={investigation} /></div>
        <RunsTable runs={runs} selected={selected.id} onSelect={(id) => void choose(id)} />
      </div> : <div className="empty-workspace"><div className="pulse-mark"><span /></div><h1>Bring a real workload into focus</h1><p>Describe the performance requirement and provide an application schema. LoadPilot will compile a reviewable plan before any traffic is sent.</p><button className="button primary" onClick={() => setDialog(true)}><Plus size={18} />Create first test</button><div className="empty-steps"><span>01 Intent</span><span>02 Discover</span><span>03 Plan</span><span>04 Execute</span><span>05 Analyze</span></div></div>}
    </main>
    {dialog && <NewTestDialog onClose={() => setDialog(false)} onCreated={(run) => { setDialog(false); setRuns((current) => [run, ...current]); void choose(run.id) }} />}
  </div>
}
