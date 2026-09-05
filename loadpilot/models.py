from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class TestType(StrEnum):
    BASELINE = "BASELINE"
    LOAD = "LOAD"
    STRESS = "STRESS"
    SOAK = "SOAK"
    SPIKE = "SPIKE"
    BREAKPOINT = "BREAKPOINT"


class ExecutionBackendType(StrEnum):
    LOCAL = "LOCAL"
    DOCKER = "DOCKER"
    KUBERNETES = "KUBERNETES"


class RunState(StrEnum):
    CREATED = "CREATED"
    DISCOVERING_APPLICATION = "DISCOVERING_APPLICATION"
    GENERATING_DATA = "GENERATING_DATA"
    PLANNING = "PLANNING"
    GENERATING_SCRIPT = "GENERATING_SCRIPT"
    VALIDATING = "VALIDATING"
    SCHEDULED = "SCHEDULED"
    QUEUED = "QUEUED"
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    COLLECTING_TELEMETRY = "COLLECTING_TELEMETRY"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    TIMED_OUT = "TIMED_OUT"


class SecretReference(StrictModel):
    provider: Literal["env", "vault", "kubernetes"] = "env"
    key: str = Field(min_length=1, max_length=256)
    version: str | None = None


class SLOs(StrictModel):
    latency_p95_ms: float | None = Field(default=None, gt=0)
    error_rate: float | None = Field(default=None, ge=0, le=1)
    throughput_rps: float | None = Field(default=None, gt=0)


class ScheduleSpec(StrictModel):
    run_at: datetime | None = None
    recurrence: str | None = None


