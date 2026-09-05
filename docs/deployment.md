# Deployment scope

The qualified path is the local Python launcher and portable k6. It binds the API and sandbox to loopback and requires no Docker or Kubernetes.

Docker Compose now starts API and sandbox by default. The API image includes k6 v1.6.1 and stores SQLite on a volume. Set SANDBOX_CONTROL_TOKEN in .env before `docker compose up --build`. Enable LOADPILOT_ALLOW_SANDBOX_REMEDIATION only for the sandbox demo. Prometheus, Alertmanager, OTel and Grafana use the optional observability profile.

Compose has not been executed on this host because Docker is unavailable. Kubernetes and Temporal are not wired into execution. Public deployment still needs authentication, tenant isolation and network controls.
