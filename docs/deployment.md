# Deployment

Core local Compose services are LoadPilot API/web, PostgreSQL, Temporal, Prometheus, Alertmanager, OTel Collector, a k6 runner image, and the sandbox target. Optional profiles add Grafana, HolmesGPT and Robusta. Kubernetes deployments add the official k6 Operator; local operation never requires Kubernetes.

Production requirements include TLS/OIDC, an external secret manager, restricted egress, dedicated load-generator networks, quotas, durable PostgreSQL, Temporal visibility/retention, Prometheus retention/remote storage and backed-up audit records.

