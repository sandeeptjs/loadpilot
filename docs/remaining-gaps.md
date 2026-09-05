# Remaining gaps

- A credentialed OpenAI-compatible provider run has not been performed. The JSON contract, refusal/invalid-output handling, and evidence-ID rejection have automated tests. Offline mode is labeled.
- OpenAPI and manual HTTP definitions are the qualified input path. GraphQL, Postman and HAR adapters are incomplete and are not a claim of broad application support. Complex recursive schemas, multipart bodies, OAuth refresh flows and arbitrary business dependencies need more adapters.
- Payload pools are schema-valid synthetic data, not production traffic distributions. Runtime IDs require explicit or supported inferred dependency links.
- One-time schedules and relative delays are implemented. Cron recurrence, timezone interpretation of phrases such as tomorrow midnight, and resumable long-running workflows are not.
- Kubernetes execution and standalone Docker backend execution deliberately reject unsupported runs instead of reporting success from an empty result. The API container embeds local k6; Docker/Compose has not been executed on this host.
- Local k6 and target samples power the demo. Prometheus range queries, OTel traces, HolmesGPT and Robusta are not connected to the main pipeline. Optional Compose observability needs deployment qualification.
- No production OIDC/RBAC, tenant isolation, TLS termination or distributed worker fleet. Bind the demo to loopback. Host allow-listing is a demo control, not complete DNS-rebinding protection.
- A short soak demonstrates sustained-load execution and measured retained memory. It does not prove hour-scale leak detection. The sandbox has bounded synthetic memory retention and an in-memory modeled connection pool.
- Follow-up search permits one child generation and requires a measured passing/failing bracket. It does not find a mathematical maximum or attach statistical confidence intervals.
- Crash recovery does not replay active load; the queue waits through its execution-timeout margin. Local recovery is conservative and does not replace a durable workflow engine.