class PerformanceTestIntent(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    raw_prompt: str = Field(min_length=3, max_length=20_000)
    test_type: TestType
    target_environment: str = "local"
    target_endpoints: list[str] = Field(default_factory=list)
    expected_traffic: str | None = None
    target_concurrency: int | None = Field(default=None, gt=0)
    target_rps: float | None = Field(default=None, gt=0)
    duration_seconds: int | None = Field(default=None, gt=0)
    slos: SLOs = Field(default_factory=SLOs)
    credentials_reference: SecretReference | None = None
    schedule: ScheduleSpec | None = None
    geographic_requirements: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    inferred_values: dict[str, Any] = Field(default_factory=dict)
    ambiguities: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class Parameter(StrictModel):
    name: str
    location: Literal["path", "query", "header", "cookie", "body"]
    required: bool = False
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    example: Any = None


class Endpoint(StrictModel):
    operation_id: str
    method: str
    path: str
    summary: str | None = None
    parameters: list[Parameter] = Field(default_factory=list)
    request_schema: dict[str, Any] | None = None
    response_schemas: dict[str, dict[str, Any]] = Field(default_factory=dict)
    auth_schemes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    examples: list[Any] = Field(default_factory=list)


class OperationDependency(StrictModel):
    producer_operation_id: str
    consumer_operation_id: str
    output_expression: str
    input_name: str
    confidence: float = Field(ge=0, le=1)
    source: Literal["openapi-link", "schema-inference", "runtime", "manual"]


class ApplicationModel(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    base_url: HttpUrl | None = None
    source_type: Literal["openapi", "graphql", "postman", "har", "manual"]
    source_fingerprint: str
    endpoints: list[Endpoint]
    dependencies: list[OperationDependency] = Field(default_factory=list)
    auth_schemes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JourneyStep(StrictModel):
    operation_id: str
    extract: dict[str, str] = Field(default_factory=dict)
    think_time_seconds: float = Field(default=0.5, ge=0, le=60)


class UserJourney(StrictModel):
    name: str
    weight: float = Field(default=1, gt=0)
    steps: list[JourneyStep] = Field(min_length=1)


class LoadStage(StrictModel):
    name: str
    duration_seconds: int = Field(gt=0)
    target_vus: int | None = Field(default=None, ge=0)
    target_rps: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def has_target(self) -> LoadStage:
        if self.target_vus is None and self.target_rps is None:
            raise ValueError("stage requires target_vus or target_rps")
        return self


class PerformanceThreshold(StrictModel):
    metric: str
    expression: str
    abort_on_fail: bool = False
    delay_abort_eval_seconds: int = Field(default=0, ge=0)


class ExecutionPlan(StrictModel):
    backend: ExecutionBackendType = ExecutionBackendType.LOCAL
    parallelism: int = Field(default=1, ge=1, le=100)
    timeout_seconds: int = Field(default=3600, ge=1)
    environment: dict[str, str] = Field(default_factory=dict)
    secret_references: dict[str, SecretReference] = Field(default_factory=dict)


class PerformanceTestPlan(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    intent_id: UUID
    application_id: UUID
    test_type: TestType
    workload_model: Literal["closed", "open"]
    executor: str
    stages: list[LoadStage] = Field(min_length=1)
    journeys: list[UserJourney] = Field(min_length=1)
    thresholds: list[PerformanceThreshold] = Field(default_factory=list)
    payload_sources: list[str] = Field(default_factory=list)
    abort_conditions: list[str] = Field(default_factory=list)
    observability_requirements: list[str] = Field(default_factory=list)
    execution: ExecutionPlan = Field(default_factory=ExecutionPlan)


class TelemetryWindow(StrictModel):
    start: datetime
    end: datetime
    padding_before_seconds: int = Field(default=120, ge=0)
    padding_after_seconds: int = Field(default=120, ge=0)


class RunArtifact(StrictModel):
    kind: str
    uri: str
    sha256: str | None = None


class TestRun(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    experiment_id: UUID | None = None
    state: RunState = RunState.CREATED
    created_at: datetime = Field(default_factory=utcnow)
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    execution_backend: ExecutionBackendType
    workers: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    artifacts: list[RunArtifact] = Field(default_factory=list)
    telemetry_window: TelemetryWindow | None = None
    error: str | None = None
    cancellation_reason: str | None = None


class MetricPoint(StrictModel):
    timestamp: datetime
    value: float


class TelemetrySeries(StrictModel):
    metric: str
    labels: dict[str, str] = Field(default_factory=dict)
    points: list[MetricPoint] = Field(default_factory=list)


class Alert(StrictModel):
    fingerprint: str
    name: str
    starts_at: datetime
    ends_at: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class AlertBatch(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    received_at: datetime = Field(default_factory=utcnow)
    source: str = "alertmanager"
    alerts: list[Alert] = Field(default_factory=list)


class CorrelatedIncident(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    service: str | None = None
    resource: str | None = None
    alerts: list[Alert] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    unrelated_alerts: list[str] = Field(default_factory=list)


class Investigation(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    summary: str
    observed_degradation_point: str | None = None
    evidence: list[str] = Field(default_factory=list)
    likely_root_cause: str | None = None
    alternative_hypotheses: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    recommended_next_experiment: str | None = None
    potential_remediation: list[str] = Field(default_factory=list)


class ExperimentBudget(StrictModel):
    max_runs: int = Field(default=4, ge=1, le=20)
    max_vus: int = Field(default=2_000, ge=1)
    max_duration_seconds: int = Field(default=14_400, ge=1)
    max_requests: int = Field(default=10_000_000, ge=1)
    max_cost_usd: float = Field(default=50, ge=0)


class Experiment(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    budget: ExperimentBudget = Field(default_factory=ExperimentBudget)
    run_ids: list[UUID] = Field(default_factory=list)
    lower_bound_vus: int | None = None
    upper_bound_vus: int | None = None
    status: Literal["ACTIVE", "COMPLETED", "CANCELED"] = "ACTIVE"


class RemediationAction(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    action: Literal["RestartDeployment", "ScaleDeployment", "IncreaseReplicaCount", "RollbackDeployment", "ClearAllowedCache", "ModifyAllowedConfig"]
    requested_by: str
    reason: str
    parameters: dict[str, Any]
    target: str
    risk_level: Literal["low", "medium", "high"]
    approval_required: bool = True
    approved_by: str | None = None
    executed_at: datetime | None = None
    result: dict[str, Any] | None = None
    rollback_plan: str


class AuditEvent(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=utcnow)
    actor: str
    agent_tool: str
    action: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    reason: str
    related_test_id: UUID | None = None
    related_investigation_id: UUID | None = None
