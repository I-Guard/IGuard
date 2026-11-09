"""Authentication: login with lockout + rate limiting, session & refresh-token rotation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ForbiddenError, RateLimitedError, UnauthorizedError
from app.database.session import utcnow
from app.models import AuthSession, RefreshToken, Role, User
from app.models.enums import RoleName
from app.security import tokens
from app.security.passwords import (
    hash_password,
    needs_rehash,
    validate_password_policy,
    verify_password,
)
from app.security.rate_limit import SlidingWindowLimiter
from app.services import audit

_limiter: SlidingWindowLimiter | None = None


def login_limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        s = get_settings()
        _limiter = SlidingWindowLimiter(
            s.login_rate_limit_attempts, s.login_rate_limit_window_seconds
        )
    return _limiter


def reset_limiter() -> None:
    global _limiter
    _limiter = None


@dataclass
class IssuedSession:
    user: User
    access_token: str
    expires_in: int
    refresh_token: str
    csrf_token: str


def get_role(db: Session, name: RoleName) -> Role:
    role = db.scalar(select(Role).where(Role.name == name.value))
    if role is None:
        role = Role(name=name.value, description=f"{name.value} role")
        db.add(role)
        db.flush()
    return role


def create_user(
    db: Session,
    *,
    email: str,
    username: str,
    password: str,
    role: RoleName,
    full_name: str = "",
    must_change_password: bool = False,
    enforce_policy: bool = True,
) -> User:
    if enforce_policy:
        validate_password_policy(password)
    user = User(
        email=email.lower(),
        username=username,
        full_name=full_name,
        password_hash=hash_password(password),
        must_change_password=must_change_password,
    )
    user.roles = [get_role(db, role)]
    db.add(user)
    db.flush()
    return user


def _find_user(db: Session, identifier: str) -> User | None:
    ident = identifier.strip()
    return db.scalar(select(User).where(or_(User.email == ident.lower(), User.username == ident)))


def _issue(db: Session, user: User, ip: str | None, ua: str | None) -> IssuedSession:
    s = get_settings()
    session = AuthSession(
        user_id=user.id,
        expires_at=tokens.expires_at(s.refresh_token_ttl_seconds),
        ip_address=ip,
        user_agent=(ua or "")[:255] or None,
    )
    db.add(session)
    db.flush()
    return _rotate_in(db, user, session)


def _rotate_in(db: Session, user: User, session: AuthSession) -> IssuedSession:
    s = get_settings()
    raw, digest = tokens.new_refresh_token()
    db.add(
        RefreshToken(
            session_id=session.id,
            token_hash=digest,
            expires_at=min(session.expires_at, tokens.expires_at(s.refresh_token_ttl_seconds)),
        )
    )
    access, ttl = tokens.create_access_token(user.id, session.id, user.role_names)
    db.flush()
    return IssuedSession(user, access, ttl, raw, tokens.new_csrf_token())


def login(db: Session, identifier: str, password: str, ip: str, ua: str | None) -> IssuedSession:
    s = get_settings()
    limiter = login_limiter()
    key = f"{ip}|{identifier.strip().lower()}"
    if limiter.is_limited(key) or limiter.is_limited(f"ip|{ip}"):
        audit.record(
            db,
            action="auth.login",
            resource_type="user",
            actor_name=identifier[:64],
            outcome="RATE_LIMITED",
            ip=ip,
        )
        db.commit()  # persist the audit record even though we raise
        raise RateLimitedError("Too many login attempts. Try again later.")

    user = _find_user(db, identifier)
    now = utcnow()
    if user and user.locked_until and user.locked_until > now:
        audit.record(
            db,
            action="auth.login",
            resource_type="user",
            resource_id=user.id,
            actor=user,
            outcome="LOCKED",
            ip=ip,
        )
        db.commit()
        raise UnauthorizedError("Invalid credentials", code="invalid_credentials")

    ok = verify_password(password, user.password_hash if user else None)
    if not ok or user is None:
        limiter.record(key)
        limiter.record(f"ip|{ip}")
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= s.account_lockout_threshold:
                user.locked_until = now + timedelta(seconds=s.account_lockout_seconds)
                user.failed_login_attempts = 0
        audit.record(
            db,
            action="auth.login",
            resource_type="user",
            resource_id=user.id if user else None,
            actor=user,
            actor_name=None if user else identifier[:64],
            outcome="FAILURE",
            ip=ip,
        )
        db.commit()
        # Identical response for unknown user / wrong password / disabled: no user enumeration.
        raise UnauthorizedError("Invalid credentials", code="invalid_credentials")
    if not user.is_active:
        audit.record(
            db,
            action="auth.login",
            resource_type="user",
            resource_id=user.id,
            actor=user,
            outcome="DISABLED",
            ip=ip,
        )
        db.commit()
        raise UnauthorizedError("Invalid credentials", code="invalid_credentials")

    limiter.reset(key)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    issued = _issue(db, user, ip, ua)
    audit.record(
        db, action="auth.login", resource_type="user", resource_id=user.id, actor=user, ip=ip
    )
    return issued


def refresh(db: Session, raw_token: str, ip: str | None) -> IssuedSession:
    now = utcnow()
    row = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == tokens.hash_token(raw_token))
    )
    if row is None:
        raise UnauthorizedError("Invalid refresh token", code="invalid_refresh_token")
    session = db.get(AuthSession, row.session_id)
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise UnauthorizedError("Session expired", code="session_expired")
    if row.used_at is not None:
        # Reuse of a rotated token => likely theft: revoke the whole session family.
        session.revoked_at = now
        audit.record(
            db,
            action="auth.refresh_reuse",
            resource_type="session",
            resource_id=session.id,
            actor=session.user,
            outcome="REVOKED",
            ip=ip,
        )
        db.commit()
        raise UnauthorizedError(
            "Refresh token reuse detected; session revoked", code="refresh_token_reuse"
        )
    if row.expires_at <= now or not session.user.is_active:
        raise UnauthorizedError("Session expired", code="session_expired")
    row.used_at = now
    return _rotate_in(db, session.user, session)


def logout(db: Session, session_id: uuid.UUID, user: User, ip: str | None) -> None:
    session = db.get(AuthSession, session_id)
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()
    audit.record(
        db, action="auth.logout", resource_type="session", resource_id=session_id, actor=user, ip=ip
    )


def revoke_all_sessions(
    db: Session, user_id: uuid.UUID, except_session: uuid.UUID | None = None
) -> None:
    now = utcnow()
    for sess in db.scalars(
        select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    ):
        if sess.id != except_session:
            sess.revoked_at = now


def change_password(
    db: Session, user: User, current: str, new: str, session_id: uuid.UUID, ip: str | None
) -> None:
    if not verify_password(current, user.password_hash):
        audit.record(
            db,
            action="auth.change_password",
            resource_type="user",
            resource_id=user.id,
            actor=user,
            outcome="FAILURE",
            ip=ip,
        )
        db.commit()
        raise ForbiddenError("Current password is incorrect", code="wrong_password")
    if current == new:
        from app.core.errors import ValidationFailed

        raise ValidationFailed("New password must differ from the current password")
    validate_password_policy(new)
    user.password_hash = hash_password(new)
    user.must_change_password = False
    revoke_all_sessions(db, user.id, except_session=session_id)
    audit.record(
        db,
        action="auth.change_password",
        resource_type="user",
        resource_id=user.id,
        actor=user,
        ip=ip,
    )


def bootstrap_admin(db: Session) -> bool:
    """Create the first admin from env vars if (and only if) there are no users."""
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return False
    if db.scalar(select(User.id).limit(1)) is not None:
        return False
    email = s.bootstrap_admin_email.lower()
    create_user(
        db,
        email=email,
        username=email.split("@")[0][:64] or "admin",
        password=s.bootstrap_admin_password.get_secret_value(),
        role=RoleName.ADMIN,
        full_name="Administrator",
    )
    audit.record(db, action="user.bootstrap_admin", resource_type="user", actor_name="system")
    return True
