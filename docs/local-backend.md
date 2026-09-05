# Local backend acceptance

The supported deployment for this iteration is one device running the API and an embedded worker, with local k6, SQLite persistence and HTTP targets on configured hosts. AI is intentionally offline at the user's request. This is a concrete support boundary, not a claim of compatibility with every application or protocol.

## Lifecycle

1. Submit an OpenAPI document, manual operations, supported Postman/HAR requests or GraphQL documents with a natural-language load requirement.
2. Generate schema-based data and a workload, or supply explicit journeys with application-specific business inputs.
3. Validate the generated script and execute one bounded preflight iteration of each journey.
4. Schedule or immediately execute the workload, collecting real request metrics and retaining run state.
5. Inspect measured results, assertions, scoped correlation and deterministic analysis.
6. Diagnose failures, correct inputs and create a linked recovery run without rewriting the failed run.

Baseline, stress and soak are supported, along with load, spike and breakpoint plans. A short soak verifies execution but does not establish hour-scale stability. Offline parsing recognizes load quantities, test types and supplied operation IDs; it does not infer undocumented business rules from arbitrary prose.

## Workflow contract

The step format in `scenarios.md` now also accepts:

| Field | Meaning |
|---|---|
| `when: {variable, equals}` | Execute only when an earlier extracted value or dataset value matches |
| `until: {pointer, equals}` | Poll a GET/HEAD response until it matches; `repeat` is the attempt limit |
| `poll_interval_seconds` | Delay between polls, between 0.1 and 30 seconds |
| `retries` | Up to three retries for GET/HEAD transport failures or HTTP 429/502/503/504 |
| `basic_auth: {username, password}` | Basic authentication using `env:TARGET_*` references |
| `files: {field: {filename, content, content_type}}` | Multipart file parts, each with at most 64 KiB of literal content |

Writes are never automatically retried. Poll exhaustion fails the journey. Retry requests remain represented in actual HTTP metrics and stage counters. Multipart operations require explicit file parts; arbitrary local file paths are not exposed to the model or request.

Each journey can contain `datasets`, a mapping from variable name to a list of rows. Rows are selected deterministically by virtual user and iteration. `${__VU}`, `${__ITER}`, `${__RUN_ID}` and `${__TIMESTAMP}` are available for unique synthetic inputs. Query arrays and deep-object parameters follow their declared serialization. Per-operation `base_url` supports HTTP journeys across services; every host is checked during preparation and again before execution. Use step-scoped authorization headers for different services.

OAuth-style client-credentials and login flows can be expressed as ordinary form/JSON token requests followed by extracted access tokens. There is no OAuth browser consent UI or implicit refresh daemon. Cookies set by a target are handled by k6's per-user cookie jar.

## Reusable definitions and recovery

- `POST /api/definitions` accepts `{name, request}` where `request` is a `/api/tests` request. Saving never starts load. An optional `previous_version` links an immutable revision to its predecessor.
- `GET /api/definitions` and `GET /api/definitions/{id}` retrieve saved versions.
- `POST /api/definitions/{id}/run` accepts `{}` for immediate execution, or `run_at`, `auto_start` and `intent_overrides`. The execution is audited against the selected definition ID.
- `GET /api/runs/{id}/diagnostics` returns preflight check names, HTTP failure status and recovery guidance without storing response bodies or credential values in the diagnostic report.
- `POST /api/runs/{id}/recover` accepts `{journeys, auto_start}`. A corrected plan is revalidated and compiled into a new linked run. The old run remains terminal. Fixing an environment credential and sending an empty object retries the original plan.

The definition request itself can contain user-provided inputs. Use environment references rather than literal credentials in definitions, datasets and upload content. The API is local storage, not a secret manager.

## Local operation

`GET /api/readiness` checks SQLite, the configured k6 executable and embedded-worker liveness. The default configuration uses one workload at a time. A separately managed local worker is supported, but readiness cannot certify an externally managed idle process.

Set `LOADPILOT_API_TOKEN` to require bearer authentication on API routes other than health. This is optional for a loopback-only device. The existing dashboard has no token-entry UI; when enabling the token use authenticated API clients. `LOADPILOT_MAX_ARTIFACT_BYTES` defaults to 250,000,000 bytes. The live monitor stops a run when its raw point file exceeds this limit; sampling means the file may briefly exceed the limit before termination.

Run state mutations use SQLite transactions across API/worker processes. Cancellation remains terminal. Recovery waits for a deadline based on worker claim time, all possible preflights and workload timeout before releasing an orphaned job. Missing execution records become failed runs. Live-monitor errors do not discard an available final summary, and missing/reset target counters are excluded from run-specific deltas.

Create a backup using the same database/generated-directory environment configuration as the running API:

```powershell
uv run python scripts/backup_local.py artifacts/backups/checkpoint-01
```

This creates a consistent SQLite snapshot and copies its referenced, hash-verified scripts. It does not copy growing raw-point files. The destination must be new. To restore, stop the API and worker, retain the current files as a separate backup, restore the database and scripts to the original configured locations, then restart. Stored artifact paths are absolute; moving a backup to another device needs path migration. Never replace an open database.

## Qualification and remaining boundaries

Automated acceptance executes real k6 through the public API for basic authentication, conditional steps, bounded polling, transient read retries, datasets, uploads, multi-service operation URLs, saved definitions, diagnostics and corrected recovery. Additional tests cover concurrent state preservation, stale preflight recovery, malformed execution records, monitor failure isolation, API authentication, backup integrity and disk budgets. Existing checkout/search/GraphQL and lifecycle regression tests remain part of the suite.

The full suite passed 40 tests. The final workflow acceptance also passed after adding a form token request and query-array/deep-object checks. A normal CLI run of `examples/scenarios/workflow.json` against the running local API completed with nine measured requests, all checks passing and no journey failures. Readiness returned `ready: true`; a SQLite backup copied six referenced scripts after verifying their hashes.

To exercise that workflow against the independent fixture, set `TARGET_USER=user` and `TARGET_PASSWORD=test-only` in the shell before starting the API. These are fixture credentials, not real service credentials. Start `python -m sandbox_target.scenario_fixture --port 8090`, then use `uv run python scripts/run_scenario.py examples/scenarios/workflow.json`. This verifies interoperability and lifecycle behavior, not a production performance benchmark.

Live provider validation is intentionally excluded while offline mode is selected. Browser interaction, WebSockets, gRPC, distributed execution, automatic semantic business-rule repair and arbitrary Postman scripts are not implemented. Long-duration qualification and compatibility with a particular real application require that application's specification, credentials and valid business data. No single percentage can certify those unknown integrations.
