from loadpilot.compiler import K6Compiler
from loadpilot.discovery import HARAdapter, OpenAPIAdapter
from loadpilot.intent import DeterministicIntentCompiler
from loadpilot.models import TestType as PerformanceTestType
from loadpilot.planner import TestPlanner


def test_openapi_links_become_journey_dependencies(checkout_openapi):
    app = OpenAPIAdapter().adapt(checkout_openapi, name="checkout")
    dependency = next(d for d in app.dependencies if d.consumer_operation_id == "checkout")
    assert dependency.producer_operation_id == "createCart"
    intent = DeterministicIntentCompiler().compile("Stress checkout from 150 concurrent users until p95 exceeds 500 ms or errors exceed 1%")
    plan = TestPlanner().plan(intent, app)
    assert plan.test_type == PerformanceTestType.BREAKPOINT
    assert [step.operation_id for step in plan.journeys[0].steps] == ["createCart", "checkout"]
    script = K6Compiler().compile(plan, app, run_id="run-1").content
    assert "ramping-vus" in script
    assert "state[\"cart_id\"]" in script
    assert "TARGET_TOKEN" in script
    assert "p(95)<500" in script


def test_har_adapter_removes_sensitive_headers():
    har = {"log": {"entries": [{"request": {"method": "GET", "url": "https://example.test/orders", "headers": [{"name": "Authorization", "value": "Bearer secret"}, {"name": "Accept", "value": "application/json"}]}}]}}
    app = HARAdapter().adapt(har, name="capture", base_url="https://example.test")
    names = [p.name for p in app.endpoints[0].parameters]
    assert "Authorization" not in names
    assert names == ["Accept"]
    assert app.metadata["sanitized"] is True
