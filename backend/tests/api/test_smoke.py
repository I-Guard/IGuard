def test_health_and_version(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    v = client.get("/api/v1/version").json()
    assert v["name"] == "IGuard" and v["version"] == "1.0.0"
    assert client.get("/api/v1/ready").json()["checks"]["database"] == "ok"
