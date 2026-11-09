from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require_viewer
from app.database.session import get_db, utcnow
from app.models import Incident, RecoveryExecution, Service
from app.models.enums import IncidentStatus
from app.services import monitoring_service

router = APIRouter(prefix="/reports", tags=["reports"])
Days = Annotated[int, Query(ge=1, le=90, description="Look-back window in days")]


def _mttr_minutes(db: Session, since: datetime) -> float | None:
    rows = db.execute(
        select(Incident.created_at, Incident.resolved_at).where(
            Incident.created_at >= since, Incident.resolved_at.is_not(None)
        )
    ).all()
    if not rows:
        return None
    return round(sum((r - c).total_seconds() for c, r in rows if r is not None) / len(rows) / 60, 2)


def _group(db: Session, col: Any, since: datetime) -> dict[str, int]:
    rows = db.execute(
        select(col, func.count()).where(Incident.created_at >= since).group_by(col)
    ).all()
    return {(k.value if hasattr(k, "value") else str(k)): int(n) for k, n in rows}


@router.get("/summary")
def summary(
    days: Days = 7, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)
) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    total = (
        db.scalar(select(func.count()).select_from(Incident).where(Incident.created_at >= since))
        or 0
    )
    open_ = (
        db.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.status != IncidentStatus.RESOLVED)
        )
        or 0
    )
    rec = db.execute(
        select(RecoveryExecution.status, func.count())
        .where(RecoveryExecution.created_at >= since, RecoveryExecution.dry_run.is_(False))
        .group_by(RecoveryExecution.status)
    ).all()
    avail = monitoring_service.availability_bulk(db, timedelta(days=days))
    return {
        "period_days": days,
        "generated_at": utcnow(),
        "incidents_total": int(total),
        "incidents_open": int(open_),
        "mttr_minutes": _mttr_minutes(db, since),
        "by_severity": _group(db, Incident.severity, since),
        "by_category": _group(db, Incident.category, since),
        "recoveries": {(s.value if hasattr(s, "value") else str(s)): int(n) for s, n in rec},
        "average_availability_percent": round(sum(avail.values()) / len(avail), 3)
        if avail
        else None,
    }


@router.get("/availability")
def availability(
    days: Days = 7, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)
) -> dict[str, Any]:
    window = timedelta(days=days)
    avail = monitoring_service.availability_bulk(db, window)
    items = []
    for s in db.scalars(select(Service).order_by(Service.name)).unique():
        items.append(
            {
                "service_id": str(s.id),
                "service": s.name,
                "status": s.status.value,
                "availability_percent": avail.get(s.id),  # None = no data (never shown as 0%)
                "last_response_ms": s.last_response_ms,
            }
        )
    return {"period_days": days, "items": items}


@router.get("/incidents")
def incidents(
    days: Days = 7, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)
) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    per_day = db.execute(
        select(func.date(Incident.created_at), func.count())
        .where(Incident.created_at >= since)
        .group_by(func.date(Incident.created_at))
        .order_by(func.date(Incident.created_at))
    ).all()
    top = db.execute(
        select(Incident.title, func.sum(Incident.occurrences))
        .where(Incident.created_at >= since)
        .group_by(Incident.title)
        .order_by(func.sum(Incident.occurrences).desc())
        .limit(5)
    ).all()
    return {
        "period_days": days,
        "mttr_minutes": _mttr_minutes(db, since),
        "by_severity": _group(db, Incident.severity, since),
        "by_category": _group(db, Incident.category, since),
        "by_status": _group(db, Incident.status, since),
        "per_day": [{"date": str(d), "count": int(n)} for d, n in per_day],
        "top_recurring": [{"title": t, "occurrences": int(n or 0)} for t, n in top],
        "flapping": int(
            db.scalar(
                select(func.count())
                .select_from(Incident)
                .where(Incident.created_at >= since, Incident.is_flapping.is_(True))
            )
            or 0
        ),
    }


@router.get("/recovery")
def recovery(
    days: Days = 7, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)
) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    rows = (
        db.execute(
            select(RecoveryExecution).where(
                RecoveryExecution.created_at >= since, RecoveryExecution.dry_run.is_(False)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    by_action: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = by_action.setdefault(
            r.action.key,
            {
                "action": r.action.key,
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "avg_duration_ms": None,
                "_d": [],
            },
        )
        d["total"] += 1
        d["succeeded"] += r.status.value == "SUCCEEDED"
        d["failed"] += r.status.value in ("FAILED", "VERIFICATION_FAILED")
        if r.duration_ms is not None:
            d["_d"].append(r.duration_ms)
    out = []
    for d in by_action.values():
        ds = d.pop("_d")
        d["avg_duration_ms"] = round(sum(ds) / len(ds), 1) if ds else None
        out.append(d)
    total = len(rows)
    ok = sum(1 for r in rows if r.status.value == "SUCCEEDED")
    return {
        "period_days": days,
        "total": total,
        "succeeded": ok,
        "success_rate_percent": round(100 * ok / total, 1) if total else None,
        "automatic": sum(1 for r in rows if r.trigger.value == "AUTOMATIC"),
        "manual": sum(1 for r in rows if r.trigger.value == "MANUAL"),
        "by_action": out,
    }
