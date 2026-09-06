export type RunState = 'CREATED' | 'DISCOVERING_APPLICATION' | 'GENERATING_DATA' | 'PLANNING' | 'GENERATING_SCRIPT' | 'VALIDATING' | 'SCHEDULED' | 'QUEUED' | 'INITIALIZING' | 'RUNNING' | 'COLLECTING_TELEMETRY' | 'ANALYZING' | 'COMPLETED' | 'FAILED' | 'CANCELED' | 'TIMED_OUT'

export const TERMINAL: RunState[] = ['COMPLETED', 'FAILED', 'CANCELED', 'TIMED_OUT']

export interface Run {
  id: string
  plan_id: string
  state: RunState
  created_at: string
  started_at?: string
  finished_at?: string
  scheduled_at?: string
  execution_backend: string
  metrics: Record<string, number>
  error?: string
  ai_mode?: 'offline' | 'provider'
  slo_passed?: boolean | null
  parent_run_id?: string
}

export interface Stage {
  name: string
  duration_seconds: number
  target_vus?: number | null
  target_rps?: number | null
  offset_seconds?: number
  measurement?: boolean
}

export interface Step {
  operation_id: string
  inputs?: Record<string, unknown>
  headers?: string[] | Record<string, string>
  extract?: Record<string, string>
  has_body?: boolean
  body?: unknown
}

export interface Journey {
  name: string
  weight?: number
  steps: Step[]
}

export interface Plan {
  id: string
  test_type: string
  executor: string
  workload_model?: string
  stages: Stage[]
  thresholds: Array<{ metric: string; expression: string; abort_on_fail?: boolean }>
  journeys: Journey[]
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

export interface SLOs {
  latency_p50_ms?: number | null
  latency_p95_ms?: number | null
  error_rate?: number | null
  throughput_rps?: number | null
}

export interface Intent {
  test_type: string
  target_endpoints: string[]
  target_concurrency?: number | null
  max_concurrency?: number | null
  target_rps?: number | null
  duration_seconds?: number | null
  slos: SLOs
  ambiguities: string[]
  confidence: number
}

/* The reading of a requirement: which words became which operation, and how the
   deterministic pass and the model each contributed. Mirrors SynthesisResult.as_dict
   plus the provider annotations the service records beside it. */
export interface ReadingStep {
  phrase: string
  operation_id: string
  method: string
  path: string
  confidence: number
  reasons: string[]
  origin: string
}

export interface Reading {
  steps: ReadingStep[]
  unrecognized_phrases: string[]
  notes: string[]
  journey_synthesized: boolean
  source?: 'synthesis' | 'provider'
  journey_source?: 'synthesis' | 'provider'
  journey_repairs?: string[]
  journey_error?: string
  provider_error?: string
  generated_inputs?: string[]
}

export interface ProgressPhase { state: RunState; label: string; reached: boolean; active: boolean }

export interface Progress {
  phase: RunState
  phase_label: string
  phase_index: number
  phases: ProgressPhase[]
  terminal: boolean
  planned_seconds: number
  elapsed_seconds: number
  fraction: number
  stages: Stage[]
  stage_index: number | null
  sample_count: number
  live_vus?: number
  live_rps?: number
  live_p95_ms?: number
  live_error_rate?: number
}

export interface RunDetail {
  run: Run
  plan?: Plan | null
  intent?: (Intent & { raw_prompt: string }) | null
  application?: { name: string; base_url?: string | null; endpoints: unknown[] } | null
  investigation?: Investigation | null
  progress: Progress
  scenario?: Reading | null
}

export interface Interpretation {
  prompt: string
  application: { name: string; base_url?: string | null; operation_count: number; dependency_count: number }
  operations: Array<{ operation_id: string; method: string; path: string; summary?: string | null; authenticated: boolean }>
  intent: Intent
  scenario: Reading
  plan: null | {
    test_type: string
    executor: string
    workload_model: string
    stages: Stage[]
    planned_seconds: number
    peak_vus: number
    peak_rps: number
    thresholds: Array<{ metric: string; expression: string; abort_on_fail: boolean }>
    journeys: Journey[]
  }
  planning_error: string | null
  provider: { enabled: boolean; model: string | null }
}

export interface Sample { id?: number; timestamp: string; metrics: Record<string, number> }

export interface Capabilities {
  ai_mode: 'offline' | 'provider'
  ai_model?: string
  max_vus: number
  max_duration_seconds: number
  max_rps: number
  sandbox_openapi_url: string
  remediation_enabled: boolean
  test_types: string[]
  scenario_sources: string[]
  scenario_features: string[]
  limitations: string[]
}
