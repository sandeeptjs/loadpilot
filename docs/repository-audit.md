# Repository forensic audit

Snapshots were inspected on 2026-09-05 using shallow clones. The upstream directories under `.research/upstream` are evidence only and are excluded from the product source tree.

## Summary classification

| Repository | Classification | License | Stack / deployment | Decision |
|---|---|---|---|---|
| Grafana k6 Performance MCP Server | REFERENCE ONLY | MIT | TypeScript MCP stdio server, k6 child process, Docker examples | Reuse prompt ideas and simple templates conceptually; its single-file server has no durable model, scheduler, secure sandbox, or serious analysis engine. |
| Schemathesis | LIBRARY | MIT | Python package/CLI; Hypothesis, OpenAPI and GraphQL engines | Primary schema parser, constrained value generator, examples, auth inference, and stateful dependency discovery. Wrap behind adapter interfaces. |
| k6 Studio | SERVICE | AGPL-3.0 | Electron/React app with proxy, Chromium/CDP recorder, HAR conversion and script generator | Run separately and accept only sanitized HAR/recording exports. Do not copy or link its source into distributed LoadPilot builds. |
| k6 | EXECUTABLE DEPENDENCY | AGPL-3.0 in inspected snapshot | Go CLI/container; HTTP, WebSocket, gRPC, browser, executors, outputs | Primary execution engine through CLI/container. No fork. Generated scripts are project artifacts, not copied engine code. |
| k6 Operator | SERVICE | Apache-2.0 | Go Kubernetes controller, CRDs, Jobs and Helm | Optional distributed backend using official `TestRun` CRD, status, abort, parallelism and cleanup semantics. |
| Orderly Ape | REFERENCE ONLY | MIT | Django admin/API plus a custom Python Kubernetes operator; Influx/Grafana | Useful lifecycle and multi-location reference, but Kubernetes-only, young, admin-oriented, duplicates official operator/Temporal, and lacks autonomous planning/RCA. |
| Temporal Server | SERVICE | MIT | Go services backed by PostgreSQL/MySQL/Cassandra; Docker/Kubernetes | Durable timers, schedules, retries, signals, cancellation, queries and long soak-test recovery. |
| Temporal Python SDK | LIBRARY | MIT | Python package with native bridge | Workflow/activity implementation used by LoadPilot workers. |
| OTel Collector Contrib | SERVICE | Apache-2.0 | Go collector distribution; receivers/processors/exporters | OTLP, Prometheus, host/Kubernetes metrics, logs/traces, span metrics and service graph pipeline. |
| Prometheus | SERVICE | Apache-2.0 | Go server with local TSDB and PromQL HTTP API | Canonical metrics query layer. Unmodified container. |
| Alertmanager | SERVICE | Apache-2.0 | Go service | Deterministic grouping, deduplication, inhibition, silencing and routing. |
| HolmesGPT | SERVICE | Apache-2.0 | Python CLI/API/operator with provider abstraction and toolsets | Evidence-backed investigation via Prometheus, Kubernetes, Grafana/Loki/Tempo, logs and traces. Isolate service and disable broad shell tools. |
| Robusta | OPTIONAL | MIT | Python Kubernetes runner/Helm; playbook actions, triggers, sinks | Optional enrichment and constrained remediation. Never expose its generic external/manual action surface directly to an LLM. |

## Technical findings

### Grafana k6 Performance MCP Server

- **Architecture:** one `src/index.ts` MCP server exposing create, run, list, result and simple load-test generation tools; k6 is spawned directly and output is stored in files.
- **Useful:** protocol/test-type prompt language, starter scripts, threshold/scenario examples, MCP resource naming.
- **Discard:** file-based lifecycle, arbitrary script acceptance, direct unsandboxed child execution, text-only result analyzer, duplicated Influx/Prometheus examples.
- **Quality/maturity/activity:** small and readable but shallow, very young, limited tests and operational controls; active August 2026.
- **Security:** caller-supplied scripts plus direct k6 execution is too permissive; no secret-reference model or durable audit.
- **Integration difficulty:** low as reference, high risk as a base. No runtime dependency.

### Schemathesis

- **Architecture:** mature Python package with protocol-specific schemas, Hypothesis strategies, generation drivers, positive/negative modes, auth inference, hooks, examples, coverage and state-machine engines.
- **Useful:** loaders, JSON Schema strategies, OpenAPI links/runtime expressions, inferred resource dependencies, GraphQL stateful transitions, hooks and reusable `Case` generation APIs.
- **Overlap:** owns schema correctness and test-data structure; LoadPilot owns workload semantics and k6 compilation.
- **Storage/auth/deployment:** no mandatory database; passed credentials/hooks; library or CLI/container.
- **Quality/maturity/activity:** high, extensive tests and documentation, active September 2026.
- **Security:** schemas and target responses are untrusted; disable arbitrary hooks from tenants and bound generation.
- **Integration difficulty:** medium due to evolving internal APIs; pin releases and keep a narrow façade.

### k6 Studio

- **Architecture:** Electron Forge/Vite/React desktop app; local proxy/recorder, CDP browser recorder, typed recording schemas, correlation rules, generator state, validation and bundled k6 runner.
- **Useful:** as-is desktop capture, HAR import/export, request inspection, dynamic value correlation and browser-action capture.
- **Discard:** its UI, cloud authentication and internal state as platform dependencies.
- **Quality/maturity/activity:** substantial tests and active development, version 2.1; desktop coupling makes library extraction expensive.
- **Security/license:** captured auth/cookies require sanitization; AGPL requires a process boundary and source-offer compliance when distributed.
- **Integration difficulty:** low through files/process, high through source modules.

