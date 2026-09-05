# Dependency and license plan

The table below records the original integration inventory. The implemented demo additionally uses the unmodified [hypothesis-jsonschema library](https://github.com/python-jsonschema/hypothesis-jsonschema), MPL-2.0, and jsonschema for validated payload generation. Schemathesis and Temporal remain optional dependencies, not the primary runtime path. The API container now includes the unmodified k6 executable; release packaging must retain the upstream license and corresponding-source information. A release notice/SBOM bundle has not been produced in this task.

| Repository | License inspected | Integration | Modified? | Distribution plan |
|---|---|---|---:|---|
| k6 Performance MCP | MIT | Ideas/reference only | No | No bundled source/runtime |
| Schemathesis | MIT | Python dependency | No | Include notices and pinned dependency metadata |
| k6 Studio | AGPL-3.0 | Separate optional desktop/process | No | Never link/copy; users install separately; provide source-offer/link obligations if redistributed |
| k6 | AGPL-3.0 | Separate executable/container | No | Do not embed; preserve notices and satisfy corresponding-source obligations for redistributed images/binaries |
| k6 Operator | Apache-2.0 | External Kubernetes service/CRD | No | Official chart/image, notices retained |
| Orderly Ape | MIT | Reference only | No | No bundled source/runtime |
| Temporal server | MIT | External service | No | Official image; notices retained |
| Temporal Python SDK | MIT | Python dependency | No | Notices retained |
| OTel Collector Contrib | Apache-2.0 | External service | Config only | Official image/custom config; NOTICE retained |
| Prometheus | Apache-2.0 | External service | Config only | Official image; NOTICE retained |
| Alertmanager | Apache-2.0 | External service | Config only | Official image; NOTICE retained |
| HolmesGPT | Apache-2.0 | Isolated service | Config only | Official image/source with notices |
| Robusta | MIT | Optional isolated service | Config only | Official chart/image; notices retained |

This is an engineering plan, not legal advice. Release automation must generate an SBOM and third-party notices and must re-check the exact version/license before distribution.

