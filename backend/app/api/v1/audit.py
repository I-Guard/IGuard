from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require_admin
from app.database.session import get_db
from app.repositories.base import paginate
from app.repositories.domain import AuditRepository
from app.schemas.common import Page, PageParams
from app.schemas.ops import AuditLogOut

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=Page[AuditLogOut], summary="Audit trail (ADMIN only)")
def list_audit(
    params: PageParams = Depends(),
    actor: str | None = Query(None, max_length=128),
    action: str | None = Query(None, max_length=64),
    resource_type: str | None = Query(None, max_length=64),
    outcome: str | None = Query(None, max_length=16),
    since: datetime | None = None,
    until: datetime | None = None,
    search: str | None = Query(None, max_length=100),
    sort: str | None = None,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_admin),
) -> Page[AuditLogOut]:
    stmt = AuditRepository(db).list(
        actor=actor,
        action=action,
        resource_type=resource_type,
        outcome=outcome,
        since=since,
        until=until,
        search=search,
        sort=sort,
    )
    rows, total = paginate(db, stmt, params)
    return Page.build(
        [AuditLogOut.model_validate(r) for r in rows], total, params.page, params.page_size
    )
