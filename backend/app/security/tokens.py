"""JWT access tokens and opaque rotating refresh tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.database.session import utcnow

ALGORITHM = "HS256"
ISSUER = "iguard"


def create_access_token(
    user_id: uuid.UUID, session_id: uuid.UUID, roles: list[str]
) -> tuple[str, int]:
    settings = get_settings()
    now = utcnow()
    ttl = settings.access_token_ttl_seconds
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "roles": roles,
        "iss": ISSUER,
        "typ": "access",
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=ALGORITHM), ttl


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            get_settings().secret_key.get_secret_value(),
            algorithms=[ALGORITHM],  # explicit allowlist: never trust the header's alg
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "sid", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid access token", code="invalid_token") from exc
    if payload.get("typ") != "access":
        raise UnauthorizedError("Invalid token type", code="invalid_token")
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Return (plaintext, sha256-hex). Only the hash is persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)


def expires_at(seconds: int) -> datetime:
    return utcnow() + timedelta(seconds=seconds)
