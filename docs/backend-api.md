# Backend API

Interactive OpenAPI documentation is served at `/docs`. `/api/capabilities` reports configured budgets, AI mode, sandbox URL and supported execution scope.

## Create and run autonomously

`POST /api/tests`

```json
{
  "prompt": "Stress checkout from 5 to 40 users for 35 seconds. Keep p95 under 500 ms and errors under 1%.",
  "source_type": "openapi",
  "source_url": "http://127.0.0.1:8080/openapi.json",
  "auto_start": true,
  "auto_followup": false
}
```

Alternatively provide a parsed OpenAPI document in `source` and an explicit `base_url`. Schema URLs are fetched by the backend, removing browser CORS requirements. Target hosts must appear in `LOADPILOT_ALLOWED_HOSTS`. Redirects and embedded URL credentials are rejected.

`auto_start: false` leaves a generated plan for review. `POST /api/runs/{id}/start` submits it and returns HTTP 202 promptly. Validation and execution run in the worker. `GET /api/runs/{id}` includes run, plan, intent, application and investigation; preparation failures still have readable run records.

`intent_overrides` accepts test_type, target_endpoints, target_concurrency, max_concurrency, target_rps, duration_seconds and slos. These fields undergo validation and budgets. Use operation IDs for generic APIs. If no journey is identified, read-only defaults are preferred; unsupported or missing explicit operations are rejected.

For a preexisting bearer credential, pass `credentials_reference: {"provider":"env","key":"TARGET_TOKEN"}`. Store the value in the execution environment, never in the request. Only environment names starting with TARGET_ are accepted. Login dependencies are used by the demo without a preseeded token.

## Schedules and cancellation

Include an ISO timestamp with offset in `run_at`, or use `POST /api/runs/{id}/schedule` with `{"run_at":"2026-09-06T10:00:00+05:30"}`. Relative “start in N seconds/minutes” phrases are supported offline. Ambiguous timezone phrases and recurrence are rejected rather than silently scheduled incorrectly.

`POST /api/runs/{id}/cancel` accepts `{"reason":"Stop the demo workload"}`. The cancellation is persisted, and either the local process handle or the worker's polling path terminates the workload.

## Evidence

| Route | Result |
|---|---|
| `GET /api/runs` | Recent lifecycle records |
| `GET /api/runs/{id}/samples?after=0&limit=1000` | Measured samples with pagination cursor and semantics |
| `GET /api/runs/{id}/script` | Hash-verified generated JavaScript |
| `GET /api/runs/{id}/report` | Stage results, evidence, correlation and investigation |
| `GET /api/audit?run_id={id}` | Stored audit events |
| `POST /api/alerts` | Alertmanager webhook payload ingestion |
| `GET /api/alerts` | Persisted incoming batches |
| `POST /api/baselines` | Save `{"id":"completed-run-uuid","name":"Healthy build"}` |
| `GET /api/baselines` | Named references |
| `GET /api/runs/{id}/compare/{baseline_id}` | Measured deltas and workload comparability |

Zero baselines produce null percentage deltas rather than division errors or false zero-change results. Different workloads are labeled non-comparable for regression conclusions. Runs with substantial transport failure are not valid application-performance comparisons.

## Follow-up and safe sandbox actions

`POST /api/runs/{id}/rerun` clones the validated workload, recompiles with a fresh run ID and queues it.

`POST /api/runs/{id}/follow-up` generates one narrower stress experiment from measured passing/failing holds. `auto_followup: true` invokes this path automatically on completion. Child runs cannot recurse; a second generation is rejected.

`POST /api/runs/{id}/remediate` accepts only `{"action":"IncreaseSandboxPool","pool_size":12}`. Policy must be explicitly enabled, the run must be completed against the configured sandbox, and measured pool contention must support the action. The action acquires a maintenance reservation, records the old value, changes the setting through the authenticated sandbox API, and queues an identical verification run. The maximum size is 32.

`GET /api/remediations` returns records and verification IDs. `POST /api/remediations/{action_id}/rollback` restores the previous pool size only if the sandbox still has the value written by that action. Work must be drained first.

No generic shell, kubectl, arbitrary URL mutation or arbitrary configuration endpoint is exposed to the model.
