from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .audit import audit_event
from .lifecycle import RunStore
from .models import Alert, AlertBatch, ExecutionBackendType, Investigation, PerformanceTestPlan, utcnow
from .service import LoadPilotService


class CreateTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    prompt: str = Field(min_length=3)
    source_type: str
    source: Any
    application_name: str = "Target application"
    base_url: str | None = None
    environment: str = "local"
    backend: ExecutionBackendType = ExecutionBackendType.LOCAL
    validate_script: bool = Field(default=False, alias="validate")


app = FastAPI(title="LoadPilot API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:8000"], allow_methods=["*"], allow_headers=["*"])
service = LoadPilotService(store=RunStore(os.environ.get("LOADPILOT_DB", "loadpilot.db")))


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.post("/api/tests", status_code=201)
async def create_test(request: CreateTestRequest):
    try:
        payload = request.model_dump(exclude={"validate_script"})
        return await service.prepare(**payload, validate=request.validate_script)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/runs")
def list_runs(limit: int = 100):
    return service.store.list(min(limit, 500))


@app.get("/api/runs/{run_id}")
def get_run(run_id: UUID):
    try:
        run = service.store.get(run_id)
        plan = service.store.get_entity("plan", run.plan_id, PerformanceTestPlan)
        investigation = next((item for item in service.store.list_entities("investigation", Investigation) if item.run_id == run.id), None)
        return {"run": run, "plan": plan, "investigation": investigation}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/runs/{run_id}/start")
async def start_run(run_id: UUID):
    try:
        return await service.start(run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


class CancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: UUID, request: CancelRequest):
    try:
        return service.cancel(run_id, request.reason)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/audit")
def audit(limit: int = 200):
    return service.store.audit(min(limit, 500))


def _alert_time(value: Any):
    if not value:
        return None
    return datetime.fromisoformat(str(value))


@app.post("/api/alerts", status_code=202)
def ingest_alerts(payload: dict[str, Any]):
    alerts = []
    for item in payload.get("alerts", []):
        labels = {str(key): str(value) for key, value in item.get("labels", {}).items()}
        alerts.append(
            Alert(
                fingerprint=str(item.get("fingerprint") or f"{labels.get('alertname', 'alert')}:{len(alerts)}"),
                name=labels.get("alertname", "UnnamedAlert"),
                starts_at=_alert_time(item.get("startsAt")) or utcnow(),
                ends_at=_alert_time(item.get("endsAt")),
                labels=labels,
                annotations={str(key): str(value) for key, value in item.get("annotations", {}).items()},
            )
        )
    batch = AlertBatch(alerts=alerts)
    service.store.put_entity("alert_batch", batch)
    service.store.append_audit(
        audit_event(
            actor="alertmanager",
            tool="alertmanager-webhook",
            action="alerts.received",
            inputs=payload,
            outputs={"batch_id": str(batch.id), "accepted": len(alerts)},
            reason="Persist external alerts for time-window correlation with performance runs.",
        )
    )
    return {"batch_id": batch.id, "accepted": len(alerts)}


@app.get("/api/alerts")
def list_alert_batches(limit: int = 100):
    return service.store.list_entities("alert_batch", AlertBatch, min(limit, 500))


web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if web_dist.exists():
    app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = web_dist / path
        return FileResponse(candidate if candidate.is_file() else web_dist / "index.html")
