"""Servers, services and service check history."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Enum, Float, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base, UTCDateTime
from app.models.base import created_col, json_col, updated_col, uuid_pk
from app.models.enums import CheckType, ServiceStatus


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    environment: Mapped[str] = mapped_column(String(32), default="demo", nullable=False)
    description: Mapped[str] = mapped_column(String(1024), default="")
    # Prometheus `instance` label of the node-exporter that represents this server.
    prometheus_instance: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tags: Mapped[Any] = json_col(default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = created_col()
    updated_at: Mapped[datetime] = updated_col()

    services: Mapped[list[Service]] = relationship(back_populates="server", passive_deletes=True)


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (Index("ix_services_server_id", "server_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(1024), default="")
    server_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("servers.id", ondelete="SET NULL"), nullable=True
    )
    check_type: Mapped[CheckType] = mapped_column(
        Enum(CheckType, native_enum=False, length=16), nullable=False
    )
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_status_codes: Mapped[Any] = json_col(default=lambda: [200])
    interval_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    retry_threshold: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    latency_threshold_ms: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Name of the Docker container that runs this service (used by recovery policies).
    container_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ServiceStatus] = mapped_column(
        Enum(ServiceStatus, native_enum=False, length=16),
        default=ServiceStatus.UNKNOWN,
        nullable=False,
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status_since: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = created_col()
    updated_at: Mapped[datetime] = updated_col()

    server: Mapped[Server | None] = relationship(back_populates="services", lazy="joined")
    checks: Mapped[list[ServiceCheck]] = relationship(
        back_populates="service", cascade="all, delete-orphan", passive_deletes=True
    )


class ServiceCheck(Base):
    __tablename__ = "service_checks"
    __table_args__ = (Index("ix_service_checks_service_checked", "service_id", "checked_at"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    service: Mapped[Service] = relationship(back_populates="checks")
