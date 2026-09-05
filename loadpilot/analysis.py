from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from .models import Investigation, PerformanceTestPlan


@dataclass(frozen=True)
class StageResult:
    vus: int
    p95_ms: float
    error_rate: float
    rps: float
    metrics: dict[str, float]


class ResultAnalyzer:
    def analyze(self, run_id: UUID, plan: PerformanceTestPlan, stages: Iterable[StageResult]) -> Investigation:
        values = sorted(stages, key=lambda item: item.vus)
        latency_slo = self._threshold(plan, "http_req_duration", "p(95)<")
        error_slo = self._threshold(plan, "http_req_failed", "rate<")
        stable = [s for s in values if (latency_slo is None or s.p95_ms < latency_slo) and (error_slo is None or s.error_rate < error_slo)]
        failing = [s for s in values if s not in stable]
        max_stable = stable[-1] if stable else None
        first_failure = failing[0] if failing else None
        evidence: list[str] = []
        if max_stable:
            evidence.append(f"{max_stable.vus} VUs: p95 {max_stable.p95_ms:g} ms, errors {max_stable.error_rate * 100:.2f}%, {max_stable.rps:g} RPS")
        if first_failure:
            evidence.append(f"{first_failure.vus} VUs: p95 {first_failure.p95_ms:g} ms, errors {first_failure.error_rate * 100:.2f}%, {first_failure.rps:g} RPS")
        root, root_evidence, confidence = self._root_cause(values)
        evidence.extend(root_evidence)
        next_experiment = None
        if max_stable and first_failure and first_failure.vus - max_stable.vus > 25:
            midpoint = (max_stable.vus + first_failure.vus) // 2
            next_experiment = f"Rerun the {max_stable.vus}-{first_failure.vus} VU range with a midpoint stage at {midpoint} VUs."
        summary = f"Maximum observed stable load: {max_stable.vus} VUs." if max_stable else "No tested stage met all configured SLOs."
        return Investigation(run_id=run_id, summary=summary, observed_degradation_point=f"Between {max_stable.vus} and {first_failure.vus} VUs" if max_stable and first_failure else None, evidence=evidence, likely_root_cause=root, alternative_hypotheses=["Downstream service saturation", "Application worker or queue contention"] if root else [], confidence=confidence, recommended_next_experiment=next_experiment, potential_remediation=["Review the saturated resource limit and rerun a bounded experiment"] if root else [])

    @staticmethod
    def _threshold(plan: PerformanceTestPlan, metric: str, prefix: str) -> float | None:
        item = next((t for t in plan.thresholds if t.metric == metric and t.expression.startswith(prefix)), None)
        return float(item.expression[len(prefix):]) if item else None

    @staticmethod
    def _root_cause(values: list[StageResult]) -> tuple[str | None, list[str], float]:
        if not values:
            return None, [], 0
        peak = values[-1]
        pool = peak.metrics.get("db_pool_utilization", 0)
        wait = peak.metrics.get("db_wait_ms", 0)
        cpu = peak.metrics.get("app_cpu_utilization")
        if pool >= .9 and wait > 0:
            evidence = [f"DB pool reached {pool * 100:.0f}% while average DB wait was {wait:g} ms."]
            confidence = .78
            if cpu is not None and cpu < .75:
                evidence.append(f"Application CPU remained at {cpu * 100:.0f}%, below CPU saturation.")
                confidence = .86
            return "Database connection-pool saturation", evidence, confidence
        memory_growth = peak.metrics.get("memory_growth_pct", 0)
        if memory_growth > 20:
            return "Probable memory growth or leak under sustained load", [f"Memory increased {memory_growth:g}% over the test window."], .74
        if cpu is not None and cpu >= .9:
            return "Application CPU saturation", [f"Application CPU reached {cpu * 100:.0f}%."], .8
        return None, [], .35


def compare_metrics(current: dict[str, float], baseline: dict[str, float]) -> dict[str, dict[str, float | bool]]:
    output = {}
    for metric, value in current.items():
        if metric not in baseline:
            continue
        old = baseline[metric]
        delta_pct = ((value - old) / old * 100) if old else 0
        worse_when_higher = metric not in {"throughput_rps", "max_stable_vus"}
        output[metric] = {"baseline": old, "current": value, "delta_pct": delta_pct, "regression": delta_pct > 10 if worse_when_higher else delta_pct < -10}
    return output
