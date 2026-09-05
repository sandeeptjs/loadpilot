# Acceptance evidence

The final local acceptance run used the official k6 v2.1.0 Windows executable against the instrumented FastAPI checkout sandbox. The durable record is `artifacts/acceptance-final.db` (ignored from source control) and the run id is `b06cf57e-52e4-40ec-9224-060b4f2418af`.

## Result

- Lifecycle completed through discovery, generation, planning, compilation, validation, execution, telemetry collection and analysis.
- All functional checks passed and HTTP error rate was 0% across 492 requests.
- At 20 VUs: p95 171.978 ms, 0% errors, 29.5 requests/second.
- At 60 VUs: p95 1122.08 ms, 0% errors, 52.5 requests/second.
- The target's modeled database pool reached 100% utilization, accumulated 279.714 ms average wait and emitted 246 saturation events.
- The investigation identified database connection-pool saturation as the likely root cause with 0.78 confidence, bounded stable capacity between 20 and 60 VUs, and proposed a 40 VU follow-up experiment.

Threshold failure is treated as a valid performance-test outcome rather than infrastructure failure, so the run reaches `COMPLETED` with the breach preserved as evidence.
