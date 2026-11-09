from sqlalchemy import select

from app.incidents import detector
from app.models import Incident, Service
from app.models.enums import IncidentCategory, IncidentStatus, ServiceStatus, Severity
from app.services import settings_service

NODE = "node-exporter:9100"


def run(db, env):
    return detector.run_detection(db, env.integrations.prometheus, settings_service.effective(db))


def active(db):
    return list(
        db.scalars(select(Incident).where(Incident.status != IncidentStatus.RESOLVED)).unique()
    )


def seed_metrics(env, cpu=10.0, mem=10.0, disk=10.0):
    env.prom.set_vector("iguard:node_cpu_usage_percent", {NODE: cpu})
    env.prom.set_vector("iguard:node_memory_usage_percent", {NODE: mem})
    env.prom.set_vector("iguard:node_disk_usage_percent", {NODE: disk})


def test_cpu_breach_must_be_sustained(db, env, seeded):
    seed_metrics(env, cpu=97)
    run(db, env)
    assert active(db) == []  # first evaluation: not yet sustained (anti-flap)
    run(db, env)
    inc = active(db)[0]
    assert inc.category == IncidentCategory.CPU and inc.severity == Severity.CRITICAL


def test_warning_vs_critical_thresholds(db, env, seeded):
    seed_metrics(env, mem=85)
    run(db, env)
    run(db, env)
    assert [i.severity for i in active(db)] == [Severity.WARNING]


def test_repeated_breach_does_not_duplicate(db, env, seeded):
    seed_metrics(env, disk=95)
    for _ in range(6):
        run(db, env)
    assert len(active(db)) == 1 and active(db)[0].occurrences >= 5


def test_metric_recovery_auto_resolves_after_clear_evaluations(db, env, seeded):
    seed_metrics(env, cpu=99)
    run(db, env)
    run(db, env)
    seed_metrics(env, cpu=10)
    for _ in range(3):
        run(db, env)
    assert active(db) == []
    assert db.scalar(select(Incident)).status == IncidentStatus.RESOLVED


def test_prometheus_outage_never_resolves_or_creates(db, env, seeded):
    seed_metrics(env, cpu=99)
    run(db, env)
    run(db, env)
    assert len(active(db)) == 1
    env.prom.down = True
    for _ in range(5):
        res = run(db, env)
    assert (
        res.prometheus_available is False and len(active(db)) == 1
    )  # missing data is not "healthy"


def test_missing_metric_is_not_treated_as_zero(db, env, seeded):
    seed_metrics(env, cpu=99)
    run(db, env)
    run(db, env)
    env.prom.responses.clear()  # series vanished
    for _ in range(5):
        run(db, env)
    assert len(active(db)) == 1


def test_target_down_detected_and_cleared(db, env, seeded):
    env.prom.set_vector("up", {NODE: 0.0})
    env.prom.responses["up"][0]["metric"]["job"] = "node-exporter"
    run(db, env)
    inc = active(db)[0]
    assert inc.category == IncidentCategory.TARGET_DOWN
    env.prom.responses["up"][0]["value"][1] = "1"
    for _ in range(3):
        run(db, env)
    assert active(db) == []


def test_service_down_creates_critical_incident_and_dedups(db, env, seeded):
    from app.services.monitoring_service import check_service

    env.http.status["game-api"] = 0
    svc = db.scalar(select(Service).where(Service.name == "game-api"))
    for _ in range(3):
        check_service(db, svc, transport=env.integrations.checker_transport)
    assert svc.status == ServiceStatus.DOWN
    r1 = run(db, env)
    run(db, env)
    run(db, env)
    incs = [i for i in active(db) if i.service_id == svc.id]
    assert len(incs) == 1 and incs[0].category == IncidentCategory.SERVICE_DOWN
    assert incs[0].severity == Severity.CRITICAL and r1.recovery_candidates


def test_http_5xx_categorised(db, env, seeded):
    from app.services.monitoring_service import check_service

    env.http.status["game-web"] = 503
    svc = db.scalar(select(Service).where(Service.name == "game-web"))
    for _ in range(3):
        check_service(db, svc, transport=env.integrations.checker_transport)
    run(db, env)
    assert any(i.category == IncidentCategory.HTTP_5XX for i in active(db))


def test_service_recovery_resolves_incident(db, env, seeded):
    from app.services.monitoring_service import check_service

    svc = db.scalar(select(Service).where(Service.name == "game-api"))
    env.http.status["game-api"] = 0
    for _ in range(3):
        check_service(db, svc, transport=env.integrations.checker_transport)
    run(db, env)
    env.http.status["game-api"] = 200
    for _ in range(4):
        check_service(db, svc, transport=env.integrations.checker_transport)
        run(db, env)
    assert [i for i in active(db) if i.service_id == svc.id] == []


def test_container_missing_and_restart_loop(db, env, seeded):
    env.prom.set_vector("container_last_seen", {"iguard-game-web": 1.0}, label="name")
    env.prom.set_vector("container_start_time_seconds", {"iguard-game-api": 9.0}, label="name")
    run(db, env)
    cats = {i.category for i in active(db)}
    assert IncidentCategory.CONTAINER_RESTARTS in cats
    assert IncidentCategory.CONTAINER_FAILURE in cats  # others are absent from cAdvisor output


def test_high_latency_detected(db, env, seeded):
    from app.database.session import utcnow
    from app.models import ServiceCheck

    svc = db.scalar(select(Service).where(Service.name == "leaderboard-service"))
    svc.status = ServiceStatus.DEGRADED
    for _ in range(3):
        db.add(
            ServiceCheck(
                service_id=svc.id,
                checked_at=utcnow(),
                success=True,
                status_code=200,
                response_time_ms=4000,
            )
        )
    db.flush()
    run(db, env)
    inc = next(i for i in active(db) if i.category == IncidentCategory.HIGH_LATENCY)
    assert inc.severity == Severity.CRITICAL  # 4000ms > 3 x 1000ms
