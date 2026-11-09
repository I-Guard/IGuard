"""Request id / correlation id propagation, access logging and secure headers."""

from __future__ import annotations

import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import correlation_id_var, get_logger, request_id_var

log = get_logger("iguard.access")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def _incoming_id(value: str | None) -> str:
    # Only accept well-formed ids so log injection via headers is impossible.
    return value if value and _SAFE_ID.match(value) else uuid.uuid4().hex


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    # API only serves JSON; Swagger/ReDoc pages get a relaxed policy in main.py.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, hsts: bool = False) -> None:
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = _incoming_id(request.headers.get("x-request-id"))
        cid = (
            _incoming_id(request.headers.get("x-correlation-id"))
            if request.headers.get("x-correlation-id")
            else rid
        )
        t_rid = request_id_var.set(rid)
        t_cid = correlation_id_var.set(cid)
        request.state.request_id = rid
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "client_ip": client_ip(request),
                },
            )
            request_id_var.reset(t_rid)
            correlation_id_var.reset(t_cid)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Correlation-ID"] = cid
        is_docs = request.url.path in ("/docs", "/redoc")
        for k, v in SECURITY_HEADERS.items():
            if is_docs and k == "Content-Security-Policy":
                continue
            response.headers.setdefault(k, v)
        if self.hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def client_ip(request: Request) -> str:
    # Behind our nginx proxy the first X-Forwarded-For hop is the client.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"
