"""Natural-language scenario synthesis, live progress, and provider autonomy."""
import json

import httpx
import pytest

from loadpilot.ai import JsonProvider
from loadpilot.api import create_app
from loadpilot.discovery import ManualAdapter, OpenAPIAdapter
from loadpilot.execution import ExecutionBackend, ExecutionResult, LocalK6Backend
from loadpilot.lifecycle import RunStore
from loadpilot.models import ExecutionBackendType, RunState
from loadpilot.service import LoadPilotService
from loadpilot.settings import GEMINI_BASE_URL, OPENAI_BASE_URL, Settings
from loadpilot.synthesis import synthesize_scenario

SHOP = [
    {'operation_id': 'createSession', 'method': 'POST', 'path': '/sessions'},
    {'operation_id': 'listProducts', 'method': 'GET', 'path': '/products', 'summary': 'Product catalogue'},
    {'operation_id': 'createOrder', 'method': 'POST', 'path': '/orders'},
    {'operation_id': 'listOrders', 'method': 'GET', 'path': '/orders'},
    {'operation_id': 'deleteOrder', 'method': 'DELETE', 'path': '/orders/{order_id}'},
    {'operation_id': 'listUsers', 'method': 'GET', 'path': '/users'},
]


@pytest.fixture
def shop():
    return ManualAdapter().adapt(SHOP, name='shop', base_url='http://localhost')


@pytest.fixture
def checkout(checkout_openapi):
    return OpenAPIAdapter().adapt(checkout_openapi, name='checkout', base_url='http://localhost:8080')


SUMMARY = {'metrics': {'http_req_duration': {'values': {'p(95)': 211}}, 'http_req_failed': {'values': {'rate': 0}}, 'http_reqs': {'values': {'count': 480}}}}


class FakeK6Backend(ExecutionBackend):
    async def validate(self, script):
        assert script.exists()

    async def execute(self, run, plan, script):
        return ExecutionResult(0, '', '', SUMMARY)


class PreflightBackend(LocalK6Backend):
    """A target that answers a journey only once it is wired the way the application replies.

    Subclassing the local backend is what puts the preflight in the path at all; k6 itself never
    runs, so what is exercised is the service's choice of journey rather than a k6 invocation.
    """

    def __init__(self, reject):
        super().__init__()
        self.reject, self.attempts, self.executed = reject, [], None

    async def validate(self, script):
        assert script.exists()

    async def preflight(self, run, plan, script):
        self.attempts.append([step.extract for journey in plan.journeys for step in journey.steps])
        if self.reject(plan):
            raise ValueError(f'Preflight failed for journey {plan.journeys[0].name}: login: missing runtime input. Load was not started.')

    async def execute(self, run, plan, script):
        self.executed = plan.journeys
        return ExecutionResult(0, '', '', SUMMARY)


def service_with(tmp_path, settings, backend=None):
    return LoadPilotService(store=RunStore(tmp_path / 'runs.db'), generated_dir=tmp_path / 'generated', backends={ExecutionBackendType.LOCAL: backend or FakeK6Backend()}, settings=settings)


def guesses_a_token(plan):
    return any('/token' in step.extract.values() for journey in plan.journeys for step in journey.steps)


def test_a_described_sequence_becomes_a_dependency_wired_journey(checkout):
    result = synthesize_scenario('Log in, create a cart, then check out with 30 users for 90 seconds', checkout)
    assert result.operation_ids == ['login', 'createCart', 'checkout']
    assert result.unmatched == []
    steps = {step.operation_id: step for step in result.journeys[0].steps}
    assert steps['createCart'].extract == {'createCart_cart_id': '/cart_id'}
    assert steps['checkout'].inputs == {'cart_id': '${createCart_cart_id}'}
    # Every step must carry the evidence that selected it; the interface shows this.
    assert all(step['reasons'] for step in result.as_dict()['steps'])
    assert result.as_dict()['steps'][0]['confidence'] >= .9


