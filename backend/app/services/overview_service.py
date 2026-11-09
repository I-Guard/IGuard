"""Aggregations for the overview dashboard and server health derivation."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import UpstreamUnavailable
from app.database.session import utcnow
from app.models import Incident, Notification, RecoveryExecution, Server, Service
from app.models.enums import IncidentStatus, ServiceStatus, Severity
from app.monitoring import prometheus as pq
from app.monitoring.prometheus import PrometheusClient
from app.schemas.ops import NotificationOut
from app.services import monitoring_service
from app.services.presenters import incident_out


def node_up_map(prom: PrometheusClient) -> dict[str, float] | None:
    """instance -> 1/0 for node-exporter targets; None when Prometheus cannot be queried."""
    try:
        return prom.by_label('up{job="node-exporter"}')
    except UpstreamUnavailable:
        return None


def active_incident_counts(db: Session) -> dict[uuid.UUID, dict[str, int]]:
    rows = db.execute(
        select(Incident.server_id, Incident.severity, func.count())
        .where(Incident.status != IncidentStatus.RESOLVED, Incident.server_id.is_not(None))
        .group_by(Incident.server_id, Incident.severity)
    ).all()
    out: dict[uuid.UUID, dict[str, int]] = {}
    for sid, sev, n in rows:
        if sid is None:
            continue
        out.setdefault(sid, {})[sev.value if hasattr(sev, "value") else sev] = int(n)
    return out


def server_health(server: Server, up: dict[str, float] | None, counts: dict[str, int]) -> str:
    if not server.is_active:
        return "unknown"
    if counts.get("CRITICAL"):
        return "unhealthy"
    if server.prometheus_instance and up is not None:
        val = up.get(server.prometheus_instance)
        if val is None:
            return "unknown"
        if val < 1:
            return "unhealthy"
    elif server.prometheus_instance and up is None:
        return "degraded" if counts.get("WARNING") else "unknown"
    if counts.get("WARNING"):
        return "degraded"
    return "healthy"


def build_overview(db: Session, prom: PrometheusClient) -> dict[str, Any]:
    now = utcnow()
    up = node_up_map(prom)
    servers = list(db.scalars(select(Server).where(Server.is_active.is_(True))))
    counts = active_incident_counts(db)
    health = [server_health(s, up, counts.get(s.id, {})) for s in servers]

    def avg_metric(expr: str) -> float | None:
        try:
            values = list(prom.by_label(expr).values())
        except UpstreamUnavailable:
            return None
        return round(sum(values) / len(values), 2) if values else None

    services = list(db.scalars(select(Service).where(Service.enabled.is_(True))))
    avail = monitoring_service.availability_bulk(db, timedelta(hours=24))
    avail_values = [avail[s.id] for s in services if s.id in avail]
    latency = monitoring_service.avg_latency(db, timedelta(minutes=15))

    active = (
        db.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.status != IncidentStatus.RESOLVED)
        )
        or 0
    )
    critical = (
        db.scalar(
            select(func.count())
            .select_from(Incident)
            .where(
                Incident.status != IncidentStatus.RESOLVED, Incident.severity == Severity.CRITICAL
            )
        )
        or 0
    )
    recent_incidents = list(
        db.scalars(select(Incident).order_by(Incident.created_at.desc()).limit(8)).unique()
    )
    recent_alerts = list(
        db.scalars(select(Notification).order_by(Notification.created_at.desc()).limit(8))
    )
    rec_rows = db.execute(
        select(RecoveryExecution.status, func.count())
        .where(
            RecoveryExecution.created_at >= now - timedelta(hours=24),
            RecoveryExecution.dry_run.is_(False),
        )
        .group_by(RecoveryExecution.status)
    ).all()
    rec_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in rec_rows}
    return {
        "generated_at": now,
        "monitoring": {"prometheus_available": up is not None},
        "servers": {
            "total": len(servers),
            "healthy": health.count("healthy"),
            "degraded": health.count("degraded"),
            "unhealthy": health.count("unhealthy"),
            "unknown": health.count("unknown"),
        },
        "incidents": {"active": int(active), "critical": int(critical)},
        "services": {
            "total": len(services),
            "up": sum(1 for s in services if s.status == ServiceStatus.UP),
            "degraded": sum(1 for s in services if s.status == ServiceStatus.DEGRADED),
            "down": sum(1 for s in services if s.status == ServiceStatus.DOWN),
            "unknown": sum(1 for s in services if s.status == ServiceStatus.UNKNOWN),
            "availability_24h_percent": round(sum(avail_values) / len(avail_values), 3)
            if avail_values
            else None,
            "avg_latency_ms_15m": round(latency, 1) if latency is not None else None,
        },
        "utilization": {
            "cpu_percent": avg_metric(pq.Q_CPU),
            "memory_percent": avg_metric(pq.Q_MEM),
            "disk_percent": avg_metric(pq.Q_DISK),
        },
        "recent_incidents": [incident_out(i).model_dump(mode="json") for i in recent_incidents],
        "recent_alerts": [
            NotificationOut.model_validate(n).model_dump(mode="json") for n in recent_alerts
        ],
        "recovery_activity_24h": rec_counts,
    }
