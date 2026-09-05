from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from .analysis import ResultAnalyzer, StageResult
from .audit import audit_event
from .compiler import K6Compiler
from .discovery import GraphQLAdapter, HARAdapter, ManualAdapter, OpenAPIAdapter, PostmanAdapter
from .execution import DockerK6Backend, ExecutionBackend, KubernetesK6Backend, LocalK6Backend
from .intent import DeterministicIntentCompiler
from .lifecycle import RunStore
from .models import (
    ExecutionBackendType,
    PerformanceTestIntent,
    PerformanceTestPlan,
    RunArtifact,
    RunState,
    TelemetryWindow,
    TestRun,
    utcnow,
)
from .planner import TestPlanner

ADAPTERS = {
    "openapi": OpenAPIAdapter,
    "graphql": GraphQLAdapter,
    "har": HARAdapter,
    "postman": PostmanAdapter,
    "manual": ManualAdapter,
}


class LoadPilotService:
    def __init__(self, store: RunStore | None = None, generated_dir: str | Path = "generated-tests", backends: dict[ExecutionBackendType, ExecutionBackend] | None = None) -> None:
        self.store = store or RunStore()
        self.generated_dir = Path(generated_dir)
        self.intent_compiler = DeterministicIntentCompiler()
        self.planner = TestPlanner()
        self.k6_compiler = K6Compiler()
        self.analyzer = ResultAnalyzer()
        self.backends = backends or {
            ExecutionBackendType.LOCAL: LocalK6Backend(),
            ExecutionBackendType.DOCKER: DockerK6Backend(),
            ExecutionBackendType.KUBERNETES: KubernetesK6Backend(),
        }

    async def prepare(self, *, prompt: str, source_type: str, source, application_name: str, base_url: str | None = None, environment: str = "local", backend: ExecutionBackendType = ExecutionBackendType.LOCAL, validate: bool = False) -> TestRun:
        run = self.store.create(TestRun(plan_id=uuid4(), execution_backend=backend))
        try:
            intent = self.intent_compiler.compile(prompt, environment=environment)
            self.store.put_entity("intent", intent)
            self._audit(run, "intent.parsed", {"prompt": prompt}, intent.model_dump(mode="json"), "Compile prose into a validated intent")
            run = self.store.transition(run.id, RunState.DISCOVERING_APPLICATION)

            adapter_type = ADAPTERS.get(source_type)
            if not adapter_type:
                raise ValueError(f"Unsupported source type: {source_type}")
            application = adapter_type().adapt(source, name=application_name, base_url=base_url)
            if not application.endpoints:
                raise ValueError("Application discovery found no operations")
            self.store.put_entity("application", application)
            self._audit(run, "application.discovered", {"source_type": source_type}, {"application_id": str(application.id), "operations": len(application.endpoints), "dependencies": len(application.dependencies)}, "Normalize the application into the canonical model")

            run = self.store.transition(run.id, RunState.GENERATING_DATA)
            self._audit(run, "data.generated", {"application_id": str(application.id)}, {"strategy": "schema-first", "candidate_count": sum(len(e.examples) for e in application.endpoints)}, "Generate deterministic schema-conforming candidates")
            run = self.store.transition(run.id, RunState.PLANNING)
            plan = self.planner.plan(intent, application, backend=backend)
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

    async def start(self, run_id: UUID | str) -> TestRun:
        run = self.store.get(run_id)
        plan = self.store.get_entity("plan", run.plan_id, PerformanceTestPlan)
        path = Path(next(a.uri for a in run.artifacts if a.kind == "k6-script"))
        if run.state == RunState.VALIDATING:
            await self._validate_and_queue(run, plan, path)
            run = self.store.get(run_id)
        if run.state == RunState.SCHEDULED:
            run = self.store.transition(run.id, RunState.QUEUED)
        run = self.store.transition(run.id, RunState.INITIALIZING)
        run = self.store.transition(run.id, RunState.RUNNING)
        self._audit(run, "test.started", {"backend": plan.execution.backend.value}, {}, "Start the validated workload")
        backend = self.backends[plan.execution.backend]
        try:
            telemetry_before = await self._target_metrics_snapshot()
            result = await backend.execute(run, plan, path)
            threshold_breach = result.exit_code != 0 and bool(result.summary) and "threshold" in result.stderr.lower()
            if result.exit_code and not threshold_breach:
                raise RuntimeError(result.stderr[-2000:] or f"k6 exited {result.exit_code}")
            metrics = self._summary_metrics(result.summary)
            telemetry_after = await self._target_metrics_snapshot()
            metrics.update(self._target_metric_deltas(telemetry_before, telemetry_after))
            finished = utcnow()
            window = TelemetryWindow(start=run.started_at or run.created_at, end=finished)
            logs = [result.stderr[-4000:]] if result.stderr else []
            if threshold_breach:
                logs.append("Performance SLO threshold crossed; execution completed and proceeded to analysis.")
            run = self.store.save(run.model_copy(update={"metrics": metrics, "telemetry_window": window, "logs": logs}))
            run = self.store.transition(run.id, RunState.COLLECTING_TELEMETRY)
            self._audit(run, "telemetry.collected", {"window": window.model_dump(mode="json")}, {"metric_count": len(metrics)}, "Time-correlate load and target evidence")
            run = self.store.transition(run.id, RunState.ANALYZING)
            investigation = self.analyzer.analyze(run.id, plan, self._stage_results(plan, metrics))
            self.store.put_entity("investigation", investigation)
            self._audit(run, "investigation.completed", {"run_id": str(run.id)}, investigation.model_dump(mode="json"), "Apply deterministic analysis before external RCA")
            return self.store.transition(run.id, RunState.COMPLETED)
        except Exception as exc:  # noqa: BLE001 - execution boundary converts failures into lifecycle state
            run = self.store.transition(run.id, RunState.FAILED, error=str(exc))
            self._audit(run, "run.failed", {}, {"error": str(exc)}, "Execution or analysis failed")
            return run

    def cancel(self, run_id: UUID | str, reason: str, actor: str = "user") -> TestRun:
        run = self.store.transition(run_id, RunState.CANCELED, cancellation_reason=reason)
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
        for stage in plan.stages:
            suffix = "_".join(filter(None, re.split(r"[^a-zA-Z0-9]+", stage.name.lower())))
            prefix = f"loadpilot_stage_{suffix}"
            p95 = metrics.get(f"{prefix}_duration.p(95)")
            if p95 is None or not stage.target_vus:
                continue
            count = metrics.get(f"{prefix}_requests.count", 0)
            results.append(StageResult(vus=stage.target_vus, p95_ms=p95, error_rate=metrics.get(f"{prefix}_failed.rate", 0), rps=count / stage.duration_seconds, metrics=metrics))
        if results:
            return results
        peak = max((s.target_vus or 0 for s in plan.stages), default=0)
        return [StageResult(vus=peak, p95_ms=metrics.get("http_req_duration.p(95)", 0), error_rate=metrics.get("http_req_failed.rate", 0), rps=metrics.get("http_reqs.rate", metrics.get("http_reqs.count", 0)), metrics=metrics)]

    @staticmethod
    async def _target_metrics_snapshot() -> dict[str, float]:
        url = os.environ.get("LOADPILOT_TARGET_METRICS_URL")
        if not url:
            return {}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
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

    @staticmethod
    def _target_metric_deltas(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
        if not after:
            return {}
        saturation = after.get("sandbox_db_pool_saturation_events_total", 0) - before.get("sandbox_db_pool_saturation_events_total", 0)
        wait_sum = after.get("sandbox_db_pool_wait_seconds_sum", 0) - before.get("sandbox_db_pool_wait_seconds_sum", 0)
        wait_count = after.get("sandbox_db_pool_wait_seconds_count", 0) - before.get("sandbox_db_pool_wait_seconds_count", 0)
        output = {"db_pool_saturation_events": max(0, saturation)}
        if saturation > 0:
            output["db_pool_utilization"] = 1.0
        if wait_count > 0:
            output["db_wait_ms"] = max(0, wait_sum / wait_count * 1000)
        return output
