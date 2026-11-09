import json

import httpx

from app.core.config import reset_settings_cache
from tests.conftest import PASSWORD

NODE = "node-exporter:9100"


# ------------------------------------------------------------------ overview
def test_overview_uses_real_sources_and_null_for_missing(client, env, seeded, viewer):
    o = client.get("/api/v1/overview", headers=viewer).json()
    assert o["monitoring"]["prometheus_available"] is True
    assert o["utilization"] == {
        "cpu_percent": None,
        "memory_percent": None,
        "disk_percent": None,
    }  # no data != 0
    assert o["services"]["total"] == 5 and o["services"]["availability_24h_percent"] is None
    assert o["servers"]["total"] == 1 and o["incidents"] == {"active": 0, "critical": 0}
    env.prom.set_vector("iguard:node_cpu_usage_percent", {NODE: 40})
    env.prom.set_vector("iguard:node_memory_usage_percent", {NODE: 60})
    env.prom.set_vector('up{job="node-exporter"}', {NODE: 1})
    o = client.get("/api/v1/overview", headers=viewer).json()
    assert o["utilization"]["cpu_percent"] == 40 and o["utilization"]["memory_percent"] == 60
    assert o["servers"]["healthy"] == 1


def test_overview_survives_prometheus_outage(client, env, seeded, viewer):
    env.prom.down = True
    r = client.get("/api/v1/overview", headers=viewer)
    assert r.status_code == 200 and r.json()["monitoring"]["prometheus_available"] is False
    assert r.json()["utilization"]["cpu_percent"] is None


def test_ready_reports_integrations(client, env):
    r = client.get("/api/v1/ready").json()
    assert r["status"] == "ready" and r["checks"]["prometheus"] == "ok"
    env.prom.down = True
    r = client.get("/api/v1/ready")
    assert r.status_code == 200 and r.json()["checks"]["prometheus"] == "unavailable"


# ------------------------------------------------------------------ logs
def test_logs_query_and_redaction(client, env, viewer):
    line = json.dumps(
        {"message": "login", "authorization": "Bearer abc.def.ghi", "severity": "INFO"}
    )
    env.loki_lines = [
        {"stream": {"service": "game-api"}, "values": [["1700000000000000000", line]]}
    ]
    r = client.get("/api/v1/logs?service=game-api&level=info&limit=5", headers=viewer)
    assert r.status_code == 200 and r.json()[0]["fields"]["authorization"] == "***REDACTED***"
    assert "abc.def.ghi" not in r.text
    sent = env.loki_requests[-1].url.params
    assert sent["query"] == '{service="game-api",level="info"}' and sent["limit"] == "5"


def test_log_search_builds_safe_logql(client, env, viewer):
    client.get("/api/v1/logs/search", params={"q": 'x" or {job=~".+"}'}, headers=viewer)
    q = env.loki_requests[-1].url.params["query"]
    assert q.endswith('|= "x\\" or {job=~\\".+\\"}"')  # quoted, cannot break out of the filter
    assert client.get("/api/v1/logs?service=a%22%7D", headers=viewer).status_code == 422
    assert client.get("/api/v1/logs/search?q=(&regex=true", headers=viewer).status_code == 422
    assert client.get("/api/v1/logs?limit=100000", headers=viewer).status_code == 422


def test_logs_when_loki_down(client, env, viewer):
    env.loki_lines = None  # makes the mock handler fail
    env.integrations.loki._client = httpx.Client(
        base_url="http://loki",
        transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x"))),
    )
    r = client.get("/api/v1/logs", headers=viewer)
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unavailable"


# ------------------------------------------------------------------ alerts / telegram
def test_alerts_list_combines_alertmanager_and_history(client, env, viewer, operator):
    env.alerts = [
        {
            "labels": {"alertname": "HostHighCpu", "severity": "warning"},
            "annotations": {"summary": "cpu"},
            "status": {"state": "active"},
            "startsAt": "2026-11-04T10:00:00Z",
        }
    ]
    a = client.get("/api/v1/alerts", headers=viewer).json()
    assert a["alertmanager_available"] and a["active"][0]["name"] == "HostHighCpu"
    client.post("/api/v1/alerts/test", headers=operator, json={})
    assert client.get("/api/v1/alerts", headers=viewer).json()["history"]["total"] == 1


def test_alert_test_without_telegram_is_reported_not_faked(client, operator, admin):
    r = client.post("/api/v1/alerts/test", headers=operator, json={"message": "hello"})
    assert (
        r.status_code == 200 and r.json()["status"] == "SKIPPED" and r.json()["configured"] is False
    )
    assert "not configured" in r.json()["error"]


