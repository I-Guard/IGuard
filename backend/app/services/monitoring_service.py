"""Service registry operations: run checks, persist results, compute availability."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database.session import utcnow
from app.models import Service, ServiceCheck
from app.models.enums import ServiceStatus
from app.monitoring.checker import CheckOutcome, run_check


def apply_outcome(service: Service, outcome: CheckOutcome, now: datetime) -> ServiceStatus:
    previous = service.status
    service.last_checked_at = now
    service.last_response_ms = outcome.response_time_ms
    service.last_status_code = outcome.status_code
    service.last_error = outcome.error
    if outcome.success:
        service.consecutive_failures = 0
        service.consecutive_successes += 1
        slow = (
            outcome.response_time_ms is not None
            and outcome.response_time_ms > service.latency_threshold_ms
        )
        service.status = ServiceStatus.DEGRADED if slow else ServiceStatus.UP
    else:
        service.consecutive_successes = 0
        service.consecutive_failures += 1
        if service.consecutive_failures >= service.retry_threshold:
            service.status = ServiceStatus.DOWN
        elif previous != ServiceStatus.DOWN:
            service.status = ServiceStatus.DEGRADED
    if service.status != previous or service.status_since is None:
        service.status_since = now
    return service.status


def check_service(
    db: Session, service: Service, transport: httpx.BaseTransport | None = None
) -> tuple[CheckOutcome, datetime]:
    outcome = run_check(service, transport=transport)
    now = utcnow()
    db.add(
        ServiceCheck(
            service_id=service.id,
            checked_at=now,
            success=outcome.success,
            status_code=outcome.status_code,
            response_time_ms=outcome.response_time_ms,
            error=outcome.error,
        )
    )
    apply_outcome(service, outcome, now)
    db.flush()
    return outcome, now


def due_services(db: Session, now: datetime | None = None) -> list[Service]:
    now = now or utcnow()
    rows = db.scalars(select(Service).where(Service.enabled.is_(True)))
    return [
        s
        for s in rows
        if s.last_checked_at is None
        or now - s.last_checked_at >= timedelta(seconds=s.interval_seconds)
    ]


def availability(db: Session, service_id: uuid.UUID, window: timedelta) -> float | None:
    """Percentage of successful checks in the window; None when there is no data."""
    since = utcnow() - window
    total, ok = db.execute(
        select(
            func.count(ServiceCheck.id), func.sum(func.cast(ServiceCheck.success, _int()))
        ).where(ServiceCheck.service_id == service_id, ServiceCheck.checked_at >= since)
    ).one()
    if not total:
        return None
    return round(100.0 * (ok or 0) / total, 3)


def availability_bulk(db: Session, window: timedelta) -> dict[uuid.UUID, float]:
    since = utcnow() - window
    rows = db.execute(
        select(
            ServiceCheck.service_id,
            func.count(ServiceCheck.id),
            func.sum(func.cast(ServiceCheck.success, _int())),
        )
        .where(ServiceCheck.checked_at >= since)
        .group_by(ServiceCheck.service_id)
    ).all()
    return {sid: round(100.0 * (ok or 0) / total, 3) for sid, total, ok in rows if total}


def avg_latency(db: Session, window: timedelta) -> float | None:
    since = utcnow() - window
    return db.scalar(
        select(func.avg(ServiceCheck.response_time_ms)).where(
            ServiceCheck.checked_at >= since, ServiceCheck.success.is_(True)
        )
    )


def purge_old_checks(db: Session, days: int) -> int:
    res = db.execute(
        delete(ServiceCheck).where(ServiceCheck.checked_at < utcnow() - timedelta(days=days))
    )
    return int(getattr(res, "rowcount", 0) or 0)


def _int():
    from sqlalchemy import Integer

    return Integer
