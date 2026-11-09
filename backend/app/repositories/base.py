"""Generic repository helpers: pagination, sorting, safe lookups."""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailed
from app.schemas.common import PageParams

T = TypeVar("T")


def paginate(db: Session, stmt: Select[Any], params: PageParams) -> tuple[list[Any], int]:
    """Return (rows, total) for a SELECT of a single ORM entity."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.offset(params.offset).limit(params.page_size)).unique())
    return rows, int(total)


def apply_sort(
    stmt: Select[Any], model: Any, sort: str | None, allowed: dict[str, Any], default: Any
) -> Select[Any]:
    """``sort`` is e.g. ``-created_at``. Only allowlisted columns are accepted."""
    if not sort:
        return stmt.order_by(default)
    desc = sort.startswith("-")
    key = sort.lstrip("-+")
    col = allowed.get(key)
    if col is None:
        raise ValidationFailed(f"Cannot sort by '{key}'. Allowed: {', '.join(sorted(allowed))}")
    return stmt.order_by(col.desc() if desc else col.asc(), default)


class Repository(Generic[T]):
    model: type[T]
    label: str = "Resource"

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id_: uuid.UUID) -> T | None:
        return self.db.get(self.model, id_)

    def get_or_404(self, id_: uuid.UUID) -> T:
        obj = self.get(id_)
        if obj is None:
            raise NotFoundError(f"{self.label} not found")
        return obj

    def add(self, obj: T) -> T:
        self.db.add(obj)
        self.db.flush()
        return obj

    def delete(self, obj: T) -> None:
        self.db.delete(obj)
        self.db.flush()