def test_missing_prerequisites_are_inserted_and_explained(checkout):
    result = synthesize_scenario('stress the checkout endpoint at 200 vus', checkout)
    assert result.operation_ids == ['createCart', 'checkout']
    inserted = [step for step in result.as_dict()['steps'] if step['origin'] == 'dependency']
    assert [step['operation_id'] for step in inserted] == ['createCart']
    assert any('createCart' in note for note in result.notes)
    assert result.journeys[0].steps[-1].inputs == {'cart_id': '${createCart_cart_id}'}


def test_load_specification_never_outranks_an_operation_of_the_same_name(shop):
    assert synthesize_scenario('load test with 500 users hitting /users for 10 minutes', shop).operation_ids == ['listUsers']
    assert synthesize_scenario('spike the product catalogue to 300 users', shop).operation_ids == ['listProducts']
    # A prompt that is only a load specification names no step, and says so quietly.
    bare = synthesize_scenario('spike to 200 users for 3 minutes, p95 under 300 ms', shop)
    assert bare.operation_ids == []
    assert bare.unmatched == []
    assert bare.journeys is None


def test_synonyms_word_forms_and_verbs_reach_the_right_method(shop):
    assert synthesize_scenario('Browse the catalogue and then place an order', shop).operation_ids == ['listProducts', 'createOrder']
    assert synthesize_scenario('sign in then look at order history', shop).operation_ids == ['createSession', 'listOrders']
    assert synthesize_scenario('remove an order', shop).operation_ids == ['deleteOrder']
    reasons = ' '.join(reason for step in synthesize_scenario('remove an order', shop).as_dict()['steps'] for reason in step['reasons'])
    assert 'implies DELETE' in reasons


def test_an_unrelated_verb_cannot_invent_a_step(checkout):
    result = synthesize_scenario('update the thing', checkout)
    assert result.operation_ids == []
    assert result.unmatched == ['update the thing']
    assert result.journeys is None


def test_prose_that_frames_a_question_is_quiet_but_a_real_instruction_is_not(checkout):
    """Suppressing commentary must not suppress an instruction the API cannot answer:
    an imperative keeps its place in the report even when nothing matches it."""
    quiet = synthesize_scenario('We wanted to find out how the shop behaves. Log in, then check out.', checkout)
    assert quiet.operation_ids == ['login', 'createCart', 'checkout']
    assert quiet.unmatched == []
    loud = synthesize_scenario('I want you to delete the invoices, then log in', checkout)
    assert loud.operation_ids == ['login']
    assert loud.unmatched == ['I want you to delete the invoices']


