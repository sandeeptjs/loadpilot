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
from .settings import Settings


class TestPlanner:
    __test__ = False
    def __init__(self, settings: Settings | None = None):
        self.settings = settings

    def plan(self, intent: PerformanceTestIntent, application: ApplicationModel, *, backend: ExecutionBackendType = ExecutionBackendType.LOCAL, journeys=None) -> PerformanceTestPlan:
        target = intent.target_concurrency or 1
        duration = intent.duration_seconds or 30
        stages = self._stages(intent.test_type, target, duration, intent.max_concurrency)
        selected = [] if journeys else self._select_endpoints(intent, application)
        steps = [JourneyStep(operation_id=e.operation_id, extract=self._extracts(e, application)) for e in selected]
        if journeys:
            from .scenarios import validate_journeys
            journeys = validate_journeys(journeys, application)
            steps = [step for journey in journeys for step in journey.steps]
        if not steps:
            raise ValueError("No target operations matched the intent")
        if intent.target_rps:
            if len(steps) != 1:
                raise ValueError('HTTP RPS workloads currently require one operation; use concurrent users for multi-step journeys')
            stages = [s.model_copy(update={'target_rps': (s.target_vus or 0) / target * intent.target_rps, 'target_vus': None}) for s in stages]
        cap = self.settings.max_vus if self.settings else max(100, max((s.target_vus or 0 for s in stages), default=100))
        if self.settings:
            if duration > self.settings.max_duration_seconds or duration < 5:
                raise ValueError(f'Duration must be between 5 and {self.settings.max_duration_seconds} seconds')
            if max(s.target_vus or 0 for s in stages) > cap:
                raise ValueError(f'Workload exceeds the configured {cap} VU limit; provide a bounded range')
            if max(s.target_rps or 0 for s in stages) > self.settings.max_rps:
                raise ValueError('Workload exceeds the configured RPS limit')
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
            journeys=journeys or [UserJourney(name="primary", steps=steps)],
            thresholds=thresholds,
            payload_sources=["json-schema-validated-sample-pools", "runtime-dependency-values"],
            abort_conditions=['Execution timeout', 'Transport failure rate reaches 20% after 5 seconds'],
            observability_requirements=["k6", "application", "infrastructure", "database"],
            execution=ExecutionPlan(backend=backend, timeout_seconds=timeout, max_vus=cap),
        )

    @staticmethod
    def _stages(test_type: TestType, target: int, duration: int, maximum: int | None = None) -> list[LoadStage]:
        peak = maximum or target * (6 if test_type == TestType.BREAKPOINT else 3)
        if maximum and maximum < target:
            raise ValueError('Maximum concurrency must be at least the starting concurrency')
        if test_type in {TestType.STRESS, TestType.BREAKPOINT}:
            levels = sorted({target, math.ceil((target + peak) / 2), peak})
        elif test_type == TestType.SPIKE:
            levels = [target, peak, target]
        else:
            levels = [target]
        if duration < len(levels) * 2 + 1:
            raise ValueError('Duration is too short for ramp and measurement stages')
        ramp_seconds = max(1, int(duration * .05))
        hold_total = duration - ramp_seconds * (len(levels) + 1)
        holds = [hold_total // len(levels)] * len(levels)
        holds[-1] += hold_total % len(levels)
        stages = []
        for index, (level, hold) in enumerate(zip(levels, holds)):
            stages.append(LoadStage(name=f'ramp-{index + 1}', duration_seconds=ramp_seconds, target_vus=level, measurement=False))
            stages.append(LoadStage(name=f'hold-{index + 1}-{level}', duration_seconds=hold, target_vus=level, measurement=True))
        stages.append(LoadStage(name='cooldown', duration_seconds=ramp_seconds, target_vus=0, measurement=False))
        return stages

    @staticmethod
    def _select_endpoints(intent: PerformanceTestIntent, application: ApplicationModel):
        if not intent.target_endpoints:
            reads = [endpoint for endpoint in application.endpoints if endpoint.method == 'GET']
            if not reads:
                raise ValueError('Name the operation or journey to test; no read-only default operations exist')
            return reads
        matches = [e for e in application.endpoints if any(term.lower() in (e.path + " " + e.operation_id + " " + " ".join(e.tags)).lower() for term in intent.target_endpoints)]
        if not matches:
            raise ValueError('No operations match the requested journey; supply an operation ID or endpoint')
        endpoints = {e.operation_id: e for e in application.endpoints}
        ordered, visited, visiting = [], set(), set()
        def visit(operation_id):
            if operation_id in visiting:
                raise ValueError('Cyclic operation dependencies require an explicit journey')
            if operation_id in visited:
                return
            if operation_id not in endpoints:
                raise ValueError(f'Unknown dependency operation {operation_id}')
            visiting.add(operation_id)
            for dependency in application.dependencies:
                if dependency.consumer_operation_id == operation_id:
                    visit(dependency.producer_operation_id)
            visiting.remove(operation_id)
            visited.add(operation_id)
            ordered.append(endpoints[operation_id])
        for endpoint in matches:
            visit(endpoint.operation_id)
        return ordered

    @staticmethod
    def _extracts(endpoint, application: ApplicationModel) -> dict[str, str]:
        return {d.input_name: d.output_expression for d in application.dependencies if d.producer_operation_id == endpoint.operation_id}

