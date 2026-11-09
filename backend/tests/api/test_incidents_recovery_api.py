"""End-to-end API flows: incident lifecycle, recovery dry-run/execute, audit and notifications."""

from sqlalchemy import select

from app.database.session import session_scope
from app.incidents import detector
from app.models import Service
from app.services import settings_service


def force_down(client, env, db_name="game-api", operator=None):
    """Make a synthetic service fail checks and run detection -> returns the incident dict."""
    env.http.status[db_name] = 0
    with session_scope() as db:
        sid = str(db.scalar(select(Service).where(Service.name == db_name)).id)
    for _ in range(3):
        client.post(f"/api/v1/services/{sid}/check", headers=operator)
    with session_scope() as db:
        detector.run_detection(db, env.integrations.prometheus, settings_service.effective(db))
    inc = client.get(f"/api/v1/incidents?service_id={sid}&active=true", headers=operator).json()[
        "items"
    ]
    assert len(inc) == 1
    return inc[0], sid


def test_incident_lifecycle_via_api(client, env, seeded, operator, admin, viewer):
    inc, _ = force_down(client, env, operator=operator)
    iid = inc["id"]
    assert (
        inc["status"] == "DETECTED"
        and inc["severity"] == "CRITICAL"
        and inc["category"] == "SERVICE_DOWN"
    )
    assert inc["service_name"] == "game-api" and inc["server_name"] == "demo-host"
    for key in (
        "title",
        "description",
        "source",
        "created_at",
        "updated_at",
        "resolved_at",
        "acknowledged_by",
        "assigned_to",
        "root_cause",
        "resolution_summary",
        "fingerprint",
    ):
        assert key in inc

    assert client.post(f"/api/v1/incidents/{iid}/acknowledge", headers=viewer).status_code == 403
    ack = client.post(
        f"/api/v1/incidents/{iid}/acknowledge", headers=operator, json={"note": "on it"}
    )
    assert ack.status_code == 200 and ack.json()["status"] == "ACKNOWLEDGED"
    assert ack.json()["acknowledged_by"]["username"] == "operator-user"
    assert client.post(f"/api/v1/incidents/{iid}/acknowledge", headers=operator).status_code == 409

    users = client.get("/api/v1/users/assignable", headers=operator).json()
    assert {u["username"] for u in users} == {"operator-user", "admin-user"}
    me = next(u for u in users if u["username"] == "operator-user")
    asg = client.post(
        f"/api/v1/incidents/{iid}/assign", headers=operator, json={"assignee_id": me["id"]}
    )
    assert (
        asg.json()["status"] == "INVESTIGATING"
        and asg.json()["assigned_to"]["username"] == "operator-user"
    )
    st = client.post(
        f"/api/v1/incidents/{iid}/status", headers=operator, json={"status": "RESOLVED"}
    )
    assert st.status_code == 422

    res = client.post(
        f"/api/v1/incidents/{iid}/resolve",
        headers=operator,
        json={"resolution_summary": "restarted by hand", "root_cause": "OOM"},
    )
    assert (
        res.status_code == 200 and res.json()["status"] == "RESOLVED" and res.json()["resolved_at"]
    )
    assert (
        client.post(
            f"/api/v1/incidents/{iid}/resolve",
            headers=operator,
            json={"resolution_summary": "again"},
        ).status_code
        == 409
    )

    tl = client.get(f"/api/v1/incidents/{iid}/timeline", headers=viewer).json()
    kinds = [e["event_type"] for e in tl]
    assert (
        kinds[0] == "DETECTED"
        and kinds[-1] == "RESOLVED"
        and "ACKNOWLEDGED" in kinds
        and "ASSIGNED" in kinds
    )
    audit = client.get("/api/v1/audit-logs?search=incident", headers=admin).json()["items"]
    assert {a["action"] for a in audit} >= {
        "incident.acknowledge",
        "incident.assign",
        "incident.resolve",
    }