async def test_preview_explains_the_reading_without_creating_a_run(tmp_path, checkout_openapi):
    app = create_app(Settings(db=str(tmp_path / 'db'), generated_dir=str(tmp_path / 'scripts'), embedded_worker=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/scenario/preview', json={'prompt': 'Log in, create a cart, then check out with 30 users for 90 seconds', 'source_type': 'openapi', 'source': checkout_openapi, 'application_name': 'checkout'})
        assert response.status_code == 200, response.text
        body = response.json()
        assert [step['operation_id'] for step in body['scenario']['steps']] == ['login', 'createCart', 'checkout']
        assert body['intent']['target_concurrency'] == 30
        assert body['intent']['duration_seconds'] == 90
        assert body['plan']['planned_seconds'] == 90
        assert body['plan']['peak_vus'] == 30
        assert [journey_step['operation_id'] for journey_step in body['plan']['journeys'][0]['steps']] == ['login', 'createCart', 'checkout']
        assert body['plan']['stages'][0]['offset_seconds'] == 0
        assert body['provider'] == {'enabled': False, 'model': None}
        assert body['planning_error'] is None
        assert (await client.get('/api/runs')).json() == []


async def test_preview_reports_why_it_cannot_plan_instead_of_failing(tmp_path, checkout_openapi):
    app = create_app(Settings(db=str(tmp_path / 'db'), generated_dir=str(tmp_path / 'scripts'), embedded_worker=False, max_vus=10))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/scenario/preview', json={'prompt': 'Stress checkout with 900 users for 2 minutes', 'source_type': 'openapi', 'source': checkout_openapi, 'application_name': 'checkout'})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['plan'] is None
        assert 'VU limit' in body['planning_error']
        assert [step['operation_id'] for step in body['scenario']['steps']] == ['createCart', 'checkout']


async def test_progress_tracks_lifecycle_phases_and_the_load_profile(tmp_path, checkout_openapi):
    service = service_with(tmp_path, Settings(db=str(tmp_path / 'runs.db'), max_vus=2000))
    run = await service.prepare(prompt='Log in, create a cart, then check out with 5 users for 20 seconds', source_type='openapi', source=checkout_openapi, application_name='checkout')
    waiting = service.detail(run.id)['progress']
    assert waiting['phase'] == 'VALIDATING'
    assert waiting['terminal'] is False
    assert waiting['fraction'] == 0
    assert [phase['label'] for phase in waiting['phases']][:2] == ['Accepted', 'Reading the API']
    assert 'SCHEDULED' not in [phase['state'] for phase in waiting['phases']]
    assert waiting['planned_seconds'] == 20
    assert sum(stage['duration_seconds'] for stage in waiting['stages']) == 20
    assert waiting['stages'][0]['offset_seconds'] == 0
    assert next(phase for phase in waiting['phases'] if phase['active'])['state'] == 'VALIDATING'

    completed = await service.start(run.id)
    assert completed.state == RunState.COMPLETED
    progress = service.detail(run.id)['progress']
    assert progress['phase_label'] == 'Complete'
    assert progress['terminal'] is True
    assert progress['fraction'] == 1
    assert all(phase['reached'] for phase in progress['phases'])
    assert progress['elapsed_seconds'] <= progress['planned_seconds']
    reading = service.detail(run.id)['scenario']
    assert [step['operation_id'] for step in reading['steps']] == ['login', 'createCart', 'checkout']
    assert reading['source'] == 'synthesis'


def scripted(service, handler):
    """Point the service's bounded JSON client at a scripted provider."""
    service.ai = JsonProvider(service.settings, httpx.MockTransport(handler))
    return service


def answers(fields):
    """One provider reply, shaped the way an OpenAI-compatible endpoint shapes it."""
    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(fields)}}]})


def gemini_settings(tmp_path, **overrides):
    return Settings(db=str(tmp_path / 'runs.db'), max_vus=2000, llm_model='gemini-2.5-flash', llm_api_key='test-only', **overrides)


CHECKOUT_PROMPT = 'Log in, create a cart, then check out with 5 users for 20 seconds, p95 under 300 ms'


async def test_the_model_sharpens_the_reading_without_taking_over_the_run(tmp_path, checkout_openapi):
    calls = []

    def respond(request):
        assert str(request.url) == GEMINI_BASE_URL + '/chat/completions'
        assert request.headers['Authorization'] == 'Bearer test-only'
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload['model'] == 'gemini-2.5-flash'
        assert 'tools' not in payload
        if 'evidence_ids' in payload['messages'][0]['content']:
            # The same bounded client narrates the finished run, citing measured evidence.
            evidence = json.loads(payload['messages'][1]['content'])
            return answers({'summary': 'Latency stayed inside the stated objective throughout.', 'evidence_ids': sorted(evidence)[:1], 'limitations': []})
        assert 'createCart' in payload['messages'][1]['content']
        # A terse answer: the model names the shape of the load and stays silent elsewhere.
        return answers({'test_type': 'STRESS'})

    service = scripted(service_with(tmp_path, gemini_settings(tmp_path)), respond)
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    detail = service.detail(run.id)
    assert len(calls) == 1
    assert detail['run'].ai_mode == 'provider'
    assert detail['intent'].test_type.value == 'STRESS'
    # Silence from the model must not erase a threshold the prompt already stated.
    assert detail['intent'].slos.latency_p95_ms == 300
    assert detail['intent'].target_endpoints == ['login', 'createCart', 'checkout']
    assert detail['scenario']['source'] == 'provider'
    assert detail['scenario']['journey_source'] == 'synthesis'
    assert (await service.start(run.id)).state == RunState.COMPLETED
    # Two bounded calls per run — read the requirement, narrate the result. Nothing else.
    assert len(calls) == 2
    assert service.detail(run.id)['investigation'].ai_summary.startswith('Latency stayed')


