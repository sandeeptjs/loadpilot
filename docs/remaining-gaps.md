# Remaining gaps

- The first vertical slice uses deterministic intent parsing; a provider adapter for structured LLM parsing is defined but production provider wiring is intentionally not hard-coded.
- Full Schemathesis runtime generation is optional until its pinned package is installed; the OpenAPI adapter has a deterministic JSON-Schema fallback.
- Browser capture is an external k6 Studio workflow; automated process control and source-offer packaging remain release work.
- Temporal/Prometheus/Holmes integrations have local adapters and Compose contracts; full credentialed production qualification requires a deployment environment.
- Docker was not available on the Windows development host. A real local k6 v2.1.0 acceptance run was completed; the full Compose topology and Kubernetes manifests still require qualification on Docker/Kubernetes-capable hosts.
- Kubernetes multi-location scheduling, OIDC tenant isolation, SBOM automation and approved Robusta dispatch are later hardening phases.
- A two-hour soak acceptance run is intentionally not executed during ordinary unit tests; CI has a short canary, while release qualification runs the full duration against the instrumented sandbox.
