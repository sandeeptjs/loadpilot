from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from .ai import JsonProvider
from .analysis import ResultAnalyzer, StageResult
from .audit import audit_event, redact
from .compiler import K6Compiler
from .discovery import GraphQLAdapter, HARAdapter, ManualAdapter, OpenAPIAdapter, PostmanAdapter
from .execution import DockerK6Backend, ExecutionBackend, KubernetesK6Backend, LocalK6Backend
from .intent import DeterministicIntentCompiler
from .lifecycle import TERMINAL, RunStore
from .models import (
    ApplicationModel,
    ExecutionBackendType,
    Investigation,
    PerformanceTestIntent,
    PerformanceTestPlan,
    RunArtifact,
    RunState,
    ScheduleSpec,
    SecretReference,
    TelemetryWindow,
    TestRun,
    utcnow,
)
from .planner import TestPlanner
from .reports import build_report
from .settings import Settings, get_settings

ADAPTERS = {
    "openapi": OpenAPIAdapter,
    "graphql": GraphQLAdapter,
    "har": HARAdapter,
    "postman": PostmanAdapter,
    "manual": ManualAdapter,
}


class LoadPilotService:
    def __init__(self, store: RunStore | None = None, generated_dir: str | Path = "generated-tests", backends: dict[ExecutionBackendType, ExecutionBackend] | None = None, settings: Settings | None = None) -> None:
        self.store = store or RunStore()
        self.generated_dir = Path(generated_dir)
        self.intent_compiler = DeterministicIntentCompiler()
        self.settings = settings or get_settings()
        self.planner = TestPlanner(self.settings)
        self.ai = JsonProvider(self.settings)
        self.k6_compiler = K6Compiler()
        self.analyzer = ResultAnalyzer()
        self.backends = backends or {
            ExecutionBackendType.LOCAL: LocalK6Backend(self.settings.k6_bin),
            ExecutionBackendType.DOCKER: DockerK6Backend(),
            ExecutionBackendType.KUBERNETES: KubernetesK6Backend(),
        }
        for backend in self.backends.values():
            if isinstance(backend, LocalK6Backend):
                backend.on_sample = self._record_sample

    async def prepare(self, *, prompt: str, source_type: str, source, application_name: str, base_url: str | None = None, environment: str = "local", backend: ExecutionBackendType = ExecutionBackendType.LOCAL, validate: bool = False, intent_overrides: dict | None = None, credentials_reference: SecretReference | None = None, run_at: datetime | None = None, auto_start: bool = False, auto_followup: bool = False) -> TestRun:
        run = self.store.create(TestRun(plan_id=uuid4(), execution_backend=backend, auto_followup=auto_followup))
        try:
            intent = self.intent_compiler.compile(prompt, environment=environment)
            run = self.store.transition(run.id, RunState.DISCOVERING_APPLICATION)

            adapter_type = ADAPTERS.get(source_type)
            if not adapter_type:
                raise ValueError(f"Unsupported source type: {source_type}")
            application = await asyncio.to_thread(adapter_type().adapt, source, name=application_name, base_url=base_url)
            if not application.endpoints:
                raise ValueError("Application discovery found no operations")
            if not application.base_url:
                raise ValueError('A target base URL is required')
            self.settings.check_target(str(application.base_url))
            if backend != ExecutionBackendType.LOCAL:
                raise ValueError('Only local execution is currently qualified; it also runs inside the API container')
            if self.settings.ai_enabled:
                parsed = await self.ai.parse(prompt, [{'id': e.operation_id, 'path': e.path, 'method': e.method} for e in application.endpoints])
                updates = parsed.model_dump(exclude_none=True)
                intent = PerformanceTestIntent.model_validate({**intent.model_dump(), **updates})
                run = self.store.update(run.id, ai_mode='provider')
            else:
                # Match arbitrary API operation IDs and literal paths, not only demo nouns.
                matches = [e.operation_id for e in application.endpoints if e.operation_id.lower() in prompt.lower() or e.path.lower() in prompt.lower()]
                if matches:
                    intent.target_endpoints = matches
            if intent_overrides:
                allowed = {'test_type', 'target_endpoints', 'target_concurrency', 'max_concurrency', 'target_rps', 'duration_seconds', 'slos'}
                if set(intent_overrides) - allowed:
                    raise ValueError('Unsupported intent override field')
                intent = PerformanceTestIntent.model_validate({**intent.model_dump(), **intent_overrides})
            if run_at:
                if run_at.tzinfo is None:
                    raise ValueError('run_at must include a timezone offset')
                intent.schedule = ScheduleSpec(run_at=run_at)
            if intent.schedule and (not intent.schedule.run_at or intent.schedule.recurrence):
                raise ValueError('Provide a timezone-aware run_at or say start in N seconds; recurring schedules are not implemented')
            intent.raw_prompt = redact(intent.raw_prompt)
            self.store.put_entity('intent', intent)
            self._audit(run, 'intent.parsed', {'prompt': prompt}, intent.model_dump(mode='json'), 'Validated provider JSON' if self.settings.ai_enabled else 'Explicit offline deterministic parsing')
            self.store.put_entity("application", application)
            self._audit(run, "application.discovered", {"source_type": source_type}, {"application_id": str(application.id), "operations": len(application.endpoints), "dependencies": len(application.dependencies)}, "Normalize the application into the canonical model")

            run = self.store.transition(run.id, RunState.GENERATING_DATA)
            self._audit(run, "data.generated", {"application_id": str(application.id)}, {"strategy": "schema-first", "candidate_count": sum(len(e.examples) for e in application.endpoints)}, "Generate deterministic schema-conforming candidates")
            run = self.store.transition(run.id, RunState.PLANNING)
            plan = self.planner.plan(intent, application, backend=backend)
            if credentials_reference:
                if credentials_reference.provider != 'env':
                    raise ValueError('Only env credential references are supported')
                if not re.fullmatch(r'TARGET_[A-Z0-9_]+', credentials_reference.key):
                    raise ValueError('Execution secret references must use TARGET_ environment variables')
                plan.execution.secret_references['TARGET_TOKEN'] = credentials_reference
            # Authenticated operations need a token binding or a supplied secret reference.
            for step in plan.journeys[0].steps:
                endpoint = next(e for e in application.endpoints if e.operation_id == step.operation_id)
                bound_auth = any(d.consumer_operation_id == endpoint.operation_id and d.input_name == 'Authorization' for d in application.dependencies)
                if endpoint.auth_schemes and not bound_auth and not credentials_reference:
                    raise ValueError(f'Authentication for {endpoint.operation_id} requires a credential reference or login dependency')
            self.store.put_entity("plan", plan)
            run = self.store.save(run.model_copy(update={"plan_id": plan.id}))
            self._audit(run, "plan.generated", {"intent_id": str(intent.id)}, plan.model_dump(mode="json"), "Create a bounded deterministic workload")

            run = self.store.transition(run.id, RunState.GENERATING_SCRIPT)
            compiled = self.k6_compiler.compile(plan, application, run_id=str(run.id))
            path = self.generated_dir / f"{run.id}.js"
            self.k6_compiler.write(compiled, path)
            artifact = RunArtifact(kind="k6-script", uri=str(path.resolve()), sha256=compiled.sha256)
            run = self.store.save(run.model_copy(update={"artifacts": [*run.artifacts, artifact]}))
            self._audit(run, "script.generated", {"plan_id": str(plan.id)}, {"uri": artifact.uri, "sha256": compiled.sha256}, "Compile validated plan through a fixed k6 template")

            run = self.store.transition(run.id, RunState.VALIDATING)
            if validate:
                await self._validate_and_queue(run, plan, path)
                run = self.store.get(run.id)
            if auto_start or intent.schedule:
                return self.submit(run.id, intent.schedule.run_at if intent.schedule else None)
            return run
        except Exception as exc:
            current = self.store.get(run.id)
            if current.state not in {RunState.FAILED, RunState.CANCELED, RunState.COMPLETED}:
                try:
                    current = self.store.transition(run.id, RunState.FAILED, error=str(exc))
                except Exception:  # noqa: BLE001 - preserve failure record if transition itself is unavailable
                    current = self.store.save(current.model_copy(update={"state": RunState.FAILED, "error": str(exc), "finished_at": utcnow()}))
            self._audit(current, "run.failed", {}, {"error": str(exc)}, "Pipeline activity failed")
            raise

    def submit(self, run_id, run_at=None):
        run = self.store.get(run_id)
        if run.state in TERMINAL:
            raise ValueError('Terminal runs cannot be restarted; create a rerun')
        if run.state in {RunState.RUNNING, RunState.INITIALIZING, RunState.COLLECTING_TELEMETRY, RunState.ANALYZING}:
            return run
        due = run_at or run.scheduled_at or utcnow()
        if due.tzinfo is None:
            raise ValueError('Scheduled time must include a timezone')
        if due > utcnow() and run.state == RunState.VALIDATING:
            run = self.store.transition(run.id, RunState.SCHEDULED)
        run = self.store.update(run.id, scheduled_at=due)
        self.store.enqueue(run.id, due.timestamp())
        self._audit(run, 'test.scheduled', {}, {'run_at': due.isoformat()}, 'Persist execution request for the worker')
        return run

    async def start(self, run_id: UUID | str) -> TestRun:
        run = self.store.get(run_id)
        plan = self.store.get_entity("plan", run.plan_id, PerformanceTestPlan)
        path = Path(next(a.uri for a in run.artifacts if a.kind == "k6-script"))
        backend = self.backends[plan.execution.backend]
        try:
            if run.state in TERMINAL:
                return run
            if run.scheduled_at and run.scheduled_at > utcnow():
                raise ValueError('Scheduled time has not arrived')
            expected_hash = next(a.sha256 for a in run.artifacts if a.kind == 'k6-script')
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                raise ValueError('Generated script changed after planning')
            if run.state in {RunState.VALIDATING, RunState.SCHEDULED}:
                await backend.validate(path)
                self._audit(run, 'script.validated', {}, {}, 'k6 inspect passed')
                if self.store.get(run.id).state == RunState.CANCELED:
                    return self.store.get(run.id)
                run = self.store.transition(run.id, RunState.QUEUED)
            run = self.store.transition(run.id, RunState.INITIALIZING)
            run = self.store.transition(run.id, RunState.RUNNING)
            self._audit(run, 'test.started', {'backend': plan.execution.backend.value}, {}, 'Start the validated workload')
            telemetry_before = await self._target_metrics_snapshot(run.id)
            result = await backend.execute(run, plan, path)
            if self.store.get(run.id).state in TERMINAL:
                return self.store.get(run.id)
            threshold_breach = result.exit_code == 99 and bool(result.summary.get('metrics'))
            if result.exit_code and not threshold_breach:
                raise RuntimeError(result.stderr[-2000:] or f"k6 exited {result.exit_code}")
            metrics = self._summary_metrics(result.summary)
            if metrics.get('http_reqs.count', 0) <= 0:
                raise ValueError('Execution produced no HTTP request evidence')
            telemetry_after = await self._target_metrics_snapshot(run.id)
            metrics.update(self._target_metric_deltas(telemetry_before, telemetry_after))
            finished = utcnow()
            metrics['loadpilot.elapsed_seconds'] = (finished - run.started_at).total_seconds()
            window = TelemetryWindow(start=run.started_at or run.created_at, end=finished)
            logs = [result.stderr[-4000:]] if result.stderr else []
            if threshold_breach:
                logs.append("Performance SLO threshold crossed; execution completed and proceeded to analysis.")
            run = self.store.update(run.id, metrics=metrics, telemetry_window=window, logs=redact(logs), slo_passed=not threshold_breach)
            run = self.store.transition(run.id, RunState.COLLECTING_TELEMETRY)
            self._audit(run, "telemetry.collected", {"window": window.model_dump(mode="json")}, {"metric_count": len(metrics)}, "Time-correlate load and target evidence")
            run = self.store.transition(run.id, RunState.ANALYZING)
            investigation = self.analyzer.analyze(run.id, plan, self._stage_results(plan, metrics))
            if metrics.get('loadpilot_transport_failed.rate', 0) > 0:
                investigation.limitations.append('Transport failures occurred. Zero-duration failed connections must not be interpreted as fast application responses.')
            if metrics.get('loadpilot_transport_failed.rate', 0) >= .2:
                investigation.summary = 'Load-generator connections failed; application capacity is unassessed.'
                investigation.likely_root_cause = 'Load generator or network connection failure'
                investigation.confidence = .8
                investigation.observed_degradation_point = None
                investigation.recommended_next_experiment = None
            if not telemetry_after:
                investigation.limitations.append('Target metrics unavailable; root cause cannot be established from load metrics alone.')
            report = build_report(self, run, plan, investigation)
            evidence = report.evidence
            if self.settings.ai_enabled:
                try:
                    narrative = await self.ai.summarize(evidence)
                    investigation.ai_summary = narrative.summary
                    investigation.ai_evidence_ids = narrative.evidence_ids
                    investigation.limitations.extend(narrative.limitations)
                except (ValueError, httpx.HTTPError):
                    investigation.limitations.append('AI summary unavailable; deterministic evidence is retained.')
            self.store.put_entity("investigation", investigation)
            self.store.put_entity('report', report)
            self._audit(run, 'alerts.correlated', {}, report.correlation, 'Deduplicate and group scoped evidence without merging unrelated targets')
            self._audit(run, "investigation.completed", {"run_id": str(run.id)}, investigation.model_dump(mode="json"), "Apply deterministic analysis before external RCA")
            return self.store.transition(run.id, RunState.COMPLETED)
        except asyncio.CancelledError:
            if self.store.get(run.id).state not in TERMINAL:
                self.cancel(run.id, 'Worker stopped; no automatic replay of load traffic')
            raise
        except Exception as exc:  # noqa: BLE001 - execution boundary converts failures into lifecycle state
            if self.store.get(run.id).state in TERMINAL:
                return self.store.get(run.id)
            target = RunState.TIMED_OUT if isinstance(exc, TimeoutError) and self.store.get(run.id).state == RunState.RUNNING else RunState.FAILED
            run = self.store.transition(run.id, target, error=redact(str(exc)) or type(exc).__name__)
            self._audit(run, "run.failed", {}, {"error": str(exc)}, "Execution or analysis failed")
            return run

    def cancel(self, run_id: UUID | str, reason: str, actor: str = "user") -> TestRun:
        current = self.store.get(run_id)
        if current.state == RunState.CANCELED:
            return current
        run = self.store.transition(run_id, RunState.CANCELED, cancellation_reason=reason)
        backend = self.backends[run.execution_backend]
        if hasattr(backend, 'cancel'):
            backend.cancel(run.id)
        self._audit(run, "test.canceled", {"reason": reason}, {}, "User or policy requested cancellation", actor=actor)
        return run

    async def _validate_and_queue(self, run: TestRun, plan: PerformanceTestPlan, path: Path) -> None:
        backend = self.backends[plan.execution.backend]
        await backend.validate(path)
        self._audit(run, "script.validated", {"uri": str(path)}, {"validator": "k6 inspect"}, "Block syntactically invalid workloads")
        intent = self.store.get_entity("intent", plan.intent_id, PerformanceTestIntent)
        self.store.transition(run.id, RunState.SCHEDULED if intent.schedule else RunState.QUEUED)

    def _audit(self, run: TestRun, action: str, inputs: dict, outputs: dict, reason: str, actor: str = "loadpilot") -> None:
        self.store.append_audit(audit_event(actor=actor, tool="loadpilot", action=action, inputs=inputs, outputs=outputs, reason=reason, test_id=run.id))

    @staticmethod
    def _summary_metrics(summary: dict) -> dict[str, float]:
        output: dict[str, float] = {}
        for name, value in summary.get("metrics", {}).items():
            values = value.get("values", value) if isinstance(value, dict) else {}
            if not isinstance(values, dict):
                continue
            for key in ("p(95)", "rate", "count", "avg", "max"):
                if isinstance(values.get(key), (int, float)):
                    output[f"{name}.{key}"] = float(values[key])
        return output

    @staticmethod
    def _stage_results(plan: PerformanceTestPlan, metrics: dict[str, float]) -> list[StageResult]:
        results: list[StageResult] = []
        if metrics.get('loadpilot_transport_failed.rate', 0) >= .2:
            return results
        boundary = 0
        for stage in plan.stages:
            boundary += stage.duration_seconds
            suffix = "_".join(filter(None, re.split(r"[^a-zA-Z0-9]+", stage.name.lower())))
            prefix = f"loadpilot_stage_{suffix}"
            p95 = metrics.get(f"{prefix}_duration.p(95)")
            if p95 is None or not stage.target_vus or not stage.measurement:
                continue
            count = metrics.get(f"{prefix}_requests.count", 0)
            if count < 5 or metrics.get('loadpilot.elapsed_seconds', float('inf')) < boundary:
                continue
            results.append(StageResult(vus=stage.target_vus, p95_ms=p95, error_rate=metrics.get(f"{prefix}_failed.rate", 0), rps=count / stage.duration_seconds, metrics=metrics))
        if results:
            return results
        return []

    async def _target_metrics_snapshot(self, run_id) -> dict[str, float]:
        run = self.store.get(run_id)
        plan = self.store.get_entity('plan', run.plan_id, PerformanceTestPlan)
        app = self.store.get_entity('application', plan.application_id, ApplicationModel)
        url = str(app.base_url).rstrip('/') + '/metrics'
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                response = await client.get(url)
                response.raise_for_status()
            values: dict[str, float] = {}
            for line in response.text.splitlines():
                if not line or line.startswith("#") or " " not in line:
                    continue
                name, raw = line.rsplit(" ", 1)
                if "{" in name:
                    continue
                try:
                    values[name] = float(raw)
                except ValueError:
                    continue
            return values
        except (httpx.HTTPError, ValueError):
            return {}

    async def _record_sample(self, run_id, values):
        if self.store.get(run_id).state in TERMINAL:
            return
        target = await self._target_metrics_snapshot(run_id)
        values = {**values, **target}
        self.store.add_sample(run_id, utcnow().isoformat(), values)
        run = self.store.get(run_id)
        if run.state not in TERMINAL:
            self.store.update(run_id, metrics=values)

    def detail(self, run_id):
        run = self.store.get(run_id)
        try:
            plan = self.store.get_entity('plan', run.plan_id, PerformanceTestPlan)
        except KeyError:
            return {'run': run, 'plan': None, 'intent': None, 'application': None, 'investigation': None}
        investigation = next((item for item in self.store.list_entities('investigation', Investigation, 10000) if item.run_id == run.id), None)
        return {'run': run, 'plan': plan, 'intent': self.store.get_entity('intent', plan.intent_id, PerformanceTestIntent), 'application': self.store.get_entity('application', plan.application_id, ApplicationModel), 'investigation': investigation}

    def rerun(self, run_id, *, followup=False, auto_start=True):
        detail = self.detail(run_id)
        original, old_plan, application = detail['run'], detail['plan'], detail['application']
        if original.state != RunState.COMPLETED:
            raise ValueError('Only completed runs can be repeated')
        intent = detail['intent'].model_copy(deep=True, update={'id': uuid4(), 'schedule': None})
        if followup:
            if original.parent_run_id:
                raise ValueError('Only one automatic follow-up generation is allowed')
            existing = next((r for r in self.store.list(10000) if r.parent_run_id == original.id), None)
            if existing:
                return existing
            results = self._stage_results(old_plan, original.metrics)
            latency, errors = intent.slos.latency_p95_ms, intent.slos.error_rate
            if latency is None and errors is None:
                raise ValueError('Follow-up search requires configured SLOs')
            failing = [s.vus for s in results if (latency is not None and s.p95_ms >= latency) or (errors is not None and s.error_rate >= errors)]
            if not failing:
                raise ValueError('No failing plateau was observed; no narrower boundary is known')
            high = min(failing)
            passing = [s.vus for s in results if s.vus < high and (latency is None or s.p95_ms < latency) and (errors is None or s.error_rate < errors)]
            if not passing or high - max(passing) < 2:
                raise ValueError('No measured pass/fail bracket can be narrowed')
            intent.target_concurrency, intent.max_concurrency = max(passing), high
            intent.duration_seconds = min(intent.duration_seconds or 60, 60)
            plan = self.planner.plan(intent, application)
        else:
            plan = old_plan.model_copy(deep=True, update={'id': uuid4(), 'intent_id': intent.id})
        plan.execution.secret_references = old_plan.execution.secret_references.copy()
        run = self.store.create(TestRun(plan_id=plan.id, execution_backend=plan.execution.backend, parent_run_id=original.id, ai_mode=original.ai_mode))
        self.store.put_entity('intent', intent)
        self.store.put_entity('plan', plan)
        for state in (RunState.DISCOVERING_APPLICATION, RunState.GENERATING_DATA, RunState.PLANNING, RunState.GENERATING_SCRIPT):
            run = self.store.transition(run.id, state)
        script = self.k6_compiler.compile(plan, application, run_id=str(run.id))
        path = self.generated_dir / f'{run.id}.js'
        self.k6_compiler.write(script, path)
        run = self.store.update(run.id, artifacts=[RunArtifact(kind='k6-script', uri=str(path.resolve()), sha256=script.sha256)])
        run = self.store.transition(run.id, RunState.VALIDATING)
        self._audit(run, 'experiment.followup' if followup else 'test.repeated', {'parent_run_id': str(original.id)}, {'plan_id': str(plan.id)}, 'Reuse validated application and payload pools; compile an independently validated run')
        return self.submit(run.id) if auto_start else run

    @staticmethod
    def _target_metric_deltas(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
        if not after:
            return {}
        saturation = after.get("sandbox_db_pool_saturation_events_total", 0) - before.get("sandbox_db_pool_saturation_events_total", 0)
        wait_sum = after.get("sandbox_db_pool_wait_seconds_sum", 0) - before.get("sandbox_db_pool_wait_seconds_sum", 0)
        wait_count = after.get("sandbox_db_pool_wait_seconds_count", 0) - before.get("sandbox_db_pool_wait_seconds_count", 0)
        output = {"db_pool_saturation_events": max(0, saturation)}
        # A saturation event is not a measured utilization percentage.
        if wait_count > 0:
            output["db_wait_ms"] = max(0, wait_sum / wait_count * 1000)
        return output
