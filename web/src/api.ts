import type { Capabilities, Interpretation, Run, RunDetail, Sample } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) {
    /* An error body is not guaranteed to be JSON: a proxy or a crash returns text, and
       swallowing that in a parse failure would report the wrong problem. */
    const body = await response.text()
    let detail = body.slice(0, 400)
    try { detail = (JSON.parse(body).detail as string) ?? detail } catch { /* keep the raw text */ }
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export interface TestRequest {
  prompt: string
  source_type: string
  source_url?: string
  source?: unknown
  application_name: string
  backend?: string
  auto_start?: boolean
  run_at?: string
}

export const api = {
  runs: () => request<Run[]>('/api/runs'),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  create: (payload: TestRequest) => request<Run>('/api/tests', { method: 'POST', body: JSON.stringify(payload) }),
  start: (id: string) => request<Run>(`/api/runs/${id}/start`, { method: 'POST' }),
  cancel: (id: string, reason: string) => request<Run>(`/api/runs/${id}/cancel`, { method: 'POST', body: JSON.stringify({ reason }) }),
  /* Reading a requirement never runs anything, so the composer can call it while
     somebody is still typing. `refine` spends one bounded model call on top. */
  preview: (payload: TestRequest, refine = false) => request<Interpretation>(`/api/scenario/preview${refine ? '?refine=true' : ''}`, { method: 'POST', body: JSON.stringify(payload) }),
  samples: (id: string, after = 0) => request<{ samples: Sample[]; next_cursor: number }>(`/api/runs/${id}/samples?after=${after}&limit=10000`),
  capabilities: () => request<Capabilities>('/api/capabilities'),
}
