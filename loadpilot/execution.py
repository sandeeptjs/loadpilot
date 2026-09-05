from __future__ import annotations

import asyncio
import json
import os
import shutil
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import PerformanceTestPlan, TestRun


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    summary: dict[str, Any]


class K6Unavailable(RuntimeError):
    pass


class ExecutionBackend(ABC):
    @abstractmethod
    async def validate(self, script: Path) -> None: ...

    @abstractmethod
    async def execute(self, run: TestRun, plan: PerformanceTestPlan, script: Path) -> ExecutionResult: ...


class LocalK6Backend(ExecutionBackend):
    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or os.environ.get("LOADPILOT_K6_BIN", "k6")
        self.processes = {}
        self.on_sample = None

    def cancel(self, run_id):
        process = self.processes.get(str(run_id))
        if process and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def _require(self) -> str:
        resolved = shutil.which(self.binary)
        if not resolved:
            raise K6Unavailable(f"k6 executable '{self.binary}' was not found")
        return resolved

    async def _run(self, *args: str, timeout: int = 60, env: dict[str, str] | None = None, run_id=None):
        process = await asyncio.create_subprocess_exec(self._require(), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        if run_id:
            self.processes[str(run_id)] = process
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        finally:
            if run_id:
                self.processes.pop(str(run_id), None)
        return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")

    async def validate(self, script: Path) -> None:
        code, _, stderr = await self._run("inspect", str(script))
        if code:
            raise ValueError(f"k6 inspect failed: {stderr[-2000:]}")

    async def execute(self, run: TestRun, plan: PerformanceTestPlan, script: Path) -> ExecutionResult:
        # Do not forward provider keys, control tokens or unrelated target overrides to k6.
        environment = {key: value for key, value in os.environ.items() if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HOME', 'USERPROFILE'}}
        for reference in plan.execution.secret_references.values():
            if reference.provider != 'env':
                raise ValueError('Only environment secret references are supported by the local backend')
            value = os.environ.get(reference.key)
            if not value:
                raise ValueError(f'Missing configured execution secret: {reference.key}')
            environment[reference.key] = value
        environment["LOADPILOT_RUN_ID"] = str(run.id)
        summary_path = script.with_suffix(".summary.json").resolve()
        environment["LOADPILOT_SUMMARY_PATH"] = str(summary_path)
        output_path = script.with_suffix('.points.json').resolve()
        for artifact in (summary_path, output_path):
            artifact.unlink(missing_ok=True)
        done = asyncio.Event()
        monitor = asyncio.create_task(self._monitor(run.id, output_path, done))
        try:
            code, stdout, stderr = await self._run('run', '--quiet', '--out', f'json={output_path}', '--tag', f'test_run_id={run.id}', str(script), timeout=plan.execution.timeout_seconds, env=environment, run_id=run.id)
        finally:
            done.set()
            await monitor
        summary = {}
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        else:
            try:
                summary = json.loads(stdout)
            except json.JSONDecodeError:
                pass
        return ExecutionResult(code, stdout, stderr, summary)

    async def _monitor(self, run_id, path, done):
        offset, partial, count, errors = 0, '', 0, 0
        durations = deque(maxlen=10000)
        vus = 0
        loop = asyncio.get_running_loop()
        started = loop.time()
        while True:
            if path.exists():
                with path.open(encoding='utf-8') as stream:
                    stream.seek(offset)
                    chunk = stream.read(4 * 1024 * 1024)
                    offset = stream.tell()
                lines = (partial + chunk).split('\n')
                partial = lines.pop()
                for line in lines:
                    if not line:
                        continue
                    item = json.loads(line)
                    if item.get('type') != 'Point':
                        continue
                    value = item['data']['value']
                    metric = item['metric']
                    if metric == 'http_req_duration':
                        durations.append(value)
                    elif metric == 'http_reqs':
                        count += value
                    elif metric == 'http_req_failed':
                        errors += value
                    elif metric == 'vus':
                        vus = value
                if self.on_sample and count:
                    ordered = sorted(durations)
                    values = {'http_reqs.count': count, 'http_reqs.rate': count / max(.001, loop.time() - started), 'http_req_failed.rate': errors / count, 'vus': vus}
                    if ordered:
                        values['http_req_duration.p(95)'] = ordered[min(len(ordered) - 1, int(.95 * len(ordered)))]
                    await self.on_sample(run_id, values)
            if done.is_set():
                return
            try:
                await asyncio.wait_for(done.wait(), 1)
            except TimeoutError:
                pass


class DockerK6Backend(ExecutionBackend):
    """Contract adapter; delegates to Docker CLI without accepting arbitrary arguments."""
    def __init__(self, image: str = "grafana/k6:latest") -> None:
        self.image = image

    async def validate(self, script: Path) -> None:
        if not shutil.which("docker"):
            raise K6Unavailable("docker executable was not found")
        process = await asyncio.create_subprocess_exec("docker", "run", "--rm", "-v", f"{script.parent.resolve()}:/scripts:ro", self.image, "inspect", f"/scripts/{script.name}")
        if await process.wait():
            raise ValueError("containerized k6 inspect failed")

    async def execute(self, run: TestRun, plan: PerformanceTestPlan, script: Path) -> ExecutionResult:
        raise NotImplementedError('Use the local backend inside the supplied API container; standalone Docker execution is not qualified')


class KubernetesK6Backend(ExecutionBackend):
    def __init__(self, namespace: str = "loadpilot-runs") -> None:
        self.namespace = namespace

    async def validate(self, script: Path) -> None:
        if not script.exists() or not script.read_text(encoding="utf-8").startswith("import http"):
            raise ValueError("generated script is missing or malformed")

    def manifest(self, run: TestRun, plan: PerformanceTestPlan, script_config_map: str) -> dict[str, Any]:
        return {
            "apiVersion": "k6.io/v1alpha1",
            "kind": "TestRun",
            "metadata": {"name": f"loadpilot-{str(run.id)[:8]}", "namespace": self.namespace, "labels": {"loadpilot.io/run-id": str(run.id)}},
            "spec": {
                "parallelism": plan.execution.parallelism,
                "script": {"configMap": {"name": script_config_map, "file": "test.js"}},
                "arguments": f"--tag test_run_id={run.id}",
                "cleanup": "post",
                "separate": False,
                "runner": {"metadata": {"labels": {"loadpilot.io/run-id": str(run.id)}}},
            },
        }

    async def execute(self, run: TestRun, plan: PerformanceTestPlan, script: Path) -> ExecutionResult:
        manifest_path = script.with_suffix(".testrun.yaml")
        manifest_path.write_text(yaml.safe_dump(self.manifest(run, plan, f"loadpilot-script-{str(run.id)[:8]}"), sort_keys=False), encoding="utf-8")
        raise NotImplementedError(f'Kubernetes execution is not connected; manifest exported to {manifest_path}')
