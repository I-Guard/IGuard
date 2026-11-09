from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import NotificationEvent, NotificationStatus, Severity
from app.schemas.common import ORMModel


class AlertConfigOut(ORMModel):
    id: uuid.UUID
    channel: str
    enabled: bool
    min_severity: Severity
    notify_events: list[str]
    cooldown_seconds: int
    updated_at: datetime
    channel_configured: bool = False


class AlertConfigUpdate(BaseModel):
    channel: str = Field(default="TELEGRAM", max_length=32)
    enabled: bool | None = None
    min_severity: Severity | None = None
    notify_events: list[NotificationEvent] | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)


class AlertTestRequest(BaseModel):
    message: str = Field(default="IGuard test notification", min_length=1, max_length=500)


class NotificationOut(ORMModel):
    id: uuid.UUID
    channel: str
    event_type: str
    incident_id: uuid.UUID | None
    severity: str | None
    title: str
    body: str
    status: NotificationStatus
    attempts: int
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime


class AlertOut(BaseModel):
    source: str  # "alertmanager" (live) | "iguard" (notification history)
    name: str
    severity: str | None
    state: str
    summary: str
    started_at: datetime | None
    labels: dict[str, str] = Field(default_factory=dict)
    incident_id: uuid.UUID | None = None


class AuditLogOut(ORMModel):
    id: uuid.UUID
    created_at: datetime
    actor_id: uuid.UUID | None
    actor_name: str
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    ip_address: str | None
    request_id: str | None
    details: dict[str, Any] | None


class SettingOut(BaseModel):
    key: str
    value: Any
    description: str
    default: Any
    type: str
    minimum: float | None = None
    maximum: float | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


class SettingsUpdate(BaseModel):
    values: dict[str, Any] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def _limit(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > 50:
            raise ValueError("too many settings in one request")
        return v


class LogEntry(BaseModel):
    timestamp: datetime
    line: str
    labels: dict[str, str]
    fields: dict[str, Any] = Field(default_factory=dict)
