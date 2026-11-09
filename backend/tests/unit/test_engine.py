from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.errors import ConflictError, ValidationFailed
from app.database.session import utcnow
from app.incidents.engine import IncidentEngine, Signal, make_fingerprint
from app.models import Incident, IncidentEvent, Notification, Server
from app.models.enums import (
    EventType,
    IncidentCategory,
    IncidentStatus,
    RoleName,
    Severity,
)
from app.services import auth_service, settings_service

CFG = {
    "incident_cooldown_seconds": 300,
    "flap_window_seconds": 1800,
    "flap_threshold": 3,
    "clear_evaluations": 3,
    "escalation_after_seconds": 600,
}


def sig(server=None, sev=Severity.CRITICAL, subject="", rule="cpu", **kw):
    return Signal(
        rule=rule,
        category=IncidentCategory.CPU,
        severity=sev,
        title="CPU high",
        description="cpu is high",
        server_id=server.id if server else None,
        subject=subject,
        **kw,
    )


@pytest.fixture
def server(db):
    s = Server(name="srv", hostname="h")
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def user(db):
    return auth_service.create_user(
        db, email="o@x.test", username="op", password="Str0ngPassw0rd!xyz", role=RoleName.OPERATOR
    )


def count(db):
    return db.scalar(select(func.count()).select_from(Incident))


def test_fingerprint_is_stable_and_discriminating(server):
    a = make_fingerprint("cpu", server.id, None, "")
    assert a == make_fingerprint("cpu", server.id, None, "")
    assert a != make_fingerprint("memory", server.id, None, "")
    assert a != make_fingerprint("cpu", None, None, "")
    assert len(a) == 64


def test_create_then_dedup_repeated_observations(db, server):
    eng = IncidentEngine(db, CFG)
    first = eng.observe(sig(server))
    assert first.action == "created"
    for _ in range(5):
        again = eng.observe(sig(server))
        assert again.action == "updated" and again.incident.id == first.incident.id
    assert count(db) == 1
    inc = db.get(Incident, first.incident.id)
    assert inc.occurrences == 6
    events = db.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id)).all()
    assert [e.event_type for e in events].count(
        EventType.DETECTED
    ) == 1  # no duplicate timeline spam


def test_different_fingerprints_create_separate_incidents(db, server):
    eng = IncidentEngine(db, CFG)
    eng.observe(sig(server, rule="cpu"))
    eng.observe(sig(server, rule="memory"))
    assert count(db) == 2


def test_severity_escalates_but_never_downgrades_while_active(db, server):
    eng = IncidentEngine(db, CFG)
    inc = eng.observe(sig(server, sev=Severity.WARNING)).incident
    obs = eng.observe(sig(server, sev=Severity.CRITICAL))
    assert obs.severity_raised and obs.incident.severity == Severity.CRITICAL
    eng.observe(sig(server, sev=Severity.WARNING))
    assert db.get(Incident, inc.id).severity == Severity.CRITICAL


def test_db_unique_index_blocks_duplicate_active_fingerprint(db, server):
    from sqlalchemy.exc import IntegrityError

    eng = IncidentEngine(db, CFG)
    inc = eng.observe(sig(server)).incident
    dup = Incident(
        fingerprint=inc.fingerprint,
        title="dup",
        severity=Severity.INFO,
        category=IncidentCategory.CPU,
        status=IncidentStatus.DETECTED,
        source="x",
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(dup)
        db.flush()


def test_clear_requires_consecutive_healthy_evaluations(db, server):
    eng = IncidentEngine(db, CFG)
    inc = eng.observe(sig(server)).incident
    fp = inc.fingerprint
    eng.clear(fp)
    eng.clear(fp)
    assert db.get(Incident, inc.id).status == IncidentStatus.DETECTED
    eng.observe(sig(server))  # failure again resets the streak
    eng.clear(fp)
    eng.clear(fp)
    assert db.get(Incident, inc.id).status == IncidentStatus.DETECTED
    eng.clear(fp)
    done = db.get(Incident, inc.id)
    assert done.status == IncidentStatus.RESOLVED and done.resolved_at is not None
    assert "cleared" in done.resolution_summary.lower()


def test_reopen_within_cooldown_instead_of_duplicate(db, server):
    eng = IncidentEngine(db, CFG)
    inc = eng.observe(sig(server)).incident
    eng.resolve(inc, None, "fixed")
    obs = eng.observe(sig(server))
    assert obs.action == "reopened" and obs.incident.id == inc.id and count(db) == 1
    assert obs.incident.status == IncidentStatus.DETECTED and obs.incident.flap_count == 1


def test_new_incident_after_cooldown_expired(db, server):
    eng = IncidentEngine(db, CFG)
    inc = eng.observe(sig(server)).incident
    eng.resolve(inc, None, "fixed")
    inc.resolved_at = utcnow() - timedelta(hours=2)
    db.flush()
    assert IncidentEngine(db, CFG).observe(sig(server)).action == "created"
    assert count(db) == 2


def test_flapping_detected_and_notifications_suppressed(db, server):
    from app.notifications import dispatcher

    dispatcher.get_or_create_config(db).cooldown_seconds = 0  # so only flapping can suppress
    eng = IncidentEngine(db, CFG)
    inc = eng.observe(sig(server)).incident
    for _ in range(3):
        eng.resolve(inc, None, "ok")
        inc = eng.observe(sig(server)).incident
    assert inc.is_flapping
    assert any(e.event_type == EventType.FLAPPING for e in db.scalars(select(IncidentEvent)))

    def alerts():
        return db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.event_type == "INCIDENT_CRITICAL")
        )

    before = alerts()
    eng.resolve(inc, None, "ok")
    eng.observe(sig(server))  # another reopen while flapping
    assert alerts() == before  # no new alert for a flapping incident
    resolved = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.event_type == "INCIDENT_RESOLVED")
    )
    assert resolved >= 4  # resolutions are still delivered


