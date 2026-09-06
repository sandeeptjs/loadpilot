import { useEffect, useRef, useState } from 'react'
import { Plus, RotateCw, Square } from 'lucide-react'
import { api } from './api'
import { count, errorTone, millis, percent } from './format'
import { Band } from './components/Band'
import { Chain } from './components/Chain'
import { Composer } from './components/Composer'
import { Evidence } from './components/Evidence'
import { Gauge } from './components/Gauge'
import { Ladder } from './components/Ladder'
import { Log } from './components/Log'
import { Rail, type View } from './components/Rail'
import { Reading } from './components/Reading'
import { Ribbon } from './components/Ribbon'
import { Sections } from './components/Sections'
import { Trace } from './components/Trace'
import type { Capabilities, Run, RunDetail, Sample } from './types'
import './console.css'

const LIVE = ['INITIALIZING', 'RUNNING', 'COLLECTING_TELEMETRY', 'ANALYZING']

function stateTone(run: Run) {
  if (LIVE.includes(run.state)) return 'live'
  if (run.state === 'COMPLETED') return run.slo_passed === false ? 'bad' : 'good'
  if (['FAILED', 'TIMED_OUT', 'CANCELED'].includes(run.state)) return 'bad'
  return 'wait'
}

export default function App() {
  const [runs, setRuns] = useState<Run[]>([])
  const [id, setId] = useState<string>()
  const [detail, setDetail] = useState<RunDetail>()
  const [samples, setSamples] = useState<Sample[]>([])
  const [capabilities, setCapabilities] = useState<Capabilities>()
  const [view, setView] = useState<View>('brief')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const cursor = useRef(0)
  const opened = useRef(false)

  useEffect(() => { void api.capabilities().then(setCapabilities).catch(() => {}) }, [])

  useEffect(() => {
    let live = true
    const tick = async () => {
      try {
        const data = await api.runs()
        if (!live) return
        setRuns(data)
        setError('')
        /* A workspace with history opens on its latest run; an empty one opens on the
           brief, because there is nothing else to look at yet. */
        if (!opened.current) { opened.current = true; if (data.length) { setId(data[0].id); setView('run') } }
      } catch (reason) { if (live) setError(reason instanceof Error ? reason.message : String(reason)) }
    }
    void tick()
    const timer = window.setInterval(() => void tick(), 2500)
    return () => { live = false; window.clearInterval(timer) }
  }, [])

  const terminal = detail?.progress.terminal ?? true
  useEffect(() => {
    if (!id) { setDetail(undefined); return }
    let live = true
    const tick = async () => {
      try { const data = await api.run(id); if (live) setDetail(data) }
      catch (reason) { if (live) setError(reason instanceof Error ? reason.message : String(reason)) }
    }
    void tick()
    /* A live run is polled at the rate its samples arrive; a finished one only needs a
       slow refresh so a late analysis or a follow-up still appears. */
    const timer = window.setInterval(() => void tick(), terminal ? 6000 : 1200)
    return () => { live = false; window.clearInterval(timer) }
  }, [id, terminal])

  useEffect(() => { setSamples([]); cursor.current = 0 }, [id])
  useEffect(() => {
    if (!id) return
    let live = true
    const tick = async () => {
      try {
        const data = await api.samples(id, cursor.current)
        if (!live || !data.samples.length) return
        cursor.current = data.next_cursor ?? cursor.current
        setSamples((current) => [...current, ...data.samples])
      } catch { /* a dropped sample poll is not worth interrupting the view for */ }
    }
    void tick()
    if (terminal) return () => { live = false }
    const timer = window.setInterval(() => void tick(), 1500)
    return () => { live = false; window.clearInterval(timer) }
  }, [id, terminal])

  function choose(runId: string) { setId(runId); setView('run') }

  async function act(work: () => Promise<unknown>) {
    setBusy(true); setError('')
    try { await work() }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  const run = detail?.run
  const progress = detail?.progress
  const plan = detail?.plan
  const flagged = runs.filter((item) => ['FAILED', 'TIMED_OUT', 'CANCELED'].includes(item.state) || item.slo_passed === false).length

  async function refresh() {
    await act(async () => {
      setRuns(await api.runs())
      if (id) setDetail(await api.run(id))
    })
  }

  const strip = run && progress
    ? <div className="strip">
        <div className="strip-id"><b>{run.id.slice(0, 8)}</b><span className="m">{plan ? plan.test_type.toLowerCase() : 'plan pending'}</span></div>
        <div className="strip-state"><span className={`dot ${stateTone(run)}`} />{progress.phase_label}</div>
        <div className="strip-readouts">
          <div className="readout"><b>{count(progress.live_vus ?? run.metrics['vus.max'])}</b><span>virtual users</span></div>
          <div className="readout"><b>{progress.live_rps === undefined ? '—' : progress.live_rps.toFixed(1)}</b><span>req / s</span></div>
          <div className="readout"><b>{millis(progress.live_p95_ms ?? run.metrics['http_req_duration.p(95)'])}</b><span>p95 ms</span></div>
          <div className={`readout ${errorTone(progress.live_error_rate ?? run.metrics['http_req_failed.rate'])}`}><b>{percent(progress.live_error_rate ?? run.metrics['http_req_failed.rate'])}</b><span>errors</span></div>
        </div>
        <div className="strip-actions">
          {run.state === 'VALIDATING' && <button className="act key" disabled={busy} onClick={() => void act(() => api.start(run.id))}>start</button>}
          {!terminal && <button className="act stop" disabled={busy} onClick={() => void act(() => api.cancel(run.id, 'Stopped from the workspace'))}><Square size={10} fill="currentColor" />stop</button>}
          <button className="act bare" onClick={() => setView('brief')} aria-label="Write a new requirement" title="Write a new requirement"><Plus size={17} /></button>
          <button className="act bare" onClick={() => void refresh()} aria-label="Refresh" title="Refresh"><RotateCw size={15} /></button>
        </div>
      </div>
    : <div className="strip">
        <div className="strip-id"><b>loadpilot</b><span className="m">performance workspace</span></div>
        <div className="strip-readouts">
          <div className="readout"><b>{runs.length}</b><span>runs recorded</span></div>
          <div className="readout"><b>{runs.filter((item) => item.state === 'COMPLETED').length}</b><span>completed</span></div>
          <div className={flagged ? 'readout bad' : 'readout'}><b>{flagged}</b><span>flagged</span></div>
        </div>
        <div className="strip-actions"><button className="act bare" onClick={() => void refresh()} aria-label="Refresh" title="Refresh"><RotateCw size={15} /></button></div>
      </div>

  return <div className="deck">
    <Rail view={view} onNavigate={setView} provider={capabilities?.ai_model || undefined} />
    <main className="stage">
      {strip}
      {error && <div className="notice"><b>workspace</b><span>{error}</span></div>}
      {run?.error && <div className="notice"><b>run</b><span>{run.error}</span></div>}

      {view === 'brief' && <Composer capabilities={capabilities} onCreated={(created) => {
        setRuns((prev) => [created, ...prev.filter((item) => item.id !== created.id)])
        choose(created.id)
      }} />}

      {view !== 'brief' && view !== 'run' && <Sections view={view} runs={runs} selected={id} onSelect={choose} />}

      {view === 'run' && !(run && progress) && <div className="overture">
        <h1>Nothing has been asked of the target yet.</h1>
        <p>Describe a performance requirement the way you would say it out loud. LoadPilot reads the sentence, builds the journey, runs k6 against the target, and reports only what the samples support.</p>
        <div className="overture-steps">
          <span><b>01</b>write</span><span><b>02</b>read</span><span><b>03</b>run</span><span><b>04</b>evidence</span>
        </div>
        <button className="act key" onClick={() => setView('brief')}>write a requirement</button>
      </div>}

      {view === 'run' && run && progress && <>
        <Band index="01" title="Flight" lead="One instrument for the whole run. The ring carries the pipeline while the plan is being built, then becomes the clock once k6 is in the air." note={progress.terminal ? 'settled' : 'in flight'}>
          <div className="instrument">
            <Gauge progress={progress} breached={run.slo_passed === false} />
            <div className="instrument-side">
              <Ladder progress={progress} />
              {plan && plan.thresholds.length > 0 && <div className="limits">
                {plan.thresholds.map((threshold) => <div className="limit" key={`${threshold.metric}-${threshold.expression}`}>
                  <span>{threshold.metric}</span><b>{threshold.expression}</b>
                </div>)}
              </div>}
            </div>
          </div>
        </Band>

        <Band index="02" title="Telemetry" lead="Latency and failure rate exactly as k6 reported them, each on its own scale. Nothing is smoothed and nothing is extrapolated between samples." note={`${count(progress.sample_count)} samples`} tint>
          <Trace samples={samples} live={!progress.terminal} />
        </Band>

        {plan && <Band index="03" title="Profile" lead="The compiled stage ladder handed to k6, with the played portion filled in as the run advances." note={plan.executor.split('-').join(' ')}>
          <Ribbon stages={plan.stages} elapsed={progress.elapsed_seconds} planned={progress.planned_seconds} stageIndex={progress.stage_index ?? undefined} />
        </Band>}

        {plan && plan.journeys.length > 0 && <Band index="04" title="Sequence" lead="Every request the virtual users will make, in order, with the values each step hands to the next." note={`${count(plan.journeys.length)} ${plan.journeys.length === 1 ? 'journey' : 'journeys'}`} tint>
          <Chain journeys={plan.journeys} />
        </Band>}

        {detail?.scenario && detail.intent && <Band index="05" title="Reading" lead="What the sentence was taken to mean, phrase by phrase, and what it did not cover." note={detail.scenario.source === 'provider' ? 'model assisted' : 'deterministic'}>
          <div className="finding">
            <p className="finding-lead">“{detail.intent.raw_prompt}”</p>
            <Reading reading={detail.scenario} intent={detail.intent} plannedSeconds={progress.planned_seconds} />
          </div>
        </Band>}

        <Band index="06" title="Findings" lead="The written conclusion, the figures behind it, and the next action worth taking — each with the artifact it came from." note={run.slo_passed === false ? 'objective missed' : run.slo_passed ? 'objective met' : 'not yet judged'} tint>
          <Evidence run={run} plan={plan} investigation={detail?.investigation} capabilities={capabilities} onSelect={choose} />
        </Band>

        {runs.length > 1 && <Band index="07" title="Log" lead="Every run this workspace has recorded, with p95 drawn against the worst one so the comparison is real." note={`${count(runs.length)} runs`}>
          <Log runs={runs} selected={id} onSelect={choose} />
        </Band>}
      </>}
    </main>
  </div>
}