### k6

- **Architecture:** mature Go executable with JS runtime, scenario executors, protocol modules, checks/thresholds, custom metrics, output extensions, secrets sources and browser support.
- **Useful:** all load generation and validation (`k6 inspect`), local/container execution, Prometheus remote write output.
- **Discard:** none; do not embed server/control-plane responsibilities or modify the engine.
- **Quality/maturity/activity:** very high and active September 2026.
- **Security/license:** test scripts are executable code and need generated-only policy, resource limits and isolation. Current inspected tree is AGPL-3.0, so ship/operate it as a separate executable/container and publish corresponding source obligations when distributing it.
- **Integration difficulty:** low through CLI/container.

### k6 Operator

- **Architecture:** Kubernetes controller with `TestRun` CRD, initializer/starter/runner Jobs, script provisioning, parallelism, arguments, environment, service account, private load-zone and status support.
- **Useful:** distributed execution, cancellation/abort, placement and cleanup.
- **Overlap:** replaces Orderly Ape's custom worker/operator.
- **Quality/maturity/activity:** mature official project, active September 2026.
- **Security:** apply least-privilege service accounts, namespaces, quotas and network policy; secret values only through Kubernetes Secret references.
- **Integration difficulty:** medium; optional because cluster access is not required locally.

### Orderly Ape

- **Architecture:** Django admin and REST API with models for tests, labels/env vars, outputs, locations and per-location finite-state transitions; independent custom operator polls the API and starts Kubernetes jobs.
- **Useful:** multi-location vocabulary, status transition tests, start/cancel UX and deployment lessons.
- **Discard:** custom operator, Influx-first metrics path, Django admin UI and its run state as a source of truth.
- **Quality/maturity/activity:** coherent but small/early (0.1.x), last inspected commit June 2025.
- **Auth/storage/deployment:** Django auth, PostgreSQL, Kubernetes/Helm and worker credentials.
- **Security:** environment values are part of the run model; not adequate as the platform secret design.
- **Integration difficulty:** high if extracted, and redundant; reference only.

### Temporal / Python SDK

- **Architecture:** durable event-history server plus deterministic SDK workflows and retryable activities; schedules, signals, queries, cancellation and worker task queues.
- **Useful:** end-to-end lifecycle, persisted schedules, soak runs, cancellation, retries, recovery and experiment loops.
- **Overlap:** replaces Celery/Redis and Orderly Ape scheduling/queueing.
- **Quality/maturity/activity:** very high, broad test suite, active September 2026.
- **Storage/auth/deployment:** production database, mTLS/API controls supported; local dev server/Compose available.
- **Security:** workflow inputs are persisted in history, so only secret references may enter workflows.
- **Integration difficulty:** medium and justified by long-running durable workflows.

### OpenTelemetry Collector Contrib

- **Architecture:** componentized Go collector distribution with receivers, processors, connectors and exporters.
- **Useful:** OTLP, Prometheus scrape, hostmetrics, kubelet/cluster receivers, file logs, resource attributes, batching, spanmetrics/servicegraph and Prometheus exporters.
- **Overlap:** owns transport/enrichment, not storage or analysis.
- **Quality/maturity/activity:** high and very active; huge surface requires an allow-listed distribution/config.
- **Security:** receivers must not be public by default; scrub attributes and enforce memory/batch limits.
- **Integration difficulty:** low through configuration.

### Prometheus

- **Architecture:** scrape manager, rule engine, PromQL, TSDB and HTTP API.
- **Useful:** unified k6/app/infrastructure time-series query and alert rules.
- **Discard:** no code changes or custom storage.
- **Quality/maturity/activity:** very high and active.
- **Security:** local defaults lack tenancy/auth; place behind platform/network boundaries and cap expensive queries.
- **Integration difficulty:** low.

### Alertmanager

- **Architecture:** alert ingestion, grouping dispatcher, notification log, silences, inhibition and routing tree.
- **Useful:** deterministic noise reduction before incident correlation.
- **Overlap:** it deduplicates/routes alerts; LoadPilot correlates test-phase evidence; Robusta enriches Kubernetes events.
- **Quality/maturity/activity:** high and active.
- **Security:** administrative silence/config endpoints need protection.
- **Integration difficulty:** low through webhook/API.

### HolmesGPT

- **Architecture:** provider-independent investigation loop with configurable toolsets for Prometheus, Kubernetes/logs, Grafana/Loki/Tempo, databases and MCP plus CLI/API/operator forms.
- **Useful:** evidence collection and hypothesis generation across metrics, traces, logs and cluster state; structured investigation adapter.
- **Discard/disable:** bash, unrestricted kubectl-run and internet tools in the LoadPilot profile.
- **Quality/maturity/activity:** broad tests/evaluations and very active September 2026.
- **Security:** tool configuration is the trust boundary; prompts and telemetry must be scoped/redacted.
- **Integration difficulty:** medium as a service.

### Robusta

- **Architecture:** Kubernetes event triggers, configurable playbooks, registered typed actions, enrichments, sinks, schedules and Holmes integration.
- **Useful:** Kubernetes alert enrichment and selected typed actions.
- **Discard/disable:** generic manual/external action dispatch and any bash-style action.
- **Quality/maturity/activity:** mature codebase and active security maintenance.
- **Security:** broad action registry is powerful; LoadPilot requires a second allow-list, approval, rollback metadata and audit before dispatch.
- **Integration difficulty:** medium/high; optional profile only.

