from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import Principal, get_integrations, require_viewer
from app.core.config import get_settings
from app.database.session import get_db
from app.integrations import Integrations
from app.services import overview_service

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness probe")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe (database required; monitoring stack reported)")
def ready(
    response: Response,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
) -> dict[str, Any]:
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    # Monitoring integrations are optional for readiness: degraded, not failed.
    checks["prometheus"] = "ok" if integ.prometheus.is_available() else "unavailable"
    checks["loki"] = "ok" if integ.loki.is_available() else "unavailable"
    ready_ = checks["database"] == "ok"
    if not ready_:
        response.status_code = 503
    return {"status": "ready" if ready_ else "not_ready", "checks": checks}


@router.get("/version")
def version() -> dict[str, str]:
    s = get_settings()
    return {"name": "IGuard", "version": __version__, "environment": s.env}


@router.get("/overview", summary="Aggregated dashboard data")
def overview(
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    _: Principal = Depends(require_viewer),
) -> dict[str, Any]:
    return overview_service.build_overview(db, integ.prometheus)