@pytest.mark.parametrize('failure', ['transport', 'quota', 'malformed'])
async def test_a_provider_outage_cannot_fail_a_run_the_offline_path_could_execute(tmp_path, checkout_openapi, failure, monkeypatch):
    monkeypatch.setattr('loadpilot.ai.RETRY_BACKOFF_SECONDS', 0)

    def respond(request):
        if failure == 'transport':
            raise httpx.ConnectError('connection refused', request=request)
        if failure == 'quota':
            return httpx.Response(429, json={'error': {'message': 'quota exhausted'}})
        return httpx.Response(200, json={'choices': [{'message': {'content': 'not json'}}]})

    service = scripted(service_with(tmp_path, gemini_settings(tmp_path)), respond)
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    detail = service.detail(run.id)
    assert detail['run'].ai_mode == 'offline'
    assert detail['scenario']['source'] == 'synthesis'
    assert detail['scenario']['provider_error']
    assert 'Model provider was unavailable; used the deterministic reading' in detail['intent'].ambiguities
    assert [step.operation_id for step in detail['plan'].journeys[0].steps] == ['login', 'createCart', 'checkout']
    assert detail['intent'].slos.latency_p95_ms == 300
    assert (await service.start(run.id)).state == RunState.COMPLETED


async def test_a_transient_refusal_is_retried_before_the_reading_degrades(tmp_path, checkout_openapi, monkeypatch):
    """A free-tier model answers 503 under load and spends its token budget thinking. Neither
    says anything about the requirement, so the reading is worth asking for again."""
    monkeypatch.setattr('loadpilot.ai.RETRY_BACKOFF_SECONDS', 0)
    attempts = []

    def respond(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503, json={'error': {'message': 'model is overloaded'}})
        if len(attempts) == 2:
            return httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': '{"test_type": "SPI'}}]})
        return answers({'test_type': 'SPIKE'})

    service = scripted(service_with(tmp_path, gemini_settings(tmp_path, llm_retries=2)), respond)
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    detail = service.detail(run.id)
    assert len(attempts) == 3
    assert detail['run'].ai_mode == 'provider'
    assert detail['intent'].test_type.value == 'SPIKE'
    assert detail['scenario'].get('provider_error') is None


async def test_a_reading_the_schema_rejects_is_not_asked_for_twice(tmp_path, checkout_openapi):
    """Retrying a refusal is patience; retrying a wrong answer is hope. A reply that breaks
    the schema is the model's considered answer, so the run degrades on the first one."""
    attempts = []

    def respond(request):
        attempts.append(request)
        return answers({'test_type': 'LOAD', 'target_concurrency': -5})

    service = scripted(service_with(tmp_path, gemini_settings(tmp_path, llm_retries=3)), respond)
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    detail = service.detail(run.id)
    assert len(attempts) == 1
    assert detail['run'].ai_mode == 'offline'
    assert 'invalid structured output' in detail['scenario']['provider_error']
    assert detail['intent'].target_concurrency == 5


async def test_business_inputs_the_model_asks_for_are_generated_not_refused(tmp_path, checkout_openapi):
    service = scripted(service_with(tmp_path, gemini_settings(tmp_path)), lambda request: answers({'test_type': 'LOAD', 'required_inputs': ['email', 'password', 'card_number']}))
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    detail = service.detail(run.id)
    assert detail['scenario']['generated_inputs'] == ['email', 'password', 'card_number']
    assert any('Generated values from the request schema' in note for note in detail['intent'].ambiguities)
    assert (await service.start(run.id)).state == RunState.COMPLETED


async def test_a_journey_the_model_invents_falls_back_to_the_synthesized_one(tmp_path, checkout_openapi):
    invented = {'name': 'invented', 'steps': [{'operation_id': 'chargeCreditCard'}]}
    service = scripted(service_with(tmp_path, gemini_settings(tmp_path)), lambda request: answers({'test_type': 'LOAD', 'journeys': [invented]}))
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    detail = service.detail(run.id)
    assert 'chargeCreditCard' in detail['scenario']['journey_error']
    assert detail['scenario']['journey_source'] == 'synthesis'
    assert [step.operation_id for step in detail['plan'].journeys[0].steps] == ['login', 'createCart', 'checkout']
    assert (await service.start(run.id)).state == RunState.COMPLETED


async def test_a_model_journey_that_validates_is_executed_as_written(tmp_path, checkout_openapi):
    wired = {'name': 'model wiring', 'steps': [
        {'operation_id': 'createCart', 'body': {'quantity': 2}, 'extract': {'cart': '/cart_id'}},
        {'operation_id': 'checkout', 'inputs': {'cart_id': '${cart}'}},
    ]}
    service = scripted(service_with(tmp_path, gemini_settings(tmp_path)), lambda request: answers({'test_type': 'LOAD', 'journeys': [wired]}))
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    detail = service.detail(run.id)
    assert detail['scenario']['journey_source'] == 'provider'
    assert 'journey_error' not in detail['scenario']
    journey = detail['plan'].journeys[0]
    assert [step.operation_id for step in journey.steps] == ['createCart', 'checkout']
    assert journey.steps[0].body == {'quantity': 2}
    assert journey.steps[1].inputs == {'cart_id': '${cart}'}
    assert (await service.start(run.id)).state == RunState.COMPLETED


# The shape a real Gemini reply takes: the workflow is right, but every business field is
# written as a variable even though only the cart id is genuinely carried between steps.
LIVE_JOURNEY = {'name': 'checkout flow', 'steps': [
    {'operation_id': 'login', 'body': {'email': '${email}', 'password': '${password}'}},
    {'operation_id': 'createCart', 'body': {'quantity': '${quantity}'}, 'extract': {'cart_id': '/cart_id'}},
    {'operation_id': 'checkout', 'inputs': {'cart_id': '${cart_id}'}},
]}


async def test_the_workflow_a_live_model_writes_survives_its_own_variable_habit(tmp_path, checkout_openapi):
    service = scripted(service_with(tmp_path, gemini_settings(tmp_path)), lambda request: answers({'test_type': 'LOAD', 'journeys': [LIVE_JOURNEY]}))
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    detail = service.detail(run.id)
    assert detail['scenario']['journey_source'] == 'provider'
    assert 'journey_error' not in detail['scenario']
    # Bodies written in unavailable variables are regenerated from their schemas, and the
    # repair is reported rather than left as a silent difference from what the model wrote.
    assert detail['scenario']['journey_repairs'] == ['login.body.email', 'login.body.password', 'login.body', 'createCart.body.quantity', 'createCart.body']
    journey = detail['plan'].journeys[0]
    assert [step.operation_id for step in journey.steps] == ['login', 'createCart', 'checkout']
    assert [step.body for step in journey.steps] == [None, None, None]
    # The one handoff the model got right is exactly what it must not lose.
    assert journey.steps[1].extract == {'cart_id': '/cart_id'}
    assert journey.steps[2].inputs == {'cart_id': '${cart_id}'}
    assert (await service.start(run.id)).state == RunState.COMPLETED


async def test_a_fixed_value_beside_a_stray_variable_is_kept(tmp_path, checkout_openapi):
    partial = {'name': 'coupon', 'steps': [
        {'operation_id': 'createCart', 'body': {'quantity': 3, 'coupon': '${coupon}'}, 'extract': {'cart_id': '/cart_id'}},
        {'operation_id': 'checkout', 'inputs': {'cart_id': '${cart_id}'}},
    ]}
    service = scripted(service_with(tmp_path, gemini_settings(tmp_path)), lambda request: answers({'test_type': 'LOAD', 'journeys': [partial]}))
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    detail = service.detail(run.id)
    assert detail['scenario']['journey_repairs'] == ['createCart.body.coupon']
    # What remains still satisfies the schema, so the quantity the requirement named stands.
    assert detail['plan'].journeys[0].steps[0].body == {'quantity': 3}
    assert (await service.start(run.id)).state == RunState.COMPLETED


async def test_a_path_variable_nothing_produces_is_refused_not_papered_over(tmp_path, checkout_openapi):
    invented = {'name': 'no producer', 'steps': [{'operation_id': 'checkout', 'inputs': {'cart_id': '${order_id}'}}]}
    service = scripted(service_with(tmp_path, gemini_settings(tmp_path)), lambda request: answers({'test_type': 'LOAD', 'journeys': [invented]}))
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    reading = service.detail(run.id)['scenario']
    # Dropping a path binding would build a URL with a hole in it, so the gate must still
    # reject the journey and the synthesized workflow must still run.
    assert 'order_id' in reading['journey_error']
    assert reading['journey_source'] == 'synthesis'
    assert [step.operation_id for step in service.detail(run.id)['plan'].journeys[0].steps] == ['login', 'createCart', 'checkout']
    assert (await service.start(run.id)).state == RunState.COMPLETED


# A login whose contract says where the token sits, exactly as the sandbox documents it.
def documented_login(spec):
    spec = json.loads(json.dumps(spec))
    spec['paths']['/login']['post']['responses']['200'] = {'description': 'token', 'content': {'application/json': {'schema': {'type': 'object', 'properties': {'access_token': {'type': 'string'}}}}}, 'links': {'authorize': {'operationId': 'createCart', 'parameters': {'Authorization': '$response.body#/access_token'}}}}
    return spec


GUESSED_HANDOFFS = {'name': 'guessed handoffs', 'steps': [
    {'operation_id': 'login', 'extract': {'token': '/token'}},
    {'operation_id': 'createCart', 'body': {'quantity': 2}, 'headers': {'authorization': 'Bearer ${token}'}, 'extract': {'cart_id': '/id'}},
    {'operation_id': 'checkout', 'inputs': {'cart_id': '${cart_id}'}, 'headers': {'authorization': 'Bearer ${token}'}},
]}


async def test_a_pointer_the_contract_contradicts_is_corrected_not_run_as_written(tmp_path, checkout_openapi):
    """The workflow is right and the wiring is a guess. A login that answers with access_token
    does not stop being the step that produces the token because the model wrote /token, so the
    documented pointer wins and the correction is reported rather than executed silently."""
    service = scripted(service_with(tmp_path, gemini_settings(tmp_path)), lambda request: answers({'test_type': 'LOAD', 'journeys': [GUESSED_HANDOFFS]}))
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=documented_login(checkout_openapi), application_name='checkout')
    detail = service.detail(run.id)
    assert detail['scenario']['journey_source'] == 'provider'
    assert detail['scenario']['journey_repairs'] == ['login.extract.token', 'createCart.extract.cart_id']
    steps = detail['plan'].journeys[0].steps
    assert [step.extract for step in steps] == [{'token': '/access_token'}, {'cart_id': '/cart_id'}, {}]
    # The names the model chose are what its own later steps read, so those must not move.
    assert steps[2].inputs == {'cart_id': '${cart_id}'}
    assert (await service.start(run.id)).state == RunState.COMPLETED