def test_alert_test_with_telegram_sends_message(client, env, operator, monkeypatch):
    monkeypatch.setenv("IGUARD_TELEGRAM_BOT_TOKEN", "999:SECRETTOKEN")
    monkeypatch.setenv("IGUARD_TELEGRAM_CHAT_ID", "42")
    reset_settings_cache()
    from app.notifications.telegram import TelegramClient

    env.integrations.telegram = TelegramClient(transport=httpx.MockTransport(env.telegram.handler))
    r = client.post("/api/v1/alerts/test", headers=operator, json={"message": "ping"})
    assert r.json()["status"] == "SENT" and len(env.telegram.requests) == 1
    assert "SECRETTOKEN" not in r.text
    monkeypatch.delenv("IGUARD_TELEGRAM_BOT_TOKEN")
    monkeypatch.delenv("IGUARD_TELEGRAM_CHAT_ID")
    reset_settings_cache()


def test_alert_configuration_roundtrip_and_validation(client, admin, viewer):
    cfg = client.get("/api/v1/alerts/configuration", headers=viewer).json()
    assert cfg["channel"] == "TELEGRAM" and "INCIDENT_CRITICAL" in cfg["notify_events"]
    r = client.patch(
        "/api/v1/alerts/configuration",
        headers=admin,
        json={
            "min_severity": "CRITICAL",
            "notify_events": ["INCIDENT_CRITICAL"],
            "cooldown_seconds": 60,
        },
    )
    assert (
        r.status_code == 200
        and r.json()["min_severity"] == "CRITICAL"
        and r.json()["notify_events"] == ["INCIDENT_CRITICAL"]
    )
    assert (
        client.patch(
            "/api/v1/alerts/configuration", headers=admin, json={"notify_events": ["NOPE"]}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/alerts/configuration", headers=admin, json={"cooldown_seconds": -1}
        ).status_code
        == 422
    )


# ------------------------------------------------------------------ alertmanager webhook
def payload(status="firing"):
    return {
        "alerts": [
            {
                "status": status,
                "labels": {"alertname": "HostHighCpu", "severity": "critical", "instance": NODE},
                "annotations": {"summary": "CPU high on node"},
            }
        ]
    }


def test_webhook_requires_token(client):
    assert client.post("/api/v1/alerts/webhook", json=payload()).status_code == 401
    assert (
        client.post(
            "/api/v1/alerts/webhook", json=payload(), headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )


def test_webhook_creates_and_dedups_incidents(client, seeded, operator):
    h = {"Authorization": "Bearer test-webhook-token-123456"}
    assert client.post("/api/v1/alerts/webhook", json=payload(), headers=h).json()["created"] == 1
    assert client.post("/api/v1/alerts/webhook", json=payload(), headers=h).json()["created"] == 0
    items = client.get("/api/v1/incidents", headers=operator).json()["items"]
    assert (
        len(items) == 1 and items[0]["source"] == "alertmanager" and items[0]["category"] == "CPU"
    )
    assert items[0]["server_name"] == "demo-host" and items[0]["occurrences"] == 2


# ------------------------------------------------------------------ audit
def test_audit_log_filters_and_login_events(client, admin):
    client.post(
        "/api/v1/auth/login", json={"identifier": "admin-user", "password": "bad-Password-1A"}
    )
    r = client.get("/api/v1/audit-logs?action=auth.login&outcome=FAILURE", headers=admin).json()
    assert (
        r["total"] == 1
        and r["items"][0]["actor_name"] == "admin-user"
        and r["items"][0]["ip_address"]
    )
    assert "password" not in json.dumps(r).lower().replace("password_reset", "")
    assert (
        client.get("/api/v1/audit-logs?sort=-created_at&page_size=2", headers=admin).json()[
            "page_size"
        ]
        == 2
    )


def test_audit_log_is_append_only_via_api(client, admin):
    for m in ("post", "patch", "delete", "put"):
        assert getattr(client, m)("/api/v1/audit-logs", headers=admin).status_code in (404, 405)


# ------------------------------------------------------------------ settings
def test_settings_read_update_validate(client, admin, viewer):
    s = {x["key"]: x for x in client.get("/api/v1/settings", headers=viewer).json()}
    assert s["cpu_warning_percent"]["value"] == 80 and s["auto_recovery_enabled"]["type"] == "bool"
    r = client.patch(
        "/api/v1/settings",
        headers=admin,
        json={"values": {"cpu_warning_percent": 70, "auto_recovery_enabled": False}},
    )
    assert r.status_code == 200
    now = {x["key"]: x["value"] for x in r.json()}
    assert now["cpu_warning_percent"] == 70 and now["auto_recovery_enabled"] is False
    bad = [
        {"nope": 1},
        {"cpu_warning_percent": 99},
        {"cpu_warning_percent": "abc"},
        {"auto_recovery_enabled": "yes"},
        {"cpu_warning_percent": 500},
        {"flap_threshold": 2.5},
    ]
    for values in bad:
        assert (
            client.patch("/api/v1/settings", headers=admin, json={"values": values}).status_code
            == 422
        ), values
    assert client.patch("/api/v1/settings", headers=admin, json={"values": {}}).status_code == 422


def test_settings_change_affects_detection(client, env, seeded, admin, operator):
    from app.database.session import session_scope
    from app.incidents import detector
    from app.services import settings_service

    env.prom.set_vector("iguard:node_cpu_usage_percent", {NODE: 75})
    client.patch(
        "/api/v1/settings",
        headers=admin,
        json={"values": {"cpu_warning_percent": 70, "sustained_evaluations": 1}},
    )
    with session_scope() as db:
        detector.run_detection(db, env.integrations.prometheus, settings_service.effective(db))
    assert client.get("/api/v1/incidents?category=CPU", headers=operator).json()["total"] == 1


# ------------------------------------------------------------------ users & profile
def test_user_management_flow(client, admin, viewer):
    new = {
        "email": "New.User@Example.test",
        "username": "new.user",
        "password": "Str0ngPassw0rd!xyz",
        "role": "OPERATOR",
    }
    r = client.post("/api/v1/users", headers=admin, json=new)
    assert (
        r.status_code == 201
        and r.json()["email"] == "new.user@example.test"
        and r.json()["must_change_password"]
    )
    assert "password" not in json.dumps(r.json()).lower().replace("must_change_password", "")
    uid = r.json()["id"]
    assert client.post("/api/v1/users", headers=admin, json=new).status_code == 409
    assert (
        client.post(
            "/api/v1/users",
            headers=admin,
            json={**new, "email": "x@y.test", "username": "u2", "password": "weak"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/users", headers=admin, json={**new, "email": "bad", "username": "u3"}
        ).status_code
        == 422
    )
    login = client.post(
        "/api/v1/auth/login", json={"identifier": "new.user", "password": new["password"]}
    ).json()
    assert login["user"]["roles"] == ["OPERATOR"] and login["user"]["must_change_password"] is True
    assert client.patch(f"/api/v1/users/{uid}", headers=admin, json={"role": "VIEWER"}).json()[
        "roles"
    ] == ["VIEWER"]
    assert (
        client.patch(f"/api/v1/users/{uid}", headers=admin, json={"is_active": False}).json()[
            "is_active"
        ]
        is False
    )
    old = {"Authorization": f"Bearer {login['access_token']}"}
    assert (
        client.get("/api/v1/auth/me", headers=old).status_code == 401
    )  # sessions revoked on disable
    assert client.get("/api/v1/users?search=new&active=false", headers=admin).json()["total"] == 1
    assert client.delete(f"/api/v1/users/{uid}", headers=admin).status_code == 204


def test_cannot_lock_out_last_admin(client, admin):
    me = client.get("/api/v1/auth/me", headers=admin).json()["id"]
    assert (
        client.patch(f"/api/v1/users/{me}", headers=admin, json={"role": "VIEWER"}).status_code
        == 403
    )
    assert (
        client.patch(f"/api/v1/users/{me}", headers=admin, json={"is_active": False}).status_code
        == 403
    )
    assert client.delete(f"/api/v1/users/{me}", headers=admin).status_code == 403


def test_admin_password_reset_forces_change_and_revokes(client, admin, operator):
    ops = client.get("/api/v1/users?search=operator", headers=admin).json()["items"][0]
    r = client.patch(
        f"/api/v1/users/{ops['id']}", headers=admin, json={"password": "Br4ndNewPassw0rd!!"}
    )
    assert r.json()["must_change_password"] is True
    assert client.get("/api/v1/auth/me", headers=operator).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", json={"identifier": "operator-user", "password": PASSWORD}
        ).status_code
        == 401
    )


