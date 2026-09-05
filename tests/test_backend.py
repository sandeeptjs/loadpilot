import asyncio
import json
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from jsonschema import validate

from loadpilot.ai import JsonProvider, Narrative
from loadpilot.api import create_app
from loadpilot.data import generate_samples
from loadpilot.discovery import OpenAPIAdapter
from loadpilot.execution import ExecutionBackend, ExecutionResult, LocalK6Backend
from loadpilot.intent import DeterministicIntentCompiler
from loadpilot.lifecycle import RunStore
from loadpilot.models import Alert, ExecutionBackendType, RunState, utcnow
from loadpilot.planner import TestPlanner
from loadpilot.service import LoadPilotService
from loadpilot.settings import Settings
from loadpilot.telemetry import AlertCorrelator
from loadpilot.worker import Worker


class SlowBackend(ExecutionBackend):
    def __init__(self):
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.calls = 0

    async def validate(self, script):
        pass

    async def execute(self, run, plan, script):
        self.calls += 1
        self.started.set()
        try:
            await asyncio.sleep(30)
        finally:
            self.stopped.set()
        return ExecutionResult(0, '', '', {})


def make_service(tmp_path, backend):
    cfg = Settings(db=str(tmp_path / 'runs.db'), generated_dir=str(tmp_path / 'scripts'), llm_model='', llm_api_key='')
    service = LoadPilotService(RunStore(cfg.db), cfg.generated_dir, {ExecutionBackendType.LOCAL: backend}, cfg)
    async def no_metrics(run_id):
        return {}
    service._target_metrics_snapshot = no_metrics
    return service, cfg


async def test_api_start_returns_promptly_and_cancel_stops_worker(tmp_path, checkout_openapi):
    backend = SlowBackend()
    service, cfg = make_service(tmp_path, backend)
    app = create_app(cfg, service)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/tests', json={'prompt': 'Baseline checkout with 1 user for 5 seconds', 'source': checkout_openapi})
        assert response.status_code == 201, response.text
        run_id = response.json()['id']
        response = await asyncio.wait_for(client.post(f'/api/runs/{run_id}/start'), 1)
        assert response.status_code == 202
        await asyncio.wait_for(backend.started.wait(), 2)
        assert (await client.post(f'/api/runs/{run_id}/start')).status_code == 202
        assert backend.calls == 1
        assert (await client.post(f'/api/runs/{run_id}/cancel', json={'reason': 'Cancel the actual worker'})).status_code == 200
        await asyncio.wait_for(backend.stopped.wait(), 2)
        assert service.store.get(run_id).state == RunState.CANCELED


async def test_scheduled_job_survives_service_recreation(tmp_path, checkout_openapi):
    backend = SlowBackend()
    first, _ = make_service(tmp_path, backend)
    due = utcnow() + timedelta(seconds=.5)
    run = await first.prepare(prompt='Baseline checkout with 1 user for 5 seconds', source_type='openapi', source=checkout_openapi, application_name='test', run_at=due)
    assert run.state == RunState.SCHEDULED
    assert not backend.started.is_set()
    second, _ = make_service(tmp_path, backend)
    worker = asyncio.create_task(Worker(second).run())
    try:
        await asyncio.sleep(.1)
        assert not backend.started.is_set()
        await asyncio.wait_for(backend.started.wait(), 2)
        second.cancel(run.id, 'Stop scheduled test')
        await asyncio.wait_for(backend.stopped.wait(), 2)
        assert second.store.get(run.id).state == RunState.CANCELED
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_script_tampering_is_rejected(tmp_path, checkout_openapi):
    backend = SlowBackend()
    service, _ = make_service(tmp_path, backend)
    run = await service.prepare(prompt='Baseline checkout with 1 user for 5 seconds', source_type='openapi', source=checkout_openapi, application_name='test')
    from pathlib import Path
    Path(run.artifacts[0].uri).write_text('tampered')
    result = await service.start(run.id)
    assert result.state == RunState.FAILED
    assert 'changed' in result.error
    assert backend.calls == 0


