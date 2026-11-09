from datetime import timedelta

import pytest
import yaml
from sqlalchemy import select

from app.core.errors import AppError, ForbiddenError
from app.database.session import utcnow
from app.incidents.engine import IncidentEngine, Signal
from app.models import RecoveryAction, RecoveryExecution, Service
from app.models.enums import (
    ExecutionStatus,
    IncidentCategory,
    IncidentStatus,
    RoleName,
    Severity,
    Trigger,
)
from app.recovery.policies import PolicyError, load_policy_files, sync_policies
from app.recovery.service import RecoveryRejected, RecoveryService
from app.services import auth_service, settings_service


@pytest.fixture
def users(db):
    mk = lambda n, r: auth_service.create_user(
        db, email=f"{n}@x.test", username=n, password="Str0ngPassw0rd!xyz", role=r
    )  # noqa: E731
    return {
        "admin": mk("adm", RoleName.ADMIN),
        "op": mk("op", RoleName.OPERATOR),
        "viewer": mk("vw", RoleName.VIEWER),
    }


@pytest.fixture
def svc(db, env, seeded):
    return RecoveryService(
        db,
        env.integrations.recovery_adapter,
        settings_service.effective(db),
        checker_transport=env.integrations.checker_transport,
        sleep=lambda s: None,
    )


def action(db, key):
    return db.scalar(select(RecoveryAction).where(RecoveryAction.key == key))


def incident_for(db, env, name="game-api"):
    service = db.scalar(select(Service).where(Service.name == name))
    sig = Signal(
        rule="availability",
        category=IncidentCategory.SERVICE_DOWN,
        severity=Severity.CRITICAL,
        title=f"{name} down",
        description="down",
        server_id=service.server_id,
        service_id=service.id,
    )
    return IncidentEngine(db, settings_service.effective(db)).observe(sig).incident


# ------------------------------------------------------------- policy loading / allowlist
def write_policy(tmp_path, **over):
    a = {
        "key": "restart-x",
        "name": "Restart X",
        "action_type": "CONTAINER_RESTART",
        "target": "app-x",
    }
    a.update(over)
    (tmp_path / "p.yaml").write_text(yaml.safe_dump({"actions": [a]}))
    return tmp_path


@pytest.mark.parametrize(
    "target",
    [
        "iguard-postgres",
        "prometheus",
        "grafana",
        "docker-socket-proxy",
        "iguard-backend",
        "my-database",
        "loki",
    ],
)
def test_critical_targets_are_rejected(tmp_path, target):
    with pytest.raises(PolicyError):
        load_policy_files(write_policy(tmp_path, target=target))


def test_critical_target_requires_sensitive_and_never_auto(tmp_path):
    with pytest.raises(PolicyError):
        load_policy_files(write_policy(tmp_path, target="legacy-db", allow_critical=True))
    with pytest.raises(PolicyError):
        load_policy_files(
            write_policy(
                tmp_path,
                target="legacy-db",
                allow_critical=True,
                sensitive=True,
                auto_trigger=True,
                trigger_categories=["SERVICE_DOWN"],
            )
        )
    ok = load_policy_files(
        write_policy(tmp_path, target="legacy-db", allow_critical=True, sensitive=True)
    )
    assert ok[0].sensitive


@pytest.mark.parametrize(
    "target", ["../etc/passwd", "a; rm -rf /", "a b", "$(id)", "/bin/sh", "a|b", ""]
)
def test_shell_and_path_syntax_in_targets_rejected(tmp_path, target):
    with pytest.raises(PolicyError):
        load_policy_files(write_policy(tmp_path, target=target))


def test_sensitive_cannot_auto_trigger(tmp_path):
    with pytest.raises(PolicyError):
        load_policy_files(
            write_policy(tmp_path, sensitive=True, auto_trigger=True, trigger_categories=["CPU"])
        )


def test_duplicate_keys_rejected(tmp_path):
    a = {
        "key": "restart-x",
        "name": "Restart X",
        "action_type": "CONTAINER_RESTART",
        "target": "app-x",
    }
    (tmp_path / "p.yaml").write_text(yaml.safe_dump({"actions": [a, a]}))
    with pytest.raises(PolicyError):
        load_policy_files(tmp_path)


