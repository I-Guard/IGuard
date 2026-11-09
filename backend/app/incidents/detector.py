"""Incident detection: turns service state and Prometheus metrics into engine signals.

Principle: *missing data is not healthy data*. If a Prometheus query cannot be evaluated (Prometheus
down, metric absent), the corresponding incidents are left untouched - they are neither raised nor
cleared - so an outage of the monitoring stack never auto-resolves real incidents.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import UpstreamUnavailable
from app.core.logging import get_logger
from app.incidents.engine import IncidentEngine, Signal, make_fingerprint
from app.models import Server, Service, ServiceCheck
from app.models.enums import IncidentCategory, ServiceStatus, Severity
from app.monitoring import prometheus as pq
from app.monitoring.prometheus import PrometheusClient

log = get_logger(__name__)

# Sustained-breach counters (per fingerprint, per process). Reset on restart by design.
_streaks: dict[str, int] = {}

CONTAINER_STALE_SECONDS = 60


@dataclass
class DetectionResult:
    created: list[uuid.UUID] = field(default_factory=list)
    recovery_candidates: list[uuid.UUID] = field(default_factory=list)
    prometheus_available: bool = True
    signals: int = 0


def reset_streaks() -> None:
    _streaks.clear()


def _metric_signals(
    engine: IncidentEngine,
    result: DetectionResult,
    *,
    rule: str,
    category: IncidentCategory,
    label: str,
    value: float | None,
    warn: float,
    crit: float,
    server: Server,
) -> None:
    fp = make_fingerprint(rule, server.id, None, "")
    if value is None:
        return  # missing data: neither raise nor clear
    if value >= warn:
        _streaks[fp] = _streaks.get(fp, 0) + 1
        if _streaks[fp] < int(engine.cfg.get("sustained_evaluations", 2)):
            return
        sev = Severity.CRITICAL if value >= crit else Severity.WARNING
        _emit(
            engine,
            result,
            Signal(
                rule=rule,
                category=category,
                severity=sev,
                server_id=server.id,
                title=f"{label} usage {sev.value.lower()} on {server.name}: {value:.1f}%",
                description=(
                    f"{label} usage is {value:.1f}% on {server.name} "
                    f"(warning >= {warn:g}%, critical >= {crit:g}%)."
                ),
                context={
                    "value": round(value, 2),
                    "warn": warn,
                    "crit": crit,
                    "instance": server.prometheus_instance,
                },
            ),
        )
    else:
        _streaks.pop(fp, None)
        engine.clear(fp)


def _emit(engine: IncidentEngine, result: DetectionResult, sig: Signal) -> None:
    result.signals += 1
    obs = engine.observe(sig)
    if obs.action == "created":
        result.created.append(obs.incident.id)
    if (
        obs.action in ("created", "reopened") or obs.severity_raised
    ) and obs.incident.severity == Severity.CRITICAL:
        result.recovery_candidates.append(obs.incident.id)


def evaluate_services(db: Session, engine: IncidentEngine, result: DetectionResult) -> None:
    for svc in db.scalars(select(Service).where(Service.enabled.is_(True))):
        if svc.status == ServiceStatus.UNKNOWN:
            continue
        avail_fp = make_fingerprint("availability", svc.server_id, svc.id, "")
        lat_fp = make_fingerprint("latency", svc.server_id, svc.id, "")
        code = svc.last_status_code or 0

        if svc.status == ServiceStatus.DOWN:
            is_5xx = 500 <= code <= 599
            cat = IncidentCategory.HTTP_5XX if is_5xx else IncidentCategory.SERVICE_DOWN
            detail = f"HTTP {code}" if is_5xx else (svc.last_error or "no response")
            _emit(
                engine,
                result,
                Signal(
                    rule="availability",
                    category=cat,
                    severity=Severity.CRITICAL,
                    server_id=svc.server_id,
                    service_id=svc.id,
                    title=f"Service {svc.name} is down ({detail})",
                    description=(
                        f"Service '{svc.name}' failed {svc.consecutive_failures} consecutive checks "
                        f"(threshold {svc.retry_threshold}). Last error: {svc.last_error or detail}."
                    ),
                    context={
                        "status_code": svc.last_status_code,
                        "error": svc.last_error,
                        "consecutive_failures": svc.consecutive_failures,
                    },
                    root_cause=f"Health check failing: {svc.last_error or detail}",
                ),
            )
            continue  # latency is meaningless while down; do not clear availability either

        if 500 <= code <= 599 and svc.consecutive_failures >= 1:
            _emit(
                engine,
                result,
                Signal(
                    rule="availability",
                    category=IncidentCategory.HTTP_5XX,
                    severity=Severity.WARNING,
                    server_id=svc.server_id,
                    service_id=svc.id,
                    title=f"Service {svc.name} returned HTTP {code}",
                    description=f"'{svc.name}' returned {code}; {svc.consecutive_failures}/{svc.retry_threshold} failures before DOWN.",
                    context={"status_code": code, "consecutive_failures": svc.consecutive_failures},
                ),
            )
            continue

        if (
            svc.status in (ServiceStatus.UP, ServiceStatus.DEGRADED)
            and svc.consecutive_failures == 0
        ):
            engine.clear(avail_fp)
            recent = [
                c.response_time_ms
                for c in db.scalars(
                    select(ServiceCheck)
                    .where(ServiceCheck.service_id == svc.id, ServiceCheck.success.is_(True))
                    .order_by(ServiceCheck.checked_at.desc())
                    .limit(3)
                )
                if c.response_time_ms is not None
            ]
            if not recent:
                continue
            avg = sum(recent) / len(recent)
            thr = svc.latency_threshold_ms
            mult = float(engine.cfg.get("latency_critical_multiplier", 3))
            if avg > thr:
                sev = Severity.CRITICAL if avg > thr * mult else Severity.WARNING
                _emit(
                    engine,
                    result,
                    Signal(
                        rule="latency",
                        category=IncidentCategory.HIGH_LATENCY,
                        severity=sev,
                        server_id=svc.server_id,
                        service_id=svc.id,
                        title=f"High latency on {svc.name}: {avg:.0f} ms",
                        description=f"Average response time of '{svc.name}' is {avg:.0f} ms (threshold {thr} ms).",
                        context={"avg_ms": round(avg, 1), "threshold_ms": thr},
                    ),
                )
            else:
                engine.clear(lat_fp)


def evaluate_prometheus(
    db: Session, engine: IncidentEngine, prom: PrometheusClient, result: DetectionResult
) -> None:
    cfg = engine.cfg
    servers = list(db.scalars(select(Server).where(Server.is_active.is_(True))))
    try:
        cpu = prom.by_label(pq.Q_CPU)
        mem = prom.by_label(pq.Q_MEM)
        disk = prom.by_label(pq.Q_DISK)
        up = prom.query(pq.Q_UP)
        seen = prom.by_label(pq.Q_CONTAINER_LAST_SEEN, "name")
        restarts = prom.by_label(pq.Q_CONTAINER_RESTARTS, "name")
    except UpstreamUnavailable:
        result.prometheus_available = False
        log.warning("prometheus unavailable; skipping metric evaluation")
        return

    for srv in servers:
        inst = srv.prometheus_instance
        if not inst:
            continue
        for rule, cat, label, data in (
            ("cpu", IncidentCategory.CPU, "CPU", cpu),
            ("memory", IncidentCategory.MEMORY, "Memory", mem),
            ("disk", IncidentCategory.DISK, "Disk", disk),
        ):
            _metric_signals(
                engine,
                result,
                rule=rule,
                category=cat,
                label=label,
                value=data.get(inst),
                warn=float(cfg[f"{rule}_warning_percent"]),
                crit=float(cfg[f"{rule}_critical_percent"]),
                server=srv,
            )

    by_instance = {s.prometheus_instance: s for s in servers if s.prometheus_instance}
    for sample in up:
        job, inst = sample.labels.get("job", "?"), sample.labels.get("instance", "?")
        subject = f"{job}/{inst}"
        target_srv = by_instance.get(inst)
        fp = make_fingerprint("target_down", target_srv.id if target_srv else None, None, subject)
        if sample.value < 1:
            _emit(
                engine,
                result,
                Signal(
                    rule="target_down",
                    category=IncidentCategory.TARGET_DOWN,
                    severity=Severity.WARNING,
                    server_id=target_srv.id if target_srv else None,
                    subject=subject,
                    title=f"Monitoring target down: {subject}",
                    description=f"Prometheus cannot scrape target '{inst}' (job '{job}').",
                    context={"job": job, "instance": inst},
                ),
            )
        else:
            engine.clear(fp)

    container_seen_available = bool(seen)
    for svc in db.scalars(
        select(Service).where(Service.enabled.is_(True), Service.container_name.is_not(None))
    ):
        name = svc.container_name or ""
        fp_fail = make_fingerprint("container_failure", svc.server_id, svc.id, name)
        fp_rst = make_fingerprint("container_restarts", svc.server_id, svc.id, name)
        if (
            container_seen_available
        ):  # cAdvisor is reporting; absence of this container is meaningful
            age = seen.get(name)
            if age is None or age > CONTAINER_STALE_SECONDS:
                _emit(
                    engine,
                    result,
                    Signal(
                        rule="container_failure",
                        category=IncidentCategory.CONTAINER_FAILURE,
                        severity=Severity.CRITICAL,
                        server_id=svc.server_id,
                        service_id=svc.id,
                        subject=name,
                        title=f"Container {name} is not running",
                        description=f"cAdvisor has not seen container '{name}' for "
                        f"{'over ' + str(CONTAINER_STALE_SECONDS) if age is None else int(age)}s.",
                        context={"container": name},
                    ),
                )
            else:
                engine.clear(fp_fail)
        count = restarts.get(name)
        if count is not None:
            thr = int(cfg.get("container_restart_threshold", 3))
            if count >= thr:
                sev = Severity.CRITICAL if count >= 2 * thr else Severity.WARNING
                _emit(
                    engine,
                    result,
                    Signal(
                        rule="container_restarts",
                        category=IncidentCategory.CONTAINER_RESTARTS,
                        severity=sev,
                        server_id=svc.server_id,
                        service_id=svc.id,
                        subject=name,
                        title=f"Container {name} restarting repeatedly ({int(count)} in 10m)",
                        description=f"Container '{name}' restarted {int(count)} times in the last 10 minutes.",
                        context={"container": name, "restarts_10m": int(count)},
                    ),
                )
            else:
                engine.clear(fp_rst)


def run_detection(
    db: Session, prom: PrometheusClient | None, settings: dict[str, Any]
) -> DetectionResult:
    engine = IncidentEngine(db, settings)
    result = DetectionResult()
    evaluate_services(db, engine, result)
    if prom is not None:
        evaluate_prometheus(db, engine, prom, result)
    else:
        result.prometheus_available = False
    engine.escalate_pending()
    db.flush()
    return result


__all__ = ["DetectionResult", "run_detection", "reset_streaks", "timedelta"]
