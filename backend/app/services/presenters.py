"""Map ORM objects to API schemas (adds derived/joined fields)."""

from __future__ import annotations

from typing import Any

from app.models import Incident, RecoveryAction, RecoveryExecution, Server, Service
from app.schemas.incident import IncidentDetail, IncidentOut
from app.schemas.infra import ServerOut, ServiceOut
from app.schemas.recovery import RecoveryActionOut, RecoveryExecutionOut


def incident_out(inc: Incident) -> IncidentOut:
    out = IncidentOut.model_validate(inc)
    out.server_name = inc.server.name if inc.server else None
    out.service_name = inc.service.name if inc.service else None
    return out


def incident_detail(inc: Incident, related: list[Incident]) -> IncidentDetail:
    base = incident_out(inc)
    return IncidentDetail(**base.model_dump(), related=[incident_out(r) for r in related])


def service_out(svc: Service, availability: float | None = None) -> ServiceOut:
    out = ServiceOut.model_validate(svc)
    out.server_name = svc.server.name if svc.server else None
    out.availability_24h = availability
    return out


def server_out(
    srv: Server, health: str = "unknown", active_incidents: int = 0, service_count: int = 0
) -> ServerOut:
    out = ServerOut.model_validate(srv)
    out.health = health  # type: ignore[assignment]
    out.active_incidents = active_incidents
    out.service_count = service_count
    return out


def action_out(action: RecoveryAction, state: dict[str, Any] | None = None) -> RecoveryActionOut:
    out = RecoveryActionOut.model_validate(action)
    out.service_name = action.service.name if action.service else None
    if state:
        for k, v in state.items():
            setattr(out, k, v)
    return out


def execution_out(ex: RecoveryExecution) -> RecoveryExecutionOut:
    out = RecoveryExecutionOut.model_validate(ex)
    out.action_key = ex.action.key if ex.action else None
    out.action_name = ex.action.name if ex.action else None
    return out
