"""Run a short, real k6 acceptance test against the instrumented sandbox."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from loadpilot.execution import LocalK6Backend
from loadpilot.lifecycle import RunStore
from loadpilot.models import ExecutionBackendType
from loadpilot.service import LoadPilotService


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:8080")
    parser.add_argument("--k6", default="k6")
    parser.add_argument("--database", default="artifacts/acceptance.db")
    args = parser.parse_args()
    base_url = args.target.rstrip("/")
    os.environ["LOADPILOT_TARGET_METRICS_URL"] = f"{base_url}/metrics"
    async with httpx.AsyncClient(timeout=10) as client:
        schema = (await client.get(f"{base_url}/openapi.json")).raise_for_status().json()
    store_path = Path(args.database)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    service = LoadPilotService(
        store=RunStore(store_path),
        generated_dir="artifacts/generated-tests",
        backends={ExecutionBackendType.LOCAL: LocalK6Backend(args.k6)},
    )
    run = await service.prepare(
        prompt="Stress checkout from 10 concurrent users for 20 seconds. Find the maximum load while p95 stays under 500 ms and errors under 1%.",
        source_type="openapi",
        source=schema,
        application_name="Checkout sandbox",
        base_url=base_url,
        validate=True,
    )
    completed = await service.start(run.id)
    print(json.dumps(completed.model_dump(mode="json"), indent=2))
    return 0 if completed.state.value == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