def test_removed_policy_is_disabled_not_deleted(db, tmp_path):
    sync_policies(db, write_policy(tmp_path))
    (tmp_path / "p.yaml").write_text(yaml.safe_dump({"actions": []}))
    stats = sync_policies(db, tmp_path)
    assert stats["disabled"] == 1 and action(db, "restart-x").enabled is False


def test_shipped_policies_are_valid_and_safe(db, seeded):
    rows = db.scalars(select(RecoveryAction)).unique().all()
    assert len(rows) >= 6
    for a in rows:
        if a.sensitive:
            assert not a.auto_trigger and a.min_role == RoleName.ADMIN
    assert action(db, "restart-wallet-mock").sensitive


# ------------------------------------------------------------- dry run
def test_dry_run_makes_no_changes_and_is_audited(db, env, svc, seeded, users):
    ex = svc.dry_run(action(db, "restart-game-api"), users["op"], None)
    assert ex.status == ExecutionStatus.DRY_RUN_OK and ex.dry_run and "DRY-RUN" in ex.output
    assert env.http.healed == []  # the heal hook (only used for real runs) was not hit
    from app.models import AuditLog

    assert db.scalar(select(AuditLog).where(AuditLog.action == "recovery.dry_run")) is not None


def test_dry_run_denied_for_viewer(db, svc, seeded, users):
    with pytest.raises(ForbiddenError):
        svc.dry_run(action(db, "restart-game-api"), users["viewer"], None)


# ------------------------------------------------------------- guards on execution
def test_execute_requires_prior_dry_run(db, svc, seeded, users):
    with pytest.raises(RecoveryRejected) as e:
        svc.request_execution(action(db, "restart-game-api"), users["op"], None)
    assert e.value.code == "dry_run_required"


def test_stale_dry_run_not_accepted(db, svc, seeded, users):
    a = action(db, "restart-game-api")
    ex = svc.dry_run(a, users["op"], None)
    ex.created_at = utcnow() - timedelta(minutes=30)
    db.flush()
    with pytest.raises(RecoveryRejected):
        svc.request_execution(a, users["op"], None)


def test_manual_execute_success_verifies_health_and_resolves_incident(db, env, svc, seeded, users):
    inc = incident_for(db, env)
    env.http.status["game-api"] = 0  # service is down; the "restart" heals it via the demo hook
    a = action(db, "restart-game-api")
    svc.dry_run(a, users["op"], inc)
    ex, created = svc.request_execution(a, users["op"], inc)
    assert created and ex.status == ExecutionStatus.RUNNING
    assert inc.status == IncidentStatus.RECOVERING
    done = svc.run_execution(ex.id)
    assert done.status == ExecutionStatus.SUCCEEDED and done.verification_passed is True
    assert done.simulated is True and env.http.healed == ["game-api"]
    db.refresh(inc)
    assert inc.status == IncidentStatus.RESOLVED and "health check passed" in inc.resolution_summary
    from app.models import AuditLog, Notification

    actions = {a.action for a in db.scalars(select(AuditLog))}
    assert {"recovery.dry_run", "recovery.execute", "recovery.result"} <= actions
    kinds = {n.event_type for n in db.scalars(select(Notification))}
    assert {"RECOVERY_STARTED", "RECOVERY_SUCCEEDED", "INCIDENT_RESOLVED"} <= kinds


def test_verification_failure_keeps_incident_open(db, env, svc, seeded, users):
    inc = incident_for(db, env)
    env.http.status["game-api"] = 0
    env.http.heals_fix = False  # restart "works" but the service stays down
    a = action(db, "restart-game-api")
    svc.dry_run(a, users["op"], inc)
    ex, _ = svc.request_execution(a, users["op"], inc)
    done = svc.run_execution(ex.id)
    assert done.status == ExecutionStatus.VERIFICATION_FAILED and done.verification_passed is False
    db.refresh(inc)
    assert inc.status == IncidentStatus.INVESTIGATING


