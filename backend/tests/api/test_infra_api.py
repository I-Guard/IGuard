import uuid

from tests.conftest import PASSWORD  # noqa: F401


def srv(**kw):
    return {"name": "edge-01", "hostname": "edge-01.local", "environment": "demo", **kw}


def test_server_crud_validation_and_audit(client, admin, viewer):
    r = client.post(
        "/api/v1/servers", headers=admin, json=srv(prometheus_instance="n:9100", tags=["a"])
    )
    assert r.status_code == 201
    sid = r.json()["id"]
    assert client.post("/api/v1/servers", headers=admin, json=srv()).status_code == 409
    assert (
        client.post("/api/v1/servers", headers=admin, json=srv(name="bad;name")).status_code == 422
    )
    assert client.get(f"/api/v1/servers/{sid}", headers=viewer).json()["name"] == "edge-01"
    assert client.get(f"/api/v1/servers/{uuid.uuid4()}", headers=viewer).status_code == 404
    assert client.get("/api/v1/servers/not-a-uuid", headers=viewer).status_code == 422
    p = client.patch(f"/api/v1/servers/{sid}", headers=admin, json={"description": "new"})
    assert p.status_code == 200 and p.json()["description"] == "new"
    page = client.get("/api/v1/servers?search=EDGE&sort=-name", headers=viewer).json()
    assert page["total"] == 1 and page["page"] == 1 and page["pages"] == 1
    assert (
        client.get("/api/v1/servers?sort=password", headers=viewer).status_code == 422
    )  # sort allowlist
    assert client.delete(f"/api/v1/servers/{sid}", headers=admin).status_code == 204
    assert client.get(f"/api/v1/servers/{sid}", headers=admin).status_code == 404
    logs = client.get("/api/v1/audit-logs?search=server", headers=admin).json()
    assert {x["action"] for x in logs["items"]} >= {
        "server.create",
        "server.update",
        "server.delete",
    }


def test_server_health_reflects_prometheus_and_incidents(client, admin, env):
    sid = client.post(
        "/api/v1/servers", headers=admin, json=srv(prometheus_instance="n:9100")
    ).json()["id"]
    assert (
        client.get(f"/api/v1/servers/{sid}", headers=admin).json()["health"] == "unknown"
    )  # no data != healthy
    env.prom.set_vector('up{job="node-exporter"}', {"n:9100": 1})
    assert client.get(f"/api/v1/servers/{sid}", headers=admin).json()["health"] == "healthy"
    env.prom.set_vector('up{job="node-exporter"}', {"n:9100": 0})
    assert client.get(f"/api/v1/servers/{sid}", headers=admin).json()["health"] == "unhealthy"


def test_server_metrics_missing_data_is_null_not_zero(client, admin, env):
    sid = client.post(
        "/api/v1/servers", headers=admin, json=srv(prometheus_instance="n:9100")
    ).json()["id"]
    m = client.get(f"/api/v1/servers/{sid}/metrics", headers=admin).json()
    assert (
        m["available"] is False
        and m["metrics"] is None
        or m["metrics"]["cpu_usage_percent"] is None
    )
    env.prom.set_vector("iguard:node_cpu_usage_percent", {"n:9100": 12.5})
    m = client.get(f"/api/v1/servers/{sid}/metrics", headers=admin).json()
    assert m["available"] and m["metrics"]["cpu_usage_percent"] == 12.5
    assert m["metrics"]["memory_usage_percent"] is None


def test_server_metrics_when_prometheus_down(client, admin, env):
    sid = client.post(
        "/api/v1/servers", headers=admin, json=srv(prometheus_instance="n:9100")
    ).json()["id"]
    env.prom.down = True
    r = client.get(f"/api/v1/servers/{sid}/metrics", headers=admin)
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unavailable"


def svc_body(**kw):
    return {"name": "game-x", "check_type": "HTTP", "url": "http://game-x:8080/health", **kw}


def test_service_crud_and_validation(client, admin, operator):
    r = client.post("/api/v1/services", headers=admin, json=svc_body())
    assert r.status_code == 201 and r.json()["status"] == "UNKNOWN"
    sid = r.json()["id"]
    assert client.post("/api/v1/services", headers=admin, json=svc_body()).status_code == 409
    assert (
        client.post(
            "/api/v1/services", headers=admin, json=svc_body(name="a", url="ftp://x")
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/services", headers=admin, json=svc_body(name="b", check_type="TCP")
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/services", headers=admin, json=svc_body(name="c", interval_seconds=1)
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/services", headers=admin, json=svc_body(name="d", server_id=str(uuid.uuid4()))
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/services",
            headers=admin,
            json=svc_body(name="meta", url="http://169.254.169.254/latest"),
        ).status_code
        == 422
    )  # SSRF guard at registration
    tcp = client.post(
        "/api/v1/services",
        headers=admin,
        json={"name": "db-port", "check_type": "TCP", "host": "db", "port": 5432},
    )
    assert tcp.status_code == 201
    assert (
        client.patch(
            f"/api/v1/services/{sid}", headers=admin, json={"url": "http://169.254.169.254/"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/services/{sid}", headers=admin, json={"latency_threshold_ms": 250}
        ).json()["latency_threshold_ms"]
        == 250
    )
    q = client.get(
        "/api/v1/services?status=UNKNOWN&sort=-name&page_size=1", headers=operator
    ).json()
    assert q["total"] == 2 and len(q["items"]) == 1 and q["pages"] == 2
    assert client.delete(f"/api/v1/services/{sid}", headers=admin).status_code == 204


def test_service_check_records_history_and_availability(client, admin, operator, env):
    sid = client.post("/api/v1/services", headers=admin, json=svc_body(retry_threshold=2)).json()[
        "id"
    ]
    r = client.post(f"/api/v1/services/{sid}/check", headers=operator).json()
    assert r["success"] and r["status"] == "UP" and r["response_time_ms"] is not None
    env.http.status["game-x"] = 500
    assert (
        client.post(f"/api/v1/services/{sid}/check", headers=operator).json()["status"]
        == "DEGRADED"
    )
    down = client.post(f"/api/v1/services/{sid}/check", headers=operator).json()
    assert down["status"] == "DOWN" and not down["success"] and down["status_code"] == 500
    av = client.get(f"/api/v1/services/{sid}/availability", headers=operator).json()
    assert av["24h"] == 33.333
    hist = client.get(f"/api/v1/services/{sid}/checks", headers=operator).json()
    assert len(hist) == 3 and hist[0]["success"] is False
    assert (
        client.get(f"/api/v1/services/{sid}", headers=operator).json()["availability_24h"] == 33.333
    )
    assert any(
        a["action"] == "service.check"
        for a in client.get("/api/v1/audit-logs", headers=admin).json()["items"]
    )


def test_service_without_checks_has_null_availability(client, admin):
    sid = client.post("/api/v1/services", headers=admin, json=svc_body()).json()["id"]
    assert client.get(f"/api/v1/services/{sid}", headers=admin).json()["availability_24h"] is None
