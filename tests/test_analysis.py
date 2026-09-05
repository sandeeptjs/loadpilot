from uuid import uuid4

from loadpilot.analysis import ResultAnalyzer, StageResult, compare_metrics
from loadpilot.discovery import ManualAdapter
from loadpilot.intent import DeterministicIntentCompiler
from loadpilot.planner import TestPlanner


def test_breakpoint_and_root_cause_are_evidence_backed():
    intent = DeterministicIntentCompiler().compile("Find maximum checkout load from 150 VUs with p95 under 500 ms and errors under 1%")
    app = ManualAdapter().adapt([{"method": "POST", "path": "/checkout"}], name="target", base_url="http://localhost:8080")
    plan = TestPlanner().plan(intent, app)
    stages = [
        StageResult(700, 402, .003, 650, {"db_pool_utilization": .72, "db_wait_ms": 2, "app_cpu_utilization": .46}),
        StageResult(800, 463, .006, 742, {"db_pool_utilization": .88, "db_wait_ms": 8, "app_cpu_utilization": .50}),
        StageResult(900, 1020, .029, 821, {"db_pool_utilization": .98, "db_wait_ms": 64, "app_cpu_utilization": .51}),
    ]
    result = ResultAnalyzer().analyze(uuid4(), plan, stages)
    assert "800 VUs" in result.summary
    assert result.likely_root_cause == "Database connection-pool saturation"
    assert result.confidence == .86
    assert "850" in result.recommended_next_experiment


def test_regression_math():
    result = compare_metrics({"p95_ms": 470, "throughput_rps": 1560}, {"p95_ms": 320, "throughput_rps": 1900})
    assert round(result["p95_ms"]["delta_pct"], 1) == 46.9
    assert result["throughput_rps"]["regression"] is True

