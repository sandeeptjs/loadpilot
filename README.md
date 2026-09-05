# LoadPilot

LoadPilot is an open-source control plane that turns a validated performance-testing intent plus an application definition into a planned, generated, validated, executed and evidence-backed k6 run.

It composes Schemathesis, k6, k6 Operator, Temporal, OpenTelemetry, Prometheus, Alertmanager, HolmesGPT and optionally Robusta behind one typed lifecycle. It does not merge or fork those projects.

## Quick start

```powershell
uv sync --extra dev
uv run pytest
uv run uvicorn loadpilot.api:app --reload
```

Then open `http://localhost:8000`. See [development](docs/development.md), [architecture](docs/architecture.md), [repository audit](docs/repository-audit.md), and [acceptance evidence](docs/acceptance.md).

## Demo configuration

The dashboard is configured to use the local API through Vite's `/api` proxy in development, and the API serves the compiled dashboard in the demo setup. After the first dependency install, start the whole local demo with:

```powershell
uv sync --extra dev
cd web; npm ci; cd ..
.\scripts\start_demo.ps1
```

Open `http://127.0.0.1:8000`, select **New test**, and use the pre-filled sandbox OpenAPI URL. The dashboard creates a reviewable load-test plan without sending traffic. Use the full acceptance command in [development](docs/development.md) when you want to execute a real k6 run.

If either default port is occupied, pass `-ApiPort` and `-TargetPort` to the launcher. Update the OpenAPI URL in the dialog to match the target port.

For containers, `docker compose up --build` now compiles the dashboard inside the API image; Docker is optional for the local demo.
