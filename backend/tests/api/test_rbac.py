"""Role-based access control matrix: every endpoint x every role (and anonymous)."""

import uuid

import pytest

ID = str(uuid.uuid4())

# (method, path, min_role)  -- min_role None = public
MATRIX = [
    ("GET", "/api/v1/health", None),
    ("GET", "/api/v1/version", None),
    ("GET", "/api/v1/overview", "VIEWER"),
    ("GET", "/api/v1/auth/me", "VIEWER"),
    ("GET", "/api/v1/servers", "VIEWER"),
    ("POST", "/api/v1/servers", "ADMIN"),
    ("GET", f"/api/v1/servers/{ID}", "VIEWER"),
    ("PATCH", f"/api/v1/servers/{ID}", "ADMIN"),
    ("DELETE", f"/api/v1/servers/{ID}", "ADMIN"),
    ("GET", "/api/v1/services", "VIEWER"),
    ("POST", "/api/v1/services", "ADMIN"),
    ("GET", f"/api/v1/services/{ID}", "VIEWER"),
    ("PATCH", f"/api/v1/services/{ID}", "ADMIN"),
    ("DELETE", f"/api/v1/services/{ID}", "ADMIN"),
    ("POST", f"/api/v1/services/{ID}/check", "OPERATOR"),
    ("GET", "/api/v1/incidents", "VIEWER"),
    ("GET", f"/api/v1/incidents/{ID}", "VIEWER"),
    ("GET", f"/api/v1/incidents/{ID}/timeline", "VIEWER"),
    ("POST", f"/api/v1/incidents/{ID}/acknowledge", "OPERATOR"),
    ("POST", f"/api/v1/incidents/{ID}/assign", "OPERATOR"),
    ("POST", f"/api/v1/incidents/{ID}/resolve", "OPERATOR"),
    ("GET", "/api/v1/recovery/actions", "VIEWER"),
    ("GET", "/api/v1/recovery/history", "VIEWER"),
    ("GET", f"/api/v1/recovery/history/{ID}", "VIEWER"),
    ("POST", f"/api/v1/recovery/actions/{ID}/execute", "OPERATOR"),
    ("POST", f"/api/v1/recovery/actions/{ID}/dry-run", "OPERATOR"),
    ("GET", "/api/v1/logs", "VIEWER"),
    ("GET", "/api/v1/logs/search?q=x", "VIEWER"),
    ("GET", "/api/v1/alerts", "VIEWER"),
    ("POST", "/api/v1/alerts/test", "OPERATOR"),
    ("GET", "/api/v1/alerts/configuration", "VIEWER"),
    ("PATCH", "/api/v1/alerts/configuration", "ADMIN"),
    ("GET", "/api/v1/audit-logs", "ADMIN"),
    ("GET", "/api/v1/reports/summary", "VIEWER"),
    ("GET", "/api/v1/reports/availability", "VIEWER"),
    ("GET", "/api/v1/reports/incidents", "VIEWER"),
    ("GET", "/api/v1/reports/recovery", "VIEWER"),
    ("GET", "/api/v1/settings", "VIEWER"),
    ("PATCH", "/api/v1/settings", "ADMIN"),
    ("GET", "/api/v1/users", "ADMIN"),
    ("POST", "/api/v1/users", "ADMIN"),
    ("PATCH", f"/api/v1/users/{ID}", "ADMIN"),
    ("DELETE", f"/api/v1/users/{ID}", "ADMIN"),
    ("GET", "/api/v1/users/assignable", "OPERATOR"),
]
RANK = {None: 0, "VIEWER": 1, "OPERATOR": 2, "ADMIN": 3}


@pytest.mark.parametrize("method,path,minimum", MATRIX)
def test_anonymous_access(client, method, path, minimum):
    r = client.request(method, path, json={} if method in ("POST", "PATCH") else None)
    if minimum is None:
        assert r.status_code == 200
    else:
        assert r.status_code == 401, f"{method} {path} must require authentication"


@pytest.mark.parametrize("method,path,minimum", [m for m in MATRIX if m[2]])
@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_role_enforcement(client, request, method, path, minimum, role):
    headers = request.getfixturevalue(role)
    r = client.request(
        method, path, headers=headers, json={} if method in ("POST", "PATCH") else None
    )
    if RANK[role.upper()] < RANK[minimum]:
        assert r.status_code == 403, f"{role} must not access {method} {path} (got {r.status_code})"
        assert r.json()["error"]["code"] == "insufficient_role"
    else:
        assert r.status_code != 403 and r.status_code != 401, f"{role} should reach {method} {path}"


def test_every_registered_api_route_is_covered_by_matrix(client):
    paths = client.get("/openapi.json").json()["paths"]
    covered = {p.split("?")[0].replace(ID, "{x}") for _, p, _ in MATRIX}
    import re

    norm = lambda p: re.sub(r"\{[^}]+\}", "{x}", p)  # noqa: E731
    registered = {norm(p) for p in paths if p.startswith("/api/v1")}
    exempt = {
        "/api/v1/ready",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/change-password",
        "/api/v1/alerts/webhook",
        "/api/v1/users/me",
        "/api/v1/servers/{x}/metrics",
        "/api/v1/servers/{x}/metrics/range",
        "/api/v1/services/{x}/checks",
        "/api/v1/services/{x}/availability",
        "/api/v1/incidents/{x}/status",
    }
    assert registered - covered - exempt == set(), "new endpoint without an RBAC test"
