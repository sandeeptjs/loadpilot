from __future__ import annotations

import asyncio
import json
import os
import shutil
from abc import ABC, abstractmethod
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

    def _require(self) -> str:
        resolved = shutil.which(self.binary)
        if not resolved:
            raise K6Unavailable(f"k6 executable '{self.binary}' was not found")
        return resolved

    async def _run(self, *args: str, timeout: int = 60, env: dict[str, str] | None = None):
        process = await asyncio.create_subprocess_exec(self._require(), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")

    async def validate(self, script: Path) -> None:
        code, _, stderr = await self._run("inspect", str(script))
        if code:
            raise ValueError(f"k6 inspect failed: {stderr[-2000:]}")

    async def execute(self, run: TestRun, plan: PerformanceTestPlan, script: Path) -> ExecutionResult:
        environment = os.environ.copy()
        environment.update(plan.execution.environment)
        environment["LOADPILOT_RUN_ID"] = str(run.id)
        summary_path = script.with_suffix(".summary.json").resolve()
        environment["LOADPILOT_SUMMARY_PATH"] = str(summary_path)
        code, stdout, stderr = await self._run("run", "--tag", f"test_run_id={run.id}", str(script), timeout=plan.execution.timeout_seconds, env=environment)
        summary = {}
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        else:
            try:
                summary = json.loads(stdout)
            except json.JSONDecodeError:
                pass
        return ExecutionResult(code, stdout, stderr, summary)


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
        process = await asyncio.create_subprocess_exec("docker", "run", "--rm", "--cpus", "2", "--memory", "1g", "-v", f"{script.parent.resolve()}:/scripts:ro", self.image, "run", "--tag", f"test_run_id={run.id}", f"/scripts/{script.name}", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=plan.execution.timeout_seconds)
        return ExecutionResult(process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace"), {})


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
        return ExecutionResult(0, str(manifest_path), "Submission is performed by the Kubernetes activity", {"manifest": str(manifest_path)})
