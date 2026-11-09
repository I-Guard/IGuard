"""Shared column helpers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import UTCDateTime, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def created_col() -> Mapped[datetime]:
    return mapped_column(UTCDateTime, default=utcnow, nullable=False)


def updated_col() -> Mapped[datetime]:
    return mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


def json_col(default: Any = None, nullable: bool = True) -> Mapped[Any]:
    return mapped_column(JSONType, default=default, nullable=nullable)
