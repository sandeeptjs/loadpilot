# Local development

Follow the README quick start. `uv sync --extra dev` installs the backend. `npm ci` and `npm run build` inside web build the dashboard. `scripts/install_k6.ps1` installs portable, checksum-verified k6 on Windows.

Start the API alone with `uv run uvicorn loadpilot.api:app --host 127.0.0.1 --port 8000`. The compiled dashboard is served from web/dist. For Vite development, `npm run dev` proxies `/api` to the API.

Configuration lives in `.env` or environment variables. `.env` is ignored. The demo launcher creates a per-session sandbox control token.

Run `uv run pytest`, `uv run ruff check .`, `npm run build` and `npm run lint`. The real-k6 transport test skips if the portable binary is absent. `uv run python scripts/demo_acceptance.py` launches isolated processes and writes timestamped measured artifacts.

For a separate worker, set `LOADPILOT_EMBEDDED_WORKER=false` on the API and run `uv run python -m loadpilot.worker` against the same database and generated directory. Use one shared queue per target to avoid overlapping load experiments.
