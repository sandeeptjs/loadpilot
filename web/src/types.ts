export type RunState = 'CREATED' | 'DISCOVERING_APPLICATION' | 'GENERATING_DATA' | 'PLANNING' | 'GENERATING_SCRIPT' | 'VALIDATING' | 'SCHEDULED' | 'QUEUED' | 'INITIALIZING' | 'RUNNING' | 'COLLECTING_TELEMETRY' | 'ANALYZING' | 'COMPLETED' | 'FAILED' | 'CANCELED' | 'TIMED_OUT'

export interface Run {
  id: string
  plan_id: string
  state: RunState
  created_at: string
  started_at?: string
  finished_at?: string
  execution_backend: string
  metrics: Record<string, number>
  error?: string
  ai_mode?: 'offline' | 'provider'
  slo_passed?: boolean | null
  parent_run_id?: string
}

export interface Plan {
  id: string
  test_type: string
  executor: string
  stages: Array<{ name: string; duration_seconds: number; target_vus?: number }>
  thresholds: Array<{ metric: string; expression: string }>
  journeys: Array<{ name: string; steps: Array<{ operation_id: string }> }>
}

export interface Investigation {
  summary: string
  observed_degradation_point?: string
  evidence: string[]
  likely_root_cause?: string
  confidence: number
  recommended_next_experiment?: string
  ai_summary?: string
  limitations?: string[]
}
