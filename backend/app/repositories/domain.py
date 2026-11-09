"""Entity repositories with filter builders."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Incident,
    Notification,
    RecoveryAction,
    RecoveryExecution,
    Server,
    Service,
    User,
)
from app.models.enums import IncidentCategory, IncidentStatus, Severity
from app.repositories.base import Repository, apply_sort


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class UserRepository(Repository[User]):
    model = User
    label = "User"

    def list(self, search: str | None, active: bool | None, sort: str | None) -> Select[Any]:
        stmt = select(User)
        if search:
            like = _like(search.lower())
            stmt = stmt.where(
                or_(
                    func.lower(User.email).like(like, escape="\\"),
                    func.lower(User.username).like(like, escape="\\"),
                    func.lower(User.full_name).like(like, escape="\\"),
                )
            )
        if active is not None:
            stmt = stmt.where(User.is_active.is_(active))
        return apply_sort(
            stmt,
            User,
            sort,
            {"username": User.username, "email": User.email, "created_at": User.created_at},
            User.created_at.desc(),
        )


class ServerRepository(Repository[Server]):
    model = Server
    label = "Server"

    def list(self, search: str | None, environment: str | None, sort: str | None) -> Select[Any]:
        stmt = select(Server)
        if search:
            like = _like(search.lower())
            stmt = stmt.where(
                or_(
                    func.lower(Server.name).like(like, escape="\\"),
                    func.lower(Server.hostname).like(like, escape="\\"),
                )
            )
        if environment:
            stmt = stmt.where(Server.environment == environment)
        return apply_sort(
            stmt,
            Server,
            sort,
            {"name": Server.name, "hostname": Server.hostname, "created_at": Server.created_at},
            Server.name.asc(),
        )


class ServiceRepository(Repository[Service]):
    model = Service
    label = "Service"

    def list(
        self,
        search: str | None,
        status: str | None,
        server_id: uuid.UUID | None,
        enabled: bool | None,
        sort: str | None,
    ) -> Select[Any]:
        stmt = select(Service)
        if search:
            stmt = stmt.where(func.lower(Service.name).like(_like(search.lower()), escape="\\"))
        if status:
            stmt = stmt.where(Service.status == status)
        if server_id:
            stmt = stmt.where(Service.server_id == server_id)
        if enabled is not None:
            stmt = stmt.where(Service.enabled.is_(enabled))
        return apply_sort(
            stmt,
            Service,
            sort,
            {
                "name": Service.name,
                "status": Service.status,
                "last_checked_at": Service.last_checked_at,
                "last_response_ms": Service.last_response_ms,
            },
            Service.name.asc(),
        )


class IncidentRepository(Repository[Incident]):
    model = Incident
    label = "Incident"

    def list(
        self,
        *,
        status: list[IncidentStatus] | None,
        severity: list[Severity] | None,
        category: IncidentCategory | None,
        server_id: uuid.UUID | None,
        service_id: uuid.UUID | None,
        assigned_to: uuid.UUID | None,
        active: bool | None,
        search: str | None,
        since: datetime | None,
        until: datetime | None,
        sort: str | None,
    ) -> Select[Any]:
        stmt = select(Incident)
        if status:
            stmt = stmt.where(Incident.status.in_(status))
        if severity:
            stmt = stmt.where(Incident.severity.in_(severity))
        if category:
            stmt = stmt.where(Incident.category == category)
        if server_id:
            stmt = stmt.where(Incident.server_id == server_id)
        if service_id:
            stmt = stmt.where(Incident.service_id == service_id)
        if assigned_to:
            stmt = stmt.where(Incident.assigned_to_id == assigned_to)
        if active is True:
            stmt = stmt.where(Incident.status != IncidentStatus.RESOLVED)
        elif active is False:
            stmt = stmt.where(Incident.status == IncidentStatus.RESOLVED)
        if search:
            like = _like(search.lower())
            stmt = stmt.where(
                or_(
                    func.lower(Incident.title).like(like, escape="\\"),
                    func.lower(Incident.description).like(like, escape="\\"),
                )
            )
        if since:
            stmt = stmt.where(Incident.created_at >= since)
        if until:
            stmt = stmt.where(Incident.created_at <= until)
        allowed = {
            "created_at": Incident.created_at,
            "updated_at": Incident.updated_at,
            "severity": Incident.severity,
            "status": Incident.status,
            "occurrences": Incident.occurrences,
            "title": Incident.title,
        }
        return apply_sort(stmt, Incident, sort, allowed, Incident.created_at.desc())


class RecoveryActionRepository(Repository[RecoveryAction]):
    model = RecoveryAction
    label = "Recovery action"

    def by_key(self, key: str) -> RecoveryAction | None:
        return self.db.scalar(select(RecoveryAction).where(RecoveryAction.key == key))


class RecoveryExecutionRepository(Repository[RecoveryExecution]):
    model = RecoveryExecution
    label = "Recovery execution"

    def list(
        self,
        *,
        action_id: uuid.UUID | None,
        incident_id: uuid.UUID | None,
        status: str | None,
        dry_run: bool | None,
        sort: str | None,
    ) -> Select[Any]:
        stmt = select(RecoveryExecution)
        if action_id:
            stmt = stmt.where(RecoveryExecution.action_id == action_id)
        if incident_id:
            stmt = stmt.where(RecoveryExecution.incident_id == incident_id)
        if status:
            stmt = stmt.where(RecoveryExecution.status == status)
        if dry_run is not None:
            stmt = stmt.where(RecoveryExecution.dry_run.is_(dry_run))
        return apply_sort(
            stmt,
            RecoveryExecution,
            sort,
            {
                "created_at": RecoveryExecution.created_at,
                "status": RecoveryExecution.status,
                "duration_ms": RecoveryExecution.duration_ms,
            },
            RecoveryExecution.created_at.desc(),
        )


class AuditRepository(Repository[AuditLog]):
    model = AuditLog
    label = "Audit log"

    def list(
        self,
        *,
        actor: str | None,
        action: str | None,
        resource_type: str | None,
        outcome: str | None,
        since: datetime | None,
        until: datetime | None,
        search: str | None,
        sort: str | None,
    ) -> Select[Any]:
        stmt = select(AuditLog)
        if actor:
            stmt = stmt.where(AuditLog.actor_name == actor)
        if action:
            stmt = stmt.where(
                AuditLog.action.like(_like(action) if "%" not in action else action, escape="\\")
            )
        if resource_type:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if outcome:
            stmt = stmt.where(AuditLog.outcome == outcome)
        if since:
            stmt = stmt.where(AuditLog.created_at >= since)
        if until:
            stmt = stmt.where(AuditLog.created_at <= until)
        if search:
            like = _like(search.lower())
            stmt = stmt.where(
                or_(
                    func.lower(AuditLog.action).like(like, escape="\\"),
                    func.lower(AuditLog.actor_name).like(like, escape="\\"),
                    AuditLog.resource_id == search,
                )
            )
        return apply_sort(
            stmt,
            AuditLog,
            sort,
            {
                "created_at": AuditLog.created_at,
                "action": AuditLog.action,
                "actor_name": AuditLog.actor_name,
            },
            AuditLog.created_at.desc(),
        )


class NotificationRepository(Repository[Notification]):
    model = Notification
    label = "Notification"


def make_repos(db: Session) -> dict[str, Any]:
    return {}
