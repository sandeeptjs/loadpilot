import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { seconds } from '../format'
import type { Capabilities, Interpretation, Run } from '../types'
import { Band } from './Band'
import { Chain } from './Chain'
import { Reading } from './Reading'
import { Ribbon } from './Ribbon'

/* Write the requirement in prose and watch it become a plan. Reading a requirement runs
   nothing and costs nothing, so it happens while somebody is still typing: the resolved
   operations, the load profile and the thresholds are all on screen before a run exists.
   Refining spends one bounded model call, which is a deliberate press rather than a
   keystroke side effect. */
const PRESETS: Array<[string, string]> = [
  ['baseline', 'Baseline checkout with 5 users for 20 seconds. Keep p95 under 300 ms and errors under 1%.'],
  ['load', 'Log in, create a cart, then check out with 20 users for 45 seconds. Keep p95 under 400 ms and errors under 1%.'],
  ['stress', 'Stress checkout from 5 to 60 users for 90 seconds. Keep p95 under 800 ms and errors under 2%.'],
  ['soak', 'Soak checkout with 8 users for 10 minutes. Keep p95 under 500 ms and errors under 0.5%.'],
  ['spike', 'Spike checkout from 3 to 45 users for 40 seconds. Keep errors under 2%.'],
  ['breakpoint', 'Find the breakpoint for checkout by ramping from 5 to 90 users for 3 minutes. Keep p95 under 1200 ms.'],
]

