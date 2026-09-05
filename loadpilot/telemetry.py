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
        graph = defaultdict(set)
        for left, right in dependency_edges:
            graph[left].add(right)
            graph[right].add(left)
        groups = defaultdict(list)
        seen = set()
        for alert in alerts:
            if alert.starts_at > run_end or (alert.ends_at is not None and alert.ends_at < run_start):
                continue
            labels = alert.labels
            scope = (labels.get('environment', ''), labels.get('target', ''), labels.get('test_run_id', ''))
            service = labels.get('service') or labels.get('app') or 'unknown'
            resource = labels.get('pod') or labels.get('instance') or labels.get('database') or service
            identity = (*scope, alert.fingerprint, service, resource)
            if identity in seen:
                continue
            seen.add(identity)
            groups[(*scope, service, resource)].append(alert)
        remaining = set(groups)
        incidents = []
        while remaining:
            first = min(remaining)
            remaining.remove(first)
            queue, component = [first], [first]
            while queue:
                node = queue.pop()
                connected = [other for other in sorted(remaining) if other[:3] == node[:3] and other[3] in graph[node[3]]]
                for other in connected:
                    remaining.remove(other)
                    queue.append(other)
                    component.append(other)
            combined = [alert for key in component for alert in groups[key]]
            incidents.append(CorrelatedIncident(title=f"{first[3]} degradation during test window", service=first[3], resource=first[4], alerts=combined, signals=sorted({alert.name for alert in combined})))
        return incidents
