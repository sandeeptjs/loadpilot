# Execution flow

1. Parse prose into `PerformanceTestIntent`; reject unknown test types, unsafe targets and incomplete SLOs.
2. Convert the selected source through an adapter into `ApplicationModel`.
3. Generate structurally valid candidates with Schemathesis; enrich semantic fields deterministically; bind live IDs/tokens only at runtime.
4. Produce `PerformanceTestPlan` with bounded stages, thresholds and an execution backend.
5. Compile through fixed k6 templates. Secret references become environment-variable lookups.
6. Run `k6 inspect`; validation failure is terminal and audited.
7. Temporal schedules and advances idempotent activities while the database records the state.
8. A backend starts local/container k6 or submits a k6 Operator CRD. Cancellation maps to process termination or CRD abort/deletion.
9. k6 metrics and target telemetry are queried over the run's padded telemetry window.
10. Deterministic comparison/correlation runs before HolmesGPT receives a scoped evidence package.
11. The planner may propose a narrower breakpoint run when experiment budgets permit. It never silently exceeds VU, duration, request or run caps.

