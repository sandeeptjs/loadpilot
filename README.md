# LoadPilot

Describe an HTTP performance test, provide an OpenAPI document, and LoadPilot builds a schema-valid journey and k6 workload, queues it, records live measurements, and explains the outcome.

## Local demo

```powershell
uv sync --extra dev
.\scripts\install_k6.ps1
cd web
npm ci
npm run build
cd ..
uv run python scripts/start_demo.py
```

Open http://127.0.0.1:8000. Choose **New test**, keep the Stress preset and select **Create and run**. The launcher starts a deliberately constrained checkout sandbox. After the report, select **Increase sandbox pool to 12 and verify** to rerun the same workload. The setting change is allow-listed, token-protected and audited; rollback is exposed by the API.

Use `--api-port` and `--target-port` if ports are occupied. `--healthy` starts without the deliberate bottleneck. Ctrl+C stops the launcher and its services. History remains in `artifacts/demo.db`.

## AI configuration

Copy `.env.example` to `.env` and name a model:

```
LOADPILOT_LLM_MODEL=gemini-3.6-flash
```

That is the whole configuration for Gemini. Google publishes it behind an OpenAI-compatible Chat Completions surface, so naming a `gemini-*` model settles the base URL, and the key is read from the ambient `GEMINI_API_KEY` or `GOOGLE_API_KEY` rather than duplicated into this project. An `openai/*`-shaped deployment works the same way through `OPENAI_API_KEY`. Set `LOADPILOT_LLM_BASE_URL` and `LOADPILOT_LLM_API_KEY` explicitly only for a provider this resolution does not cover. `/api/capabilities` reports the resolved `ai_mode` and `ai_model`, so a misconfiguration is visible before a run.

With a model configured, the same prompt drives the run end to end: the model sharpens the deterministic reading of the requirement and may propose the workflow itself. What it proposes is checked, not trusted. `LOADPILOT_LLM_RETRIES` (default 2, exponential backoff) retries only refusals that say nothing about the request — 429 quota windows, 503 overload, an envelope that will not parse, a reply cut off at `LOADPILOT_LLM_MAX_TOKENS`. A reply the schema rejects is the model's considered answer and is not asked for twice. A workflow that names an operation the API does not have, reads a value from a pointer the contract contradicts, or cannot complete one preflight iteration is repaired where the contract can say what was meant and otherwise replaced by the deterministic journey planned beside it. Every substitution is reported on the run as `journey_source`, `journey_repairs`, `journey_error` or `journey_preflight_error` and recorded in the audit log.

Without a configured model/key the app explicitly uses **offline mode**: deterministic intent parsing and evidence summaries. Do not present offline summaries as AI output. A quota refusal or an outage is not a failure either; the run keeps the deterministic reading and records why. Provider HTTP contracts are tested with a mock; a credentialed provider run still needs validation.

## Verification

```powershell
uv run pytest
uv run ruff check .
uv run python scripts/demo_acceptance.py
cd web
npm run build
npm run lint
```

The acceptance script launches isolated servers, generates real k6 traffic, exercises baseline/stress/short-soak, checks alert grouping, applies and rolls back a bounded pool change, restarts the API around a scheduled job, and cancels a running workload. It writes the database, scripts, logs and measured evidence under `artifacts/demo-acceptance/`.

## What is implemented

- OpenAPI discovery and transitive response-value dependencies; manual HTTP definitions.
- JSON-Schema-validated sample pools with Hypothesis fallback for constrained schemas.
- Baseline, load, stress, soak, spike and breakpoint plans with explicit ramp/hold stages.
- Generated k6 scripts, hash integrity, `k6 inspect`, runtime auth/ID extraction and failure pacing.
- Background execution, persisted one-time schedules, cancellation, timeouts and no automatic replay of interrupted traffic.
- Live k6 samples, target metrics, scoped alert correlation, report JSON, audit records and baseline comparison.
- Optional one-generation bounded follow-up search and allow-listed sandbox pool remediation with an identical verification run.

The demo uses FastAPI, SQLite, React and a local k6 executable. The supplied API container also includes k6. Prometheus/Alertmanager/OTel/Grafana are optional Compose observability services, not required for the demo. Kubernetes and Temporal are not connected execution backends.

See [demo script](docs/demo.md), [API examples](docs/backend-api.md), [architecture](docs/architecture.md), [acceptance evidence](docs/backend-acceptance.md), and [remaining gaps](docs/remaining-gaps.md).

See [general HTTP scenarios](docs/scenarios.md) for model-generated or explicit journeys, preflight validation, budget controls and runnable ticket/search/GraphQL examples.

[Local backend operation and acceptance](docs/local-backend.md) covers saved definitions, conditions, polling, authentication, uploads, recovery, readiness and backups.
