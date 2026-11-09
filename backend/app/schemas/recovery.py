from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ActionType, ExecutionStatus, RoleName, Trigger
from app.schemas.common import ORMModel


class RecoveryActionOut(ORMModel):
    id: uuid.UUID
    key: str
    name: str
    description: str
    action_type: ActionType
    target: str
    service_id: uuid.UUID | None
    service_name: str | None = None
    sensitive: bool
    requires_dry_run: bool
    auto_trigger: bool
    trigger_categories: list[str]
    enabled: bool
    cooldown_seconds: int
    timeout_seconds: float
    max_attempts_per_hour: int
    breaker_threshold: int
    breaker_reset_seconds: int
    min_role: RoleName
    # Live runtime state
    circuit_open: bool = False
    cooldown_remaining_seconds: int = 0
    last_execution_at: datetime | None = None
    last_status: ExecutionStatus | None = None


class ExecuteRequest(BaseModel):
    incident_id: uuid.UUID | None = None
    # Sensitive actions require an explicit second confirmation from an ADMIN.
    confirm: bool = False
    reason: str | None = Field(default=None, max_length=1000)


class DryRunRequest(BaseModel):
    incident_id: uuid.UUID | None = None


class RecoveryExecutionOut(ORMModel):
    id: uuid.UUID
    action_id: uuid.UUID
    action_key: str | None = None
    action_name: str | None = None
    incident_id: uuid.UUID | None
    requested_by_name: str | None
    trigger: Trigger
    dry_run: bool
    status: ExecutionStatus
    simulated: bool
    verification_passed: bool | None
    output: str | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: float | None
    created_at: datetime
