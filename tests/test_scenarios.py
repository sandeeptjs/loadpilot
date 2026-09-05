import asyncio
import json
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from loadpilot.ai import JsonProvider
from loadpilot.api import create_app
from loadpilot.discovery import ManualAdapter, PostmanAdapter
from loadpilot.scenarios import validate_journeys
from loadpilot.settings import Settings
from sandbox_target.scenario_fixture import Target

SOURCE = [
    {'operation_id': 'form', 'method': 'POST', 'path': '/form', 'content_type': 'application/x-www-form-urlencoded'},
    {'operation_id': 'text', 'method': 'POST', 'path': '/text', 'content_type': 'text/plain'},
    {'operation_id': 'session', 'method': 'POST', 'path': '/sessions'},
    {'operation_id': 'ticket', 'method': 'POST', 'path': '/tickets'},
    {'operation_id': 'read', 'method': 'GET', 'path': '/tickets/{id}'},
    {'operation_id': 'search', 'method': 'GET', 'path': '/search', 'parameters': [{'name': 'q', 'location': 'query'}]},
    {'operation_id': 'query', 'method': 'POST', 'path': '/graphql'},
]
JOURNEYS = [
    {'name': 'support tickets', 'steps': [
        {'operation_id': 'session', 'extract': {'token': '/token'}},
        {'operation_id': 'ticket', 'headers': {'Authorization': 'Bearer ${token}'}, 'body': {'owner': {'name': 'Ada'}}, 'expected_statuses': [201], 'extract': {'id': '/ticket/id'}},
        {'operation_id': 'read', 'inputs': {'id': '${id}'}, 'assertions': [{'pointer': '/status', 'equals': 'open'}]},
    ]},
    {'name': 'catalog search', 'steps': [{'operation_id': 'search', 'inputs': {'q': 'books'}, 'repeat': 2, 'assertions': [{'pointer': '/results/0', 'equals': 'book'}]}]},
    {'name': 'graphql health', 'steps': [{'operation_id': 'query', 'body': {'query': 'query { health }'}, 'assertions': [{'pointer': '/data/health', 'equals': 'ok'}]}]},
]


def test_scenario_validation_rejects_unbound_values_and_invalid_status():
    application = ManualAdapter().adapt(SOURCE, name='fixture', base_url='http://localhost')
    with pytest.raises(ValueError, match='before extraction'):
        validate_journeys([{'name': 'bad', 'steps': [{'operation_id': 'read', 'inputs': {'id': '${missing}'}}]}], application)
    with pytest.raises(ValueError, match='status codes'):
        validate_journeys([{'name': 'bad', 'steps': [{'operation_id': 'read', 'expected_statuses': [999]}]}], application)


def test_postman_keeps_json_and_query():
    application = PostmanAdapter().adapt({'item': [{'name': 'create', 'request': {'method': 'POST', 'url': '{{baseUrl}}/tickets?q=books', 'body': {'mode': 'raw', 'raw': '{"owner":{"name":"Ada"}}'}}}]}, name='tickets', base_url='http://localhost')
    assert application.endpoints[0].examples == [{'owner': {'name': 'Ada'}}]
    assert application.endpoints[0].parameters[0].example == 'books'


async def test_provider_generates_validated_journey_in_one_bounded_call():
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload['max_tokens'] == 2500
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'test_type': 'BASELINE', 'journeys': [JOURNEYS[0]]})}}]})

    provider = JsonProvider(Settings(llm_model='test-model', llm_api_key='test-only'), httpx.MockTransport(respond))
    result = await provider.parse('Create a support ticket after login, then read its status', SOURCE)
    application = ManualAdapter().adapt(SOURCE, name='fixture', base_url='http://localhost')
    validated = validate_journeys(result.journeys, application)
    assert len(calls) == 1
    assert validated[0].steps[2].inputs == {'id': '${id}'}


async def test_public_api_real_k6_general_journeys(tmp_path):
    binary = shutil.which('k6') or next(iter(Path('.tools').glob('**/k6.exe')), None)
    if not binary:
        pytest.skip('Install k6 to run the public API acceptance test')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Target)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = Settings(db=str(tmp_path / 'runs.db'), generated_dir=str(tmp_path / 'scripts'), k6_bin=str(Path(binary).resolve()), llm_model='', llm_api_key='')
    app = create_app(cfg)
    try:
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            async def run(journeys):
                response = await client.post('/api/tests', json={'prompt': 'Baseline with 1 user for 5 seconds', 'source_type': 'graphql' if journeys[0]['name'] == 'graphql health' else 'manual', 'source': {'operations': [{'name': 'query', 'query': 'query { health }'}]} if journeys[0]['name'] == 'graphql health' else SOURCE, 'base_url': f'http://127.0.0.1:{server.server_port}', 'journeys': journeys, 'auto_start': True})
                assert response.status_code == 201, response.text
                identifier = response.json()['id']
                for _ in range(200):
                    detail = (await client.get(f'/api/runs/{identifier}')).json()
                    if detail['run']['state'] in {'COMPLETED', 'FAILED'}:
                        return detail
                    await asyncio.sleep(.1)
                pytest.fail('Run did not finish')

            for journey in [*JOURNEYS, {'name': 'encodings', 'steps': [{'operation_id': 'form', 'body': {'name': 'Ada Lovelace'}, 'assertions': [{'pointer': '/accepted', 'equals': True}]}, {'operation_id': 'text', 'body': 'hello'}]}]:
                result = await run([journey])
                assert result['run']['state'] == 'COMPLETED', result['run'].get('error')
                assert result['run']['metrics']['loadpilot_journey_failed.rate'] == 0
            # Every weighted journey must pass preflight even if random load selection misses one.
            result = await run(JOURNEYS)
            assert result['run']['state'] == 'COMPLETED', result['run'].get('error')
            before = Target.calls.count('/tickets/99')
            result = await run([{'name': 'invalid resource', 'steps': [{'operation_id': 'read', 'inputs': {'id': 99}}]}])
            assert result['run']['state'] == 'FAILED'
            assert 'Preflight failed' in result['run']['error']
            assert Target.calls.count('/tickets/99') - before == 1
    finally:
        server.shutdown()
        server.server_close()
