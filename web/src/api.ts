import type { Investigation, Plan, Run } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) throw new Error((await response.json()).detail ?? `Request failed (${response.status})`)
  return response.json()
}

export const api = {
  runs: () => request<Run[]>('/api/runs'),
  run: (id: string) => request<{ run: Run; plan: Plan; investigation?: Investigation }>(`/api/runs/${id}`),
  create: (payload: unknown) => request<Run>('/api/tests', { method: 'POST', body: JSON.stringify(payload) }),
  start: (id: string) => request<Run>(`/api/runs/${id}/start`, { method: 'POST' }),
  cancel: (id: string, reason: string) => request<Run>(`/api/runs/${id}/cancel`, { method: 'POST', body: JSON.stringify({ reason }) }),
}