def test_incident_filters_pagination_sorting(client, env, seeded, operator):
    inc, sid = force_down(client, env, operator=operator)
    force_down(client, env, "game-web", operator=operator)
    all_ = client.get("/api/v1/incidents?sort=-created_at&page_size=1", headers=operator).json()
    assert all_["total"] == 2 and len(all_["items"]) == 1 and all_["pages"] == 2
    assert (
        client.get("/api/v1/incidents?severity=CRITICAL&status=DETECTED", headers=operator).json()[
            "total"
        ]
        == 2
    )
    assert client.get("/api/v1/incidents?severity=INFO", headers=operator).json()["total"] == 0
    assert client.get(f"/api/v1/incidents?service_id={sid}", headers=operator).json()["total"] == 1
    assert client.get("/api/v1/incidents?search=game-web", headers=operator).json()["total"] == 1
    assert (
        client.get("/api/v1/incidents?search=%25", headers=operator).json()["total"] == 0
    )  # LIKE wildcard escaped
    assert client.get("/api/v1/incidents?sort=hacker", headers=operator).status_code == 422
    assert client.get("/api/v1/incidents?status=BOGUS", headers=operator).status_code == 422
    assert client.get("/api/v1/incidents?page=0", headers=operator).status_code == 422
    assert client.get("/api/v1/incidents?page_size=9999", headers=operator).status_code == 422


def test_sql_injection_attempts_are_inert(client, env, seeded, operator):
    force_down(client, env, operator=operator)
    for payload in (
        "' OR 1=1 --",
        "'; DROP TABLE incidents; --",
        "%' UNION SELECT * FROM users --",
    ):
        r = client.get("/api/v1/incidents", params={"search": payload}, headers=operator)
        assert r.status_code == 200 and r.json()["total"] == 0
    assert client.get("/api/v1/incidents", headers=operator).json()["total"] == 1


def test_unknown_ids_return_404_not_500(client, operator):
    import uuid

    for path in ("incidents", "recovery/history"):
        assert client.get(f"/api/v1/{path}/{uuid.uuid4()}", headers=operator).status_code == 404


def test_recovery_actions_listing_has_live_state(client, seeded, viewer):
    acts = client.get("/api/v1/recovery/actions", headers=viewer).json()
    by_key = {a["key"]: a for a in acts}
    assert (
        by_key["restart-wallet-mock"]["sensitive"] is True
        and by_key["restart-wallet-mock"]["min_role"] == "ADMIN"
    )
    assert (
        by_key["restart-game-api"]["auto_trigger"] is True
        and by_key["restart-game-api"]["circuit_open"] is False
    )
    assert all(
        "command" not in a and "shell" not in a for a in acts
    )  # no arbitrary command surface


def act_id(client, headers, key):
    return next(
        a["id"]
        for a in client.get("/api/v1/recovery/actions", headers=headers).json()
        if a["key"] == key
    )


