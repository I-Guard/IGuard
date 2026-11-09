from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, client_ip, require_operator, require_viewer
from app.core.errors import NotFoundError
from app.database.session import get_db
from app.incidents.engine import IncidentEngine, get_incident_or_404
from app.models import Incident, IncidentEvent, User
from app.models.enums import IncidentCategory, IncidentStatus, Severity
from app.repositories.base import paginate
from app.repositories.domain import IncidentRepository
from app.schemas.common import Page, PageParams
from app.schemas.incident import (
    AcknowledgeRequest,
    AssignRequest,
    IncidentDetail,
    IncidentEventOut,
    IncidentOut,
    ResolveRequest,
    StatusUpdateRequest,
)
from app.services import audit, settings_service
from app.services.presenters import incident_detail, incident_out

router = APIRouter(prefix="/incidents", tags=["incidents"])


def _engine(db: Session) -> IncidentEngine:
    return IncidentEngine(db, settings_service.effective(db))


@router.get("", response_model=Page[IncidentOut])
def list_incidents(
    params: PageParams = Depends(),
    status: list[IncidentStatus] | None = Query(None),
    severity: list[Severity] | None = Query(None),
    category: IncidentCategory | None = None,
    server_id: uuid.UUID | None = None,
    service_id: uuid.UUID | None = None,
    assigned_to: uuid.UUID | None = None,
    active: bool | None = None,
    search: str | None = Query(None, max_length=100),
    since: datetime | None = None,
    until: datetime | None = None,
    sort: str | None = Query(
        None, description="created_at|updated_at|severity|status|occurrences|title; '-' for desc"
    ),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_viewer),
) -> Page[IncidentOut]:
    stmt = IncidentRepository(db).list(
        status=status,
        severity=severity,
        category=category,
        server_id=server_id,
        service_id=service_id,
        assigned_to=assigned_to,
        active=active,
        search=search,
        since=since,
        until=until,
        sort=sort,
    )
    rows, total = paginate(db, stmt, params)
    return Page.build([incident_out(i) for i in rows], total, params.page, params.page_size)


@router.get("/{incident_id}", response_model=IncidentDetail)
def get_incident(
    incident_id: uuid.UUID, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)
) -> IncidentDetail:
    inc = get_incident_or_404(db, incident_id)
    related: list[Incident] = []
    if inc.correlation_group:
        related = list(
            db.scalars(
                select(Incident).where(
                    Incident.correlation_group == inc.correlation_group, Incident.id != inc.id
                )
            ).unique()
        )
    return incident_detail(inc, related)


@router.get("/{incident_id}/timeline", response_model=list[IncidentEventOut])
def timeline(
    incident_id: uuid.UUID, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)
) -> list[IncidentEventOut]:
    get_incident_or_404(db, incident_id)
    rows = db.scalars(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.created_at, IncidentEvent.id)
    )
    return [IncidentEventOut.model_validate(e) for e in rows]


@router.post("/{incident_id}/acknowledge", response_model=IncidentOut)
def acknowledge(
    incident_id: uuid.UUID,
    request: Request,
    body: AcknowledgeRequest | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_operator),
) -> IncidentOut:
    inc = get_incident_or_404(db, incident_id)
    _engine(db).acknowledge(inc, principal.user, body.note if body else None)
    audit.record(
        db,
        action="incident.acknowledge",
        resource_type="incident",
        resource_id=inc.id,
        actor=principal.user,
        ip=client_ip(request),
    )
    return incident_out(inc)


@router.post("/{incident_id}/assign", response_model=IncidentOut)
def assign(
    incident_id: uuid.UUID,
    body: AssignRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_operator),
) -> IncidentOut:
    inc = get_incident_or_404(db, incident_id)
    assignee = db.get(User, body.assignee_id)
    if assignee is None:
        raise NotFoundError("Assignee not found")
    _engine(db).assign(inc, assignee, principal.user, body.note)
    audit.record(
        db,
        action="incident.assign",
        resource_type="incident",
        resource_id=inc.id,
        actor=principal.user,
        ip=client_ip(request),
        details={"assignee": assignee.username},
    )
    return incident_out(inc)


@router.post(
    "/{incident_id}/status",
    response_model=IncidentOut,
    summary="Move an incident to INVESTIGATING or RECOVERING",
)
def set_status(
    incident_id: uuid.UUID,
    body: StatusUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_operator),
) -> IncidentOut:
    inc = get_incident_or_404(db, incident_id)
    _engine(db).set_status(inc, body.status, principal.user, body.note, body.root_cause)
    audit.record(
        db,
        action="incident.status",
        resource_type="incident",
        resource_id=inc.id,
        actor=principal.user,
        ip=client_ip(request),
        details={"status": body.status.value},
    )
    return incident_out(inc)


@router.post("/{incident_id}/resolve", response_model=IncidentOut)
def resolve(
    incident_id: uuid.UUID,
    body: ResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_operator),
) -> IncidentOut:
    inc = get_incident_or_404(db, incident_id)
    _engine(db).resolve(inc, principal.user, body.resolution_summary, body.root_cause)
    audit.record(
        db,
        action="incident.resolve",
        resource_type="incident",
        resource_id=inc.id,
        actor=principal.user,
        ip=client_ip(request),
    )
    return incident_out(inc)