def test_adapter_failure_is_recorded_safely(db, env, svc, seeded, users):
    class Boom:
        name = "boom"

        def execute(self, *a, **k):
            raise RuntimeError("secret internals")

    svc.adapter = Boom()
    a = action(db, "restart-game-api")
    svc.dry_run(a, users["op"], None)  # dry-run also fails safely
    db.execute(RecoveryExecution.__table__.update().values(status=ExecutionStatus.DRY_RUN_OK))
    ex, _ = svc.request_execution(a, users["op"], None)
    done = svc.run_execution(ex.id)
    assert done.status == ExecutionStatus.FAILED and "RuntimeError" in done.error
    assert "secret internals" not in (done.error or "")


def test_idempotency_key_replays_same_execution(db, svc, seeded, users):
    a = action(db, "clear-demo-cache")
    svc.dry_run(a, users["op"], None)
    ex1, c1 = svc.request_execution(a, users["op"], None, idempotency_key="key-1")
    ex2, c2 = svc.request_execution(a, users["op"], None, idempotency_key="key-1")
    assert c1 and not c2 and ex1.id == ex2.id
    assert (
        len(db.scalars(select(RecoveryExecution).where(RecoveryExecution.dry_run.is_(False))).all())
        == 1
    )


def test_concurrent_run_is_blocked(db, svc, seeded, users):
    a = action(db, "clear-demo-cache")
    svc.dry_run(a, users["op"], None)
    svc.request_execution(a, users["op"], None)
    with pytest.raises(AppError) as e:
        svc.request_execution(a, users["op"], None)
    assert e.value.code == "already_running"


def finish(db, ex, status):
    ex.status = status
    ex.finished_at = utcnow()
    db.flush()


def test_cooldown_enforced(db, svc, seeded, users):
    a = action(db, "clear-demo-cache")
    svc.dry_run(a, users["op"], None)
    ex, _ = svc.request_execution(a, users["op"], None)
    finish(db, ex, ExecutionStatus.SUCCEEDED)
    with pytest.raises(AppError) as e:
        svc.request_execution(a, users["op"], None)
    assert e.value.code == "cooldown_active" and e.value.status_code == 429
    rejected = db.scalar(
        select(RecoveryExecution).where(RecoveryExecution.status == ExecutionStatus.REJECTED)
    )
    assert rejected is not None  # rejections are recorded too


def test_retry_limit_per_hour(db, svc, seeded, users):
    a = action(db, "clear-demo-cache")
    a.cooldown_seconds = 0
    a.max_attempts_per_hour = 2
    svc.dry_run(a, users["op"], None)
    for _ in range(2):
        ex, _ = svc.request_execution(a, users["op"], None)
        finish(db, ex, ExecutionStatus.SUCCEEDED)
    with pytest.raises(AppError) as e:
        svc.request_execution(a, users["op"], None)
    assert e.value.code == "retry_limit"


def test_circuit_breaker_opens_after_consecutive_failures(db, svc, seeded, users):
    a = action(db, "clear-demo-cache")
    a.cooldown_seconds = 0
    a.max_attempts_per_hour = 50
    a.breaker_threshold = 3
    svc.dry_run(a, users["op"], None)
    for _ in range(3):
        ex, _ = svc.request_execution(a, users["op"], None)
        finish(db, ex, ExecutionStatus.FAILED)
    assert svc.runtime_state(a)["circuit_open"] is True
    with pytest.raises(AppError) as e:
        svc.request_execution(a, users["op"], None)
    assert e.value.code == "circuit_open"


def test_circuit_breaker_resets_after_window(db, svc, seeded, users):
    a = action(db, "clear-demo-cache")
    a.cooldown_seconds = 0
    a.breaker_threshold = 2
    a.breaker_reset_seconds = 60
    svc.dry_run(a, users["op"], None)
    for _ in range(2):
        ex, _ = svc.request_execution(a, users["op"], None)
        finish(db, ex, ExecutionStatus.FAILED)
        ex.finished_at = utcnow() - timedelta(minutes=5)
    db.flush()
    assert svc.runtime_state(a)["circuit_open"] is False


