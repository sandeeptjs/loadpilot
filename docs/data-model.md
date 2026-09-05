# Canonical data model

The executable schema lives in `loadpilot/models.py`. Key aggregates are:

- `PerformanceTestIntent`: raw prompt, normalized test type, target, traffic, SLOs, scheduling, constraints, explicit inferences/ambiguities and confidence.
- `ApplicationModel`: source provenance, endpoints, schemas, auth requirements, examples and inferred operation dependencies.
- `GeneratedDataset`: provenance and rows with no stored secrets.
- `PerformanceTestPlan`: scenarios, workload model, stages, thresholds, journeys, abort conditions, telemetry requirements and backend.
- `TestRun`: the only canonical run state, timestamps, backend/workers, artifacts, telemetry window, error and cancellation reason.
- `Experiment`: safety budget plus a sequence of run IDs and the current breakpoint interval.
- `CorrelatedIncident`: time-overlapping signals grouped by service/resource/dependency topology.
- `Investigation`: evidence, hypotheses, confidence, next experiment and safe remediation proposals.
- `RemediationAction`: typed action, policy/risk/approval, execution result and rollback plan.
- `AuditEvent`: actor/tool/action, redacted inputs/outputs, reason and related identifiers.

Identifiers are UUIDs. Times are timezone-aware UTC. Unknown intent fields remain null and appear in `ambiguities`; inferred fields are named in `inferred_values`.

