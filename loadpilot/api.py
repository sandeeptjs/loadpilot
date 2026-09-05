from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .analysis import compare_metrics
from .audit import audit_event, redact
from .definitions import DefinitionExecution, SavedDefinition
from .lifecycle import RunStore
from .models import Alert, AlertBatch, ExecutionBackendType, SecretReference, StrictModel, UserJourney, utcnow
from .remediation import PoolAction, Remediator
from .reports import Report
from .service import LoadPilotService
from .settings import Settings, get_settings
from .worker import Worker


class CreateTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    prompt: str = Field(min_length=3, max_length=20000)
    source_type: Literal['openapi', 'manual', 'har', 'postman', 'graphql'] = 'openapi'
    source: Any = None
    source_url: str | None = None
    application_name: str = 'Target application'
    base_url: str | None = None
    environment: str = 'local'
    backend: ExecutionBackendType = ExecutionBackendType.LOCAL
    validate_script: bool = Field(default=False, alias='validate')
    intent_overrides: dict | None = None
    credentials_reference: SecretReference | None = None
    run_at: datetime | None = None
    auto_start: bool = False
    auto_followup: bool = False
    journeys: list[UserJourney] | None = Field(default=None, min_length=1, max_length=10)


class DefinitionRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    previous_version: UUID | None = None
    request: CreateTestRequest


class RecoveryRequest(StrictModel):
    journeys: list[UserJourney] | None = Field(default=None, min_length=1, max_length=10)
    auto_start: bool = True


class CancelRequest(StrictModel):
    reason: str = Field(min_length=3, max_length=500)


class ScheduleRequest(StrictModel):
    run_at: datetime


class RemediationRequest(StrictModel):
    action: Literal['IncreaseSandboxPool'] = 'IncreaseSandboxPool'
    pool_size: int = Field(ge=1, le=32)


class Baseline(StrictModel):
    id: UUID
    name: str = Field(min_length=1, max_length=100)


