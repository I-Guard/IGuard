"""FastAPI dependencies: authentication and role-based access control."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, UnauthorizedError
from app.database.session import get_db, utcnow
from app.models import AuthSession, User
from app.models.enums import ROLE_RANK, RoleName
from app.security.tokens import decode_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user: User
    session_id: uuid.UUID

    @property
    def highest_role(self) -> RoleName:
        names = [RoleName(r) for r in self.user.role_names if r in RoleName.__members__]
        return max(names, key=lambda r: ROLE_RANK[r]) if names else RoleName.VIEWER

    def has_role(self, minimum: RoleName) -> bool:
        return ROLE_RANK[self.highest_role] >= ROLE_RANK[minimum]


def get_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise UnauthorizedError("Authentication required", code="not_authenticated")
    payload = decode_access_token(creds.credentials)
    try:
        sid = uuid.UUID(payload["sid"])
        uid = uuid.UUID(payload["sub"])
    except ValueError as exc:
        raise UnauthorizedError("Invalid access token", code="invalid_token") from exc
    session = db.get(AuthSession, sid)
    now = utcnow()
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= now
        or session.user_id != uid
    ):
        raise UnauthorizedError("Session is no longer valid", code="session_revoked")
    user = session.user
    if not user.is_active:
        raise UnauthorizedError("Account disabled", code="account_disabled")
    request.state.principal = Principal(user=user, session_id=sid)
    return request.state.principal


def require_role(minimum: RoleName) -> Callable[..., Principal]:
    """Dependency factory enforcing a minimum role (VIEWER < OPERATOR < ADMIN)."""

    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.has_role(minimum):
            raise ForbiddenError(
                f"Requires role {minimum.value} or higher", code="insufficient_role"
            )
        return principal

    return _dep


require_viewer = require_role(RoleName.VIEWER)
require_operator = require_role(RoleName.OPERATOR)
require_admin = require_role(RoleName.ADMIN)
