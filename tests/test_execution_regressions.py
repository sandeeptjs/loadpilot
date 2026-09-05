import asyncio

from loadpilot.execution import ExecutionBackend, ExecutionResult
from loadpilot.lifecycle import RunStore
from loadpilot.models import ExecutionBackendType, RunState
from loadpilot.service import LoadPilotService


class ControlledBackend(ExecutionBackend):
    def __init__(self):
        self.running = asyncio.Event()
        self.release = asyncio.Event()

    async def validate(self, script):
        pass

    async def execute(self, run, plan, script):
        self.running.set()
        await self.release.wait()
        return ExecutionResult(0, '', '', {'metrics': {'http_reqs': {'values': {'count': 1}}}})


async def test_cancel_remains_terminal_after_execution_returns(tmp_path, checkout_openapi):
    backend = ControlledBackend()
    service = LoadPilotService(RunStore(tmp_path / 'runs.db'), tmp_path / 'scripts', {ExecutionBackendType.LOCAL: backend})
    run = await service.prepare(prompt='Baseline checkout with 1 user for 5 seconds', source_type='openapi', source=checkout_openapi, application_name='checkout')
    task = asyncio.create_task(service.start(run.id))
    await asyncio.wait_for(backend.running.wait(), 2)
    service.cancel(run.id, 'User stopped the run')
    backend.release.set()
    await task
    assert service.store.get(run.id).state == RunState.CANCELED


async def test_empty_summary_cannot_be_a_successful_run(tmp_path, checkout_openapi):
    class EmptyBackend(ControlledBackend):
        async def execute(self, run, plan, script):
            return ExecutionResult(0, '', '', {})

    service = LoadPilotService(RunStore(tmp_path / 'runs.db'), tmp_path / 'scripts', {ExecutionBackendType.LOCAL: EmptyBackend()})
    run = await service.prepare(prompt='Baseline checkout with 1 user for 5 seconds', source_type='openapi', source=checkout_openapi, application_name='checkout')
    result = await service.start(run.id)
    assert result.state == RunState.FAILED
