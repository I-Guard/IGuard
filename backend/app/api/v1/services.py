from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    client_ip,
    get_integrations,
    require_admin,
    require_operator,
    require_viewer,
)
from app.core.errors import ConflictError, NotFoundError, ValidationFailed
from app.database.session import get_db
from app.integrations import Integrations
from app.models import Server, Service, ServiceCheck
from app.models.enums import CheckType, ServiceStatus
from app.monitoring.checker import validate_service_target
from app.repositories.base import paginate
from app.repositories.domain import ServiceRepository
from app.schemas.common import Page, PageParams
from app.schemas.infra import (
    CheckResultOut,
    ServiceCheckOut,
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
    _validate_target,
)
from app.services import audit, monitoring_service
from app.services.presenters import service_out

router = APIRouter(prefix="/services", tags=["services"])


def _ensure_server(db: Session, server_id: uuid.UUID | None) -> None:
    if server_id is not None and db.get(Server, server_id) is None:
        raise ValidationFailed("server_id does not reference an existing server")


@router.get("", response_model=Page[ServiceOut])
def list_services(
    params: PageParams = Depends(),
    search: str | None = Query(None, max_length=100),
    status: ServiceStatus | None = None,
    server_id: uuid.UUID | None = None,
    enabled: bool | None = None,
    sort: str | None = Query(None),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_viewer),
) -> Page[ServiceOut]:
    rows, total = paginate(
        db,
        ServiceRepository(db).list(
            search, status.value if status else None, server_id, enabled, sort
        ),
        params,
    )
    avail = monitoring_service.availability_bulk(db, timedelta(hours=24))
    return Page.build(
        [service_out(s, avail.get(s.id)) for s in rows], total, params.page, params.page_size
    )


@router.post("", response_model=ServiceOut, status_code=201)
def create_service(
    body: ServiceCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> ServiceOut:
    _ensure_server(db, body.server_id)
    svc = Service(**body.model_dump())
    validate_service_target(svc)
    try:
        with db.begin_nested():
            db.add(svc)
            db.flush()
    except IntegrityError as exc:
        raise ConflictError(f"A service named '{body.name}' already exists") from exc
    audit.record(
        db,
        action="service.create",
        resource_type="service",
        resource_id=svc.id,
        actor=principal.user,
        ip=client_ip(request),
        details={"name": svc.name},
    )
    return service_out(svc)


@router.get("/{service_id}", response_model=ServiceOut)
def get_service(
    service_id: uuid.UUID, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)
) -> ServiceOut:
    svc = ServiceRepository(db).get_or_404(service_id)
    return service_out(svc, monitoring_service.availability(db, svc.id, timedelta(hours=24)))


@router.get(
    "/{service_id}/checks",
    response_model=list[ServiceCheckOut],
    summary="Recent check history (newest first)",
)
def service_checks(
    service_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    hours: Annotated[int, Query(ge=1, le=336)] = 24,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_viewer),
) -> list:
    ServiceRepository(db).get_or_404(service_id)
    from app.database.session import utcnow

    stmt = (
        select(ServiceCheck)
        .where(
            ServiceCheck.service_id == service_id,
            ServiceCheck.checked_at >= utcnow() - timedelta(hours=hours),
        )
        .order_by(ServiceCheck.checked_at.desc())
        .limit(limit)
    )
    return [ServiceCheckOut.model_validate(c) for c in db.scalars(stmt)]


@router.get("/{service_id}/availability")
def service_availability(
    service_id: uuid.UUID, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)
) -> dict:
    ServiceRepository(db).get_or_404(service_id)
    return {
        f"{label}": monitoring_service.availability(db, service_id, delta)
        for label, delta in (
            ("1h", timedelta(hours=1)),
            ("24h", timedelta(hours=24)),
            ("7d", timedelta(days=7)),
        )
    }


@router.patch("/{service_id}", response_model=ServiceOut)
def update_service(
    service_id: uuid.UUID,
    body: ServiceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> ServiceOut:
    svc = ServiceRepository(db).get_or_404(service_id)
    changes = body.model_dump(exclude_unset=True)
    if "server_id" in changes:
        _ensure_server(db, changes["server_id"])
    for k, v in changes.items():
        setattr(svc, k, v)
    try:
        _validate_target(CheckType(svc.check_type), svc.url, svc.host, svc.port)
    except ValueError as exc:
        db.rollback()
        raise ValidationFailed(str(exc)) from exc
    validate_service_target(svc)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A service with that name already exists") from exc
    audit.record(
        db,
        action="service.update",
        resource_type="service",
        resource_id=svc.id,
        actor=principal.user,
        ip=client_ip(request),
        details={"fields": sorted(changes)},
    )
    return service_out(svc)


@router.delete("/{service_id}", status_code=204)
def delete_service(
    service_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> Response:
    svc = ServiceRepository(db).get_or_404(service_id)
    name = svc.name
    ServiceRepository(db).delete(svc)
    audit.record(
        db,
        action="service.delete",
        resource_type="service",
        resource_id=service_id,
        actor=principal.user,
        ip=client_ip(request),
        details={"name": name},
    )
    return Response(status_code=204)


@router.post(
    "/{service_id}/check",
    response_model=CheckResultOut,
    summary="Run a health check now and record the result",
)
def check_now(
    service_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    principal: Principal = Depends(require_operator),
) -> CheckResultOut:
    svc = ServiceRepository(db).get_or_404(service_id)
    if svc is None:
        raise NotFoundError("Service not found")
    outcome, when = monitoring_service.check_service(db, svc, transport=integ.checker_transport)
    audit.record(
        db,
        action="service.check",
        resource_type="service",
        resource_id=svc.id,
        actor=principal.user,
        ip=client_ip(request),
        outcome="SUCCESS" if outcome.success else "FAILURE",
        details={"status_code": outcome.status_code},
    )
    return CheckResultOut(
        service_id=svc.id,
        success=outcome.success,
        status=svc.status,
        status_code=outcome.status_code,
        response_time_ms=outcome.response_time_ms,
        error=outcome.error,
        checked_at=when,
    )
