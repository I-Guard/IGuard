"""Needs a real PostgreSQL (IGUARD_TEST_DATABASE_URL). Skipped on SQLite."""

import threading

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database.session import get_engine, session_scope
from app.incidents.engine import IncidentEngine, Signal
from app.models import Incident, Server
from app.models.enums import IncidentCategory, IncidentStatus, Severity

pytestmark = pytest.mark.integration

CFG = {
    "incident_cooldown_seconds": 300,
    "flap_window_seconds": 1800,
    "flap_threshold": 3,
    "clear_evaluations": 3,
    "escalation_after_seconds": 600,
}


@pytest.fixture(autouse=True)
def _require_postgres():
    if get_engine().dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL (set IGUARD_TEST_DATABASE_URL)")


def _signal(server_id):
    return Signal(
        rule="cpu",
        category=IncidentCategory.CPU,
        severity=Severity.CRITICAL,
        title="CPU high",
        description="cpu is high",
        server_id=server_id,
    )


def test_concurrent_workers_produce_exactly_one_active_incident():
    with session_scope() as db:
        srv = Server(name="race", hostname="race-host")
        db.add(srv)
        db.flush()
        server_id = srv.id

    workers, errors = 8, []
    barrier = threading.Barrier(workers)

    def worker():
        try:
            barrier.wait(timeout=10)
            with session_scope() as db:
                IncidentEngine(db, CFG).observe(_signal(server_id))
        except Exception as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    [t.start() for t in threads]
    [t.join(timeout=30) for t in threads]

    assert not errors, errors
    with session_scope() as db:
        rows = db.scalars(select(Incident).where(Incident.status != IncidentStatus.RESOLVED)).all()
        assert len(rows) == 1
        assert rows[0].occurrences == workers


def test_unique_index_rejects_second_active_incident_with_same_fingerprint():
    with session_scope() as db:
        srv = Server(name="uq", hostname="uq-host")
        db.add(srv)
        db.flush()
        IncidentEngine(db, CFG).observe(_signal(srv.id))
        fp = _signal(srv.id).fingerprint
    with pytest.raises(IntegrityError), session_scope() as db:
        db.add(
            Incident(
                fingerprint=fp,
                title="dup",
                description="",
                severity=Severity.WARNING,
                category=IncidentCategory.CPU,
                status=IncidentStatus.DETECTED,
                source="test",
            )
        )
        db.flush()
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Incident)) == 1