export function Composer({ capabilities, onCreated }: { capabilities?: Capabilities; onCreated: (run: Run) => void }) {
  const [prompt, setPrompt] = useState(PRESETS[1][1])
  const [preset, setPreset] = useState<string>(PRESETS[1][0])
  const [schemaUrl, setSchemaUrl] = useState('')
  const [appName, setAppName] = useState('Checkout target')
  const [delay, setDelay] = useState(0)
  const [autoStart, setAutoStart] = useState(true)
  const [preview, setPreview] = useState<Interpretation>()
  const [reading, setReading] = useState(false)
  const [refining, setRefining] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)
  const ticket = useRef(0)

  useEffect(() => { if (capabilities?.sandbox_openapi_url && !schemaUrl) setSchemaUrl(capabilities.sandbox_openapi_url) }, [capabilities, schemaUrl])
  /* The requirement is set in display type, so the field has to grow with the prose
     instead of scrolling a three-line window. */
  useEffect(() => { const el = box.current; if (el) { el.style.height = 'auto'; el.style.height = `${el.scrollHeight}px` } }, [prompt])

  const payload = useMemo(() => ({ prompt, source_type: 'openapi', source_url: schemaUrl, application_name: appName }), [prompt, schemaUrl, appName])
  const short = prompt.trim().length < 12

  useEffect(() => {
    if (!schemaUrl || short) return
    const mine = ++ticket.current
    const timer = window.setTimeout(() => {
      setReading(true)
      api.preview(payload)
        .then((result) => { if (mine === ticket.current) { setPreview(result); setError('') } })
        .catch((reason) => { if (mine === ticket.current) setError(reason instanceof Error ? reason.message : String(reason)) })
        .finally(() => { if (mine === ticket.current) setReading(false) })
    }, 700)
    return () => window.clearTimeout(timer)
  }, [payload, schemaUrl, short])

  async function refine() {
    const mine = ++ticket.current
    setRefining(true); setError('')
    try {
      const result = await api.preview(payload, true)
      if (mine === ticket.current) setPreview(result)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { if (mine === ticket.current) setRefining(false) }
  }

  async function launch() {
    setBusy(true); setError('')
    try {
      onCreated(await api.create({ ...payload, backend: 'LOCAL', auto_start: autoStart, ...(delay > 0 ? { run_at: new Date(Date.now() + delay * 1000).toISOString() } : {}) }))
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  const plan = preview?.plan ?? null
  const provider = preview?.provider ?? { enabled: capabilities?.ai_mode === 'provider', model: null }

  return <>
    <Band index="01" title="The requirement" lead="Describe the workload the way you would to a colleague. Every operation, payload, threshold and stage below is derived from these words." note={reading ? 'reading…' : preview ? `${preview.application.operation_count} operations discovered` : 'awaiting a schema'}>
      <div className="brief">
        <div className="brief-write">
          <textarea ref={box} rows={2} value={prompt} spellCheck={false} aria-label="Performance requirement in plain language" placeholder="Log in, add two items to a cart, then check out with 25 users for a minute. Keep p95 under 400 ms." onChange={(event) => { setPrompt(event.target.value); setPreset('') }} />
          <div className="brief-meta">
            <span className="m">{prompt.trim().split(/\s+/).filter(Boolean).length} words</span>
            <span className="m">{provider.enabled ? `model ${provider.model ?? 'configured'}` : 'deterministic reading'}</span>
            {preview?.planning_error && <span className="m">plan blocked</span>}
          </div>
          <div className="brief-presets" role="group" aria-label="Requirement starting points">
            {PRESETS.map(([label, text]) => <button type="button" key={label} className={preset === label ? 'chip on' : 'chip'} aria-pressed={preset === label} onClick={() => { setPreset(label); setPrompt(text) }}>{label}</button>)}
          </div>
          <div className="brief-launch">
            <button className="act key" disabled={busy || short || !schemaUrl} onClick={() => void launch()}>{busy ? 'compiling…' : delay > 0 ? 'schedule the run' : autoStart ? 'compile and run' : 'compile the plan'}</button>
            {provider.enabled && <button className="act" disabled={refining || short} onClick={() => void refine()}>{refining ? 'refining…' : 'refine with the model'}</button>}
          </div>
        </div>
        <div className="brief-settings">
          <label className="field"><span>application schema</span><input value={schemaUrl} spellCheck={false} onChange={(event) => setSchemaUrl(event.target.value)} /></label>
          <label className="field"><span>application name</span><input value={appName} onChange={(event) => setAppName(event.target.value)} /></label>
          <label className="field"><span>start delay, seconds</span><input type="number" min={0} max={86400} value={delay} onChange={(event) => setDelay(Math.max(0, Number(event.target.value) || 0))} /></label>
          <label className="switch"><span>run after validation</span><input type="checkbox" checked={autoStart} onChange={(event) => setAutoStart(event.target.checked)} /></label>
          {capabilities && <span className="m">ceiling {capabilities.max_vus} vu · {capabilities.max_rps} rps · {seconds(capabilities.max_duration_seconds)}</span>}
        </div>
      </div>
    </Band>

    {error && <div className="notice"><b>not read</b><span>{error}</span></div>}

    {preview && <Band index="02" tint title="The reading" lead="Which words became which operation, and how sure the resolution is. Correct the sentence, not a form." note={`${preview.scenario.steps.length} phrases resolved`}>
      <Reading reading={preview.scenario} intent={preview.intent} plannedSeconds={plan?.planned_seconds} peak={plan ? (plan.peak_rps ? `${plan.peak_rps} rps` : `${plan.peak_vus} vu`) : undefined} />
    </Band>}

    {preview?.planning_error && <div className="notice"><b>no plan</b><span>{preview.planning_error}</span></div>}

    {plan && <Band index="03" title="The profile" lead="The stages k6 will execute, in the order and shape it will execute them." note={`${plan.executor} · ${plan.workload_model}`}>
      <Ribbon stages={plan.stages} />
      {plan.thresholds.length > 0 && <div className="limits">
        {plan.thresholds.map((threshold) => <div className="limit" key={threshold.metric + threshold.expression}><span>{threshold.metric}{threshold.abort_on_fail ? ' · aborts the run' : ''}</span><b>{threshold.expression}</b></div>)}
      </div>}
    </Band>}

    {plan && plan.journeys.length > 0 && <Band index="04" tint title="The sequence" lead="Each request in order, with the values carried from one response into the next. This wiring is what makes it a workload rather than a loop." note={`${plan.journeys.length} journey${plan.journeys.length === 1 ? '' : 's'}`}>
      <Chain journeys={plan.journeys} />
    </Band>}
  </>
}
