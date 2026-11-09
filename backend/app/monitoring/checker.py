"""Synthetic/real service health checks (HTTP, HTTPS, TCP) with an SSRF guard."""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.models import Service
from app.models.enums import CheckType

_ALWAYS_BLOCKED_NETS = [
    ipaddress.ip_network("169.254.0.0/16"),  # link-local incl. cloud metadata 169.254.169.254
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),
]
_ALWAYS_BLOCKED_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}


@dataclass
class CheckOutcome:
    success: bool
    status_code: int | None
    response_time_ms: float | None
    error: str | None


def validate_target(host: str) -> None:
    """Reject hosts that must never be probed (SSRF defence). Private ranges stay allowed
    because monitoring internal services is the purpose of the tool."""
    h = host.strip().lower().strip("[]")
    if not h:
        raise ValidationFailed("Empty host")
    if h in _ALWAYS_BLOCKED_HOSTS or h in get_settings().blocked_host_list:
        raise ValidationFailed(f"Host '{host}' is not allowed as a check target")
    try:
        ip = ipaddress.ip_address(h)
        if any(ip in net for net in _ALWAYS_BLOCKED_NETS):
            raise ValidationFailed(f"Address '{host}' is not allowed as a check target")
    except ValueError:
        pass  # hostname, not a literal IP


def validate_service_target(service: Service) -> None:
    if service.check_type in (CheckType.HTTP, CheckType.HTTPS):
        parts = urlsplit(service.url or "")
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValidationFailed("Invalid service URL")
        if parts.username or parts.password:
            raise ValidationFailed("Credentials in URLs are not allowed")
        validate_target(parts.hostname)
    else:
        validate_target(service.host or "")


def _resolve_guard(host: str) -> None:
    """Resolve at check time and block rebinding to metadata addresses."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return  # let the actual request fail with a clear DNS error
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any(ip in net for net in _ALWAYS_BLOCKED_NETS):
            raise ValidationFailed("Target resolves to a blocked address")


def run_check(service: Service, transport: httpx.BaseTransport | None = None) -> CheckOutcome:
    timeout = float(service.timeout_seconds)
    start = time.perf_counter()
    try:
        validate_service_target(service)
        if service.check_type in (CheckType.HTTP, CheckType.HTTPS):
            host = urlsplit(service.url or "").hostname or ""
            if transport is None:
                _resolve_guard(host)
            with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as c:
                resp = c.get(service.url or "", headers={"User-Agent": "IGuard-Monitor/1.0"})
            elapsed = (time.perf_counter() - start) * 1000
            expected = set(service.expected_status_codes or [200])
            ok = resp.status_code in expected
            return CheckOutcome(
                ok,
                resp.status_code,
                elapsed,
                None if ok else f"Unexpected status {resp.status_code}",
            )
        host = service.host or ""
        if transport is None:
            _resolve_guard(host)
        with socket.create_connection((host, int(service.port or 0)), timeout=timeout):
            pass
        return CheckOutcome(True, None, (time.perf_counter() - start) * 1000, None)
    except ValidationFailed as exc:
        return CheckOutcome(False, None, None, f"Blocked target: {exc.message}")
    except httpx.TimeoutException:
        return CheckOutcome(False, None, (time.perf_counter() - start) * 1000, "Request timed out")
    except httpx.HTTPError as exc:
        return CheckOutcome(False, None, None, f"{type(exc).__name__}: connection failed")
    except (TimeoutError, OSError) as exc:
        return CheckOutcome(False, None, None, f"{type(exc).__name__}: connection failed")
