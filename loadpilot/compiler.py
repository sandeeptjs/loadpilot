from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from .models import ApplicationModel, PerformanceTestPlan

_TEMPLATE = r'''import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = {{ base_url }}.replace(/\/+$/, '');
const definitions = {{ steps }};
const plannedStages = {{ instrumented_stages }}.map(stage => ({
  ...stage,
  durationMetric: new Trend(`loadpilot_stage_${stage.suffix}_duration`, true),
  failedMetric: new Rate(`loadpilot_stage_${stage.suffix}_failed`),
  requestsMetric: new Counter(`loadpilot_stage_${stage.suffix}_requests`),
}));
const journeyFailed = new Rate('loadpilot_journey_failed');
const transportFailed = new Rate('loadpilot_transport_failed');
export const options = {{ options }};

function failJourney() { journeyFailed.add(true); sleep(0.5); }

export default function () {
  const state = {};
  for (const step of definitions) {
    const stageAtStart = currentStage();
    let payload = step.payloads.length ? JSON.parse(JSON.stringify(step.payloads[(__VU + __ITER) % step.payloads.length])) : null;
    const headers = { 'Content-Type': 'application/json', 'X-LoadPilot-Run': {{ run_id }} };
    for (const [name, reference] of Object.entries(step.secrets)) {
      if (!__ENV[reference]) { failJourney(); return; }
      if (name === 'TARGET_TOKEN') headers.Authorization = `Bearer ${__ENV[reference]}`;
      else headers[name] = __ENV[reference];
    }
    if (__ENV.TARGET_TOKEN) headers.Authorization = `Bearer ${__ENV.TARGET_TOKEN}`;
    const inputs = {};
    for (const binding of step.bindings) {
      const value = state[binding.stateKey];
      if (value === undefined || value === null) { failJourney(); return; }
      inputs[binding.name] = value;
      if (binding.name === 'Authorization') headers.Authorization = `Bearer ${value}`;
      else if (payload && Object.prototype.hasOwnProperty.call(payload, binding.name)) payload[binding.name] = value;
    }
    let path = step.path;
    for (const parameter of step.parameters) {
      const value = inputs[parameter.name] ?? parameter.example;
      if (parameter.location === 'path') path = path.replace(`{${parameter.name}}`, encodeURIComponent(value));
      if (parameter.location === 'header' && parameter.name.toLowerCase() !== 'authorization') headers[parameter.name] = String(value);
      if (parameter.location === 'query') path += `${path.includes('?') ? '&' : '?'}${encodeURIComponent(parameter.name)}=${encodeURIComponent(value)}`;
    }
    path = path.replace(/\{([^}]+)\}/g, (_, name) => {
      if (inputs[name] === undefined) throw new Error(`Missing runtime path binding: ${name}`);
      return encodeURIComponent(inputs[name]);
    });
    const response = http.request(step.method, BASE_URL + path, payload === null ? null : JSON.stringify(payload), {
      headers, timeout: '10s', redirects: 0,
      tags: { operation_id: step.id, stage: stageAtStart.name },
    });
    const ok = check(response, { 'operation succeeded': r => r.status >= 200 && r.status < 400 });
    transportFailed.add(response.status === 0);
    // Boundary-crossing requests are excluded from plateau capacity estimates.
    if (stageAtStart === currentStage()) {
      stageAtStart.durationMetric.add(response.timings.duration);
      stageAtStart.failedMetric.add(!ok);
      stageAtStart.requestsMetric.add(1);
    }
    if (!ok) { failJourney(); return; }
    for (const extraction of step.extracts) {
      try {
        const value = extraction.path.split('/').filter(Boolean).reduce((current, key) => current?.[key.replace(/~1/g, '/').replace(/~0/g, '~')], response.json());
        if (value === undefined || value === null) { failJourney(); return; }
        state[extraction.stateKey] = value;
      } catch (_) { failJourney(); return; }
    }
    if (step.think > 0) sleep(step.think);
  }
  journeyFailed.add(false);
}

function currentStage() {
  const elapsed = exec.instance.currentTestRunDuration / 1000;
  let boundary = 0;
  for (const stage of plannedStages) {
    boundary += stage.duration;
    if (elapsed < boundary) return stage;
  }
  return plannedStages[plannedStages.length - 1];
}

export function handleSummary(data) {
  return { [__ENV.LOADPILOT_SUMMARY_PATH || 'stdout']: JSON.stringify({ metrics: data.metrics, state: data.state }) };
}
'''


