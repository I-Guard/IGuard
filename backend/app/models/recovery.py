"""Recovery actions (allowlist registry) and their executions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base, UTCDateTime
from app.models.base import created_col, json_col, updated_col, uuid_pk
from app.models.enums import ActionType, ExecutionStatus, RoleName, Trigger
from app.models.incident import Incident
from app.models.infra import Service


class RecoveryAction(Base):
    """An allowlisted recovery action. Only these rows can ever be executed."""

    __tablename__ = "recovery_actions"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType, native_enum=False, length=32), nullable=False
    )
    # Container name or script name; validated against the allowlist by the adapter too.
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_dry_run: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_trigger: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trigger_categories: Mapped[Any] = json_col(default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=60.0, nullable=False)
    max_attempts_per_hour: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    breaker_threshold: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    breaker_reset_seconds: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    min_role: Mapped[RoleName] = mapped_column(
        Enum(RoleName, native_enum=False, length=16), default=RoleName.OPERATOR, nullable=False
    )
    verify_after_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    created_at: Mapped[datetime] = created_col()
    updated_at: Mapped[datetime] = updated_col()

    service: Mapped[Service | None] = relationship(lazy="joined")


class RecoveryExecution(Base):
    __tablename__ = "recovery_executions"
    __table_args__ = (
        UniqueConstraint("action_id", "idempotency_key", name="uq_recovery_exec_idempotency"),
        Index("ix_recovery_exec_action_created", "action_id", "created_at"),
        Index("ix_recovery_exec_incident", "incident_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    action_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("recovery_actions.id", ondelete="RESTRICT"), nullable=False
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trigger: Mapped[Trigger] = mapped_column(
        Enum(Trigger, native_enum=False, length=16), nullable=False
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, native_enum=False, length=32), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = created_col()

    action: Mapped[RecoveryAction] = relationship(lazy="joined")
    incident: Mapped[Incident | None] = relationship(lazy="joined")
