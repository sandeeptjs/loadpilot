import { useState } from 'react'
import { X } from 'lucide-react'
import { api } from '../api'
import type { Run } from '../types'

export function NewTestDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (run: Run) => void }) {
  const [prompt, setPrompt] = useState('Stress test the checkout flow with 10 concurrent users for 20 seconds. Keep p95 under 500 ms and errors under 1%.')
  const [schemaUrl, setSchemaUrl] = useState('http://localhost:8080/openapi.json')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const schema = await fetch(schemaUrl).then((response) => { if (!response.ok) throw new Error('Could not load OpenAPI schema'); return response.json() })
      const run = await api.create({ prompt, source_type: 'openapi', source: schema, application_name: schema.info?.title ?? 'Target application', base_url: schema.servers?.[0]?.url?.replace('sandbox-target', 'localhost'), backend: 'LOCAL', validate: false })
      onCreated(run)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><form className="dialog" onSubmit={submit} onMouseDown={(e) => e.stopPropagation()}>
    <header><div><h2>Define a performance test</h2><p>Intent becomes a typed, editable plan before execution.</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X /></button></header>
    <label>Requirement<textarea rows={6} value={prompt} onChange={(e) => setPrompt(e.target.value)} /></label>
    <label>OpenAPI URL<input value={schemaUrl} onChange={(e) => setSchemaUrl(e.target.value)} /></label>
    {error && <p className="form-error">{error}</p>}
    <footer><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}>{busy ? 'Compiling…' : 'Generate plan'}</button></footer>
  </form></div>
}