def test_manual_recovery_dry_run_then_execute_resolves_incident(client, env, seeded, operator):
    inc, _ = force_down(client, env, operator=operator)
    aid = act_id(client, operator, "restart-game-api")
    blocked = client.post(
        f"/api/v1/recovery/actions/{aid}/execute", headers=operator, json={"incident_id": inc["id"]}
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "dry_run_required"

    dry = client.post(
        f"/api/v1/recovery/actions/{aid}/dry-run", headers=operator, json={"incident_id": inc["id"]}
    )
    assert (
        dry.status_code == 200
        and dry.json()["status"] == "DRY_RUN_OK"
        and dry.json()["dry_run"] is True
    )
    assert env.http.healed == []

    from app.recovery.service import RecoveryService  # make verification instant

    orig = RecoveryService.__init__
    RecoveryService.__init__ = lambda self, *a, **k: orig(
        self, *a, **{**k, "sleep": lambda s: None}
    )
    try:
        ex = client.post(
            f"/api/v1/recovery/actions/{aid}/execute",
            headers=operator,
            json={"incident_id": inc["id"]},
        )
    finally:
        RecoveryService.__init__ = orig
    body = ex.json()
    assert (
        ex.status_code == 200
        and body["status"] == "SUCCEEDED"
        and body["verification_passed"] is True
    )
    assert body["simulated"] is True and body["trigger"] == "MANUAL"
    assert (
        client.get(f"/api/v1/incidents/{inc['id']}", headers=operator).json()["status"]
        == "RESOLVED"
    )
    hist = client.get("/api/v1/recovery/history?dry_run=false", headers=operator).json()
    assert hist["total"] == 1 and hist["items"][0]["action_key"] == "restart-game-api"
    assert (
        client.get(f"/api/v1/recovery/history/{body['id']}", headers=operator).json()["id"]
        == body["id"]
    )
    tl = [
        e["event_type"]
        for e in client.get(f"/api/v1/incidents/{inc['id']}/timeline", headers=operator).json()
    ]
    assert "RECOVERY_STARTED" in tl and "RECOVERY_SUCCEEDED" in tl


def test_execute_idempotency_header_replays(client, seeded, operator):
    aid = act_id(client, operator, "clear-demo-cache")
    client.post(f"/api/v1/recovery/actions/{aid}/dry-run", headers=operator)
    h = {**operator, "Idempotency-Key": "demo-key-1"}
    first = client.post(f"/api/v1/recovery/actions/{aid}/execute", headers=h, json={})
    second = client.post(f"/api/v1/recovery/actions/{aid}/execute", headers=h, json={})
    assert (
        first.status_code == second.status_code == 200 and first.json()["id"] == second.json()["id"]
    )
    assert second.headers["idempotent-replay"] == "true"
    assert (
        client.get("/api/v1/recovery/history?dry_run=false", headers=operator).json()["total"] == 1
    )


def test_sensitive_action_flow_via_api(client, seeded, operator, admin):
    aid = act_id(client, admin, "restart-wallet-mock")
    assert (
        client.post(f"/api/v1/recovery/actions/{aid}/dry-run", headers=operator).status_code == 403
    )
    assert client.post(f"/api/v1/recovery/actions/{aid}/dry-run", headers=admin).status_code == 200
    r = client.post(f"/api/v1/recovery/actions/{aid}/execute", headers=admin, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirmation_required"
    assert (
        client.post(
            f"/api/v1/recovery/actions/{aid}/execute", headers=operator, json={"confirm": True}
        ).status_code
        == 403
    )
    ok = client.post(
        f"/api/v1/recovery/actions/{aid}/execute",
        headers=admin,
        json={"confirm": True, "reason": "demo"},
    )
    assert ok.status_code == 200 and ok.json()["status"] in ("SUCCEEDED", "VERIFICATION_FAILED")
    entries = client.get("/api/v1/audit-logs?search=recovery", headers=admin).json()["items"]
    started = next(e for e in entries if e["action"] == "recovery.execute")
    assert started["details"]["sensitive"] is True and started["details"]["confirmed"] is True


def test_cooldown_returns_429_via_api(client, seeded, operator):
    aid = act_id(client, operator, "clear-demo-cache")
    client.post(f"/api/v1/recovery/actions/{aid}/dry-run", headers=operator)
    assert (
        client.post(
            f"/api/v1/recovery/actions/{aid}/execute", headers=operator, json={}
        ).status_code
        == 200
    )
    r = client.post(f"/api/v1/recovery/actions/{aid}/execute", headers=operator, json={})
    assert r.status_code == 429 and r.json()["error"]["code"] == "cooldown_active"


def test_unknown_action_and_incident_rejected(client, seeded, operator):
    import uuid

    assert (
        client.post(
            f"/api/v1/recovery/actions/{uuid.uuid4()}/dry-run", headers=operator
        ).status_code
        == 404
    )
    aid = act_id(client, operator, "clear-demo-cache")
    r = client.post(
        f"/api/v1/recovery/actions/{aid}/dry-run",
        headers=operator,
        json={"incident_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404
    # arbitrary command injection fields are not part of the schema and are ignored/never executed
    r = client.post(
        f"/api/v1/recovery/actions/{aid}/execute",
        headers=operator,
        json={"command": "rm -rf /", "target": "iguard-postgres"},
    )
    assert r.status_code in (200, 409) and "rm -rf" not in r.text


def test_automatic_recovery_through_worker_tick(client, env, seeded, operator):
    from app.workers.loops import check_tick, detection_tick

    env.http.status["game-api"] = 0
    import app.recovery.service as rs

    orig = rs.time.sleep
    rs.time.sleep = lambda s: None
    try:
        for _ in range(3):
            check_tick(env.integrations)
            with session_scope() as db:
                for s in db.scalars(select(Service)).unique():
                    s.last_checked_at = None
        res = detection_tick(env.integrations)
    finally:
        rs.time.sleep = orig
    assert res.recovery_candidates
    hist = client.get("/api/v1/recovery/history?dry_run=false", headers=operator).json()
    assert hist["total"] >= 1 and hist["items"][0]["trigger"] == "AUTOMATIC"
    assert hist["items"][0]["status"] == "SUCCEEDED"
    assert client.get("/api/v1/incidents?active=true", headers=operator).json()["total"] == 0
