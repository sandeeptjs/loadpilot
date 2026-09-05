from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from .models import ApplicationModel, PerformanceTestPlan

_TEMPLATE = r'''import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = (__ENV.TARGET_BASE_URL || {{ base_url }}).replace(/\/+$/, '');
const runErrors = new Counter('loadpilot_errors');
const journeyDuration = new Trend('loadpilot_journey_duration', true);
const plannedStages = {{ instrumented_stages }}.map((stage) => ({
  ...stage,
  requestDuration: new Trend(`loadpilot_stage_${stage.metricSuffix}_duration`, true),
  failures: new Rate(`loadpilot_stage_${stage.metricSuffix}_failed`),
  requests: new Counter(`loadpilot_stage_${stage.metricSuffix}_requests`),
}));

export const options = {
  tags: {{ tags }},
  scenarios: {
    primary: {
      executor: {{ executor }},
      startVUs: 0,
      stages: {{ stages }},
      gracefulRampDown: '30s',
    },
  },
  thresholds: {{ thresholds }},
};

export function setup() {
  return { startedAt: new Date().toISOString() };
}

export default function (data) {
  const started = Date.now();
  const state = {};
  const activeStage = currentStage(data);
  group('primary', function () {
{% for step in steps %}
    {
      const url = BASE_URL + renderPath({{ step.path }}, state);
      const payload = {{ step.payload }};
      const params = { headers: { 'Content-Type': 'application/json', ...authHeaders() }, tags: { operation_id: {{ step.operation_id }} } };
      const response = http.request({{ step.method }}, url, payload === null ? null : JSON.stringify(resolve(payload, state)), params);
      const ok = check(response, { {{ step.check_name }}: (r) => r.status >= 200 && r.status < 400 });
      if (!ok) runErrors.add(1, { operation_id: {{ step.operation_id }} });
      activeStage.requestDuration.add(response.timings.duration);
      activeStage.failures.add(!ok);
      activeStage.requests.add(1);
{% for extraction in step.extractions %}
      try { state[{{ extraction.name }}] = readPath(response.json(), {{ extraction.path }}); } catch (_) { /* optional correlation */ }
{% endfor %}
      sleep({{ step.think_time }});
    }
{% endfor %}
  });
  journeyDuration.add(Date.now() - started);
}

function authHeaders() {
  const token = __ENV.TARGET_TOKEN;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function renderPath(path, state) {
  return path.replace(/\{([^}]+)\}/g, (_, key) => encodeURIComponent(state[key] ?? '1'));
}

function resolve(value, state) {
  if (Array.isArray(value)) return value.map((v) => resolve(v, state));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, resolve(v, state)]));
  if (typeof value === 'string') return value.replace(/\{\{([^}]+)\}\}/g, (_, key) => state[key] ?? `${__VU}-${__ITER}`);
  return value;
}

function readPath(value, path) {
  return path.split('.').filter(Boolean).reduce((current, key) => current?.[key], value);
}

function currentStage(data) {
  const elapsedSeconds = (Date.now() - new Date(data.startedAt).getTime()) / 1000;
  let boundary = 0;
  for (const stage of plannedStages) {
    boundary += stage.duration;
    if (elapsedSeconds <= boundary) return stage;
  }
  return plannedStages[plannedStages.length - 1];
}

export function handleSummary(data) {
  const destination = __ENV.LOADPILOT_SUMMARY_PATH || 'stdout';
  return { [destination]: JSON.stringify({ loadpilot: { planId: {{ plan_id }}, generated: true }, metrics: data.metrics }, null, 2) };
}
'''


@dataclass(frozen=True)
class CompiledScript:
    content: str
    sha256: str


class K6Compiler:
    def __init__(self) -> None:
        self.environment = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)

    def compile(self, plan: PerformanceTestPlan, application: ApplicationModel, *, run_id: str = "pending") -> CompiledScript:
        endpoints = {e.operation_id: e for e in application.endpoints}
        steps = []
        for journey in plan.journeys:
            for step in journey.steps:
                endpoint = endpoints[step.operation_id]
                example = endpoint.examples[0] if endpoint.examples else None
                extractions = []
                for name, expression in step.extract.items():
                    path = re.sub(r"^\$response\.body#?/?", "", expression).replace("/", ".")
                    extractions.append({"name": self._js(name), "path": self._js(path)})
                steps.append({
                    "operation_id": self._js(endpoint.operation_id),
                    "method": self._js(endpoint.method),
                    "path": self._js(endpoint.path),
                    "payload": self._js_value(example),
                    "think_time": step.think_time_seconds,
                    "check_name": self._js(f"{endpoint.operation_id} succeeded"),
                    "extractions": extractions,
                })
        thresholds = {t.metric: [{"threshold": t.expression, "abortOnFail": t.abort_on_fail, "delayAbortEval": f"{t.delay_abort_eval_seconds}s"}] for t in plan.thresholds}
        context = {
            "base_url": self._js(str(application.base_url or "http://localhost:8080")),
            "tags": self._js_value({"plan_id": str(plan.id), "test_run_id": run_id, "test_type": plan.test_type.value}),
            "executor": self._js(plan.executor),
            "stages": self._js_value([{"duration": f"{s.duration_seconds}s", "target": s.target_vus or 0} for s in plan.stages]),
            "instrumented_stages": self._js_value([{"name": s.name, "metricSuffix": re.sub(r"[^a-zA-Z0-9]+", "_", s.name).strip("_").lower(), "duration": s.duration_seconds, "target": s.target_vus or 0} for s in plan.stages]),
            "thresholds": self._js_value(thresholds),
            "steps": steps,
            "plan_id": self._js(str(plan.id)),
        }
        content = self.environment.from_string(_TEMPLATE).render(**context)
        return CompiledScript(content=content, sha256=hashlib.sha256(content.encode()).hexdigest())

    @staticmethod
    def _js(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _js_value(value) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def write(script: CompiledScript, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script.content, encoding="utf-8")
