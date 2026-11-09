"""Recovery orchestration.

Workflow (see docs/recovery-engine.md):
 1 incident detected -> 2 classified -> 3 policy evaluated -> 4 permissions checked ->
 5 dry-run (where required) -> 6 execute -> 7 verify health -> 8 incident updated ->
 9 notification queued -> 10 audit record stored.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
)
from app.core.logging import get_logger
from app.database.session import utcnow
from app.incidents.engine import IncidentEngine
from app.models import Incident, RecoveryAction, RecoveryExecution, Service, User
from app.models.enums import (
    ROLE_RANK,
    ActionType,
    EventType,
    ExecutionStatus,
    IncidentStatus,
    NotificationEvent,
    RoleName,
    Trigger,
)
from app.notifications import dispatcher
from app.recovery.adapters import AdapterResult, RecoveryAdapter
from app.services import audit
from app.services.monitoring_service import check_service

log = get_logger(__name__)

DRY_RUN_VALIDITY = timedelta(minutes=15)
STALE_RUNNING = timedelta(minutes=10)
_REAL = (
    ExecutionStatus.RUNNING,
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.VERIFICATION_FAILED,
)


class RecoveryRejected(AppError):
    status_code = 409
    code = "recovery_rejected"


def _highest(user: User) -> RoleName:
    names = [RoleName(r) for r in user.role_names if r in RoleName.__members__]
    return max(names, key=lambda r: ROLE_RANK[r]) if names else RoleName.VIEWER


class RecoveryService:
    def __init__(
        self,
        db: Session,
        adapter: RecoveryAdapter,
        settings: dict[str, Any],
        *,
        checker_transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.db = db
        self.adapter = adapter
        self.cfg = settings
        self.checker_transport = checker_transport
        self.sleep = sleep

    # ------------------------------------------------------------ state helpers
    def _real_executions(self, action: RecoveryAction, since: datetime) -> list[RecoveryExecution]:
        return list(
            self.db.scalars(
                select(RecoveryExecution)
                .where(
                    RecoveryExecution.action_id == action.id,
                    RecoveryExecution.dry_run.is_(False),
                    RecoveryExecution.status.in_(_REAL),
                    RecoveryExecution.created_at >= since,
                )
                .order_by(RecoveryExecution.created_at.desc())
            )
        )

    def runtime_state(self, action: RecoveryAction) -> dict[str, Any]:
        now = utcnow()
        recent = self._real_executions(
            action,
            now
            - timedelta(seconds=max(action.cooldown_seconds, action.breaker_reset_seconds, 3600)),
        )
        cooldown_remaining = 0
        for ex in recent:
            if ex.status in (
                ExecutionStatus.SUCCEEDED,
                ExecutionStatus.FAILED,
                ExecutionStatus.VERIFICATION_FAILED,
            ):
                ref = ex.finished_at or ex.created_at
                cooldown_remaining = int(action.cooldown_seconds - (now - ref).total_seconds()) + 1
                break
        last = self.db.scalar(
            select(RecoveryExecution)
            .where(RecoveryExecution.action_id == action.id, RecoveryExecution.dry_run.is_(False))
            .order_by(RecoveryExecution.created_at.desc())
            .limit(1)
        )
        return {
            "circuit_open": self._circuit_open(action, recent, now),
            "cooldown_remaining_seconds": max(0, cooldown_remaining),
            "last_execution_at": last.created_at if last else None,
            "last_status": last.status if last else None,
        }

    def _circuit_open(
        self, action: RecoveryAction, recent: list[RecoveryExecution], now: datetime
    ) -> bool:
        finished = [e for e in recent if e.status != ExecutionStatus.RUNNING]
        window = finished[: action.breaker_threshold]
        if len(window) < action.breaker_threshold:
            return False
        if not all(
            e.status in (ExecutionStatus.FAILED, ExecutionStatus.VERIFICATION_FAILED)
            for e in window
        ):
            return False
        newest = window[0].finished_at or window[0].created_at
        return now - newest < timedelta(seconds=action.breaker_reset_seconds)

    # ------------------------------------------------------------ guards
    def _reject(
        self,
        action: RecoveryAction,
        actor: User | None,
        incident_id: uuid.UUID | None,
        trigger: Trigger,
        reason: str,
        code: str,
        status: int = 409,
    ) -> None:
        ex = RecoveryExecution(
            action_id=action.id,
            incident_id=incident_id,
            requested_by_id=actor.id if actor else None,
            requested_by_name=actor.username if actor else "system",
            trigger=trigger,
            dry_run=False,
            status=ExecutionStatus.REJECTED,
            error=reason,
            created_at=utcnow(),
            finished_at=utcnow(),
        )
        self.db.add(ex)
        audit.record(
            self.db,
            action="recovery.rejected",
            resource_type="recovery_action",
            resource_id=action.id,
            actor=actor,
            outcome="REJECTED",
            details={
                "reason": reason,
                "code": code,
                "action_key": action.key,
                "trigger": trigger.value,
            },
        )
        self.db.commit()  # keep the rejection record even though we raise
        err_cls = RateLimitedError if status == 429 else RecoveryRejected
        raise err_cls(reason, code=code)

    def _check_permission(
        self, action: RecoveryAction, actor: User | None, confirm: bool, trigger: Trigger
    ) -> None:
        if trigger == Trigger.AUTOMATIC:
            if action.sensitive:
                raise ForbiddenError(
                    "Sensitive actions are never executed automatically",
                    code="sensitive_requires_approval",
                )
            return
        assert actor is not None
        rank = ROLE_RANK[_highest(actor)]
        if rank < ROLE_RANK[action.min_role]:
            raise ForbiddenError(
                f"Action requires role {action.min_role.value} or higher", code="insufficient_role"
            )
        if action.sensitive:
            if rank < ROLE_RANK[RoleName.ADMIN]:
                raise ForbiddenError(
                    "Sensitive actions require ADMIN approval", code="sensitive_requires_admin"
                )
            if not confirm:
                raise RecoveryRejected(
                    "This action is sensitive: resubmit with confirm=true to approve it",
                    code="confirmation_required",
                )

    def _validate_action(self, action: RecoveryAction) -> None:
        if not action.enabled:
            raise RecoveryRejected("Action is disabled", code="action_disabled")

    # ------------------------------------------------------------ dry-run
    def dry_run(
        self,
        action: RecoveryAction,
        actor: User | None,
        incident: Incident | None,
        trigger: Trigger = Trigger.MANUAL,
    ) -> RecoveryExecution:
        self._validate_action(action)
        if actor is not None:
            rank = ROLE_RANK[_highest(actor)]
            if rank < ROLE_RANK[action.min_role]:
                raise ForbiddenError(
                    f"Action requires role {action.min_role.value} or higher",
                    code="insufficient_role",
                )
        started = utcnow()
        result = self._call_adapter(action, dry_run=True)
        ex = RecoveryExecution(
            action_id=action.id,
            incident_id=incident.id if incident else None,
            requested_by_id=actor.id if actor else None,
            requested_by_name=actor.username if actor else "system",
            trigger=trigger,
            dry_run=True,
            status=ExecutionStatus.DRY_RUN_OK if result.ok else ExecutionStatus.FAILED,
            simulated=result.simulated,
            output=result.output,
            error=result.error,
            started_at=started,
            finished_at=utcnow(),
            duration_ms=(utcnow() - started).total_seconds() * 1000,
            created_at=utcnow(),
        )
        self.db.add(ex)
        self.db.flush()
        audit.record(
            self.db,
            action="recovery.dry_run",
            resource_type="recovery_action",
            resource_id=action.id,
            actor=actor,
            outcome="SUCCESS" if result.ok else "FAILURE",
            details={
                "action_key": action.key,
                "execution_id": str(ex.id),
                "incident_id": str(incident.id) if incident else None,
            },
        )
        return ex

    # ------------------------------------------------------------ execute (request phase)
    def request_execution(
        self,
        action: RecoveryAction,
        actor: User | None,
        incident: Incident | None,
        *,
        confirm: bool = False,
        idempotency_key: str | None = None,
        trigger: Trigger = Trigger.MANUAL,
        reason: str | None = None,
    ) -> tuple[RecoveryExecution, bool]:
        """Validate every guard and create a RUNNING execution.

        Returns (execution, created). ``created`` is False when an existing execution was returned
        because of an idempotency-key replay.
        """
        if idempotency_key:
            existing = self.db.scalar(
                select(RecoveryExecution).where(
                    RecoveryExecution.action_id == action.id,
                    RecoveryExecution.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return existing, False

        self._validate_action(action)
        self._check_permission(action, actor, confirm, trigger)
        now = utcnow()
        incident_id = incident.id if incident else None
        if incident is not None and incident.status == IncidentStatus.RESOLVED:
            raise RecoveryRejected("Incident is already resolved", code="incident_resolved")

        if trigger == Trigger.MANUAL and action.requires_dry_run:
            ok = self.db.scalar(
                select(RecoveryExecution.id)
                .where(
                    RecoveryExecution.action_id == action.id,
                    RecoveryExecution.dry_run.is_(True),
                    RecoveryExecution.status == ExecutionStatus.DRY_RUN_OK,
                    RecoveryExecution.created_at >= now - DRY_RUN_VALIDITY,
                )
                .limit(1)
            )
            if ok is None:
                raise RecoveryRejected(
                    "A successful dry-run within the last 15 minutes is required before execution",
                    code="dry_run_required",
                )

        recent = self._real_executions(
            action,
            now
            - timedelta(seconds=max(3600, action.cooldown_seconds, action.breaker_reset_seconds)),
        )
        running = [
            e
            for e in recent
            if e.status == ExecutionStatus.RUNNING and now - e.created_at < STALE_RUNNING
        ]
        if running:
            raise ConflictError("This action is already running", code="already_running")
        if self._circuit_open(action, recent, now):
            self._reject(
                action,
                actor,
                incident_id,
                trigger,
                f"Circuit breaker open after {action.breaker_threshold} consecutive failures; "
                f"retry after {action.breaker_reset_seconds}s",
                "circuit_open",
            )
        for ex in recent:
            if ex.status in (
                ExecutionStatus.SUCCEEDED,
                ExecutionStatus.FAILED,
                ExecutionStatus.VERIFICATION_FAILED,
            ):
                ref = ex.finished_at or ex.created_at
                wait = action.cooldown_seconds - (now - ref).total_seconds()
                if wait > 0:
                    self._reject(
                        action,
                        actor,
                        incident_id,
                        trigger,
                        f"Cooldown active: retry in {int(wait) + 1}s",
                        "cooldown_active",
                        429,
                    )
                break
        hour = [e for e in recent if e.created_at >= now - timedelta(hours=1)]
        if len(hour) >= action.max_attempts_per_hour:
            self._reject(
                action,
                actor,
                incident_id,
                trigger,
                f"Retry limit reached ({action.max_attempts_per_hour} executions/hour)",
                "retry_limit",
                429,
            )

        ex = RecoveryExecution(
            action_id=action.id,
            incident_id=incident_id,
            requested_by_id=actor.id if actor else None,
            requested_by_name=actor.username if actor else "system",
            trigger=trigger,
            dry_run=False,
            status=ExecutionStatus.RUNNING,
            idempotency_key=idempotency_key,
            started_at=now,
            created_at=now,
        )
        try:
            with self.db.begin_nested():
                self.db.add(ex)
                self.db.flush()
        except IntegrityError:
            existing = self.db.scalar(
                select(RecoveryExecution).where(
                    RecoveryExecution.action_id == action.id,
                    RecoveryExecution.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise
            return existing, False

        audit.record(
            self.db,
            action="recovery.execute",
            resource_type="recovery_action",
            resource_id=action.id,
            actor=actor,
            outcome="STARTED",
            details={
                "action_key": action.key,
                "execution_id": str(ex.id),
                "incident_id": str(incident_id) if incident_id else None,
                "trigger": trigger.value,
                "reason": reason,
                "sensitive": action.sensitive,
                "confirmed": confirm,
            },
        )
        if incident is not None:
            engine = IncidentEngine(self.db, self.cfg)
            engine.add_event(
                incident,
                EventType.RECOVERY_STARTED,
                f"Recovery action '{action.name}' started ({trigger.value.lower()})",
                actor,
                data={"execution_id": str(ex.id), "action": action.key},
            )
            if incident.status != IncidentStatus.RESOLVED:
                incident.status = IncidentStatus.RECOVERING
            dispatcher.enqueue(
                self.db,
                NotificationEvent.RECOVERY_STARTED,
                title=f"Recovery started: {action.name}",
                incident=incident,
                description=f"Action '{action.key}' on target '{action.target}'",
            )
        self.db.flush()
        return ex, True

    # ------------------------------------------------------------ execute (run phase)
    def _call_adapter(self, action: RecoveryAction, *, dry_run: bool) -> AdapterResult:
        if action.action_type == ActionType.HEALTH_VERIFY:
            return AdapterResult(True, "Health verification only; no host action", simulated=False)
        try:
            return self.adapter.execute(
                action.action_type,
                action.target,
                dry_run=dry_run,
                timeout=action.timeout_seconds,
                request_id=uuid.uuid4().hex,
            )
        except Exception as exc:  # adapters must never crash the engine
            log.exception("recovery adapter raised")
            return AdapterResult(False, error=f"Adapter error: {type(exc).__name__}")

    def _verification_service(
        self, action: RecoveryAction, incident: Incident | None
    ) -> Service | None:
        if action.service is not None:
            return action.service
        return incident.service if incident is not None else None

    def _verify(self, action: RecoveryAction, service: Service) -> bool:
        """Poll the service health check every 2s for up to ``timeout_seconds`` (attempt-based so
        behaviour is deterministic and independent of wall-clock drift)."""
        if action.verify_after_seconds:
            self.sleep(action.verify_after_seconds)
        attempts = max(2, int(min(action.timeout_seconds, 120) // 2))
        for attempt in range(attempts):
            outcome, _ = check_service(self.db, service, transport=self.checker_transport)
            if outcome.success:
                return True
            if attempt < attempts - 1:
                self.sleep(2)
        return False

    def run_execution(self, execution_id: uuid.UUID) -> RecoveryExecution:
        ex = self.db.get(RecoveryExecution, execution_id)
        if ex is None:
            raise NotFoundError("Execution not found")
        if ex.status != ExecutionStatus.RUNNING:
            return ex
        action = ex.action
        incident = ex.incident
        engine = IncidentEngine(self.db, self.cfg)
        started = ex.started_at or utcnow()

        result = self._call_adapter(action, dry_run=False)
        ex.simulated = result.simulated
        ex.output = result.output
        service = self._verification_service(action, incident)
        verified: bool | None = None
        if result.ok and (service is not None):
            self.db.commit()  # release locks during the (possibly long) verification wait
            verified = self._verify(action, service)
        ex.verification_passed = verified
        if not result.ok:
            ex.status = ExecutionStatus.FAILED
            ex.error = result.error or "Recovery action failed"
        elif verified is False:
            ex.status = ExecutionStatus.VERIFICATION_FAILED
            ex.error = "Action ran but the service did not become healthy"
        else:
            ex.status = ExecutionStatus.SUCCEEDED
        ex.finished_at = utcnow()
        ex.duration_ms = (ex.finished_at - started).total_seconds() * 1000

        succeeded = ex.status == ExecutionStatus.SUCCEEDED
        actor = None
        if ex.requested_by_id:
            actor = self.db.get(User, ex.requested_by_id)
        if incident is not None and incident.status != IncidentStatus.RESOLVED:
            summary = f"{ex.status.value}: {action.name}" + (f" - {ex.error}" if ex.error else "")
            engine.add_event(
                incident,
                EventType.RECOVERY_SUCCEEDED if succeeded else EventType.RECOVERY_FAILED,
                summary,
                actor,
                data={"execution_id": str(ex.id), "verification": verified},
            )
            if succeeded and verified:
                engine.resolve(
                    incident,
                    actor,
                    f"Recovered automatically by '{action.name}'; health check passed."
                    if ex.trigger == Trigger.AUTOMATIC
                    else f"Recovered by '{action.name}'; health check passed.",
                    auto=ex.trigger == Trigger.AUTOMATIC,
                )
            else:
                incident.status = IncidentStatus.INVESTIGATING
        dispatcher.enqueue(
            self.db,
            NotificationEvent.RECOVERY_SUCCEEDED
            if succeeded
            else NotificationEvent.RECOVERY_FAILED,
            title=f"Recovery {'succeeded' if succeeded else 'failed'}: {action.name}",
            incident=incident,
            severity=incident.severity if incident else None,
            description=f"Action '{action.key}' -> {ex.status.value}",
            recovery_result=ex.error or ex.output or ex.status.value,
        )
        audit.record(
            self.db,
            action="recovery.result",
            resource_type="recovery_execution",
            resource_id=ex.id,
            actor=actor,
            outcome="SUCCESS" if succeeded else "FAILURE",
            details={
                "action_key": action.key,
                "status": ex.status.value,
                "verification": verified,
                "duration_ms": ex.duration_ms,
                "simulated": ex.simulated,
            },
        )
        self.db.flush()
        return ex

    # ------------------------------------------------------------ automatic recovery
    def auto_recover(self, incident_id: uuid.UUID) -> RecoveryExecution | None:
        if not self.cfg.get("auto_recovery_enabled", True):
            return None
        incident = self.db.get(Incident, incident_id)
        if incident is None or incident.status == IncidentStatus.RESOLVED or incident.is_flapping:
            return None
        candidates = self.db.scalars(
            select(RecoveryAction).where(
                RecoveryAction.enabled.is_(True),
                RecoveryAction.auto_trigger.is_(True),
                RecoveryAction.sensitive.is_(False),
            )
        )
        for action in candidates:
            if incident.category.value not in (action.trigger_categories or []):
                continue
            if action.service_id is None or action.service_id != incident.service_id:
                continue
            try:
                if action.requires_dry_run:
                    dry = self.dry_run(action, None, incident, Trigger.AUTOMATIC)
                    if dry.status != ExecutionStatus.DRY_RUN_OK:
                        continue
                ex, created = self.request_execution(
                    action,
                    None,
                    incident,
                    trigger=Trigger.AUTOMATIC,
                    reason="automatic recovery policy",
                )
                self.db.commit()
                return self.run_execution(ex.id) if created else ex
            except AppError as exc:
                log.info(
                    "automatic recovery not executed",
                    extra={"action": action.key, "reason": exc.message, "code": exc.code},
                )
                self.db.commit()
        return None


def count_executions(db: Session, since: datetime) -> dict[str, int]:
    rows = db.execute(
        select(RecoveryExecution.status, func.count())
        .where(RecoveryExecution.created_at >= since, RecoveryExecution.dry_run.is_(False))
        .group_by(RecoveryExecution.status)
    ).all()
    return {str(s.value if hasattr(s, "value") else s): int(c) for s, c in rows}
