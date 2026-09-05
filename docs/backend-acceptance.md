# Backend acceptance evidence

On 2026-09-05 the public API acceptance runner completed with real, checksum-verified k6 v1.6.1 and isolated local servers. AI mode was explicitly offline.

The saved evidence is `artifacts/demo-acceptance/20260905-123053/evidence.json`, accompanied by its SQLite database, generated scripts, summaries, point records and server logs. These local artifacts are gitignored. Reproduce them with `uv run python scripts/demo_acceptance.py`.

| Scenario | Observed p95 | Outcome |
|---|---:|---|
| Healthy baseline, 2 users / 10 seconds | 77.1 ms | Passed configured limits |
| Stress, 5 to 40 users / 35 seconds, pool size 2 | 1634.0 ms | Latency limit breached |
| Identical stress after pool size 12 | 124.7 ms | Measured p95 improved by 92.4% |
| Short soak, 3 users / 10 seconds | 78.2 ms | Passed; retained sandbox memory growth measured |

The stress run produced 45 rule-derived notifications, two distinct alerts and one correlated incident. Forty-three duplicates were removed. One deliberately unrelated alert fixture was excluded. The 97.8% notification reduction is specific to this demo's sampled rules, not a production benchmark.

The runner verified generated login/product/cart/checkout dependencies, baseline persistence, rejection of unauthenticated controls and unsupported actions, a bounded pool change with verification and rollback, a scheduled job completing after API restart, and actual cancellation.

Browser QA subsequently exposed an immediate retry loop after a Windows socket failure. Failed journeys now wait before retrying, a measured transport-failure threshold aborts sustained connection failures, and reports withhold capacity claims when the load generator cannot connect. A focused real-k6 regression test uses a closed localhost port to verify bounded request counts and transport evidence.

The browser stress retest completed with 714 requests, no HTTP errors, p95 1585.9 ms and measured modeled pool contention. The dashboard showed its generated journey, live-sample plot, incident reduction and sandbox verification action.

The browser-triggered verification then completed with 1384 requests, no HTTP errors and p95 124.7 ms. The dashboard displayed the identical-workload comparison. These runs remain in `artifacts/demo.db` for inspection.

Provider validation uses a mock HTTP transport, not a real provider key. Docker/Kubernetes and long-duration soak qualification were not performed on this host.
