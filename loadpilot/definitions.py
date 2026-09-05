"""Immutable saved requests, reusable without rerunning discovery by hand."""
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field

from .models import StrictModel, utcnow


class SavedDefinition(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    previous_version: UUID | None = None
    created_at: datetime = Field(default_factory=utcnow)
    request: dict


class DefinitionExecution(StrictModel):
    run_at: datetime | None = None
    auto_start: bool = True
    intent_overrides: dict | None = None
