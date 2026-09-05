from __future__ import annotations

import math

from .models import (
    ApplicationModel,
    ExecutionBackendType,
    ExecutionPlan,
    JourneyStep,
    LoadStage,
    PerformanceTestIntent,
    PerformanceTestPlan,
    PerformanceThreshold,
    TestType,
    UserJourney,
)


class TestPlanner:
    def plan(self, intent: PerformanceTestIntent, application: ApplicationModel, *, backend: ExecutionBackendType = ExecutionBackendType.LOCAL) -> PerformanceTestPlan:
        target = intent.target_concurrency or 100
        duration = intent.duration_seconds or 1200
        stages = self._stages(intent.test_type, target, duration)
        selected = self._select_endpoints(intent, application)
        steps = [JourneyStep(operation_id=e.operation_id, extract=self._extracts(e, application)) for e in selected]
        if not steps:
            raise ValueError("No target operations matched the intent")
        thresholds: list[PerformanceThreshold] = []
        if intent.slos.latency_p95_ms:
            thresholds.append(PerformanceThreshold(metric="http_req_duration", expression=f"p(95)<{intent.slos.latency_p95_ms:g}", abort_on_fail=intent.test_type in {TestType.BASELINE, TestType.SOAK}, delay_abort_eval_seconds=min(60, duration // 10)))
        if intent.slos.error_rate is not None:
            thresholds.append(PerformanceThreshold(metric="http_req_failed", expression=f"rate<{intent.slos.error_rate:g}", abort_on_fail=intent.test_type == TestType.SOAK, delay_abort_eval_seconds=min(60, duration // 10)))
        timeout = sum(s.duration_seconds for s in stages) + 300
        return PerformanceTestPlan(
            intent_id=intent.id,
            application_id=application.id,
            test_type=intent.test_type,
            workload_model="open" if intent.target_rps else "closed",
            executor="ramping-arrival-rate" if intent.target_rps else "ramping-vus",
            stages=stages,
            journeys=[UserJourney(name="primary", steps=steps)],
            thresholds=thresholds,
            payload_sources=["schemathesis", "runtime-dependency-values"],
            abort_conditions=["platform safety budget exceeded", "target unreachable for 60s"],
            observability_requirements=["k6", "application", "infrastructure", "database"],
            execution=ExecutionPlan(backend=backend, timeout_seconds=timeout),
        )

    @staticmethod
    def _stages(test_type: TestType, target: int, duration: int) -> list[LoadStage]:
        def stage(name: str, fraction: float, vus: int) -> LoadStage:
            return LoadStage(name=name, duration_seconds=max(1, int(duration * fraction)), target_vus=max(0, vus))
        if test_type == TestType.BASELINE:
            return [stage("warmup", .2, target), stage("baseline", .7, target), stage("cooldown", .1, 0)]
        if test_type == TestType.SOAK:
            return [stage("warmup", .05, target), stage("soak", .9, target), stage("cooldown", .05, 0)]
        if test_type == TestType.SPIKE:
            return [stage("warmup", .2, target), stage("spike", .1, target * 3), stage("recovery", .5, target), stage("cooldown", .2, 0)]
        if test_type in {TestType.STRESS, TestType.BREAKPOINT}:
            peak = target * (6 if test_type == TestType.BREAKPOINT else 3)
            levels = [target, math.ceil(target * 1.5), target * 2, peak]
            each = .85 / len(levels)
            return [stage("warmup", .1, max(1, target // 2))] + [stage(f"level-{value}", each, value) for value in levels] + [stage("cooldown", .05, 0)]
        return [stage("ramp", .2, target), stage("steady", .7, target), stage("cooldown", .1, 0)]

    @staticmethod
    def _select_endpoints(intent: PerformanceTestIntent, application: ApplicationModel):
        if not intent.target_endpoints:
            return application.endpoints
        matches = [e for e in application.endpoints if any(term in (e.path + " " + e.operation_id + " " + " ".join(e.tags)).lower() for term in intent.target_endpoints)]
        if not matches:
            return application.endpoints
        required_ids = {d.producer_operation_id for d in application.dependencies if d.consumer_operation_id in {e.operation_id for e in matches}}
        dependencies = [e for e in application.endpoints if e.operation_id in required_ids]
        return dependencies + [e for e in matches if e.operation_id not in required_ids]

    @staticmethod
    def _extracts(endpoint, application: ApplicationModel) -> dict[str, str]:
        return {d.input_name: d.output_expression for d in application.dependencies if d.producer_operation_id == endpoint.operation_id}