def test_correlation_groups_incidents_on_same_server(db, server):
    eng = IncidentEngine(db, CFG)
    a = eng.observe(sig(server, rule="cpu")).incident
    b = eng.observe(sig(server, rule="memory")).incident
    db.refresh(a)
    assert a.correlation_group and a.correlation_group == b.correlation_group
    assert any(e.event_type == EventType.CORRELATED for e in db.scalars(select(IncidentEvent)))


def test_lifecycle_acknowledge_assign_resolve(db, server, user):
    eng = IncidentEngine(db, CFG)
    inc = eng.observe(sig(server)).incident
    eng.acknowledge(inc, user, "looking")
    assert inc.status == IncidentStatus.ACKNOWLEDGED and inc.acknowledged_by_id == user.id
    with pytest.raises(ConflictError):
        eng.acknowledge(inc, user)
    eng.assign(inc, user, user)
    assert inc.status == IncidentStatus.INVESTIGATING and inc.assigned_to_id == user.id
    eng.set_status(inc, IncidentStatus.RECOVERING, user)
    with pytest.raises(ValidationFailed):
        eng.set_status(inc, IncidentStatus.RESOLVED, user)
    eng.resolve(inc, user, "restarted", root_cause="memory leak")
    assert inc.status == IncidentStatus.RESOLVED and inc.root_cause == "memory leak"
    with pytest.raises(ConflictError):
        eng.resolve(inc, user, "again")
    types = [
        e.event_type for e in db.scalars(select(IncidentEvent).order_by(IncidentEvent.created_at))
    ]
    assert types[0] == EventType.DETECTED and types[-1] == EventType.RESOLVED


def test_cannot_assign_viewer(db, server):
    viewer = auth_service.create_user(
        db, email="v@x.test", username="vw", password="Str0ngPassw0rd!xyz", role=RoleName.VIEWER
    )
    eng = IncidentEngine(db, CFG)
    inc = eng.observe(sig(server)).incident
    with pytest.raises(ValidationFailed):
        eng.assign(inc, viewer, viewer)


def test_escalation_policy(db, server):
    eng = IncidentEngine(db, CFG)
    inc = eng.observe(sig(server)).incident
    assert IncidentEngine(db, CFG).escalate_pending() == []
    later = IncidentEngine(db, CFG, now=utcnow() + timedelta(seconds=601))
    assert [i.id for i in later.escalate_pending()] == [inc.id] and inc.escalation_level == 1
    assert later.escalate_pending() == []  # next level needs another interval
    again = IncidentEngine(db, CFG, now=utcnow() + timedelta(seconds=1300))
    again.escalate_pending()
    assert inc.escalation_level == 2


def test_acknowledged_incidents_do_not_escalate(db, server, user):
    eng = IncidentEngine(db, CFG)
    inc = eng.observe(sig(server)).incident
    eng.acknowledge(inc, user)
    later = IncidentEngine(db, CFG, now=utcnow() + timedelta(hours=1))
    assert later.escalate_pending() == []


def test_notification_queued_for_critical_with_incident_details(db, server):
    eng = IncidentEngine(db, settings_service.effective(db))
    inc = eng.observe(sig(server)).incident
    n = db.scalar(select(Notification).where(Notification.incident_id == inc.id))
    assert n is not None and str(inc.id) in n.body and "CRITICAL" in n.body and "srv" in n.body
