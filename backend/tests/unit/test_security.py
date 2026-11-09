import json
import logging
import time

import jwt
import pytest

from app.core.errors import UnauthorizedError, ValidationFailed
from app.core.logging import JsonFormatter, redact, redact_text, request_id_var
from app.security import tokens
from app.security.passwords import hash_password, validate_password_policy, verify_password
from app.security.rate_limit import SlidingWindowLimiter


def test_argon2_hash_and_verify():
    h = hash_password("CorrectHorse1Battery")
    assert h.startswith("$argon2id$")
    assert verify_password("CorrectHorse1Battery", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)  # unknown user path


@pytest.mark.parametrize(
    "pw", ["short1A", "alllowercase123", "ALLUPPERCASE123", "NoDigitsHereAtAll"]
)
def test_password_policy_rejects_weak(pw):
    with pytest.raises(ValidationFailed):
        validate_password_policy(pw)


def test_password_policy_accepts_strong():
    validate_password_policy("Str0ngPassw0rd!xyz")


def test_access_token_roundtrip_and_tamper(db):
    import uuid

    uid, sid = uuid.uuid4(), uuid.uuid4()
    tok, ttl = tokens.create_access_token(uid, sid, ["ADMIN"])
    assert ttl > 0
    payload = tokens.decode_access_token(tok)
    assert payload["sub"] == str(uid) and payload["sid"] == str(sid)
    with pytest.raises(UnauthorizedError):
        tokens.decode_access_token(tok[:-3] + "abc")


def test_alg_none_and_wrong_key_rejected():
    forged = jwt.encode(
        {
            "sub": "x",
            "sid": "y",
            "iss": "iguard",
            "iat": 1,
            "exp": int(time.time()) + 60,
            "typ": "access",
        },
        "other-key-other-key-other-key-0000",
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError):
        tokens.decode_access_token(forged)
    none_tok = jwt.encode({"sub": "x"}, None, algorithm="none")
    with pytest.raises(UnauthorizedError):
        tokens.decode_access_token(none_tok)


def test_expired_token():
    from app.core.config import get_settings

    payload = {"sub": "a", "sid": "b", "iss": "iguard", "typ": "access", "iat": 1, "exp": 2}
    tok = jwt.encode(payload, get_settings().secret_key.get_secret_value(), algorithm="HS256")
    with pytest.raises(UnauthorizedError) as e:
        tokens.decode_access_token(tok)
    assert e.value.code == "token_expired"


def test_refresh_tokens_are_hashed_not_stored_raw():
    raw, digest = tokens.new_refresh_token()
    assert raw != digest and len(digest) == 64 and tokens.hash_token(raw) == digest


def test_csrf_compare():
    assert tokens.csrf_matches("abc", "abc")
    assert not tokens.csrf_matches("abc", "abd")
    assert not tokens.csrf_matches(None, "abc")


def test_rate_limiter_window():
    lim = SlidingWindowLimiter(2, 0.2)
    lim.record("k")
    lim.record("k")
    assert lim.is_limited("k")
    time.sleep(0.25)
    assert not lim.is_limited("k")


def test_redaction_of_secrets():
    data = {
        "password": "hunter2",
        "nested": {"Authorization": "Bearer abc.def", "ok": "fine"},
        "list": [{"api_key": "k"}],
        "msg": "login with password=hunter2 and Bearer abc.def.ghi",
    }
    out = redact(data)
    assert out["password"] == "***REDACTED***"
    assert out["nested"]["Authorization"] == "***REDACTED***" and out["nested"]["ok"] == "fine"
    assert out["list"][0]["api_key"] == "***REDACTED***"
    assert "hunter2" not in out["msg"] and "abc.def.ghi" not in out["msg"]
    assert "123456:ABCdef" not in redact_text(
        "https://api.telegram.org/bot123456:ABCdef_ghi/sendMessage"
    )


def test_json_log_format_contains_required_fields_and_redacts():
    fmt = JsonFormatter("svc", "test")
    tok = request_id_var.set("req-12345678")
    try:
        rec = logging.LogRecord("x", logging.INFO, "f", 1, "hello token=SECRETVALUE", (), None)
        rec.password = "p4ss"
        out = json.loads(fmt.format(rec))
    finally:
        request_id_var.reset(tok)
    for key in (
        "timestamp",
        "severity",
        "service",
        "environment",
        "request_id",
        "correlation_id",
        "message",
    ):
        assert key in out
    assert out["request_id"] == "req-12345678"
    assert "SECRETVALUE" not in out["message"] and out["password"] == "***REDACTED***"