async def test_a_handoff_nothing_can_settle_is_withdrawn_rather_than_guessed(tmp_path, checkout_openapi):
    """Two guessed pointers on a response that documents one value: nothing can say which value
    was meant. Rewriting either would be invention, and clearing the credential that reads it
    would send the next request unauthenticated, so the journey is refused and synthesis runs."""
    ambiguous = {'name': 'ambiguous', 'steps': [
        {'operation_id': 'login', 'extract': {'token': '/token', 'user': '/user/id'}},
        {'operation_id': 'createCart', 'body': {'quantity': 2}, 'headers': {'authorization': 'Bearer ${token}'}},
    ]}
    service = scripted(service_with(tmp_path, gemini_settings(tmp_path)), lambda request: answers({'test_type': 'LOAD', 'journeys': [ambiguous]}))
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=documented_login(checkout_openapi), application_name='checkout')
    detail = service.detail(run.id)
    assert 'token' in detail['scenario']['journey_error']
    assert detail['scenario']['journey_source'] == 'synthesis'
    assert [step.operation_id for step in detail['plan'].journeys[0].steps] == ['login', 'createCart', 'checkout']
    assert (await service.start(run.id)).state == RunState.COMPLETED


async def test_a_model_workflow_that_fails_preflight_does_not_fail_the_run(tmp_path, checkout_openapi):
    """An undocumented response is the one case nothing static can settle: the model's pointer is
    a guess, and only the target can answer it. When the answer is no, the run must still be the
    run the requirement asked for, so the journey planned beside it executes instead."""
    backend = PreflightBackend(guesses_a_token)
    service = scripted(service_with(tmp_path, gemini_settings(tmp_path), backend), lambda request: answers({'test_type': 'LOAD', 'journeys': [GUESSED_HANDOFFS]}))
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    assert service.detail(run.id)['scenario']['journey_source'] == 'provider'
    assert (await service.start(run.id)).state == RunState.COMPLETED
    # Two preflights: the model's wiring, then the deterministic wiring that replaced it. The
    # cart pointer was already corrected from the contract; only the undocumented login reached
    # the target as the model wrote it, which is precisely what execution had to settle.
    assert backend.attempts == [[{'token': '/token'}, {'cart_id': '/cart_id'}, {}], [{}, {'createCart_cart_id': '/cart_id'}, {}]]
    assert [step.extract for journey in backend.executed for step in journey.steps] == [{}, {'createCart_cart_id': '/cart_id'}, {}]
    reading = service.detail(run.id)['scenario']
    assert reading['journey_source'] == 'synthesis'
    assert 'missing runtime input' in reading['journey_preflight_error']
    # What was attempted stays inspectable beside what ran, and the exchange is auditable.
    assert {artifact.kind for artifact in service.store.get(run.id).artifacts} == {'k6-script', 'k6-script-provider'}
    assert any(event.action == 'scenario.preflight.degraded' for event in service.store.audit())


