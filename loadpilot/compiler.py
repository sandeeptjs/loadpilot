from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from .models import ApplicationModel, PerformanceTestPlan

_TEMPLATE = r'''import http from 'k6/http';
import encoding from 'k6/encoding';
import { check, sleep } from 'k6';
import exec from 'k6/execution';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = {{ base_url }}.replace(/\/+$/, '');
const journeys = {{ steps }};
const plannedStages = {{ instrumented_stages }}.map(stage => ({
  ...stage,
  durationMetric: new Trend(`loadpilot_stage_${stage.suffix}_duration`, true),
  failedMetric: new Rate(`loadpilot_stage_${stage.suffix}_failed`),
  requestsMetric: new Counter(`loadpilot_stage_${stage.suffix}_requests`),
}));
const journeyFailed = new Rate('loadpilot_journey_failed');
const transportFailed = new Rate('loadpilot_transport_failed');
export const options = __ENV.LOADPILOT_PREFLIGHT !== undefined ? {
  scenarios: { preflight: { executor: 'shared-iterations', vus: 1, iterations: 1, maxDuration: '60s' } },
  thresholds: { loadpilot_journey_failed: ['rate==0'], checks: ['rate==1'] },
} : {{ options }};

function pointer(value, path) {
  return path.split('/').slice(1).reduce((v, k) => v?.[k.replace(/~1/g, '/').replace(/~0/g, '~')], value);
}
function resolve(value, state) {
  if (Array.isArray(value)) return value.map(v => resolve(v, state));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k,v]) => [k, resolve(v,state)]));
  if (typeof value !== 'string') return value;
  if (value.startsWith('env:TARGET_')) {
    const secret = __ENV[value.slice(4)];
    if (!secret) throw new Error('Missing target credential reference');
    return secret;
  }
  const exact = value.match(/^\$\{([^}]+)\}$/);
  if (exact) {
    if (state[exact[1]] === undefined) throw new Error('Missing scenario variable');
    return state[exact[1]];
  }
  return value.replace(/\$\{([^}]+)\}/g, (_, key) => {
    if (state[key] === undefined) throw new Error('Missing scenario variable');
    return String(state[key]);
  });
}

let activeStep = 'journey';
function failJourney(reason = 'missing runtime input') {
  if (__ENV.LOADPILOT_PREFLIGHT !== undefined) check(false, { [activeStep + ': ' + reason]: () => false });
  journeyFailed.add(true); sleep(0.5);
}

export default function () {
  const state = { __VU, __ITER, __RUN_ID: {{ run_id }}, __TIMESTAMP: new Date().toISOString() };
  let selected;
  if (__ENV.LOADPILOT_PREFLIGHT !== undefined) selected = journeys[Number(__ENV.LOADPILOT_PREFLIGHT)];
  else {
    let ticket = Math.random() * journeys.reduce((sum,j) => sum + j.weight, 0);
    selected = journeys.find(j => (ticket -= j.weight) < 0) || journeys[journeys.length - 1];
  }
  for (const [name, rows] of Object.entries(selected.datasets)) state[name] = rows[(__VU - 1 + __ITER) % rows.length];
  try {
  for (const step of selected.steps) {
   activeStep = step.id;
   if (step.when && JSON.stringify(state[step.when.variable]) !== JSON.stringify(resolve(step.when.equals, state))) continue;
   for (let repetition = 0; repetition < step.repeat; repetition++) {
    let payload = step.payloads.length ? JSON.parse(JSON.stringify(step.payloads[(__VU + __ITER) % step.payloads.length])) : null;
    const headers = { 'Content-Type': step.contentType, 'X-LoadPilot-Run': {{ run_id }} };
    for (const [name, reference] of Object.entries(step.secrets)) {
      if (!__ENV[reference]) { failJourney(); return; }
      if (name === 'TARGET_TOKEN') headers.Authorization = `Bearer ${__ENV[reference]}`;
      else if (!name.startsWith('TARGET_')) headers[name] = __ENV[reference];
    }
    if (__ENV.TARGET_TOKEN) headers.Authorization = `Bearer ${__ENV.TARGET_TOKEN}`;
    if (step.body !== null) payload = resolve(step.body, state);
    Object.assign(headers, resolve(step.headers, state));
    if (step.basicAuth) headers.Authorization = 'Basic ' + encoding.b64encode(resolve(step.basicAuth.username, state) + ':' + resolve(step.basicAuth.password, state));
    if (step.contentType === 'multipart/form-data') {
      delete headers['Content-Type'];
      payload = payload || {};
      for (const [field, part] of Object.entries(step.files)) {
        const content = resolve(part.content, state);
        if (typeof content !== 'string' || content.length > 65536) throw new Error('Upload content exceeds its limit');
        payload[field] = http.file(content, part.filename, part.content_type);
      }
    }
    const inputs = resolve(step.inputs, state);
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
      if (value === undefined || value === null) {
        if (parameter.required || parameter.location === 'path') throw new Error('Missing required parameter');
        continue;
      }
      if (parameter.location === 'path') path = path.replace(`{${parameter.name}}`, encodeURIComponent(value));
      if (parameter.location === 'header' && parameter.name.toLowerCase() !== 'authorization') headers[parameter.name] = String(value);
      if (value === undefined || value === null) continue;
      if (parameter.location === 'cookie') headers.Cookie = (headers.Cookie ? headers.Cookie + '; ' : '') + `${parameter.name}=${encodeURIComponent(value)}`;
      if (parameter.location === 'query') {
        let pairs;
        if (Array.isArray(value)) pairs = parameter.explode ? value.map(v => [parameter.name, v]) : [[parameter.name, value.join(parameter.style === 'spaceDelimited' ? ' ' : parameter.style === 'pipeDelimited' ? '|' : ',')]];
        else if (value && typeof value === 'object') pairs = parameter.style === 'deepObject' ? Object.entries(value).map(([k,v]) => [`${parameter.name}[${k}]`, v]) : parameter.explode ? Object.entries(value) : [[parameter.name, Object.entries(value).flat().join(',')]];
        else pairs = [[parameter.name, value]];
        for (const [key, item] of pairs) path += `${path.includes('?') ? '&' : '?'}${encodeURIComponent(key)}=${encodeURIComponent(item)}`;
      }
    }
    path = path.replace(/\{([^}]+)\}/g, (_, name) => {
      if (inputs[name] === undefined) throw new Error(`Missing runtime path binding: ${name}`);
      return encodeURIComponent(inputs[name]);
    });
    let response;
    for (let attempt = 0; attempt <= step.retries; attempt++) {
    const requestStage = currentStage();
    response = http.request(step.method, (step.baseUrl || BASE_URL) + path, payload === null ? null : step.contentType === 'application/json' ? JSON.stringify(payload) : step.contentType === 'text/plain' ? String(payload) : payload, {
      headers, timeout: '10s', redirects: 0,
      responseCallback: step.statuses.length ? http.expectedStatuses(...step.statuses) : http.expectedStatuses({min: 200, max: 399}),
      tags: { operation_id: step.id, journey: selected.name, stage: requestStage.name },
    });
    transportFailed.add(response.status === 0);
    if (requestStage === currentStage()) {
      requestStage.durationMetric.add(response.timings.duration);
      requestStage.failedMetric.add(!(step.statuses.length ? step.statuses.includes(response.status) : response.status >= 200 && response.status < 400));
      requestStage.requestsMetric.add(1);
    }
    if (![0, 429, 502, 503, 504].includes(response.status) || attempt === step.retries) break;
    sleep(Math.min(2, .25 * (2 ** attempt)));
    }
    const ok = check(response, { [step.id + ' succeeded']: r => (step.statuses.length ? step.statuses.includes(r.status) : r.status >= 200 && r.status < 400) && step.assertions.every(a => { try { return JSON.stringify(pointer(r.json(), a.pointer)) === JSON.stringify(resolve(a.equals, state)); } catch (_) { return false; } }) });
    if (!ok) { failJourney('unexpected response or assertion, HTTP ' + response.status); return; }
    for (const extraction of step.extracts) {
      try {
        const value = extraction.path.split('/').filter(Boolean).reduce((current, key) => current?.[key.replace(/~1/g, '/').replace(/~0/g, '~')], response.json());
        if (value === undefined || value === null) { failJourney(); return; }
        state[extraction.stateKey] = value;
      } catch (_) { failJourney(); return; }
    }
    if (step.until) {
      if (JSON.stringify(pointer(response.json(), step.until.pointer)) === JSON.stringify(resolve(step.until.equals, state))) break;
      if (repetition === step.repeat - 1) { failJourney('polling attempt budget exhausted'); return; }
      sleep(step.pollInterval);
    }
    if (step.think > 0 && __ENV.LOADPILOT_PREFLIGHT === undefined) sleep(step.think);
   }
  }
  journeyFailed.add(false);
  } catch (_) { failJourney('runtime expression or extraction failed'); }
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
  return { [__ENV.LOADPILOT_SUMMARY_PATH || 'stdout']: JSON.stringify({ metrics: data.metrics, state: data.state, checks: data.root_group }) };
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
        journeys = []
        for journey in plan.journeys:
            steps = []
            for step in journey.steps:
                endpoint = endpoints[step.operation_id]
                if not endpoint.path.startswith('/') or endpoint.path.startswith('//'):
                    raise ValueError('Operation paths must be absolute paths on the allowed target, not URLs')
                if endpoint.content_type == 'multipart/form-data' and not step.files:
                    raise ValueError('Multipart requests require explicit files with bounded content')
                bindings, extractions = [], []
                for dependency in application.dependencies if journey.infer_dependencies else []:
                    key = dependency.producer_operation_id + ':' + dependency.input_name
                    if not dependency.output_expression.startswith('$response.body#/'):
                        raise ValueError('Only response JSON-pointer dependency expressions are supported')
                    if dependency.consumer_operation_id == endpoint.operation_id:
                        bindings.append({'name': dependency.input_name, 'stateKey': key})
                    if dependency.producer_operation_id == endpoint.operation_id:
                        extractions.append({'stateKey': key, 'path': dependency.output_expression.removeprefix('$response.body#')})
                extractions.extend({'stateKey': key, 'path': pointer} for key, pointer in step.extract.items() if pointer.startswith('/'))
                steps.append({
                    'files': {key: value.model_dump() for key, value in step.files.items()},
                    'when': step.when.model_dump() if step.when else None,
                    'until': step.until.model_dump() if step.until else None, 'pollInterval': step.poll_interval_seconds, 'retries': step.retries,
                    'basicAuth': step.basic_auth.model_dump() if step.basic_auth else None,
                    'baseUrl': str(endpoint.base_url).rstrip('/') if endpoint.base_url else None,
                    'inputs': step.inputs, 'headers': step.headers, 'body': step.body,
                    'statuses': step.expected_statuses, 'assertions': [a.model_dump() for a in step.assertions], 'repeat': step.repeat,
                    'id': endpoint.operation_id, 'method': endpoint.method, 'path': endpoint.path,
                    'contentType': endpoint.content_type, 'payloads': endpoint.examples, 'bindings': bindings, 'extracts': extractions,
                    'parameters': [p.model_dump() for p in endpoint.parameters if p.required or p.location == 'path' or p.name in step.inputs],
                    'secrets': {name: reference.key for name, reference in plan.execution.secret_references.items()},
                    'think': step.think_time_seconds if plan.workload_model == 'closed' else 0,
                })
            journeys.append({'name': journey.name, 'weight': journey.weight, 'datasets': journey.datasets, 'steps': steps})
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
            steps=json.dumps(journeys), options=json.dumps(options),
            instrumented_stages=json.dumps([{'name': s.name, 'suffix': re.sub(r'[^a-zA-Z0-9]+', '_', s.name).strip('_').lower(), 'duration': s.duration_seconds} for s in plan.stages]),
        )
        return CompiledScript(content, hashlib.sha256(content.encode()).hexdigest())

    @staticmethod
    def write(script, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script.content, encoding='utf-8', newline='\n')
