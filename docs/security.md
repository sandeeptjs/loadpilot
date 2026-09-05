# Security model

Implemented demo boundary: loopback API, configured target-host allow-list, fixed generated code, script hashes, per-run validation, bounded VUs/duration, paced transport failures, environment credential references restricted to TARGET_ names, fail-closed sandbox control tokens, and one allow-listed pool change with audit and rollback. Only env references are implemented. Vault/Kubernetes resolution, OIDC and production network isolation below remain planned requirements. Local execution has workload bounds, not container CPU/memory isolation.

- Credentials are `SecretReference` values (`env`, `vault`, or `kubernetes`) and are resolved only by the execution activity.
- Raw secrets, authorization/cookie headers and sensitive query fields are redacted recursively from logs, prompts, audit events and HAR imports.
- Users cannot submit executable k6 code through the autonomous API. The compiler emits only fixed templates from validated models.
- Targets must pass scheme/host policy. Production deployments should deny localhost, link-local, metadata endpoints and private networks unless explicitly allow-listed.
- Execution uses container/namespace CPU, memory, duration and network limits.
- HolmesGPT receives read-only, time-bounded evidence tools. Bash, generic kubectl execution and arbitrary network tools are disabled.
- Remediation defaults to recommendation. Dispatch requires a named action in the allow-list, typed parameters, risk evaluation, approval when required, rollback metadata and an audit event.
- HAR ingestion strips secrets before persistence and preserves only required request/response fields.
- Multi-user production deployments must enforce OIDC-backed RBAC and tenant filters at API and query boundaries.

