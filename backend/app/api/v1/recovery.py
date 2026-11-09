from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_integrations, require_operator, require_viewer
from app.core.errors import NotFoundError
from app.database.session import get_db
from app.integrations import Integrations
from app.models import Incident, RecoveryAction
from app.recovery.service import RecoveryService
from app.repositories.base import paginate
from app.repositories.domain import RecoveryActionRepository, RecoveryExecutionRepository
from app.schemas.common import Page, PageParams
from app.schemas.recovery import (
    DryRunRequest,
    ExecuteRequest,
    RecoveryActionOut,
    RecoveryExecutionOut,
)
from app.services import settings_service
from app.services.presenters import action_out, execution_out

router = APIRouter(prefix="/recovery", tags=["recovery"])


def _svc(db: Session, integ: Integrations) -> RecoveryService:
    return RecoveryService(
        db,
        integ.recovery_adapter,
        settings_service.effective(db),
        checker_transport=integ.checker_transport,
    )


def _incident(db: Session, incident_id: uuid.UUID | None) -> Incident | None:
    if incident_id is None:
        return None
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise NotFoundError("Incident not found")
    return inc


@router.get(
    "/actions",
    response_model=list[RecoveryActionOut],
    summary="Allowlisted recovery actions with live cooldown/circuit state",
)
def list_actions(
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    _: Principal = Depends(require_viewer),
) -> list[RecoveryActionOut]:
    svc = _svc(db, integ)
    rows = db.scalars(select(RecoveryAction).order_by(RecoveryAction.key)).unique()
    return [action_out(a, svc.runtime_state(a)) for a in rows]


@router.get("/history", response_model=Page[RecoveryExecutionOut])
def history(
    params: PageParams = Depends(),
    action_id: uuid.UUID | None = None,
    incident_id: uuid.UUID | None = None,
    status: str | None = Query(None, max_length=32),
    dry_run: bool | None = None,
    sort: str | None = None,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_viewer),
) -> Page[RecoveryExecutionOut]:
    stmt = RecoveryExecutionRepository(db).list(
        action_id=action_id, incident_id=incident_id, status=status, dry_run=dry_run, sort=sort
    )
    rows, total = paginate(db, stmt, params)
    return Page.build([execution_out(r) for r in rows], total, params.page, params.page_size)


@router.get("/history/{execution_id}", response_model=RecoveryExecutionOut)
def history_item(
    execution_id: uuid.UUID, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)
) -> RecoveryExecutionOut:
    return execution_out(RecoveryExecutionRepository(db).get_or_404(execution_id))


@router.post("/actions/{action_id}/dry-run", response_model=RecoveryExecutionOut)
def dry_run(
    action_id: uuid.UUID,
    body: DryRunRequest | None = None,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    principal: Principal = Depends(require_operator),
) -> RecoveryExecutionOut:
    action = RecoveryActionRepository(db).get_or_404(action_id)
    inc = _incident(db, body.incident_id if body else None)
    ex = _svc(db, integ).dry_run(action, principal.user, inc)
    return execution_out(ex)


@router.post(
    "/actions/{action_id}/execute",
    response_model=RecoveryExecutionOut,
    summary="Execute an allowlisted action (waits for health verification)",
)
def execute(
    action_id: uuid.UUID,
    response: Response,
    body: ExecuteRequest | None = None,
    idempotency_key: Annotated[
        str | None, Header(max_length=128, pattern=r"^[A-Za-z0-9_.\-]+$")
    ] = None,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    principal: Principal = Depends(require_operator),
) -> RecoveryExecutionOut:
    body = body or ExecuteRequest()
    action = RecoveryActionRepository(db).get_or_404(action_id)
    inc = _incident(db, body.incident_id)
    svc = _svc(db, integ)
    ex, created = svc.request_execution(
        action,
        principal.user,
        inc,
        confirm=body.confirm,
        idempotency_key=idempotency_key,
        reason=body.reason,
    )
    if not created:
        response.headers["Idempotent-Replay"] = "true"
        return execution_out(ex)
    db.commit()  # make the RUNNING record visible before the (slow) run
    ex = svc.run_execution(ex.id)
    return execution_out(ex)
