"""Shared API dependencies."""

from __future__ import annotations

from fastapi import Request

from app.integrations import Integrations
from app.middleware.request_context import client_ip as _client_ip
from app.security.deps import Principal, require_admin, require_operator, require_viewer

__all__ = [
    "Principal",
    "client_ip",
    "get_integrations",
    "require_admin",
    "require_operator",
    "require_viewer",
]


def get_integrations(request: Request) -> Integrations:
    return request.app.state.integrations


def client_ip(request: Request) -> str:
    return _client_ip(request)