async def test_a_preflight_failure_with_no_alternative_still_fails_the_run(tmp_path, checkout_openapi):
    """The fallback is a second answer to one question, not a licence to keep asking. A journey
    the deterministic reader wrote itself has nothing behind it, so its refusal stands."""
    backend = PreflightBackend(lambda plan: True)
    service = service_with(tmp_path, Settings(db=str(tmp_path / 'runs.db'), max_vus=2000), backend)
    run = await service.prepare(prompt=CHECKOUT_PROMPT, source_type='openapi', source=checkout_openapi, application_name='checkout')
    assert not service.detail(run.id)['plan'].fallback_journeys
    result = await service.start(run.id)
    assert result.state == RunState.FAILED
    assert 'Preflight failed' in result.error
    assert len(backend.attempts) == 1


def routed(**fields):
    """Settings as a fresh checkout sees them, ignoring any developer .env on this machine."""
    return Settings(_env_file=None, **fields)


def test_naming_the_model_is_the_whole_configuration(monkeypatch):
    monkeypatch.setenv('GOOGLE_API_KEY', 'ambient-google')
    gemini = routed(llm_model='gemini-2.5-flash')
    assert gemini.is_gemini
    assert gemini.llm_base_url == GEMINI_BASE_URL
    assert gemini.ai_enabled
    assert gemini.llm_api_key == 'ambient-google'
    monkeypatch.setenv('GEMINI_API_KEY', 'ambient-gemini')
    assert routed(llm_model='models/gemini-2.5-pro').llm_api_key == 'ambient-gemini'
    assert routed(llm_model='learnlm-2.0-flash-experimental').llm_base_url == GEMINI_BASE_URL
    # A Google key must never be spent on an OpenAI endpoint, or the reverse.
    assert routed(llm_model='gpt-4o-mini').ai_enabled is False
    monkeypatch.setenv('OPENAI_API_KEY', 'ambient-openai')
    openai = routed(llm_model='gpt-4o-mini')
    assert (openai.llm_base_url, openai.llm_api_key) == (OPENAI_BASE_URL, 'ambient-openai')
    assert routed(llm_model='gemini-2.5-flash').llm_api_key == 'ambient-gemini'
    # An explicit endpoint wins, so a gateway or a recorded proxy stays addressable.
    assert routed(llm_model='gemini-2.5-flash', llm_base_url='http://127.0.0.1:1234/v1').llm_base_url == 'http://127.0.0.1:1234/v1'
    # Naming no model means no calls, whatever keys the environment happens to carry.
    assert routed(llm_model='').ai_enabled is False
    assert routed(llm_api_key='explicit-only').ai_enabled is False