def test_payload_generation_obeys_integer_and_string_constraints():
    schema = {'type': 'object', 'required': ['quantity', 'email'], 'properties': {'quantity': {'type': 'integer', 'minimum': 1, 'maximum': 20}, 'email': {'type': 'string', 'format': 'email'}}, 'additionalProperties': False}
    samples = generate_samples(schema)
    assert len({item['quantity'] for item in samples}) > 1
    for item in samples:
        validate(item, schema)
        assert isinstance(item['quantity'], int)
    complex_schema = {'type': 'string', 'pattern': '^[A-Z]{3}[0-9]{2}$'}
    for item in generate_samples(complex_schema):
        validate(item, complex_schema)


def test_no_schedule_is_invented_from_at_250_vus():
    assert DeterministicIntentCompiler().compile('Run checkout at 250 VUs for 2 hours').schedule is None


def test_stress_range_has_holds_and_exact_duration(checkout_openapi):
    app = OpenAPIAdapter().adapt(checkout_openapi, name='target')
    intent = DeterministicIntentCompiler().compile('Stress checkout from 5 to 40 users for 30 seconds')
    plan = TestPlanner(Settings()).plan(intent, app)
    assert max(s.target_vus for s in plan.stages) == 40
    assert sum(s.duration_seconds for s in plan.stages) == 30
    assert len([s for s in plan.stages if s.measurement]) == 3
    intent.target_endpoints = ['missing-operation']
    with pytest.raises(ValueError, match='No operations'):
        TestPlanner().plan(intent, app)


def test_target_policy_rejects_unlisted_and_embedded_credentials():
    settings = Settings()
    for target in ('http://169.254.169.254', 'http://localhost.evil.test', 'http://token@localhost', 'file:///etc/passwd'):
        with pytest.raises(ValueError):
            settings.check_target(target)


def test_correlator_deduplicates_without_cross_environment_merges():
    now = utcnow()
    alerts = []
    for env in ('demo', 'unrelated'):
        for service in ('api', 'database'):
            alerts.append(Alert(name='HighLatency', fingerprint=service, starts_at=now, labels={'environment': env, 'target': 'sandbox', 'service': service}))
    alerts.append(alerts[0])
    incidents = AlertCorrelator().correlate(alerts, run_start=now, run_end=now, dependency_edges=[('api', 'database')])
    assert len(incidents) == 2
    assert sum(len(incident.alerts) for incident in incidents) == 4
    assert all(len({a.labels['environment'] for a in item.alerts}) == 1 for item in incidents)


async def test_provider_validates_output_and_evidence_references():
    cfg = Settings(llm_model='configured-model', llm_api_key='test-only')
    def reply(request):
        payload = json.loads(request.content)
        assert payload['model'] == 'configured-model'
        assert 'tools' not in payload
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'summary': 'Unsupported claim', 'evidence_ids': ['invented'], 'limitations': []})}}]})
    provider = JsonProvider(cfg, httpx.MockTransport(reply))
    with pytest.raises(ValueError, match='nonexistent'):
        await provider.summarize({'e1': 'Measured latency'})
    def malformed(request):
        return httpx.Response(200, json={'choices': [{'message': {'content': 'not json'}}]})
    with pytest.raises(ValueError, match='invalid structured'):
        await JsonProvider(cfg, httpx.MockTransport(malformed)).generate('JSON', {}, Narrative)


async def test_local_subprocess_is_killed_on_task_cancellation(tmp_path):
    import sys
    backend = LocalK6Backend(sys.executable)
    run_id = str(uuid4())
    task = asyncio.create_task(backend._run('-c', 'import time; time.sleep(60)', timeout=70, run_id=run_id))
    for _ in range(100):
        if run_id in backend.processes:
            break
        await asyncio.sleep(.01)
    process = backend.processes[run_id]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert process.returncode is not None
    assert run_id not in backend.processes


def test_rescheduling_updates_persisted_due_time(tmp_path):
    store = RunStore(tmp_path / 'queue.db')
    from loadpilot.models import TestRun as Run
    run_id = str(store.create(Run(plan_id=uuid4(), execution_backend=ExecutionBackendType.LOCAL)).id)
    store.enqueue(run_id, 100)
    store.enqueue(run_id, 200)
    assert store.claim('worker', 150) is None
    assert store.claim('worker', 201) == run_id


