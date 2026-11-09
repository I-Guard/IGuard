from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import Principal, client_ip, require_viewer
from app.core.config import get_settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.database.session import get_db
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserOut,
)
from app.schemas.common import Message
from app.security.tokens import csrf_matches
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["authentication"])

REFRESH_COOKIE = "iguard_refresh"
CSRF_COOKIE = "iguard_csrf"


def _set_cookies(response: Response, issued: auth_service.IssuedSession) -> None:
    s = get_settings()
    secure, samesite, path = s.cookie_secure, s.cookie_samesite, "/api/v1/auth"
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        httponly=True,
        max_age=s.refresh_token_ttl_seconds,
        secure=secure,
        samesite=samesite,
        path=path,
    )
    # Readable by JS on purpose: double-submit CSRF token for cookie-authenticated endpoints.
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        httponly=False,
        max_age=s.refresh_token_ttl_seconds,
        secure=secure,
        samesite=samesite,
        path=path,
    )


def _clear_cookies(response: Response) -> None:
    for name in (REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/api/v1/auth")


def _token_response(issued: auth_service.IssuedSession) -> TokenResponse:
    return TokenResponse(
        access_token=issued.access_token,
        expires_in=issued.expires_in,
        csrf_token=issued.csrf_token,
        user=UserOut.model_validate(issued.user),
    )


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> TokenResponse:
    issued = auth_service.login(
        db, body.identifier, body.password, client_ip(request), request.headers.get("user-agent")
    )
    _set_cookies(response, issued)
    return _token_response(issued)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    db: Session = Depends(get_db),
) -> TokenResponse:
    cookie = request.cookies.get(REFRESH_COOKIE)
    raw = cookie
    if cookie:
        # Cookie-authenticated => CSRF double-submit check is mandatory.
        if not csrf_matches(request.cookies.get(CSRF_COOKIE), request.headers.get("x-csrf-token")):
            raise ForbiddenError("CSRF token missing or invalid", code="csrf_failed")
    elif body and body.refresh_token:
        raw = body.refresh_token
    if not raw:
        raise UnauthorizedError("Refresh token required", code="invalid_refresh_token")
    try:
        issued = auth_service.refresh(db, raw, client_ip(request))
    except UnauthorizedError:
        _clear_cookies(response)
        raise
    _set_cookies(response, issued)
    return _token_response(issued)


@router.post("/logout", response_model=Message)
def logout(
    request: Request,
    response: Response,
    principal: Principal = Depends(require_viewer),
    db: Session = Depends(get_db),
) -> Message:
    auth_service.logout(db, principal.session_id, principal.user, client_ip(request))
    _clear_cookies(response)
    return Message(message="Logged out")


@router.get("/me", response_model=UserOut)
def me(principal: Principal = Depends(require_viewer)) -> UserOut:
    return UserOut.model_validate(principal.user)


@router.post("/change-password", response_model=Message)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    principal: Principal = Depends(require_viewer),
    db: Session = Depends(get_db),
) -> Message:
    auth_service.change_password(
        db,
        principal.user,
        body.current_password,
        body.new_password,
        principal.session_id,
        client_ip(request),
    )
    return Message(message="Password changed. Other sessions were signed out.")
