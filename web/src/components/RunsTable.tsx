import type { Run } from '../types'

export function RunsTable({ runs, selected, onSelect }: { runs: Run[]; selected?: string; onSelect: (id: string) => void }) {
  return <section className="runs-panel"><header><h2>Recent runs</h2><span>{runs.length} recorded</span></header>
    <div className="table-scroll"><table><thead><tr><th>Run</th><th>Status</th><th>Backend</th><th>Created</th><th>p95</th><th>Errors</th></tr></thead>
      <tbody>{runs.map((run) => <tr key={run.id} className={selected === run.id ? 'selected' : ''} onClick={() => onSelect(run.id)}><td><strong>{run.id.slice(0, 8)}</strong></td><td><span className={`status status-${run.state.toLowerCase()}`}>{run.state.replaceAll('_', ' ')}</span></td><td>{run.execution_backend}</td><td>{new Date(run.created_at).toLocaleString()}</td><td>{run.metrics['http_req_duration.p(95)']?.toFixed(0) ?? '—'}</td><td>{run.metrics['http_req_failed.rate'] === undefined ? '—' : `${(run.metrics['http_req_failed.rate'] * 100).toFixed(2)}%`}</td></tr>)}</tbody>
    </table></div>
  </section>
}

