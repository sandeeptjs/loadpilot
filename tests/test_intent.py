from loadpilot.intent import DeterministicIntentCompiler
from loadpilot.models import TestType as PerformanceTestType


def test_acceptance_prompt_compiles_to_typed_breakpoint_intent():
    intent = DeterministicIntentCompiler().compile("Stress test the checkout flow. Normal traffic is roughly 150 concurrent users. Find the maximum load it can sustain while keeping p95 under 500 ms and errors under 1%.")
    assert intent.test_type == PerformanceTestType.BREAKPOINT
    assert intent.target_concurrency == 150
    assert intent.slos.latency_p95_ms == 500
    assert intent.slos.error_rate == .01
    assert intent.target_endpoints == ["checkout"]


def test_soak_duration_is_parsed():
    intent = DeterministicIntentCompiler().compile("Run checkout at 250 VUs for 2 hours and look for gradual degradation")
    assert intent.test_type == PerformanceTestType.SOAK
    assert intent.duration_seconds == 7200
    assert intent.target_concurrency == 250


def test_hyphenated_duration_is_parsed():
    intent = DeterministicIntentCompiler().compile("Stress checkout with 10 users for 20-second test.")
    assert intent.duration_seconds == 20


def test_start_delay_is_not_the_test_duration():
    intent = DeterministicIntentCompiler().compile('Start in 30 seconds. Run baseline products with 2 users for 5 minutes.')
    assert intent.duration_seconds == 300
    assert intent.schedule.run_at is not None
