from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import CheckType, ServiceStatus
from app.schemas.common import ORMModel


class ServerBase(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.\-]*$")
    hostname: str = Field(min_length=1, max_length=255)
    ip_address: str | None = Field(default=None, max_length=64)
    environment: str = Field(default="demo", max_length=32)
    description: str = Field(default="", max_length=1024)
    prometheus_instance: str | None = Field(default=None, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=20)
    is_active: bool = True


class ServerCreate(ServerBase):
    pass


class ServerUpdate(BaseModel):
    name: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.\-]*$"
    )
    hostname: str | None = Field(default=None, min_length=1, max_length=255)
    ip_address: str | None = Field(default=None, max_length=64)
    environment: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1024)
    prometheus_instance: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = Field(default=None, max_length=20)
    is_active: bool | None = None


class ServerOut(ORMModel):
    id: uuid.UUID
    name: str
    hostname: str
    ip_address: str | None
    environment: str
    description: str
    prometheus_instance: str | None
    tags: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Derived at request time from Prometheus + active incidents.
    health: Literal["healthy", "degraded", "unhealthy", "unknown"] = "unknown"
    active_incidents: int = 0
    service_count: int = 0


class ServiceBase(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.\-]*$")
    description: str = Field(default="", max_length=1024)
    server_id: uuid.UUID | None = None
    check_type: CheckType = CheckType.HTTP
    url: str | None = Field(default=None, max_length=1024)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    expected_status_codes: list[int] = Field(
        default_factory=lambda: [200], min_length=1, max_length=20
    )
    interval_seconds: int = Field(default=30, ge=5, le=86400)
    timeout_seconds: float = Field(default=5.0, ge=0.5, le=60)
    retry_threshold: int = Field(default=3, ge=1, le=20)
    latency_threshold_ms: int = Field(default=1000, ge=10, le=120000)
    enabled: bool = True
    container_name: str | None = Field(
        default=None, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$"
    )

    @field_validator("expected_status_codes")
    @classmethod
    def _codes(cls, v: list[int]) -> list[int]:
        if any(c < 100 or c > 599 for c in v):
            raise ValueError("status codes must be within 100-599")
        return v


class ServiceCreate(ServiceBase):
    @model_validator(mode="after")
    def _target(self) -> ServiceCreate:
        _validate_target(self.check_type, self.url, self.host, self.port)
        return self


class ServiceUpdate(BaseModel):
    name: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.\-]*$"
    )
    description: str | None = Field(default=None, max_length=1024)
    server_id: uuid.UUID | None = None
    check_type: CheckType | None = None
    url: str | None = Field(default=None, max_length=1024)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    expected_status_codes: list[int] | None = Field(default=None, min_length=1, max_length=20)
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    timeout_seconds: float | None = Field(default=None, ge=0.5, le=60)
    retry_threshold: int | None = Field(default=None, ge=1, le=20)
    latency_threshold_ms: int | None = Field(default=None, ge=10, le=120000)
    enabled: bool | None = None
    container_name: str | None = Field(
        default=None, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$"
    )


def _validate_target(
    check_type: CheckType, url: str | None, host: str | None, port: int | None
) -> None:
    if check_type in (CheckType.HTTP, CheckType.HTTPS):
        if not url:
            raise ValueError("url is required for HTTP/HTTPS checks")
        want = "https://" if check_type == CheckType.HTTPS else "http://"
        if not url.lower().startswith(want):
            raise ValueError(f"url must start with {want} for {check_type.value} checks")
    else:
        if not host or port is None:
            raise ValueError("host and port are required for TCP checks")


class ServiceOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    server_id: uuid.UUID | None
    server_name: str | None = None
    check_type: CheckType
    url: str | None
    host: str | None
    port: int | None
    expected_status_codes: list[int]
    interval_seconds: int
    timeout_seconds: float
    retry_threshold: int
    latency_threshold_ms: int
    enabled: bool
    container_name: str | None
    status: ServiceStatus
    consecutive_failures: int
    last_checked_at: datetime | None
    last_response_ms: float | None
    last_status_code: int | None
    last_error: str | None
    status_since: datetime | None
    created_at: datetime
    updated_at: datetime
    availability_24h: float | None = None


class ServiceCheckOut(ORMModel):
    id: int
    service_id: uuid.UUID
    checked_at: datetime
    success: bool
    status_code: int | None
    response_time_ms: float | None
    error: str | None


class CheckResultOut(BaseModel):
    service_id: uuid.UUID
    success: bool
    status: ServiceStatus
    status_code: int | None
    response_time_ms: float | None
    error: str | None
    checked_at: datetime
    extra: dict[str, Any] = Field(default_factory=dict)
