import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '../api'
import type { Run } from '../types'

export function NewTestDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (run: Run) => void }) {
  const [prompt, setPrompt] = useState('Stress checkout from 5 to 40 users for 35 seconds. Keep p95 under 500 ms and errors under 1%.')
  const [schemaUrl, setSchemaUrl] = useState('http://localhost:8080/openapi.json')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [autoStart, setAutoStart] = useState(true)
  const [delay, setDelay] = useState(0)
  const [preset, setPreset] = useState('Stress')
  useEffect(() => { void fetch('/api/capabilities').then(r => r.json()).then(data => setSchemaUrl(data.sandbox_openapi_url)).catch(() => {}) }, [])
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const run = await api.create({ prompt, source_type: 'openapi', source_url: schemaUrl, application_name: 'Performance target', backend: 'LOCAL', auto_start: autoStart, ...(delay > 0 ? { run_at: new Date(Date.now() + delay * 1000).toISOString() } : {}) })
      onCreated(run)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><form className="dialog" onSubmit={submit} onMouseDown={(e) => e.stopPropagation()}>
    <header><div><h2>Define a performance test</h2><p>Generate the journey, payloads, workload, and validated k6 script.</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X /></button></header>
    <div className="preset-row" role="group" aria-label="Requirement presets">{['Baseline', 'Stress', 'Soak'].map(kind => <button type="button" className={preset === kind ? 'button secondary is-on' : 'button secondary'} aria-pressed={preset === kind} key={kind} onClick={() => { setPreset(kind); setPrompt(`${kind} checkout ${kind === 'Stress' ? 'from 5 to 40 users for 35 seconds' : kind === 'Soak' ? 'with 3 users for 60 seconds' : 'with 2 users for 10 seconds'}. Keep p95 under 500 ms and errors under 1%.`) }}>{kind}</button>)}</div>
    <label>Requirement<textarea rows={6} value={prompt} onChange={(e) => { setPrompt(e.target.value); setPreset('') }} /></label>
    <label>OpenAPI URL<input value={schemaUrl} onChange={(e) => setSchemaUrl(e.target.value)} /></label>
    <label>Start delay in seconds, zero for now<input type="number" min="0" max="86400" value={delay} onChange={e => setDelay(Number(e.target.value))} /></label>
    <label className="checkbox-row"><input type="checkbox" checked={autoStart} onChange={e => setAutoStart(e.target.checked)} />Run automatically after validation</label>
    {error && <p className="form-error">{error}</p>}
    <footer><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}>{busy ? 'Compiling…' : delay > 0 ? 'Create scheduled test' : autoStart ? 'Create and run' : 'Generate plan'}</button></footer>
  </form></div>
}
