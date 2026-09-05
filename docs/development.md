# Local development

The minimal developer path is Python plus a locally installed k6. Docker Compose supplies the full service topology when Docker is available.

```powershell
uv sync --extra dev
uv run pytest
uv run uvicorn loadpilot.api:app --reload
```

Open `http://localhost:8000`. Set `LOADPILOT_K6_BIN` if k6 is not on `PATH`. Use secret references such as `env:TARGET_TOKEN`; never place secret values in plans.

The sandbox target runs from `sandbox_target.app:app`. Its `/control` endpoint changes bounded degradation parameters for demonstrations.

## Real local acceptance run

Start the instrumented target, then invoke the acceptance runner with a real k6 executable:

```powershell
uv run uvicorn sandbox_target.app:app --port 8081
uv run python scripts/acceptance_smoke.py --target http://127.0.0.1:8081 --k6 .tools/k6/k6-v2.1.0-windows-amd64/k6.exe --database artifacts/acceptance.db
```

The runner fetches the target's OpenAPI document, compiles and validates a k6 script, executes authenticated cart and checkout traffic, snapshots Prometheus exposition before and after the run, and persists the run plus investigation in SQLite.
