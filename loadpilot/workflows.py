"""Optional Temporal workflow definitions for durable scheduling and execution."""
from __future__ import annotations

from datetime import timedelta

try:
    from temporalio import activity, workflow
except ImportError:  # pragma: no cover
    activity = workflow = None


if workflow:
    @activity.defn
    async def advance_run(command: dict) -> dict:
        return command

    @workflow.defn
    class PerformanceTestWorkflow:
        def __init__(self) -> None:
            self.cancel_requested = False

        @workflow.signal
        def cancel(self) -> None:
            self.cancel_requested = True

        @workflow.query
        def status(self) -> dict:
            return {"cancel_requested": self.cancel_requested}

        @workflow.run
        async def run(self, run_id: str) -> dict:
            for phase in ("validate", "queue", "initialize", "execute", "collect", "analyze"):
                command = "cancel" if self.cancel_requested else phase
                result = await workflow.execute_activity(advance_run, {"run_id": run_id, "command": command}, start_to_close_timeout=timedelta(hours=24))
                if self.cancel_requested:
                    return result
            return {"run_id": run_id, "state": "COMPLETED"}

