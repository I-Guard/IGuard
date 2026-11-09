from app.services import auth_service
from tests.conftest import PASSWORD


def login(client, who, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"identifier": who, "password": password})


def test_login_success_returns_tokens_and_cookies(client, admin):
    r = login(client, "admin-user")
    body = r.json()
    assert r.status_code == 200 and body["token_type"] == "bearer"
    assert body["user"]["roles"] == ["ADMIN"] and "password_hash" not in str(body)
    cookies = r.headers.get_list("set-cookie")
    refresh = next(c for c in cookies if c.startswith("iguard_refresh="))
    assert "httponly" in refresh.lower() and "samesite=strict" in refresh.lower()


def test_login_by_email(client, admin):
    assert login(client, "admin-user@example.test").status_code == 200


def test_wrong_password_and_unknown_user_are_indistinguishable(client, admin):
    a = login(client, "admin-user", "Wrong-Pass-123abc")
    b = login(client, "ghost-user", "Wrong-Pass-123abc")
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["message"] == b.json()["error"]["message"]
    assert a.json()["error"]["code"] == b.json()["error"]["code"]


def test_login_rate_limit(client, admin):
    for _ in range(5):
        assert login(client, "admin-user", "bad-password-1A").status_code == 401
    r = login(client, "admin-user", PASSWORD)  # even the right password is throttled
    assert r.status_code == 429 and r.headers["retry-after"]


def test_account_lockout(client, admin, monkeypatch):
    from app.core.config import reset_settings_cache

    monkeypatch.setenv("IGUARD_ACCOUNT_LOCKOUT_THRESHOLD", "3")
    monkeypatch.setenv("IGUARD_LOGIN_RATE_LIMIT_ATTEMPTS", "100")
    reset_settings_cache()
    auth_service.reset_limiter()
    for _ in range(3):
        login(client, "admin-user", "bad-password-1A")
    assert login(client, "admin-user", PASSWORD).status_code == 401  # locked
    reset_settings_cache()


def test_me_requires_auth(client, admin):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code
        == 401
    )
    me = client.get("/api/v1/auth/me", headers=admin).json()
    assert me["username"] == "admin-user"


def test_logout_revokes_access_token_immediately(client, admin):
    assert client.get("/api/v1/auth/me", headers=admin).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=admin).status_code == 200
    r = client.get("/api/v1/auth/me", headers=admin)
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_revoked"


def test_refresh_rotation_and_reuse_detection(client, admin):
    r = client.post("/api/v1/auth/login", json={"identifier": "admin-user", "password": PASSWORD})
    old_refresh = r.cookies.get("iguard_refresh")
    csrf = r.json()["csrf_token"]
    client.cookies.clear()  # act as a non-browser client: refresh token in the body, no cookies
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    client.cookies.clear()
    assert r1.status_code == 200
    new_refresh = r1.cookies.get("iguard_refresh")
    assert new_refresh and new_refresh != old_refresh
    # replaying the rotated (old) token revokes the whole session
    client.cookies.clear()
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 401 and r2.json()["error"]["code"] == "refresh_token_reuse"
    client.cookies.clear()
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert r3.status_code == 401  # family revoked
    new_access = r1.json()["access_token"]
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"}).status_code
        == 401
    )
    assert csrf


def test_cookie_refresh_requires_csrf_header(client, admin):
    client.cookies.clear()
    r = client.post("/api/v1/auth/login", json={"identifier": "admin-user", "password": PASSWORD})
    csrf = r.json()["csrf_token"]
    bad = client.post("/api/v1/auth/refresh")  # cookie present, no CSRF header
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "csrf_failed"
    bad2 = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "wrong"})
    assert bad2.status_code == 403
    ok = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200


def test_change_password(client, admin):
    r = client.post(
        "/api/v1/auth/change-password",
        headers=admin,
        json={"current_password": "nope-nope-1A", "new_password": "An0therStrongPass!"},
    )
    assert r.status_code == 403
    r = client.post(
        "/api/v1/auth/change-password",
        headers=admin,
        json={"current_password": PASSWORD, "new_password": "weak"},
    )
    assert r.status_code == 422
    r = client.post(
        "/api/v1/auth/change-password",
        headers=admin,
        json={"current_password": PASSWORD, "new_password": "An0therStrongPass!"},
    )
    assert r.status_code == 200
    assert login(client, "admin-user").status_code == 401
    assert login(client, "admin-user", "An0therStrongPass!").status_code == 200


def test_disabled_user_cannot_use_existing_token(client, admin, db):
    from sqlalchemy import select

    from app.models import User

    db.execute  # noqa: B018
    u = db.scalar(select(User).where(User.username == "admin-user"))
    u.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=admin).status_code == 401


def test_security_headers_and_request_id(client):
    r = client.get("/api/v1/health", headers={"X-Request-ID": "abc12345-req"})
    assert r.headers["x-request-id"] == "abc12345-req"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    bad = client.get("/api/v1/health", headers={"X-Request-ID": "evil\nvalue"})
    assert "\n" not in bad.headers["x-request-id"]


def test_error_envelope_shape(client):
    r = client.get("/api/v1/incidents")
    err = r.json()["error"]
    assert set(err) >= {"code", "message", "request_id"}
    r = client.post("/api/v1/auth/login", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_cors_only_for_configured_origins(client):
    ok = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    evil = client.options(
        "/api/v1/health",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in evil.headers
