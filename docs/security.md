# Security model

- Credentials are `SecretReference` values (`env`, `vault`, or `kubernetes`) and are resolved only by the execution activity.
- Raw secrets, authorization/cookie headers and sensitive query fields are redacted recursively from logs, prompts, audit events and HAR imports.
- Users cannot submit executable k6 code through the autonomous API. The compiler emits only fixed templates from validated models.
- Targets must pass scheme/host policy. Production deployments should deny localhost, link-local, metadata endpoints and private networks unless explicitly allow-listed.
- Execution uses container/namespace CPU, memory, duration and network limits.
- HolmesGPT receives read-only, time-bounded evidence tools. Bash, generic kubectl execution and arbitrary network tools are disabled.
- Remediation defaults to recommendation. Dispatch requires a named action in the allow-list, typed parameters, risk evaluation, approval when required, rollback metadata and an audit event.
- HAR ingestion strips secrets before persistence and preserves only required request/response fields.
- Multi-user production deployments must enforce OIDC-backed RBAC and tenant filters at API and query boundaries.

