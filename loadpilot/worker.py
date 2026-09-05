"""One persisted queue, runnable inside the API or as a separate process."""
import asyncio
import time
from uuid import uuid4

from .lifecycle import TERMINAL, RunStore
from .models import PerformanceTestPlan, RunState
from .service import LoadPilotService
from .settings import get_settings


class Worker:
    def __init__(self, service):
        self.service = service
        self.owner = str(uuid4())
        self.active = None

    async def run(self):
        store = self.service.store
        try:
            while True:
                # Do not replay interrupted load. Wait through its execution timeout
                # before allowing another job, since an orphan k6 may still be running.
                for run_id in store.stale_jobs(time.time() - 30):
                    run = store.get(run_id)
                    plan = store.get_entity('plan', run.plan_id, PerformanceTestPlan)
                    if (run.started_at or run.created_at).timestamp() + plan.execution.timeout_seconds + 30 < time.time():
                        if run.state not in TERMINAL:
                            run = store.transition(run_id, RunState.FAILED, error='Worker lease expired; workload was not replayed')
                            self.service._audit(run, 'worker.interrupted', {}, {}, 'Recover interrupted run without duplicate traffic')
                        store.finish_job(run_id, 'interrupted')
                run_id = store.claim(self.owner, time.time())
                if not run_id:
                    await asyncio.sleep(.25)
                    continue
                self.active = asyncio.create_task(self.service.start(run_id))
                try:
                    while not self.active.done():
                        store.heartbeat(run_id, self.owner, time.time())
                        if store.get(run_id).state == RunState.CANCELED:
                            self.active.cancel()
                        await asyncio.wait({self.active}, timeout=.25)
                    await asyncio.gather(self.active, return_exceptions=True)
                    completed = store.get(run_id)
                    if completed.state == RunState.COMPLETED and completed.auto_followup:
                        try:
                            self.service.rerun(run_id, followup=True)
                        except ValueError as exc:
                            store.update(run_id, warnings=[*completed.warnings, str(exc)])
                            self.service._audit(completed, 'experiment.followup.skipped', {}, {'reason': str(exc)}, 'No defensible narrower experiment within the one-run budget')
                finally:
                    if not self.active.done():
                        self.active.cancel()
                        await asyncio.gather(self.active, return_exceptions=True)
                    store.finish_job(run_id)
                    self.active = None
        finally:
            if self.active and not self.active.done():
                self.active.cancel()
                await asyncio.gather(self.active, return_exceptions=True)


async def main():
    settings = get_settings()
    service = LoadPilotService(RunStore(settings.db), settings.generated_dir, settings=settings)
    await Worker(service).run()


if __name__ == '__main__':
    asyncio.run(main())
