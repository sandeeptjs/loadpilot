from __future__ import annotations

import re
from typing import Any

from .models import AuditEvent

SECRET_KEYS = re.compile(r"password|passwd|secret|token|authorization|cookie|api[-_]?key|session", re.IGNORECASE)
BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")


def redact(value: Any, key: str = "") -> Any:
    if SECRET_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return BEARER.sub("Bearer [REDACTED]", value)
    return value


def audit_event(*, actor: str, tool: str, action: str, inputs: dict[str, Any], outputs: dict[str, Any], reason: str, test_id=None, investigation_id=None) -> AuditEvent:
    return AuditEvent(actor=actor, agent_tool=tool, action=action, inputs=redact(inputs), outputs=redact(outputs), reason=reason, related_test_id=test_id, related_investigation_id=investigation_id)