def test_success_closes_the_breaker_streak(db, svc, seeded, users):
    a = action(db, "clear-demo-cache")
    a.cooldown_seconds = 0
    a.breaker_threshold = 2
    svc.dry_run(a, users["op"], None)
    for st in (ExecutionStatus.FAILED, ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED):
        ex, _ = svc.request_execution(a, users["op"], None)
        finish(db, ex, st)
        ex.created_at = utcnow() + timedelta(
            seconds=len(db.scalars(select(RecoveryExecution)).all())
        )
        db.flush()
    assert svc.runtime_state(a)["circuit_open"] is False


def test_sensitive_action_requires_admin_and_confirmation(db, svc, seeded, users):
    a = action(db, "restart-wallet-mock")
    with pytest.raises(ForbiddenError):  # operator below min_role
        svc.dry_run(a, users["op"], None)
    svc.dry_run(a, users["admin"], None)
    with pytest.raises(RecoveryRejected) as e:
        svc.request_execution(a, users["admin"], None, confirm=False)
    assert e.value.code == "confirmation_required"
    with pytest.raises(ForbiddenError):
        svc.request_execution(a, users["op"], None, confirm=True)
    ex, created = svc.request_execution(a, users["admin"], None, confirm=True)
    assert created


def test_disabled_action_rejected(db, svc, seeded, users):
    a = action(db, "clear-demo-cache")
    a.enabled = False
    with pytest.raises(RecoveryRejected) as e:
        svc.dry_run(a, users["op"], None)
    assert e.value.code == "action_disabled"


def test_resolved_incident_cannot_be_recovered(db, env, svc, seeded, users):
    inc = incident_for(db, env)
    IncidentEngine(db, settings_service.effective(db)).resolve(inc, users["op"], "done")
    a = action(db, "clear-demo-cache")
    svc.dry_run(a, users["op"], None)
    with pytest.raises(RecoveryRejected):
        svc.request_execution(a, users["op"], inc)


# ------------------------------------------------------------- automatic recovery
def test_auto_recovery_end_to_end(db, env, svc, seeded):
    inc = incident_for(db, env, "game-api")
    env.http.status["game-api"] = 0
    ex = svc.auto_recover(inc.id)
    assert (
        ex is not None
        and ex.trigger == Trigger.AUTOMATIC
        and ex.status == ExecutionStatus.SUCCEEDED
    )
    db.refresh(inc)
    assert inc.status == IncidentStatus.RESOLVED


def test_auto_recovery_never_runs_sensitive_actions(db, env, svc, seeded):
    inc = incident_for(db, env, "wallet-mock")
    assert svc.auto_recover(inc.id) is None
    assert db.scalars(select(RecoveryExecution)).all() == []


def test_auto_recovery_skips_manual_only_service(db, env, svc, seeded):
    inc = incident_for(db, env, "authentication-service")
    assert svc.auto_recover(inc.id) is None


def test_auto_recovery_respects_global_switch_and_flapping(db, env, seeded):
    inc = incident_for(db, env, "game-api")
    cfg = settings_service.effective(db) | {"auto_recovery_enabled": False}
    off = RecoveryService(
        db,
        env.integrations.recovery_adapter,
        cfg,
        checker_transport=env.integrations.checker_transport,
        sleep=lambda s: None,
    )
    assert off.auto_recover(inc.id) is None
    inc.is_flapping = True
    on = RecoveryService(
        db,
        env.integrations.recovery_adapter,
        settings_service.effective(db),
        checker_transport=env.integrations.checker_transport,
        sleep=lambda s: None,
    )
    assert on.auto_recover(inc.id) is None


def test_auto_recovery_respects_cooldown_after_failure(db, env, svc, seeded):
    inc = incident_for(db, env, "game-api")
    env.http.status["game-api"] = 0
    env.http.heals_fix = False
    first = svc.auto_recover(inc.id)
    assert first.status == ExecutionStatus.VERIFICATION_FAILED
    assert svc.auto_recover(inc.id) is None  # cooldown blocks an immediate second attempt
    assert (
        len(
            db.scalars(
                select(RecoveryExecution).where(
                    RecoveryExecution.dry_run.is_(False),
                    RecoveryExecution.status != ExecutionStatus.REJECTED,
                )
            ).all()
        )
        == 1
    )
