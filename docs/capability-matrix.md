# Capability matrix

`F` full, `P` partial, `N` none, `O` meaningful overlap. The **Owner** column removes runtime duplication.

| Capability | LP | MCP | ST | Studio | k6 | Operator | OA | Temporal | OTel | Prom | AM | Holmes | Robusta | Owner |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Natural-language intent / validation | F | P | N | P | N | N | N | P | N | N | N | P | N | LoadPilot |
| Application discovery | F | P | F | F | P | N | N | N | N | N | N | P | P | Adapters + Schemathesis |
| OpenAPI / GraphQL ingestion | P | P | F | N | N | N | N | N | N | N | N | N | N | Schemathesis |
| HAR ingestion / browser capture | P | N | N | F | N | N | N | N | N | N | N | N | N | LoadPilot / k6 Studio |
| Dependency discovery | P | N | F | P | N | N | N | N | N | N | N | P | N | Schemathesis |
| Auth / session correlation | P | P | P | F | F | P | P | N | N | N | N | P | P | LoadPilot + Studio export |
| Realistic/state-aware data | F | P | F | P | P | N | N | N | N | N | N | N | N | Schemathesis façade |
| Journey generation | F | P | P | F | P | N | N | N | N | N | N | N | N | LoadPilot |
| Baseline / stress / soak | F | P | N | P | F | P | P | P | N | N | N | N | N | LoadPilot planner + k6 |
| Spike / breakpoint | F | P | N | P | F | P | P | P | N | N | N | N | N | LoadPilot planner + k6 |
| Workload / threshold / k6 generation | F | P | N | F | F | N | P | N | N | N | N | N | N | LoadPilot compiler |
| Script validation | F | N | N | P | F | N | N | N | N | N | N | N | N | k6 inspect |
| Scheduling / queue / retry | P | N | N | N | N | N | P | F | N | N | N | N | P | Temporal |
| Execution / cancellation | F | P | N | P | F | F | O | P | N | N | N | N | N | k6 + backends |
| Distributed execution | P | N | N | N | P | F | O | P | N | N | N | N | P | k6 Operator |
| Live state / history / dashboard | F | N | N | P | P | P | O | P | N | P | N | P | P | LoadPilot |
| Metrics / logs / traces / infra telemetry | P | P | N | N | P | P | P | P | F | F | P | F | F | OTel + Prometheus |
| Prometheus querying | F | N | N | N | P | N | N | N | P | F | P | F | P | Prometheus API |
| Alert grouping / dedup / inhibition | P | N | N | N | N | N | N | N | P | P | F | P | F | Alertmanager |
| Anomaly / regression analysis | F | P | N | N | P | N | N | P | P | P | N | P | P | LoadPilot |
| RCA / AI summary / next experiment | P | P | N | N | N | N | N | P | N | N | N | F | P | HolmesGPT + LoadPilot policy |
| Remediation / allow-list | F | N | N | N | N | N | N | P | N | N | N | P | F | LoadPilot policy + Robusta |
| Audit / RBAC / secret references | F | N | P | P | P | P | P | P | P | N | P | P | P | LoadPilot |

LP=LoadPilot, MCP=k6 Performance MCP, ST=Schemathesis, OA=Orderly Ape, AM=Alertmanager.

