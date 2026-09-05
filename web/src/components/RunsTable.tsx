import type { Run } from '../types'

/* Error rate is the only column with an inherent direction, so it is the only one
   allowed to carry colour. Everything else stays neutral. */
function errorCell(run: Run) {
  const rate = run.metrics['http_req_failed.rate']
  if (rate === undefined) return { tone: '', label: '—' }
  return { tone: rate === 0 ? 'tone-good' : rate <= 0.01 ? 'tone-warn' : 'tone-bad', label: `${(rate * 100).toFixed(2)}%` }
}

export function RunsTable({ runs, selected, onSelect }: { runs: Run[]; selected?: string; onSelect: (id: string) => void }) {
  return <section className="runs-panel"><header><h2>Recent runs</h2><span>{runs.length} recorded</span></header>
    <div className="table-scroll"><table><thead><tr><th>Run</th><th>Status</th><th>Backend</th><th>Created</th><th>p95</th><th>Errors</th></tr></thead>
      <tbody>{runs.map((run) => { const errors = errorCell(run); return <tr key={run.id} className={selected === run.id ? 'selected' : ''} onClick={() => onSelect(run.id)}><td><strong>{run.id.slice(0, 8)}</strong></td><td><span className={`status status-${run.state.toLowerCase()}`}>{run.state.replaceAll('_', ' ')}</span></td><td>{run.execution_backend}</td><td>{new Date(run.created_at).toLocaleString()}</td><td>{run.metrics['http_req_duration.p(95)']?.toFixed(0) ?? '—'}</td><td className={errors.tone}>{errors.label}</td></tr> })}</tbody>
    </table></div>
  </section>
}
