"""Incidents, timeline events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base, UTCDateTime
from app.models.auth import User
from app.models.base import created_col, json_col, updated_col, uuid_pk
from app.models.enums import EventType, IncidentCategory, IncidentStatus, Severity
from app.models.infra import Server, Service


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        # DB-level deduplication: at most one non-resolved incident per fingerprint.
        Index(
            "uq_incidents_active_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where=text("status <> 'RESOLVED'"),
            sqlite_where=text("status <> 'RESOLVED'"),
        ),
        Index("ix_incidents_status_severity", "status", "severity"),
        Index("ix_incidents_created_at", "created_at"),
        Index("ix_incidents_server_id", "server_id"),
        Index("ix_incidents_service_id", "service_id"),
        Index("ix_incidents_fingerprint", "fingerprint"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, native_enum=False, length=16), nullable=False
    )
    category: Mapped[IncidentCategory] = mapped_column(
        Enum(IncidentCategory, native_enum=False, length=32), nullable=False
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, native_enum=False, length=16),
        default=IncidentStatus.DETECTED,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # detector | alertmanager | manual
    server_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("servers.id", ondelete="SET NULL"), nullable=True
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    clear_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    flap_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_flapping: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correlation_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context: Mapped[Any] = json_col(default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = created_col()
    updated_at: Mapped[datetime] = updated_col()

    server: Mapped[Server | None] = relationship(lazy="joined")
    service: Mapped[Service | None] = relationship(lazy="joined")
    acknowledged_by: Mapped[User | None] = relationship(
        foreign_keys=[acknowledged_by_id], lazy="joined"
    )
    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_id], lazy="joined")
    events: Mapped[list[IncidentEvent]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="IncidentEvent.created_at",
    )


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_created", "incident_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, native_enum=False, length=32), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    data: Mapped[Any] = json_col(default=dict)
    created_at: Mapped[datetime] = created_col()

    incident: Mapped[Incident] = relationship(back_populates="events")
