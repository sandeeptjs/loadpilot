from loadpilot.execution import ExecutionBackend, ExecutionResult
from loadpilot.lifecycle import RunStore
from loadpilot.models import ExecutionBackendType, RunState
from loadpilot.service import LoadPilotService
from loadpilot.settings import Settings


class FakeK6Backend(ExecutionBackend):
    validated = False

    async def validate(self, script):
        assert script.exists()
        self.validated = True

    async def execute(self, run, plan, script):
        assert self.validated
        return ExecutionResult(0, "", "", {"metrics": {"http_req_duration": {"values": {"p(95)": 463}}, "http_req_failed": {"values": {"rate": .006}}, "http_reqs": {"values": {"count": 742}}}})


async def test_service_vertical_slice_is_audited(tmp_path, checkout_openapi):
    backend = FakeK6Backend()
    service = LoadPilotService(store=RunStore(tmp_path / "runs.db"), generated_dir=tmp_path / "generated", backends={ExecutionBackendType.LOCAL: backend}, settings=Settings(max_vus=2000))
    run = await service.prepare(prompt="Stress checkout from 150 VUs and find maximum load with p95 under 500 ms and errors under 1%", source_type="openapi", source=checkout_openapi, application_name="checkout", validate=True)
    assert run.state == RunState.QUEUED
    completed = await service.start(run.id)
    assert completed.state == RunState.COMPLETED
    assert completed.metrics["http_req_duration.p(95)"] == 463
    actions = [event.action for event in service.store.audit()]
    assert "intent.parsed" in actions
    assert "script.validated" in actions
    assert "investigation.completed" in actions

