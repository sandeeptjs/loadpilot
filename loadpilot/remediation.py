import time
from typing import Literal
from uuid import UUID, uuid4

import httpx
from pydantic import Field

from .models import RunState, StrictModel, utcnow


class PoolAction(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    action: Literal['IncreaseSandboxPool'] = 'IncreaseSandboxPool'
    target: str
    previous_size: int
    new_size: int = Field(ge=1, le=32)
    status: Literal['pending', 'executed', 'failed', 'rolled_back'] = 'pending'
    reason: str
    timestamp: str = Field(default_factory=lambda: utcnow().isoformat())
    verification_run_id: UUID | None = None


class Remediator:
    def __init__(self, service):
        self.service = service

    async def apply(self, run_id, size, *, rollback_id=None):
        service, settings = self.service, self.service.settings
        if not settings.allow_sandbox_remediation or not settings.sandbox_control_token:
            raise ValueError('Sandbox remediation is disabled; configure its explicit policy and control token')
        detail = service.detail(run_id)
        run = detail['run']
        if run.state != RunState.COMPLETED or str(detail['application'].base_url).rstrip('/') != settings.sandbox_url.rstrip('/'):
            raise ValueError('Remediation requires a completed run against the configured sandbox')
        settings.check_target(settings.sandbox_url)
        owner = str(uuid4())
        service.store.reserve_maintenance(owner, time.time())
        action = None
        try:
            previous_action = service.store.get_entity('remediation', rollback_id, PoolAction) if rollback_id else None
            if previous_action and (previous_action.run_id != run.id or previous_action.status != 'executed'):
                raise ValueError('Only an executed action for this run can be rolled back')
            existing = [a for a in service.store.list_entities('remediation', PoolAction, 10000) if a.run_id == run.id and a.status == 'executed']
            if existing and not rollback_id:
                return existing[0]
            headers = {'X-Control-Token': settings.sandbox_control_token}
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(settings.sandbox_url.rstrip('/') + '/control', headers=headers)
                response.raise_for_status()
                previous = response.json()['db_pool_size']
                if previous_action:
                    if previous != previous_action.new_size:
                        raise ValueError('Sandbox changed since remediation; refusing to overwrite another change')
                    desired = previous_action.previous_size
                else:
                    if not detail['investigation'] or detail['investigation'].likely_root_cause != 'Modeled connection-pool contention':
                        raise ValueError('No measured pool contention supports this action')
                    desired = size
                    if not 1 <= desired <= 32 or desired <= previous:
                        raise ValueError('Pool increase must be above the current value and at most 32')
                action = PoolAction(run_id=run.id, target=settings.sandbox_url, previous_size=previous, new_size=desired, reason='Rollback recorded sandbox pool change' if previous_action else 'Measured pool contention; bounded sandbox policy permits one pool increase')
                service.store.put_entity('remediation', action)
                service._audit(run, 'remediation.requested', {'action_id': str(action.id), 'previous': previous, 'desired': desired}, {}, action.reason)
                response = await client.post(settings.sandbox_url.rstrip('/') + '/control', headers=headers, json={'db_pool_size': desired})
                response.raise_for_status()
                if response.json().get('db_pool_size') != desired:
                    raise ValueError('Sandbox did not confirm the requested setting')
                action.status = 'executed'
                if previous_action:
                    previous_action.status = 'rolled_back'
                    service.store.put_entity('remediation', previous_action)
                    action.status = 'rolled_back'
            service.store.put_entity('remediation', action)
            service._audit(run, 'remediation.executed', {'action_id': str(action.id)}, {'previous': previous, 'current': desired}, action.reason)
        except Exception:
            if action:
                action.status = 'failed'
                service.store.put_entity('remediation', action)
            service._audit(run, 'remediation.failed', {}, {}, 'Sandbox action failed or was rejected; inspect recorded action state')
            raise
        finally:
            service.store.release_maintenance(owner)
        if not rollback_id:
            verification = service.rerun(run.id)
            action.verification_run_id = verification.id
            service.store.put_entity('remediation', action)
        return action
