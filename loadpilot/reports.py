"""Measured evidence, local alert rules, and run-scoped correlation."""
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from pydantic import Field

from .models import Alert, AlertBatch, StrictModel
from .telemetry import AlertCorrelator


class Report(StrictModel):
    id: UUID
    stages: list[dict] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    correlation: dict = Field(default_factory=dict)
    summary_mode: str = 'offline'
    scope: str = 'One target and one workload per queue; modeled sandbox resources are labeled explicitly.'


def build_report(service, run, plan, investigation):
    stages = service._stage_results(plan, run.metrics)
    samples = service.store.samples(run.id, limit=10000)
    intent = service.detail(run.id)['intent']
    application = service.detail(run.id)['application']
    target = str(application.base_url).rstrip('/')
    alerts = []
    for sample in samples:
        metrics = sample['metrics']
        timestamp = datetime.fromisoformat(sample['timestamp'])
        names = []
        if intent.slos.latency_p95_ms and metrics.get('http_req_duration.p(95)', 0) > intent.slos.latency_p95_ms:
            names.append('MeasuredLatencyHigh')
        if intent.slos.error_rate is not None and metrics.get('http_req_failed.rate', 0) > intent.slos.error_rate:
            names.append('MeasuredErrorRateHigh')
        active, size = metrics.get('sandbox_db_pool_active'), metrics.get('sandbox_db_pool_size')
        if active is not None and size and active / size >= .9:
            names.append('ModeledPoolBusy')
        for name in names:
            alerts.append(Alert(fingerprint=f'{run.id}:{name}', name=name, starts_at=timestamp, labels={'test_run_id': str(run.id), 'target': target, 'environment': intent.target_environment, 'service': 'pool' if name == 'ModeledPoolBusy' else 'application', 'source': 'local-measured-rule'}))
    excluded = 0
    for batch in service.store.list_entities('alert_batch', AlertBatch, 10000):
        for alert in batch.alerts:
            # Alerts without reliable target/run identity are kept out of run evidence.
            run_match = alert.labels.get('test_run_id') == str(run.id)
            target_match = alert.labels.get('target', '').rstrip('/') == target and alert.labels.get('environment') == intent.target_environment
            if (run_match or target_match) and alert.starts_at <= run.telemetry_window.end and (alert.ends_at is None or alert.ends_at >= run.telemetry_window.start):
                alerts.append(alert)
            else:
                excluded += 1
    unique = {}
    for alert in alerts:
        key = (alert.fingerprint, alert.labels.get('environment', ''), alert.labels.get('service', ''), alert.labels.get('target', ''))
        if key not in unique:
            unique[key] = alert
    incidents = AlertCorrelator().correlate(unique.values(), run_start=run.telemetry_window.start, run_end=run.telemetry_window.end, dependency_edges=[('application', 'pool')])
    evidence = {f'e{index + 1}': item for index, item in enumerate(investigation.evidence)}
    evidence['assessment'] = investigation.summary
    evidence['measurement'] = {'http_requests': run.metrics.get('http_reqs.count'), 'p95_ms': run.metrics.get('http_req_duration.p(95)'), 'error_rate': run.metrics.get('http_req_failed.rate'), 'slo_passed': run.slo_passed}
    retained = [sample['metrics']['sandbox_retained_memory_bytes'] for sample in samples if 'sandbox_retained_memory_bytes' in sample['metrics']]
    if retained:
        evidence['soak_memory'] = {'first_bytes': retained[0], 'last_bytes': retained[-1], 'growth_bytes': retained[-1] - retained[0], 'meaning': 'Deliberately retained sandbox memory, not measured process RSS'}
    return Report(id=run.id, stages=[asdict(stage) for stage in stages], evidence=evidence, summary_mode=run.ai_mode,
                  correlation={'received_notifications': len(alerts), 'distinct_alerts': len(unique), 'duplicates_removed': len(alerts) - len(unique), 'incident_count': len(incidents), 'notification_reduction_pct': round(100 * (1 - len(incidents) / len(alerts)), 1) if alerts else 0, 'excluded_unrelated_notifications': excluded, 'incidents': [incident.model_dump(mode='json') for incident in incidents], 'rules': ['Exact run ID or target + environment', 'Run-window overlap', 'Fingerprint deduplication', 'Connected service dependencies within the same target and environment']})
