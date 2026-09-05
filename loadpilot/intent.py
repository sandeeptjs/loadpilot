from __future__ import annotations

import re

from .models import PerformanceTestIntent, ScheduleSpec, SLOs, TestType

_DURATION = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*-?\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)", re.IGNORECASE)
_VUS = re.compile(r"(?:roughly|approximately|about|at|with)?\s*(\d[\d,]*)\s*(?:concurrent\s+users?|users?|vus?)", re.IGNORECASE)
_RPS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:rps|requests?\s*(?:per|/)\s*second)", re.IGNORECASE)
_P95 = re.compile(r"p95\s*(?:stays?|remain|under|below|exceeds?|<|of|=|:) *?(?:under|below|<)?\s*(\d+(?:\.\d+)?)\s*(ms|s)?", re.IGNORECASE)
_ERROR = re.compile(r"(?:errors?|error\s*rate)\s*(?:stays?|remain|under|below|exceeds?|<|of|=|:) *?(?:under|below|<)?\s*(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)


class DeterministicIntentCompiler:
    """Safe local compiler and validator; an LLM adapter may enrich its structured result."""

    def compile(self, prompt: str, *, environment: str = "local") -> PerformanceTestIntent:
        text = " ".join(prompt.strip().split())
        lowered = text.lower()
        inferred: dict[str, object] = {}
        ambiguities: list[str] = []

        if "soak" in lowered or "gradual degradation" in lowered or "resource leak" in lowered:
            test_type = TestType.SOAK
        elif "breakpoint" in lowered or "maximum load" in lowered or "until" in lowered:
            test_type = TestType.BREAKPOINT
        elif "stress" in lowered:
            test_type = TestType.STRESS
        elif "spike" in lowered:
            test_type = TestType.SPIKE
        elif "baseline" in lowered or "current build" in lowered:
            test_type = TestType.BASELINE
        else:
            test_type = TestType.LOAD
            inferred["test_type"] = "LOAD"

        duration = self._duration(text)
        if duration is None:
            duration = {TestType.SOAK: 7200, TestType.BASELINE: 600}.get(test_type, 1200)
            inferred["duration_seconds"] = duration

        vus_match = _VUS.search(text)
        concurrency = int(vus_match.group(1).replace(",", "")) if vus_match else None
        if concurrency is None:
            concurrency = 100
            inferred["target_concurrency"] = concurrency

        rps_match = _RPS.search(text)
        target_rps = float(rps_match.group(1)) if rps_match else None
        p95_match = _P95.search(text)
        latency = float(p95_match.group(1)) if p95_match else None
        if p95_match and (p95_match.group(2) or "ms").lower() == "s":
            latency *= 1000
        error_match = _ERROR.search(text)
        error_rate = float(error_match.group(1)) / 100 if error_match else None
        if latency is None:
            ambiguities.append("No p95 latency SLO was provided")
        if error_rate is None:
            ambiguities.append("No error-rate SLO was provided")

        endpoints = []
        for term in ("checkout", "payments", "login", "products", "cart", "orders"):
            if term in lowered:
                endpoints.append(term)

        schedule = None
        if "tomorrow" in lowered or "midnight" in lowered or " at " in lowered and "run" in lowered:
            schedule = ScheduleSpec(recurrence="natural-language schedule requires provider resolution")
            ambiguities.append("Schedule needs timezone-aware resolution")

        known = 5 - len(ambiguities)
        confidence = max(0.45, min(0.98, 0.72 + known * 0.04 - len(inferred) * 0.03))
        return PerformanceTestIntent(
            raw_prompt=text,
            test_type=test_type,
            target_environment=environment,
            target_endpoints=endpoints,
            expected_traffic=f"approximately {concurrency} concurrent users" if vus_match else None,
            target_concurrency=concurrency,
            target_rps=target_rps,
            duration_seconds=duration,
            slos=SLOs(latency_p95_ms=latency, error_rate=error_rate),
            schedule=schedule,
            inferred_values=inferred,
            ambiguities=ambiguities,
            confidence=confidence,
        )

    @staticmethod
    def _duration(text: str) -> int | None:
        match = _DURATION.search(text)
        if not match:
            return None
        value = float(match.group("value"))
        unit = match.group("unit").lower()
        multiplier = 3600 if unit.startswith(("hour", "hr")) else 60 if unit.startswith(("minute", "min")) else 1
        return int(value * multiplier)


class StructuredLLMIntentCompiler:
    """Provider-neutral boundary. Callers supply a function returning schema-compatible JSON."""

    def __init__(self, structured_generate):
        self.structured_generate = structured_generate

    def compile(self, prompt: str, *, environment: str = "local") -> PerformanceTestIntent:
        data = self.structured_generate(prompt, PerformanceTestIntent.model_json_schema())
        data.setdefault("raw_prompt", prompt)
        data.setdefault("target_environment", environment)
        return PerformanceTestIntent.model_validate(data)
