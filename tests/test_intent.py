import pytest

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


# Prose, not parameters. Each row is a requirement a person would actually type, paired with
# the reading it has to produce: (test type, concurrency, ceiling, duration, p95 ms, error rate).
PROSE = [
    ('We need to know whether the storefront survives a busy sale hour: sign a shopper in, let them build a basket, then push the order through payments with 12 shoppers at once for 30 seconds. I want the 95th percentile response under 900 ms and fewer than 2% failures.',
     PerformanceTestType.LOAD, 12, None, 30, 900, .02),
    ('Simulate a flash sale: two hundred fifty shoppers add to basket and check the order out over half an hour, failure rate must stay below 1%',
     PerformanceTestType.SPIKE, 250, None, 1800, None, .01),
    ('Does the cart hold up? twenty five testers, 1 minute, sub-300ms p95, fewer than 2 percent errors',
     PerformanceTestType.LOAD, 25, None, 60, 300, .02),
    ('Hammer the login endpoint with 30 concurrent sessions for two minutes and tell me if p95 exceeds 400 ms',
     PerformanceTestType.STRESS, 30, None, 120, 400, None),
    ('I want to see if 40 customers can log in and place an order without the 95th percentile going past 800ms',
     PerformanceTestType.LOAD, 40, None, 30, 800, None),
    ('a hundred sessions overnight; failure rate must not exceed 0.5% - sign in, then pay',
     PerformanceTestType.SOAK, 100, None, 28800, None, .005),
    ('between 50 and 300 shoppers logging in, nothing slower than 1200ms at the 95th percentile',
     PerformanceTestType.LOAD, 50, 300, 30, 1200, None),
    ('can the basket survive a couple of dozen buyers checking out for half a minute',
     PerformanceTestType.LOAD, 24, None, 30, None, None),
    ('ramp from ten to two hundred users over a quarter of an hour and keep success above 99%',
     PerformanceTestType.LOAD, 10, 200, 900, None, .01),
    ('one thousand two hundred visitors, 5k rps, response time at most 1.5 seconds',
     PerformanceTestType.LOAD, 1200, None, 30, 1500, None),
]


@pytest.mark.parametrize(('prompt', 'test_type', 'concurrency', 'ceiling', 'duration', 'latency', 'error_rate'), PROSE)
def test_a_requirement_in_plain_english_reads_the_same_as_one_in_parameters(prompt, test_type, concurrency, ceiling, duration, latency, error_rate):
    intent = DeterministicIntentCompiler().compile(prompt)
    assert intent.test_type == test_type
    assert intent.target_concurrency == concurrency
    assert intent.max_concurrency == ceiling
    assert intent.duration_seconds == duration
    assert (intent.slos.latency_p95_ms if intent.slos else None) == latency
    assert (intent.slos.error_rate if intent.slos else None) == error_rate


def test_an_assumption_is_recorded_rather_than_applied_silently():
    """Every default the reading supplies has to be visible, because a 30-second run the
    person never asked for is a different test from the one they described."""
    intent = DeterministicIntentCompiler().compile('check the cart endpoint holds up')
    assert intent.duration_seconds == 30
    assert 'duration_seconds' in intent.inferred_values
    assert 'target_concurrency' in intent.inferred_values
    stated = DeterministicIntentCompiler().compile('soak the cart with 40 users for 20 minutes')
    assert 'duration_seconds' not in stated.inferred_values
    assert 'target_concurrency' not in stated.inferred_values


def test_an_occasion_is_a_duration_and_is_named_as_one():
    intent = DeterministicIntentCompiler().compile('run the checkout flow overnight with 20 users')
    assert intent.duration_seconds == 28800
    assert 'overnight' in intent.inferred_values['duration_seconds']
