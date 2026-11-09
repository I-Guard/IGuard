"""Background loops: service checks, incident detection (+auto recovery), notification delivery.

Each loop runs in its own thread, owns its DB session per tick and never lets an exception kill
the thread. A PostgreSQL advisory lock makes detection single-leader when several backend
replicas run.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import get_engine, session_scope
from app.incidents import detector
from app.integrations import Integrations
from app.notifications import dispatcher
from app.recovery.policies import sync_policies
from app.recovery.service import RecoveryService
from app.services import monitoring_service, settings_service

log = get_logger(__name__)
ADVISORY_LOCK_ID = 727_001


def check_tick(integ: Integrations) -> int:
    with session_scope() as db:
        due = monitoring_service.due_services(db)
        for svc in due:
            monitoring_service.check_service(db, svc, transport=integ.checker_transport)
        return len(due)


def detection_tick(integ: Integrations) -> detector.DetectionResult:
    with session_scope() as db:
        cfg = settings_service.effective(db)
        result = detector.run_detection(db, integ.prometheus, cfg)
        candidates = list(result.recovery_candidates)
    # Auto-recovery runs after the detection transaction is committed.
    for incident_id in candidates:
        with session_scope() as db:
            RecoveryService(
                db,
                integ.recovery_adapter,
                settings_service.effective(db),
                checker_transport=integ.checker_transport,
            ).auto_recover(incident_id)
    return result


def notify_tick(integ: Integrations) -> int:
    with session_scope() as db:
        return dispatcher.deliver_pending(db, integ.telegram)


def retention_tick() -> None:
    with session_scope() as db:
        days = int(settings_service.effective(db)["check_retention_days"])
        monitoring_service.purge_old_checks(db, days)


class Worker(threading.Thread):
    def __init__(
        self,
        name: str,
        interval: Callable[[], float],
        fn: Callable[[], object],
        stop: threading.Event,
        leader_only: bool = False,
    ) -> None:
        super().__init__(name=name, daemon=True)
        self.interval, self.fn, self.stop_event, self.leader_only = interval, fn, stop, leader_only

    def run(self) -> None:
        log.info("worker started", extra={"worker": self.name})
        while not self.stop_event.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("worker tick failed", extra={"worker": self.name})
            self.stop_event.wait(self.interval())
        log.info("worker stopped", extra={"worker": self.name})

    def _tick(self) -> None:
        if not self.leader_only or get_engine().dialect.name != "postgresql":
            self.fn()
            return
        with get_engine().connect() as conn:
            got = conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_ID}
            ).scalar()
            try:
                if got:
                    self.fn()
            finally:
                if got:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_ID})
                conn.commit()


class WorkerManager:
    def __init__(self, integ: Integrations) -> None:
        self.integ = integ
        self.stop = threading.Event()
        self.threads: list[Worker] = []

    def start(self) -> None:
        s = get_settings()
        tick = s.worker_tick_seconds

        def detection_interval() -> float:
            try:
                with session_scope() as db:
                    return float(settings_service.effective(db)["detection_interval_seconds"])
            except Exception:
                return 15.0

        counter = {"n": 0}

        def retention_gate() -> None:
            counter["n"] += 1
            if counter["n"] % 720 == 1:
                retention_tick()

        self.threads = [
            Worker("service-checks", lambda: tick, lambda: check_tick(self.integ), self.stop),
            Worker(
                "detector",
                detection_interval,
                lambda: detection_tick(self.integ),
                self.stop,
                leader_only=True,
            ),
            Worker("notifier", lambda: tick, lambda: notify_tick(self.integ), self.stop),
            Worker("retention", lambda: 3600.0, retention_gate, self.stop, leader_only=True),
        ]
        for t in self.threads:
            t.start()

    def shutdown(self, timeout: float = 10.0) -> None:
        self.stop.set()
        for t in self.threads:
            t.join(timeout)


def startup_sync() -> None:
    """Seed roles, bootstrap admin and sync recovery policies (idempotent)."""
    from app.models.enums import RoleName
    from app.services import auth_service

    s = get_settings()
    with session_scope() as db:
        for r in RoleName:
            auth_service.get_role(db, r)
        auth_service.bootstrap_admin(db)
        dispatcher.get_or_create_config(db)
        sync_policies(db, s.recovery_policies_dir)
