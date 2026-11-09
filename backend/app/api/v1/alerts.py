from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    client_ip,
    get_integrations,
    require_admin,
    require_operator,
    require_viewer,
)
from app.core.errors import UpstreamUnavailable
from app.database.session import get_db
from app.integrations import Integrations
from app.models import Notification
from app.notifications import dispatcher
from app.repositories.base import paginate
from app.schemas.common import PageParams
from app.schemas.ops import AlertConfigOut, AlertConfigUpdate, AlertOut, AlertTestRequest
from app.services import audit

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", summary="Active Alertmanager alerts plus IGuard notification history")
def list_alerts(
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    _: Principal = Depends(require_viewer),
) -> dict[str, Any]:
    live: list[AlertOut] = []
    alertmanager_available = True
    try:
        for a in integ.alertmanager.active_alerts():
            live.append(AlertOut(source="alertmanager", **a))
    except UpstreamUnavailable:
        alertmanager_available = False
    stmt = select(Notification).order_by(Notification.created_at.desc())
    rows, total = paginate(db, stmt, params)
    history = [
        AlertOut(
            source="iguard",
            name=n.event_type,
            severity=n.severity,
            state=n.status.value,
            summary=n.title,
            started_at=n.created_at,
            incident_id=n.incident_id,
        )
        for n in rows
    ]
    return {
        "alertmanager_available": alertmanager_available,
        "active": live,
        "history": {
            "items": history,
            "total": total,
            "page": params.page,
            "page_size": params.page_size,
        },
    }


@router.get("/configuration", response_model=AlertConfigOut)
def get_configuration(
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    _: Principal = Depends(require_viewer),
) -> AlertConfigOut:
    out = AlertConfigOut.model_validate(dispatcher.get_or_create_config(db))
    out.channel_configured = integ.telegram.configured
    return out


@router.patch("/configuration", response_model=AlertConfigOut)
def update_configuration(
    body: AlertConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    principal: Principal = Depends(require_admin),
) -> AlertConfigOut:
    cfg = dispatcher.get_or_create_config(db)
    changes = body.model_dump(exclude_unset=True, exclude={"channel"})
    if "notify_events" in changes and changes["notify_events"] is not None:
        changes["notify_events"] = [
            e.value if hasattr(e, "value") else e for e in changes["notify_events"]
        ]
    for k, v in changes.items():
        if v is not None:
            setattr(cfg, k, v)
    db.flush()
    audit.record(
        db,
        action="alerts.configure",
        resource_type="alert_configuration",
        resource_id=cfg.id,
        actor=principal.user,
        ip=client_ip(request),
        details={"fields": sorted(changes)},
    )
    out = AlertConfigOut.model_validate(cfg)
    out.channel_configured = integ.telegram.configured
    return out


@router.post("/test", summary="Send a test notification (operators and above)")
def test_alert(
    request: Request,
    body: AlertTestRequest | None = None,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    msg = body.message if body else "IGuard test notification"
    result = dispatcher.send_test(db, msg, integ.telegram)
    audit.record(
        db,
        action="alerts.test",
        resource_type="notification",
        resource_id=result["notification_id"],
        actor=principal.user,
        ip=client_ip(request),
        outcome="SUCCESS" if result["status"] == "SENT" else result["status"],
    )
    return {
        "notification_id": str(result["notification_id"]),
        "status": result["status"],
        "error": result["error"],
        "configured": integ.telegram.configured,
    }


# ---------------------------------------------------------------------------------------------
# Alertmanager webhook receiver: turns Prometheus alerts into deduplicated IGuard incidents.
# ---------------------------------------------------------------------------------------------
import hmac  # noqa: E402

from fastapi import Header  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.errors import UnauthorizedError  # noqa: E402
from app.incidents.engine import IncidentEngine, Signal  # noqa: E402
from app.models import Server  # noqa: E402
from app.models.enums import IncidentCategory, Severity  # noqa: E402
from app.services import settings_service  # noqa: E402

_CATEGORY_BY_ALERT = {
    "HostHighCpu": IncidentCategory.CPU,
    "HostHighMemory": IncidentCategory.MEMORY,
    "HostDiskSpaceLow": IncidentCategory.DISK,
    "EndpointDown": IncidentCategory.SERVICE_DOWN,
    "TargetDown": IncidentCategory.TARGET_DOWN,
    "ContainerRestarting": IncidentCategory.CONTAINER_RESTARTS,
    "ContainerDown": IncidentCategory.CONTAINER_FAILURE,
    "HighProbeLatency": IncidentCategory.HIGH_LATENCY,
}


@router.post(
    "/webhook", include_in_schema=True, summary="Alertmanager webhook receiver (token-protected)"
)
def alertmanager_webhook(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, int]:
    expected = get_settings().webhook_token.get_secret_value()
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not expected or not hmac.compare_digest(supplied, expected):
        raise UnauthorizedError("Invalid webhook token", code="invalid_webhook_token")
    engine = IncidentEngine(db, settings_service.effective(db))
    created = resolved = 0
    for alert in payload.get("alerts", [])[:100]:
        labels = alert.get("labels", {}) or {}
        ann = alert.get("annotations", {}) or {}
        name = str(labels.get("alertname", "unknown"))[:100]
        instance = str(labels.get("instance", ""))[:200]
        server = (
            db.scalar(select(Server).where(Server.prometheus_instance == instance))
            if instance
            else None
        )
        sig = Signal(
            rule=f"alertmanager:{name}",
            source="alertmanager",
            category=_CATEGORY_BY_ALERT.get(name, IncidentCategory.OTHER),
            severity=Severity.CRITICAL
            if labels.get("severity") == "critical"
            else Severity.WARNING,
            title=str(ann.get("summary") or name)[:255],
            description=str(ann.get("description") or ann.get("summary") or name)[:2000],
            server_id=server.id if server else None,
            subject=instance,
            context={"alertname": name, "instance": instance},
        )
        if alert.get("status") == "resolved":
            if engine.clear(sig.fingerprint) is not None:
                resolved += 1
        else:
            if engine.observe(sig).action == "created":
                created += 1
    return {"created": created, "cleared_signals": resolved}
