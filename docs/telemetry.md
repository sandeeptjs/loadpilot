# Implemented telemetry

Local k6 writes real JSON point records and an authoritative final summary. The backend records per-second snapshots in SQLite and samples the target's `/metrics` Prometheus exposition. The dashboard plots rolling p95, labeled as an estimate; final metrics come from k6.

Measured hold stages exclude requests that cross a stage boundary. A hold needs at least five requests and must have completed before it contributes to capacity estimates. No SLO means no assessed stable capacity. Transport failures are counted separately, paced and subject to an early-abort threshold.

The sandbox exposes modeled pool activity, size, waiting histograms, saturation-event counts, cache counters and deliberately retained memory. A saturation event is never converted into fabricated utilization. The result reports mean pool wait over the run and describes the bottleneck as modeled.

Local alert rules evaluate measured samples. Reports distinguish received notifications, distinct fingerprints, duplicates, incidents and excluded unrelated notifications. Correlation scopes by target/run and environment, filters by run window, and uses connected service dependencies. Rule-derived alerts are labeled `local-measured-rule`. External alerts without reliable run/target identity do not enter run evidence.

The Prometheus query adapter and optional Compose topology remain available for further integration. The local demo does not yet ingest full distributed logs, traces or Prometheus remote-write series.

Reference: [k6 JSON output](https://grafana.com/docs/k6/latest/results-output/real-time/json/).