def test_profile_update(client, viewer):
    r = client.patch("/api/v1/users/me", headers=viewer, json={"full_name": "  Ada Lovelace "})
    assert r.status_code == 200 and r.json()["full_name"] == "Ada Lovelace"


# ------------------------------------------------------------------ reports
def test_reports_are_computed_from_real_data(client, env, seeded, operator):
    from tests.api.test_incidents_recovery_api import force_down

    r0 = client.get("/api/v1/reports/summary", headers=operator).json()
    assert (
        r0["incidents_total"] == 0
        and r0["mttr_minutes"] is None
        and r0["average_availability_percent"] is None
    )
    inc, _ = force_down(client, env, operator=operator)
    client.post(
        f"/api/v1/incidents/{inc['id']}/resolve",
        headers=operator,
        json={"resolution_summary": "fixed"},
    )
    s = client.get("/api/v1/reports/summary?days=7", headers=operator).json()
    assert (
        s["incidents_total"] == 1
        and s["by_severity"] == {"CRITICAL": 1}
        and s["mttr_minutes"] is not None
    )
    assert s["average_availability_percent"] is not None
    av = client.get("/api/v1/reports/availability", headers=operator).json()
    ga = next(i for i in av["items"] if i["service"] == "game-api")
    gw = next(i for i in av["items"] if i["service"] == "game-web")
    assert (
        ga["availability_percent"] == 0.0 and gw["availability_percent"] is None
    )  # no data is null, not 0
    ir = client.get("/api/v1/reports/incidents", headers=operator).json()
    assert ir["by_category"] == {"SERVICE_DOWN": 1} and ir["per_day"][0]["count"] == 1
    rr = client.get("/api/v1/reports/recovery", headers=operator).json()
    assert rr["total"] == 0 and rr["success_rate_percent"] is None
    assert client.get("/api/v1/reports/summary?days=0", headers=operator).status_code == 422
