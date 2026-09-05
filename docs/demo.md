# Hackathon demonstration

Run `uv run python scripts/start_demo.py` after installing dependencies and building the dashboard. The launcher binds to loopback, uses a fresh control token, and starts a deliberately constrained modeled pool. Run history persists.

## Main story, about three minutes

1. Choose **New test**. Keep the Stress preset: checkout from 5 to 40 users for 35 seconds, p95 below 500 ms, errors below 1%.
2. Choose **Create and run**. Explain that the platform discovers login, products, cart and checkout from the schema links; it generates payload pools and extracts tokens and IDs from real responses.
3. Show the live measured latency plot and changing lifecycle. The plan contains ramp and hold stages. A run can complete while breaching its performance limits.
4. Show the analysis and alert correlation. Explain duplicates separately from distinct alerts and incidents. The report includes grouping rules; unrelated target/environment alerts are excluded.
5. Select **Increase sandbox pool to 12 and verify**. The action changes only the configured sandbox pool, with a hard maximum of 32, a control token, previous-value recording and an audit event. It automatically queues the exact same workload.
6. Show the measured before/after p95 and the Audit page. Open the full report JSON or generated script if the judges ask how the numbers were obtained.

The resources are modeled. Say “modeled connection-pool contention,” not “we diagnosed PostgreSQL.” The requests, timings, errors and pool waits are real. The launcher resets the sandbox configuration on restart; it does not delete prior run history.

## Other required scenarios

- Baseline preset: a short healthy reference. The API can save a named baseline and compare completed runs.
- Soak preset: sustained load. A sixty-second demonstration shows execution, not proof of hour-scale stability. The acceptance artifact contains a ten-second soak with deliberately retained memory.
- Scheduling: enter a start delay or send a timezone-aware `run_at`. Queued jobs survive an API restart.
- Autonomous refinement: set `auto_followup: true` on creation. After a measured pass/fail bracket, the worker creates at most one narrower child run. It records why refinement was skipped if no defensible bracket exists.
- Cancellation: create a longer soak, select Stop test, and verify CANCELED persists after refresh. The worker kills k6, not just the status label.

## Real AI versus offline mode

Configure the provider fields in `.env` to demonstrate real AI intent extraction and qualitative result summaries. Without them, the interface explicitly says offline mode. Exact numerical measurements stay in structured evidence; the AI narrative cites evidence IDs and cannot introduce numerical claims.

Do one credentialed provider rehearsal before presenting AI claims. The repository's acceptance run uses offline mode and real k6 traffic. It does not substitute a mocked provider for a live AI demonstration.

## Evidence and recovery

`uv run python scripts/demo_acceptance.py` starts isolated services and saves raw evidence, logs, scripts and a database in a timestamped artifact directory. It includes a clearly labeled unrelated alert fixture to verify exclusion. All load metrics come from real executions.

If another application occupies a port, use `--api-port` and `--target-port`. If transport failures occur, the script paces failed journeys and aborts sustained connection failure; the report explicitly withholds application-capacity claims. Do not present zero latency from failed connections as healthy performance.

This local demo is designed for one operator and one active workload. Production authentication and deployment hardening remain separate work.
