from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import EventType, IncidentCategory, IncidentStatus, Severity
from app.schemas.common import ORMModel


class UserRef(ORMModel):
    id: uuid.UUID
    username: str
    full_name: str


class IncidentOut(ORMModel):
    id: uuid.UUID
    title: str
    description: str
    severity: Severity
    category: IncidentCategory
    status: IncidentStatus
    source: str
    fingerprint: str
    server_id: uuid.UUID | None
    server_name: str | None = None
    service_id: uuid.UUID | None
    service_name: str | None = None
    acknowledged_by: UserRef | None
    assigned_to: UserRef | None
    root_cause: str | None
    resolution_summary: str | None
    occurrences: int
    flap_count: int
    is_flapping: bool
    escalation_level: int
    correlation_group: str | None
    context: dict[str, Any] | None
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None


class IncidentDetail(IncidentOut):
    related: list[IncidentOut] = Field(default_factory=list)


class IncidentEventOut(ORMModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    event_type: EventType
    message: str
    actor_name: str | None
    data: dict[str, Any] | None
    created_at: datetime


class AcknowledgeRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class AssignRequest(BaseModel):
    assignee_id: uuid.UUID
    note: str | None = Field(default=None, max_length=2000)


class ResolveRequest(BaseModel):
    resolution_summary: str = Field(min_length=3, max_length=4000)
    root_cause: str | None = Field(default=None, max_length=4000)


class StatusUpdateRequest(BaseModel):
    status: IncidentStatus
    note: str | None = Field(default=None, max_length=2000)
    root_cause: str | None = Field(default=None, max_length=4000)
