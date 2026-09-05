import asyncio
import json
import shutil
import threading
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from loadpilot.api import create_app
from loadpilot.execution import LocalK6Backend
from loadpilot.lifecycle import RunStore
from loadpilot.models import ExecutionBackendType, RunState
from loadpilot.models import TestRun as Run
from loadpilot.service import LoadPilotService
from loadpilot.settings import Settings
from loadpilot.worker import Worker
from sandbox_target.scenario_fixture import WorkflowTarget


def test_updates_preserve_other_process_fields(tmp_path, monkeypatch):
    first, second = RunStore(tmp_path / 'db'), RunStore(tmp_path / 'db')
    run = first.create(Run(plan_id=uuid4(), execution_backend=ExecutionBackendType.LOCAL))
    second.update(run.id, warnings=['set by another process'])
    monkeypatch.setattr(first, 'get', lambda _: run)
    first.update(run.id, metrics={'requests': 12})
    assert second.get(run.id).warnings == ['set by another process']
    assert second.get(run.id).metrics == {'requests': 12}


async def test_missing_execution_plan_becomes_terminal(tmp_path):
    store = RunStore(tmp_path / 'db')
    run = store.create(Run(plan_id=uuid4(), execution_backend=ExecutionBackendType.LOCAL))
    result = await LoadPilotService(store, tmp_path / 'scripts').start(run.id)
    assert result.state == RunState.FAILED


def test_missing_or_reset_counter_baselines_do_not_invent_deltas():
    after = {'sandbox_db_pool_saturation_events_total': 99, 'sandbox_db_pool_wait_seconds_sum': 100, 'sandbox_db_pool_wait_seconds_count': 20}
    assert LoadPilotService._target_metric_deltas({}, after) == {}
    assert LoadPilotService._target_metric_deltas(after, {**after, 'sandbox_db_pool_saturation_events_total': 0}) == {}


