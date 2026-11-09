"""Audit trail writer. Records are added to the caller's transaction."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import redact, request_id_var
from app.models import AuditLog, User


def record(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | uuid.UUID | None = None,
    actor: User | None = None,
    actor_name: str | None = None,
    outcome: str = "SUCCESS",
    ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_name=(actor.username if actor else actor_name) or "system",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        outcome=outcome,
        ip_address=ip,
        request_id=request_id_var.get() if request_id_var.get() != "-" else None,
        details=redact(details or {}),
    )
    db.add(entry)
    db.flush()
    return entry
