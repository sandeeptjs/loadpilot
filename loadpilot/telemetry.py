from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

import httpx

from .models import Alert, CorrelatedIncident, TelemetrySeries, TelemetryWindow


class PrometheusClient:
    def __init__(self, base_url: str = "http://localhost:9090", timeout: float = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def query_range(self, query: str, window: TelemetryWindow, step_seconds: int = 15) -> list[TelemetrySeries]:
        params = {"query": query, "start": window.start.timestamp() - window.padding_before_seconds, "end": window.end.timestamp() + window.padding_after_seconds, "step": step_seconds}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/v1/query_range", params=params)
            response.raise_for_status()
        result = response.json()["data"]["result"]
        return [TelemetrySeries(metric=query, labels=item.get("metric", {}), points=[{"timestamp": datetime.fromtimestamp(float(ts)).astimezone(), "value": float(value)} for ts, value in item.get("values", [])]) for item in result]


class AlertCorrelator:
    def correlate(self, alerts: Iterable[Alert], *, run_start: datetime, run_end: datetime, dependency_edges: Iterable[tuple[str, str]] = ()) -> list[CorrelatedIncident]:
        graph: dict[str, set[str]] = defaultdict(set)
        for left, right in dependency_edges:
            graph[left].add(right)
            graph[right].add(left)
        relevant = [a for a in alerts if a.starts_at <= run_end and (a.ends_at is None or a.ends_at >= run_start)]
        groups: dict[tuple[str, str], list[Alert]] = defaultdict(list)
        for alert in relevant:
            service = alert.labels.get("service") or alert.labels.get("app") or "unknown"
            resource = alert.labels.get("pod") or alert.labels.get("instance") or alert.labels.get("database") or service
            groups[(service, resource)].append(alert)
        incidents: list[CorrelatedIncident] = []
        consumed: set[tuple[str, str]] = set()
        for key, grouped in groups.items():
            if key in consumed:
                continue
            service, resource = key
            combined = list(grouped)
            for linked in graph.get(service, set()):
                for other_key, other in groups.items():
                    if other_key[0] == linked:
                        combined.extend(other)
                        consumed.add(other_key)
            consumed.add(key)
            names = sorted({a.name for a in combined})
            incidents.append(CorrelatedIncident(title=f"{service} degradation during test window", service=service, resource=resource, alerts=combined, signals=names))
        return incidents