async def test_stale_preflight_uses_claim_time_not_creation_time(tmp_path):
    from loadpilot.models import utcnow
    store = RunStore(tmp_path / 'db')
    service = LoadPilotService(store, tmp_path / 'scripts', settings=Settings(llm_model='', llm_api_key=''))
    run = await service.prepare(prompt='Baseline with 1 user for 5 seconds', source_type='manual', source=[{'method': 'GET', 'path': '/'}], application_name='test', base_url='http://localhost')
    now = utcnow()
    store.update(run.id, created_at=now - timedelta(days=2))
    store.enqueue(run.id, now.timestamp())
    assert store.claim('lost-worker', now.timestamp()) == str(run.id)
    store.heartbeat(run.id, 'lost-worker', now.timestamp() - 40)
    task = asyncio.create_task(Worker(service).run())
    await asyncio.sleep(.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert store.get(run.id).state == RunState.VALIDATING
    assert store.claim('new-worker', now.timestamp()) is None


def test_backup_verifies_referenced_scripts(tmp_path):
    import hashlib

    from loadpilot.models import RunArtifact
    from scripts.backup_local import backup

    store = RunStore(tmp_path / 'source.db')
    generated = tmp_path / 'scripts'
    generated.mkdir()
    script = generated / 'sample.js'
    script.write_text('export default function() {}')
    digest = hashlib.sha256(script.read_bytes()).hexdigest()
    store.create(Run(plan_id=uuid4(), execution_backend=ExecutionBackendType.LOCAL, artifacts=[RunArtifact(kind='k6-script', uri=str(script), sha256=digest)]))
    manifest = backup(Path(store.path), generated, tmp_path / 'backup')
    assert manifest == {'sample.js': digest}
    assert (tmp_path / 'backup/scripts/sample.js').read_bytes() == script.read_bytes()


async def test_final_summary_survives_monitor_failure(tmp_path):
    from loadpilot.discovery import ManualAdapter
    from loadpilot.intent import DeterministicIntentCompiler
    from loadpilot.planner import TestPlanner

    class Backend(LocalK6Backend):
        async def _run(self, *args, **kwargs):
            Path(kwargs['env']['LOADPILOT_SUMMARY_PATH']).write_text(json.dumps({'metrics': {'http_reqs': {'values': {'count': 10}}}}))
            return 0, '', ''

        async def _monitor(self, *args):
            raise ValueError('bad sample')

    application = ManualAdapter().adapt([{'method': 'GET', 'path': '/'}], name='test', base_url='http://localhost')
    plan = TestPlanner().plan(DeterministicIntentCompiler().compile('baseline'), application)
    result = await Backend().execute(Run(plan_id=plan.id, execution_backend=ExecutionBackendType.LOCAL), plan, tmp_path / 'test.js')
    assert result.summary['metrics']['http_reqs']['values']['count'] == 10
    assert 'final summary remains authoritative' in result.stderr


async def test_optional_api_auth(tmp_path):
    app = create_app(Settings(db=str(tmp_path / 'db'), generated_dir=str(tmp_path), embedded_worker=False, api_token='test-only'))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/health')).status_code == 200
        assert (await client.get('/api/runs')).status_code == 401
        assert (await client.get('/api/runs', headers={'Authorization': 'Bearer test-only'})).status_code == 200


async def test_raw_metrics_budget_stops_process(tmp_path):
    from loadpilot.execution import OutputBudgetExceeded
    backend = LocalK6Backend(max_output_bytes=10)
    stopped = []
    backend.cancel = lambda run_id: stopped.append(run_id)
    path = tmp_path / 'points.json'
    path.write_bytes(b'x' * 11)
    with pytest.raises(OutputBudgetExceeded):
        await backend._monitor('bounded-run', path, asyncio.Event())
    assert stopped == ['bounded-run']


async def test_saved_workflow_execution_diagnostics_and_recovery(tmp_path, monkeypatch):
    binary = shutil.which('k6') or next(iter(Path('.tools').glob('**/k6.exe')), None)
    if not binary:
        pytest.skip('Install k6 for workflow acceptance')
    monkeypatch.setenv('TARGET_USER', 'user')
    monkeypatch.setenv('TARGET_PASSWORD', 'test-only')
    server = ThreadingHTTPServer(('127.0.0.1', 0), WorkflowTarget)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cfg = Settings(db=str(tmp_path / 'db'), generated_dir=str(tmp_path / 'scripts'), k6_bin=str(Path(binary).resolve()), llm_model='', llm_api_key='')
    app = create_app(cfg)
    source = [{'operation_id': name, 'method': 'GET', 'path': '/' + name} for name in ['basic', 'ready', 'temporary', 'never']]
    source += [{'operation_id': 'token', 'method': 'POST', 'path': '/token', 'content_type': 'application/x-www-form-urlencoded'}, {'operation_id': 'protected', 'method': 'GET', 'path': '/protected'}, {'operation_id': 'filter', 'method': 'GET', 'path': '/filter', 'parameters': [{'name': 'tag', 'location': 'query'}, {'name': 'filter', 'location': 'query', 'style': 'deepObject'}]}]
    source.append({'operation_id': 'upload', 'method': 'POST', 'path': '/upload', 'content_type': 'multipart/form-data'})
    source.append({'operation_id': 'search', 'method': 'GET', 'path': '/search', 'parameters': [{'name': 'q', 'location': 'query'}], 'base_url': f'http://localhost:{server.server_port}'})
    journey = {'name': 'authenticated workflow', 'datasets': {'term': ['books']}, 'steps': [
        {'operation_id': 'basic', 'basic_auth': {'username': 'env:TARGET_USER', 'password': 'env:TARGET_PASSWORD'}, 'extract': {'enabled': '/enabled'}},
        {'operation_id': 'token', 'body': {'grant_type': 'client_credentials', 'client_id': 'env:TARGET_USER', 'client_secret': 'env:TARGET_PASSWORD'}, 'extract': {'access': '/access_token'}},
        {'operation_id': 'protected', 'headers': {'Authorization': 'Bearer ${access}'}, 'assertions': [{'pointer': '/accepted', 'equals': True}]},
        {'operation_id': 'filter', 'inputs': {'tag': ['one', 'two'], 'filter': {'state': 'open'}}},
        {'operation_id': 'never', 'when': {'variable': 'enabled', 'equals': False}},
        {'operation_id': 'ready', 'when': {'variable': 'enabled', 'equals': True}, 'until': {'pointer': '/ready', 'equals': True}, 'repeat': 3, 'poll_interval_seconds': .1},
        {'operation_id': 'temporary', 'retries': 1},
        {'operation_id': 'upload', 'files': {'file': {'filename': 'sample.txt', 'content': 'hello upload', 'content_type': 'text/plain'}}, 'assertions': [{'pointer': '/uploaded', 'equals': True}]},
        {'operation_id': 'search', 'inputs': {'q': '${term}'}, 'assertions': [{'pointer': '/results/0', 'equals': 'book'}]},
    ]}
    request = {'prompt': 'Baseline with 1 user for 5 seconds', 'source_type': 'manual', 'source': source, 'base_url': f'http://127.0.0.1:{server.server_port}', 'journeys': [journey]}
    try:
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            async def finish(identifier):
                for _ in range(250):
                    result = (await client.get(f'/api/runs/{identifier}')).json()['run']
                    if result['state'] in {'COMPLETED', 'FAILED'}:
                        return result
                    await asyncio.sleep(.1)
                pytest.fail('Workflow did not terminate')

            saved = await client.post('/api/definitions', json={'name': 'nightly workflow', 'request': request})
            assert saved.status_code == 201, saved.text
            definition_id = saved.json()['id']
            assert (await client.get(f'/api/definitions/{definition_id}')).json()['request']['auto_start'] is False
            launched = await client.post(f'/api/definitions/{definition_id}/run', json={})
            assert launched.status_code == 202, launched.text
            result = await finish(launched.json()['id'])
            assert result['state'] == 'COMPLETED', result['error']
            assert result['metrics']['loadpilot_journey_failed.rate'] == 0
            assert '/never' not in WorkflowTarget.calls
            bad = {'name': 'bad input', 'steps': [{'operation_id': 'search', 'inputs': {'q': 'missing'}}]}
            failed = await client.post('/api/tests', json={**request, 'journeys': [bad], 'auto_start': True})
            failure = await finish(failed.json()['id'])
            assert failure['state'] == 'FAILED'
            diagnostic = (await client.get(f"/api/runs/{failure['id']}/diagnostics")).json()
            assert diagnostic['preflights'][0]['checks']['checks']
            assert 'HTTP 404' in diagnostic['error']
            recovered = await client.post(f"/api/runs/{failure['id']}/recover", json={'journeys': [journey]})
            assert recovered.status_code == 202, recovered.text
            recovery = await finish(recovered.json()['id'])
            assert recovery['state'] == 'COMPLETED', recovery['error']
            assert recovery['parent_run_id'] == failure['id']
            assert (await client.get(f"/api/runs/{failure['id']}")).json()['run']['state'] == 'FAILED'
        reopened = create_app(cfg)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=reopened), base_url='http://test') as client:
            assert (await client.get(f'/api/definitions/{definition_id}')).status_code == 200
    finally:
        server.shutdown()
        server.server_close()