async def test_real_k6_arrival_rate_and_transport_failure(tmp_path):
    from pathlib import Path

    from loadpilot.compiler import K6Compiler
    from loadpilot.discovery import ManualAdapter
    from loadpilot.models import TestRun as Run
    binary = Path('.tools/k6/k6-v1.6.1-windows-amd64/k6.exe')
    if not binary.exists():
        pytest.skip('Portable k6 not installed; run scripts/install_k6.ps1')
    # Port 1 has no demo listener. This verifies bounded failure against localhost only.
    application = ManualAdapter().adapt([{'method': 'GET', 'path': '/missing'}], name='transport-outage', base_url='http://127.0.0.1:1')
    intent = DeterministicIntentCompiler().compile('Load with 5 RPS for 8 seconds')
    plan = TestPlanner(Settings(max_vus=5)).plan(intent, application)
    script = K6Compiler().compile(plan, application)
    path = tmp_path / 'transport.js'
    K6Compiler.write(script, path)
    backend = LocalK6Backend(str(binary))
    await backend.validate(path)
    result = await backend.execute(Run(plan_id=plan.id, execution_backend=ExecutionBackendType.LOCAL), plan, path)
    assert result.exit_code == 99
    metrics = LoadPilotService._summary_metrics(result.summary)
    assert metrics['loadpilot_transport_failed.rate'] == 1
    assert metrics['http_reqs.count'] < 100


async def test_autonomous_followup_is_bounded_to_one_child(tmp_path, checkout_openapi, monkeypatch):
    import re
    clock = [utcnow()]
    monkeypatch.setattr('loadpilot.service.utcnow', lambda: clock[0])
    monkeypatch.setattr('loadpilot.worker.time.time', lambda: clock[0].timestamp())

    class MeasuredBackend(SlowBackend):
        async def execute(self, run, plan, script):
            self.calls += 1
            clock[0] += timedelta(seconds=sum(s.duration_seconds for s in plan.stages) + 1)
            metrics = {'http_reqs': {'values': {'count': 100, 'rate': 10}}, 'http_req_duration': {'values': {'p(95)': 800}}, 'http_req_failed': {'values': {'rate': 0}}}
            for stage in plan.stages:
                prefix = 'loadpilot_stage_' + re.sub(r'[^a-zA-Z0-9]+', '_', stage.name)
                metrics[prefix + '_requests'] = {'values': {'count': 20}}
                metrics[prefix + '_duration'] = {'values': {'p(95)': 100 if stage.target_vus < 20 else 800}}
                metrics[prefix + '_failed'] = {'values': {'rate': 0}}
            return ExecutionResult(99, '', 'threshold crossed', {'metrics': metrics})

    backend = MeasuredBackend()
    service, _ = make_service(tmp_path, backend)
    run = await service.prepare(prompt='Stress checkout from 5 to 40 users for 20 seconds, p95 under 500 ms', source_type='openapi', source=checkout_openapi, application_name='test', auto_followup=True, auto_start=True)
    worker = asyncio.create_task(Worker(service).run())
    try:
        for _ in range(100):
            runs = service.store.list()
            if len(runs) == 2 and all(r.state == RunState.COMPLETED for r in runs):
                break
            await asyncio.sleep(.05)
        assert len(runs) == 2
        child = next(r for r in runs if r.parent_run_id == run.id)
        assert child.state == RunState.COMPLETED
        assert backend.calls == 2
        assert child.auto_followup is False
        assert max(s.target_vus for s in service.detail(child.id)['plan'].stages) == 23
        with pytest.raises(ValueError, match='one automatic'):
            service.rerun(child.id, followup=True)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


def test_sensitive_schema_examples_are_not_copied():
    schema = {'type': 'object', 'properties': {'password': {'type': 'string', 'default': 'real-secret-from-schema'}}, 'required': ['password']}
    assert all(value['password'] != 'real-secret-from-schema' for value in generate_samples(schema))
