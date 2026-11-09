"""Incident engine: fingerprinting, deduplication, lifecycle, flapping, correlation, escalation.

Design notes
------------
* A *fingerprint* identifies "the same failure": sha256(rule | server | service | subject).
* At most one non-resolved incident exists per fingerprint (enforced by a partial unique index).
  Repeated observations only bump counters (``occurrences``/``last_seen_at``).
* A failure that returns shortly after resolution (within ``incident_cooldown_seconds``) *reopens*
  the previous incident and counts towards flapping instead of creating a duplicate record.
* Metric-based incidents auto-resolve after ``clear_evaluations`` consecutive healthy evaluations.
  Evaluations with *missing data* never count as healthy.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationFailed
from app.core.logging import get_logger
from app.database.session import utcnow
from app.models import Incident, IncidentEvent, User
from app.models.enums import (
    SEVERITY_RANK,
    EventType,
    IncidentCategory,
    IncidentStatus,
    NotificationEvent,
    Severity,
)
from app.notifications import dispatcher

log = get_logger(__name__)

CORRELATION_WINDOW = timedelta(minutes=10)
MAX_ESCALATION_LEVEL = 3


@dataclass
class Signal:
    rule: str
    category: IncidentCategory
    severity: Severity
    title: str
    description: str
    source: str = "detector"
    server_id: uuid.UUID | None = None
    service_id: uuid.UUID | None = None
    subject: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    root_cause: str | None = None

    @property
    def fingerprint(self) -> str:
        return make_fingerprint(self.rule, self.server_id, self.service_id, self.subject)


def make_fingerprint(rule: str, server_id: Any, service_id: Any, subject: str = "") -> str:
    raw = f"{rule}|{server_id or ''}|{service_id or ''}|{subject}"
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class Observation:
    incident: Incident
    action: str  # created | updated | reopened
    severity_raised: bool = False


def actor_label(actor: User | None) -> str:
    return actor.username if actor else "system"


class IncidentEngine:
    def __init__(self, db: Session, settings: dict[str, Any], now: datetime | None = None) -> None:
        self.db = db
        self.cfg = settings
        self.now = now or utcnow()

    # ------------------------------------------------------------------ events
    def add_event(
        self,
        incident: Incident,
        event_type: EventType,
        message: str,
        actor: User | None = None,
        data: dict[str, Any] | None = None,
    ) -> IncidentEvent:
        ev = IncidentEvent(
            incident_id=incident.id,
            event_type=event_type,
            message=message,
            actor_id=actor.id if actor else None,
            actor_name=actor_label(actor),
            data=data or {},
            created_at=utcnow(),
        )
        self.db.add(ev)
        incident.updated_at = utcnow()
        self.db.flush()
        return ev

    # ------------------------------------------------------------------ lookup
    def active_by_fingerprint(self, fingerprint: str) -> Incident | None:
        return self.db.scalar(
            select(Incident).where(
                Incident.fingerprint == fingerprint, Incident.status != IncidentStatus.RESOLVED
            )
        )

    def _recently_resolved(self, fingerprint: str) -> Incident | None:
        cooldown = int(self.cfg.get("incident_cooldown_seconds", 300))
        if cooldown <= 0:
            return None
        return self.db.scalar(
            select(Incident)
            .where(
                Incident.fingerprint == fingerprint,
                Incident.status == IncidentStatus.RESOLVED,
                Incident.resolved_at >= self.now - timedelta(seconds=cooldown),
            )
            .order_by(Incident.resolved_at.desc())
            .limit(1)
        )

    # ------------------------------------------------------------------ observe
    def observe(self, sig: Signal) -> Observation:
        fp = sig.fingerprint
        existing = self.active_by_fingerprint(fp)
        if existing is not None:
            return self._update_existing(existing, sig)

        recent = self._recently_resolved(fp)
        if recent is not None:
            return self._reopen(recent, sig)

        try:
            with self.db.begin_nested():
                incident = self._create(sig)
        except IntegrityError:
            # Lost a race with another worker: the unique index guarantees dedup.
            existing = self.active_by_fingerprint(fp)
            if existing is None:
                raise
            return self._update_existing(existing, sig)
        return Observation(incident, "created")

    def _create(self, sig: Signal) -> Incident:
        now = self.now
        incident = Incident(
            fingerprint=sig.fingerprint,
            title=sig.title[:255],
            description=sig.description,
            severity=sig.severity,
            category=sig.category,
            status=IncidentStatus.DETECTED,
            source=sig.source,
            server_id=sig.server_id,
            service_id=sig.service_id,
            root_cause=sig.root_cause,
            context=sig.context,
            occurrences=1,
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        self.db.add(incident)
        self.db.flush()
        self.db.refresh(incident)
        self.add_event(
            incident,
            EventType.DETECTED,
            f"Incident detected: {sig.title}",
            data={"source": sig.source, **sig.context},
        )
        self._correlate(incident)
        self._notify_new(incident)
        log.info(
            "incident created",
            extra={
                "incident_id": str(incident.id),
                "severity": sig.severity.value,
                "category": sig.category.value,
            },
        )
        return incident

    def _bump_occurrences(self, inc: Incident) -> None:
        # Atomic SQL increment: concurrent workers must not lose updates (read-modify-write would).
        inc.occurrences = Incident.occurrences + 1
        self.db.flush()
        self.db.refresh(inc, ["occurrences"])

    def _update_existing(self, inc: Incident, sig: Signal) -> Observation:
        self._bump_occurrences(inc)
        inc.last_seen_at = self.now
        inc.clear_streak = 0
        inc.context = {**(inc.context or {}), **sig.context}
        inc.description = sig.description
        raised = False
        if SEVERITY_RANK[sig.severity] > SEVERITY_RANK[inc.severity]:
            old = inc.severity
            inc.severity = sig.severity
            raised = True
            self.add_event(
                inc,
                EventType.SEVERITY_CHANGED,
                f"Severity raised {old.value} -> {sig.severity.value}",
                data={"from": old.value, "to": sig.severity.value},
            )
            self._notify_new(inc)
        elif SEVERITY_RANK[sig.severity] < SEVERITY_RANK[inc.severity] and inc.occurrences % 5 == 0:
            pass  # severity never auto-downgrades while active; avoids noisy oscillation
        self.db.flush()
        return Observation(inc, "updated", raised)

    def _reopen(self, inc: Incident, sig: Signal) -> Observation:
        window = timedelta(seconds=int(self.cfg.get("flap_window_seconds", 1800)))
        threshold = int(self.cfg.get("flap_threshold", 3))
        reopens = [datetime.fromisoformat(t) for t in (inc.context or {}).get("reopen_times", [])]
        reopens = [t for t in reopens if self.now - t <= window] + [self.now]
        inc.context = {
            **(inc.context or {}),
            **sig.context,
            "reopen_times": [t.isoformat() for t in reopens],
        }
        inc.flap_count += 1
        inc.status = IncidentStatus.DETECTED
        inc.resolved_at = None
        inc.resolution_summary = None
        inc.acknowledged_at = None
        inc.acknowledged_by_id = None
        self._bump_occurrences(inc)
        inc.clear_streak = 0
        inc.last_seen_at = self.now
        inc.description = sig.description
        inc.severity = max(inc.severity, sig.severity, key=lambda s: SEVERITY_RANK[s])
        self.db.flush()
        self.add_event(
            inc,
            EventType.REOPENED,
            "Failure re-occurred shortly after resolution; incident reopened",
            data={"flap_count": inc.flap_count},
        )
        if len(reopens) >= threshold and not inc.is_flapping:
            inc.is_flapping = True
            self.add_event(
                inc,
                EventType.FLAPPING,
                f"Flapping detected ({len(reopens)} reopens in "
                f"{int(window.total_seconds())}s); notifications suppressed",
            )
        elif len(reopens) < threshold:
            inc.is_flapping = False
        self.db.flush()
        self._notify_new(inc)
        return Observation(inc, "reopened")

    # ------------------------------------------------------------------ correlation
    def _correlate(self, inc: Incident) -> None:
        """Group incidents that hit the same server within a short window."""
        if inc.server_id is None:
            return
        peers = list(
            self.db.scalars(
                select(Incident)
                .where(
                    Incident.server_id == inc.server_id,
                    Incident.id != inc.id,
                    Incident.status != IncidentStatus.RESOLVED,
                    Incident.created_at >= self.now - CORRELATION_WINDOW,
                )
                .order_by(Incident.created_at)
            )
        )
        if not peers:
            return
        group = next((p.correlation_group for p in peers if p.correlation_group), None) or str(
            peers[0].id
        )
        inc.correlation_group = group
        for p in peers:
            if p.correlation_group is None:
                p.correlation_group = group
        self.add_event(
            inc,
            EventType.CORRELATED,
            f"Correlated with {len(peers)} active incident(s) on the same server",
            data={"group": group, "related": [str(p.id) for p in peers]},
        )

    # ------------------------------------------------------------------ clear
    def clear(self, fingerprint: str) -> Incident | None:
        """Report a healthy evaluation. Resolves after ``clear_evaluations`` consecutive ones."""
        inc = self.active_by_fingerprint(fingerprint)
        if inc is None:
            return None
        inc.clear_streak += 1
        if inc.clear_streak >= int(self.cfg.get("clear_evaluations", 3)):
            self.resolve(
                inc, None, "Condition cleared: monitoring observed healthy state.", auto=True
            )
        self.db.flush()
        return inc

    # ------------------------------------------------------------------ lifecycle
    def _require_active(self, inc: Incident, what: str) -> None:
        if inc.status == IncidentStatus.RESOLVED:
            raise ConflictError(
                f"Cannot {what}: incident is already resolved", code="incident_resolved"
            )

    def acknowledge(self, inc: Incident, actor: User, note: str | None = None) -> Incident:
        self._require_active(inc, "acknowledge")
        if inc.acknowledged_at is not None:
            raise ConflictError("Incident is already acknowledged", code="already_acknowledged")
        inc.acknowledged_at = utcnow()
        inc.acknowledged_by_id = actor.id
        inc.acknowledged_by = actor
        if inc.status == IncidentStatus.DETECTED:
            inc.status = IncidentStatus.ACKNOWLEDGED
        self.add_event(
            inc, EventType.ACKNOWLEDGED, note or f"Acknowledged by {actor.username}", actor
        )
        return inc

    def assign(
        self, inc: Incident, assignee: User, actor: User, note: str | None = None
    ) -> Incident:
        self._require_active(inc, "assign")
        if not any(r in ("OPERATOR", "ADMIN") for r in assignee.role_names):
            raise ValidationFailed("Incidents can only be assigned to OPERATOR or ADMIN users")
        if not assignee.is_active:
            raise ValidationFailed("Assignee account is disabled")
        inc.assigned_to_id = assignee.id
        inc.assigned_to = assignee
        if inc.acknowledged_at is None:
            inc.acknowledged_at = utcnow()
            inc.acknowledged_by_id = actor.id
            inc.acknowledged_by = actor
        if inc.status in (IncidentStatus.DETECTED, IncidentStatus.ACKNOWLEDGED):
            inc.status = IncidentStatus.INVESTIGATING
        self.add_event(
            inc,
            EventType.ASSIGNED,
            note or f"Assigned to {assignee.username} by {actor.username}",
            actor,
            data={"assignee": assignee.username},
        )
        return inc

    def set_status(
        self,
        inc: Incident,
        status: IncidentStatus,
        actor: User | None,
        note: str | None = None,
        root_cause: str | None = None,
    ) -> Incident:
        self._require_active(inc, "change status of")
        if status not in (IncidentStatus.INVESTIGATING, IncidentStatus.RECOVERING):
            raise ValidationFailed(
                "Status can only be set to INVESTIGATING or RECOVERING; use "
                "acknowledge/resolve for the other transitions"
            )
        old = inc.status
        inc.status = status
        if root_cause:
            inc.root_cause = root_cause
        self.add_event(
            inc,
            EventType.STATUS_CHANGED,
            note or f"Status {old.value} -> {status.value}",
            actor,
            data={"from": old.value, "to": status.value},
        )
        return inc

    def resolve(
        self,
        inc: Incident,
        actor: User | None,
        summary: str,
        root_cause: str | None = None,
        auto: bool = False,
    ) -> Incident:
        self._require_active(inc, "resolve")
        inc.status = IncidentStatus.RESOLVED
        inc.resolved_at = utcnow()
        inc.resolution_summary = summary
        inc.clear_streak = 0
        if root_cause:
            inc.root_cause = root_cause
        self.add_event(inc, EventType.RESOLVED, summary, actor, data={"auto": auto})
        dispatcher.enqueue(
            self.db,
            NotificationEvent.INCIDENT_RESOLVED,
            title=f"Resolved: {inc.title}",
            incident=inc,
            description=summary,
        )
        log.info("incident resolved", extra={"incident_id": str(inc.id), "auto": auto})
        return inc

    # ------------------------------------------------------------------ escalation
    def escalate_pending(self) -> list[Incident]:
        """Escalate unacknowledged CRITICAL incidents. Each level waits one more interval."""
        base = int(self.cfg.get("escalation_after_seconds", 600))
        escalated: list[Incident] = []
        candidates = self.db.scalars(
            select(Incident).where(
                Incident.severity == Severity.CRITICAL,
                Incident.status == IncidentStatus.DETECTED,
                Incident.acknowledged_at.is_(None),
                Incident.escalation_level < MAX_ESCALATION_LEVEL,
            )
        )
        for inc in candidates:
            if inc.is_flapping:
                continue
            reference = inc.escalated_at or inc.created_at
            if self.now - reference >= timedelta(seconds=base):
                inc.escalation_level += 1
                inc.escalated_at = self.now
                self.add_event(
                    inc,
                    EventType.ESCALATED,
                    f"Escalated to level {inc.escalation_level}: unacknowledged for "
                    f"{int((self.now - inc.created_at).total_seconds())}s",
                    data={"level": inc.escalation_level},
                )
                dispatcher.enqueue(
                    self.db,
                    NotificationEvent.INCIDENT_ESCALATED,
                    title=f"ESCALATION L{inc.escalation_level}: {inc.title}",
                    incident=inc,
                )
                escalated.append(inc)
        self.db.flush()
        return escalated

    # ------------------------------------------------------------------ notifications
    def _notify_new(self, inc: Incident) -> None:
        if inc.severity == Severity.CRITICAL:
            ev = NotificationEvent.INCIDENT_CRITICAL
        elif inc.severity == Severity.WARNING:
            ev = NotificationEvent.INCIDENT_WARNING
        else:
            return
        dispatcher.enqueue(self.db, ev, title=inc.title, incident=inc)


def get_incident_or_404(db: Session, incident_id: uuid.UUID) -> Incident:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise NotFoundError("Incident not found")
    return inc