def create_app(settings: Settings | None = None, service: LoadPilotService | None = None):
    settings = settings or get_settings()
    service = service or LoadPilotService(RunStore(settings.db), settings.generated_dir, settings=settings)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(Worker(service).run()) if settings.embedded_worker else None
        app.state.worker_task = task
        yield
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title='LoadPilot API', version='0.2.0', lifespan=lifespan)
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173', 'http://localhost:8000', 'http://127.0.0.1:8000'], allow_methods=['*'], allow_headers=['*'])

    @app.middleware('http')
    async def api_auth(request, call_next):
        if settings.api_token and request.url.path.startswith('/api/') and request.url.path != '/api/health':
            authorization = request.headers.get('Authorization', '')
            supplied = authorization[7:] if authorization.startswith('Bearer ') else ''
            if not secrets.compare_digest(supplied.encode(), settings.api_token.encode()):
                return JSONResponse(status_code=401, content={'detail': 'A valid API bearer token is required'})
        return await call_next(request)

    @app.get('/api/readiness')
    def readiness():
        with service.store._connect() as db:
            db.execute('SELECT 1').fetchone()
        binary = shutil.which(settings.k6_bin)
        task = getattr(app.state, 'worker_task', None)
        worker_live = not settings.embedded_worker or bool(task and not task.done())
        return JSONResponse(status_code=200 if binary and worker_live else 503, content={'ready': bool(binary and worker_live), 'worker': 'embedded-running' if settings.embedded_worker and worker_live else 'embedded-stopped' if settings.embedded_worker else 'external-managed', 'database': 'ok', 'k6': 'available' if binary else 'missing', 'ai_mode': 'provider' if settings.ai_enabled else 'offline', 'execution_scope': 'one local workload per database'})

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse(status_code=404, content={'detail': 'Requested record was not found'})

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse(status_code=422, content={'detail': redact(str(exc))})

    @app.exception_handler(httpx.HTTPError)
    async def upstream(request, exc):
        return JSONResponse(status_code=502, content={'detail': 'Upstream service request failed; check target/provider configuration'})

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'version': '0.2.0', 'ai_mode': 'provider' if settings.ai_enabled else 'offline', 'worker': 'embedded' if settings.embedded_worker else 'external'}

    @app.get('/api/capabilities')
    def capabilities():
        return {'scenario_features': ['conditional steps', 'bounded polling and read retries', 'datasets and unique iteration values', 'basic auth and login/token journeys', 'multipart uploads', 'multi-service operations', 'saved definitions and recovery', 'ordered steps', 'nested JSON bindings', 'response assertions', 'weighted journeys', 'bounded repetition', 'preflight before load', 'JSON/form/text/multipart requests', 'environment credential references'], 'scenario_sources': ['openapi', 'manual', 'har', 'postman', 'graphql documents'], 'execution_backends': ['LOCAL'], 'test_types': ['BASELINE', 'LOAD', 'STRESS', 'SOAK', 'SPIKE', 'BREAKPOINT'], 'ai_mode': 'provider' if settings.ai_enabled else 'offline', 'max_vus': settings.max_vus, 'max_duration_seconds': settings.max_duration_seconds, 'max_rps': settings.max_rps, 'sandbox_openapi_url': settings.sandbox_url.rstrip('/') + '/openapi.json', 'remediation_enabled': settings.allow_sandbox_remediation and bool(settings.sandbox_control_token), 'scheduling': 'Persisted one-time jobs; relative delays or timezone-aware run_at', 'limitations': ['Only local backend is execution-qualified', 'RPS requires one HTTP operation', 'Offline parsing uses deterministic patterns', 'Sandbox pool is modeled, not PostgreSQL', 'No production multi-tenant authentication']}

    @app.post('/api/tests', status_code=201)
    async def create_test(request: CreateTestRequest):
        payload = request.model_dump(exclude={'validate_script', 'source_url', 'credentials_reference'})
        if request.source_url:
            settings.check_target(request.source_url)
            async with httpx.AsyncClient(timeout=10) as client, client.stream('GET', request.source_url) as response:
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 2_000_000:
                        raise ValueError('Application schema exceeds 2 MB')
                    chunks.append(chunk)
            payload['source'] = json.loads(b''.join(chunks))
            if not request.base_url:
                parsed = urlsplit(request.source_url)
                payload['base_url'] = f'{parsed.scheme}://{parsed.netloc}'
        if payload['source'] is None:
            raise ValueError('Provide source or source_url')
        return await service.prepare(**payload, credentials_reference=request.credentials_reference, validate=request.validate_script)

    @app.post('/api/definitions', status_code=201)
    def save_definition(request: DefinitionRequest):
        if request.previous_version:
            service.store.get_entity('definition', request.previous_version, SavedDefinition)
        payload = request.request.model_dump(mode='json', by_alias=True)
        payload.update(auto_start=False, auto_followup=False, run_at=None)
        definition = SavedDefinition(name=request.name, previous_version=request.previous_version, request=payload)
        service.store.put_entity('definition', definition)
        service.store.append_audit(audit_event(actor='user', tool='definitions', action='definition.saved', inputs={}, outputs={'id': str(definition.id), 'previous_version': str(definition.previous_version) if definition.previous_version else None}, reason='Save an immutable reusable test definition'))
        return definition

    @app.get('/api/definitions')
    def definitions(limit: int = Query(100, ge=1, le=1000)):
        return service.store.list_entities('definition', SavedDefinition, limit)

    @app.get('/api/definitions/{definition_id}')
    def definition(definition_id: UUID):
        return service.store.get_entity('definition', definition_id, SavedDefinition)

    @app.post('/api/definitions/{definition_id}/run', status_code=202)
    async def execute_definition(definition_id: UUID, request: DefinitionExecution):
        saved = service.store.get_entity('definition', definition_id, SavedDefinition)
        payload = {**saved.request, 'auto_start': request.auto_start, 'run_at': request.run_at}
        if request.intent_overrides:
            payload['intent_overrides'] = {**(payload.get('intent_overrides') or {}), **request.intent_overrides}
        run = await create_test(CreateTestRequest.model_validate(payload))
        service._audit(run, 'definition.executed', {'definition_id': str(definition_id)}, {}, 'Run the selected immutable definition version')
        return run

    @app.get('/api/runs')
    def runs(limit: int = Query(100, ge=1, le=500)):
        return service.store.list(limit)

    @app.get('/api/runs/{run_id}')
    def detail(run_id: UUID):
        return service.detail(run_id)

    @app.post('/api/runs/{run_id}/start', status_code=202)
    def start(run_id: UUID):
        return service.submit(run_id)

    @app.post('/api/runs/{run_id}/schedule', status_code=202)
    def schedule(run_id: UUID, request: ScheduleRequest):
        return service.submit(run_id, request.run_at)

    @app.post('/api/runs/{run_id}/cancel')
    def cancel(run_id: UUID, request: CancelRequest):
        return service.cancel(run_id, request.reason)

    @app.get('/api/runs/{run_id}/samples')
    def samples(run_id: UUID, after: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=10000)):
        service.store.get(run_id)
        items = service.store.samples(run_id, after, limit)
        return {'samples': items, 'next_cursor': items[-1]['id'] if items else after, 'semantics': 'Live p95 is a rolling sample estimate, RPS is cumulative since execution began; final summary is authoritative.'}

    @app.get('/api/runs/{run_id}/script')
    def script(run_id: UUID):
        run = service.store.get(run_id)
        artifact = next((item for item in run.artifacts if item.kind == 'k6-script'), None)
        if not artifact:
            raise HTTPException(404, 'No generated script')
        path = Path(artifact.uri)
        if not path.resolve().is_relative_to(service.generated_dir.resolve()):
            raise ValueError('Artifact path is outside the configured directory')
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
            raise ValueError('Script integrity check failed')
        return Response(path.read_text(encoding='utf-8'), media_type='application/javascript')

    @app.get('/api/runs/{run_id}/report')
    def report(run_id: UUID):
        detail = service.detail(run_id)
        return {'report': service.store.get_entity('report', run_id, Report), 'investigation': detail['investigation'], 'run': detail['run']}

    @app.post('/api/runs/{run_id}/rerun', status_code=202)
    def rerun(run_id: UUID):
        return service.rerun(run_id)

    @app.post('/api/runs/{run_id}/recover', status_code=202)
    def recover(run_id: UUID, request: RecoveryRequest):
        return service.rerun(run_id, auto_start=request.auto_start, journeys=request.journeys)

    @app.get('/api/runs/{run_id}/diagnostics')
    def diagnostics(run_id: UUID):
        run = service.store.get(run_id)
        path = next((Path(a.uri) for a in run.artifacts if a.kind == 'k6-script'), None)
        preflights = []
        if path and path.resolve().is_relative_to(service.generated_dir.resolve()):
            for artifact in sorted(path.parent.glob(path.stem + '.preflight-*.json')):
                try:
                    summary = json.loads(artifact.read_text(encoding='utf-8'))
                    preflights.append({'journey_index': int(artifact.name.split('.preflight-')[1].split('.')[0]), 'checks': summary.get('checks'), 'failures': summary.get('failures', [])})
                except (ValueError, OSError):
                    continue
        return {'state': run.state, 'error': run.error, 'preflights': preflights, 'recovery': 'Correct the definition or environment credentials, then POST /recover. The original run stays unchanged.'}

    @app.post('/api/runs/{run_id}/follow-up' , status_code=202)
    def followup(run_id: UUID):
        return service.rerun(run_id, followup=True)

    @app.get('/api/runs/{run_id}/compare/{baseline_id}')
    def compare(run_id: UUID, baseline_id: UUID):
        current, baseline = service.detail(run_id), service.detail(baseline_id)
        for item in (current, baseline):
            if item['run'].state.value != 'COMPLETED':
                raise ValueError('Comparison requires two completed runs')
        if current['application'].source_fingerprint != baseline['application'].source_fingerprint or current['application'].base_url != baseline['application'].base_url:
            raise ValueError('Runs belong to different applications or targets')
        same_workload = current['plan'].stages == baseline['plan'].stages and current['plan'].journeys == baseline['plan'].journeys
        if any(item['run'].metrics.get('loadpilot_transport_failed.rate', 0) >= .2 for item in (current, baseline)):
            raise ValueError('Transport failure invalidates application performance comparison')
        keys = ['http_req_duration.p(95)', 'http_req_failed.rate', 'http_reqs.rate', 'loadpilot_journey_failed.rate']
        return {'current_run_id': run_id, 'baseline_run_id': baseline_id, 'same_workload': same_workload, 'warning': None if same_workload else 'Workloads differ; differences do not establish a regression', 'metrics': compare_metrics({k: current['run'].metrics[k] for k in keys if k in current['run'].metrics}, {k: baseline['run'].metrics[k] for k in keys if k in baseline['run'].metrics})}

    @app.post('/api/baselines', status_code=201)
    def save_baseline(baseline: Baseline):
        run = service.store.get(baseline.id)
        if run.state.value != 'COMPLETED' or run.slo_passed is False:
            raise ValueError('Baseline requires a completed passing run')
        service.store.put_entity('baseline', baseline)
        service._audit(run, 'baseline.saved', {}, baseline.model_dump(mode='json'), 'Save measured reference run')
        return baseline

    @app.get('/api/baselines')
    def baselines():
        return service.store.list_entities('baseline', Baseline)

    @app.get('/api/audit')
    def audit(limit: int = Query(200, ge=1, le=10000), run_id: UUID | None = None):
        events = service.store.audit(limit)
        return [event for event in events if run_id is None or event.related_test_id == run_id]

    @app.post('/api/alerts', status_code=202)
    def alerts(payload: dict[str, Any]):
        values = []
        for item in payload.get('alerts', []):
            labels = {str(k): str(v) for k, v in item.get('labels', {}).items()}
            def timestamp(value):
                parsed = datetime.fromisoformat(value) if value else None
                if parsed and parsed.tzinfo is None:
                    raise ValueError('Alert timestamps must include timezone offsets')
                return parsed
            ends_at = timestamp(item.get('endsAt'))
            if ends_at and ends_at.year == 1:
                ends_at = None
            values.append(Alert(fingerprint=str(item.get('fingerprint') or hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest()), name=labels.get('alertname', 'UnnamedAlert'), starts_at=timestamp(item.get('startsAt')) or utcnow(), ends_at=ends_at, labels=labels, annotations=redact(item.get('annotations', {}))))
        batch = AlertBatch(alerts=values)
        service.store.put_entity('alert_batch', batch)
        service.store.append_audit(audit_event(actor='alertmanager', tool='webhook', action='alerts.received', inputs={}, outputs={'accepted': len(values), 'batch_id': str(batch.id)}, reason='Persist raw alerts for scoped correlation'))
        return {'batch_id': batch.id, 'accepted': len(values)}

    @app.get('/api/alerts')
    def alert_batches():
        return service.store.list_entities('alert_batch', AlertBatch)

    @app.post('/api/runs/{run_id}/remediate', status_code=202)
    async def remediate(run_id: UUID, request: RemediationRequest):
        return await Remediator(service).apply(run_id, request.pool_size)

    @app.get('/api/remediations')
    def remediations():
        return service.store.list_entities('remediation', PoolAction)

    @app.post('/api/remediations/{action_id}/rollback')
    async def rollback(action_id: UUID):
        action = service.store.get_entity('remediation', action_id, PoolAction)
        return await Remediator(service).apply(action.run_id, action.previous_size, rollback_id=action_id)

    web_dist = Path(__file__).resolve().parent.parent / 'web' / 'dist'
    if (web_dist / 'assets').exists():
        app.mount('/assets', StaticFiles(directory=web_dist / 'assets'), name='assets')

        @app.get('/{path:path}', include_in_schema=False)
        def spa(path: str):
            if path.startswith('api/'):
                raise HTTPException(404, 'Unknown API route')
            return FileResponse(web_dist / 'index.html')
    return app


app = create_app()
