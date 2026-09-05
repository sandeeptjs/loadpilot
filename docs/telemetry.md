# Telemetry

- k6 uses Prometheus remote write with `test_run_id`, `plan_id`, `experiment_id`, `scenario`, `stage`, `service` and `environment` labels where supported.
- The OTel Collector accepts OTLP from the platform/target, scrapes Prometheus endpoints, adds resource attributes, batches data and exports metrics to Prometheus. Production may add Loki/Tempo without changing the model.
- Each run has a `TelemetryWindow` padded two minutes before and after execution by default.
- Analysis queries latency histograms, request/error rate, iterations, VUs, dropped iterations, CPU, memory, restarts, queues, DB pools/waits, cache latency and GC, then aligns series by timestamp and stage.
- Correlation keys are time overlap, environment, service, resource identity and dependency edges. AI sees grouped incidents and supporting series, not an unfiltered alert dump.