@dataclass(frozen=True)
class CompiledScript:
    content: str
    sha256: str


class K6Compiler:
    def __init__(self):
        self.environment = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)

    def compile(self, plan: PerformanceTestPlan, application: ApplicationModel, *, run_id='pending'):
        endpoints = {e.operation_id: e for e in application.endpoints}
        steps = []
        for journey in plan.journeys:
            for step in journey.steps:
                endpoint = endpoints[step.operation_id]
                if not endpoint.path.startswith('/') or endpoint.path.startswith('//'):
                    raise ValueError('Operation paths must be absolute paths on the allowed target, not URLs')
                bindings, extractions = [], []
                for dependency in application.dependencies:
                    key = dependency.producer_operation_id + ':' + dependency.input_name
                    if not dependency.output_expression.startswith('$response.body#/'):
                        raise ValueError('Only response JSON-pointer dependency expressions are supported')
                    if dependency.consumer_operation_id == endpoint.operation_id:
                        bindings.append({'name': dependency.input_name, 'stateKey': key})
                    if dependency.producer_operation_id == endpoint.operation_id:
                        extractions.append({'stateKey': key, 'path': dependency.output_expression.removeprefix('$response.body#')})
                steps.append({
                    'id': endpoint.operation_id, 'method': endpoint.method, 'path': endpoint.path,
                    'payloads': endpoint.examples, 'bindings': bindings, 'extracts': extractions,
                    'parameters': [p.model_dump() for p in endpoint.parameters if p.required or p.location == 'path'],
                    'secrets': {name: reference.key for name, reference in plan.execution.secret_references.items()},
                    'think': step.think_time_seconds if plan.workload_model == 'closed' else 0,
                })
        stages = [{'duration': f'{stage.duration_seconds}s', 'target': round(stage.target_rps if stage.target_rps is not None else stage.target_vus or 0)} for stage in plan.stages]
        scenario = {'executor': plan.executor, 'stages': stages, 'gracefulStop': '5s'}
        if plan.workload_model == 'open':
            scenario.update(startRate=0, timeUnit='1s', preAllocatedVUs=plan.execution.max_vus, maxVUs=plan.execution.max_vus)
        else:
            scenario.update(startVUs=0, gracefulRampDown='0s')
        thresholds = {}
        for threshold in plan.thresholds:
            thresholds.setdefault(threshold.metric, []).append({'threshold': threshold.expression, 'abortOnFail': threshold.abort_on_fail, 'delayAbortEval': f'{threshold.delay_abort_eval_seconds}s'})
        thresholds['loadpilot_journey_failed'] = ['rate<0.01']
        thresholds['loadpilot_transport_failed'] = [{'threshold': 'rate<0.2', 'abortOnFail': True, 'delayAbortEval': '5s'}]
        options = {'scenarios': {'primary': scenario}, 'thresholds': thresholds, 'summaryTrendStats': ['avg', 'min', 'max', 'p(95)', 'p(99)'], 'tags': {'test_run_id': run_id, 'plan_id': str(plan.id)}, 'maxRedirects': 0}
        content = self.environment.from_string(_TEMPLATE).render(
            base_url=json.dumps(str(application.base_url)), run_id=json.dumps(run_id),
            steps=json.dumps(steps), options=json.dumps(options),
            instrumented_stages=json.dumps([{'name': s.name, 'suffix': re.sub(r'[^a-zA-Z0-9]+', '_', s.name).strip('_').lower(), 'duration': s.duration_seconds} for s in plan.stages]),
        )
        return CompiledScript(content, hashlib.sha256(content.encode()).hexdigest())

    @staticmethod
    def write(script, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script.content, encoding='utf-8', newline='\n')