# Phrasings a person would actually type, and the operations each one has to reach.
PHRASINGS = [
    ('Log in, create a cart, then check out with 30 users for 90 seconds', ['login', 'createCart', 'checkout']),
    ('sign in and check out at 50 users', ['login', 'createCart', 'checkout']),
    ('simulate 25 shoppers signing in and checking out for 2 minutes', ['login', 'createCart', 'checkout']),
    ('p95 under 250 ms while 40 users log in and check out', ['login', 'createCart', 'checkout']),
    ('keep error rate below 1% while 20 users log in and check out', ['login', 'createCart', 'checkout']),
    ('latency should stay under 400ms as 60 users log in then check out', ['login', 'createCart', 'checkout']),
    ('authenticate then purchase, 10 users, 30s', ['login', 'createCart', 'checkout']),
    ('what happens when 100 people try to buy at once', ['createCart', 'checkout']),
    ('I want to know if checkout survives Black Friday traffic', ['createCart', 'checkout']),
    ('soak the checkout flow for 10 minutes at 15 users', ['createCart', 'checkout']),
    ('breakpoint test: ramp to 300 concurrent users on checkout', ['createCart', 'checkout']),
    ('hammer the cart creation endpoint with 200 vus', ['createCart']),
    ('ramp from 10 to 200 users creating carts over five minutes', ['createCart']),
    ('test the login endpoint', ['login']),
    # Free prose: framing sentences, spelled numbers, particle verbs split by their object,
    # and objectives written in the middle of the workflow.
    ('We need to know whether the storefront survives a busy sale hour: sign a shopper in, let them build a basket, then push the order through payments with 12 shoppers at once for 30 seconds. I want the 95th percentile response under 900 ms and fewer than 2% failures.',
     ['login', 'createCart', 'checkout']),
    ('Simulate a flash sale: two hundred fifty shoppers add to basket and check the order out over half an hour, failure rate must stay below 1%',
     ['createCart', 'checkout']),
    ('Does the cart hold up? twenty five testers, 1 minute, sub-300ms p95, fewer than 2 percent errors', ['createCart']),
    ('Hammer the login endpoint with 30 concurrent sessions for two minutes and tell me if p95 exceeds 400 ms', ['login']),
    ('I want to see if 40 customers can log in and place an order without the 95th percentile going past 800ms',
     ['login', 'createCart', 'checkout']),
    ('a hundred sessions overnight; failure rate must not exceed 0.5% - sign in, then pay', ['login', 'createCart', 'checkout']),
    ('between 50 and 300 shoppers logging in, nothing slower than 1200ms at the 95th percentile', ['login']),
    ('can the basket survive a couple of dozen buyers checking out for half a minute', ['createCart', 'checkout']),
]


@pytest.mark.parametrize(('phrasing', 'expected'), PHRASINGS)
def test_a_requirement_written_any_way_reaches_the_same_operations(checkout, phrasing, expected):
    """An objective stated before the workflow, a continuous verb, a synonym or no
    numbers at all: the reading is the same, and nothing is reported as unrecognized."""
    result = synthesize_scenario(phrasing, checkout)
    assert result.operation_ids == expected
    assert result.unmatched == []
    assert [step.operation_id for step in result.journeys[0].steps] == expected


def test_reading_a_requirement_is_fast_enough_to_do_while_typing(checkout):
    """The composer reads on input, so the deterministic pass has to stay imperceptible."""
    import time

    start = time.perf_counter()
    for _ in range(20):
        for phrasing, _expected in PHRASINGS:
            synthesize_scenario(phrasing, checkout)
    per_reading = (time.perf_counter() - start) / (20 * len(PHRASINGS))
    assert per_reading < .02, f'{per_reading * 1000:.1f} ms per reading'
