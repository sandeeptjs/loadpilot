import pytest

from loadpilot.audit import redact
from loadpilot.lifecycle import InvalidTransition, RunStore
from loadpilot.models import ExecutionBackendType, RunState
from loadpilot.models import TestRun as RunModel


def test_lifecycle_rejects_skipped_states(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    run = store.create(RunModel(plan_id="00000000-0000-4000-8000-000000000001", execution_backend=ExecutionBackendType.LOCAL))
    with pytest.raises(InvalidTransition):
        store.transition(run.id, RunState.RUNNING)
    assert store.transition(run.id, RunState.DISCOVERING_APPLICATION).state == RunState.DISCOVERING_APPLICATION


def test_recursive_redaction():
    value = redact({"authorization": "Bearer abc", "nested": {"api_key": "value"}, "message": "failed with Bearer xyz"})
    assert value["authorization"] == "[REDACTED]"
    assert value["nested"]["api_key"] == "[REDACTED]"
    assert "xyz" not in value["message"]
