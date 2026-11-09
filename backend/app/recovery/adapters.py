"""Recovery adapters: the permission boundary between IGuard and the host.

IGuard's backend never talks to Docker. It calls an adapter:

* ``AgentAdapter`` - HMAC-signed HTTP request to the *recovery agent*, a separate minimal process
  that holds its own allowlist and reaches Docker only through a restricted socket proxy.
* ``SimulatedAdapter`` - performs no host changes; used for tests and demos without Docker.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.models.enums import ActionType


@dataclass
class AdapterResult:
    ok: bool
    output: str = ""
    error: str | None = None
    simulated: bool = False


class RecoveryAdapter(Protocol):
    name: str

    def execute(
        self,
        action_type: ActionType,
        target: str,
        *,
        dry_run: bool,
        timeout: float,
        request_id: str,
    ) -> AdapterResult: ...


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


class AgentAdapter:
    name = "agent"

    def __init__(
        self,
        url: str | None = None,
        secret: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        s = get_settings()
        self.url = (url or s.recovery_agent_url).rstrip("/")
        self.secret = secret if secret is not None else s.recovery_agent_secret.get_secret_value()
        self._transport = transport

    def execute(
        self,
        action_type: ActionType,
        target: str,
        *,
        dry_run: bool,
        timeout: float,
        request_id: str,
    ) -> AdapterResult:
        body = json.dumps(
            {
                "action_type": action_type.value,
                "target": target,
                "dry_run": dry_run,
                "timeout": timeout,
                "request_id": request_id,
                "nonce": uuid.uuid4().hex,
            },
            separators=(",", ":"),
        ).encode()
        ts = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-IGuard-Timestamp": ts,
            "X-IGuard-Signature": sign(self.secret, ts, body),
        }
        try:
            with httpx.Client(timeout=timeout + 5, transport=self._transport) as c:
                resp = c.post(f"{self.url}/v1/execute", content=body, headers=headers)
        except httpx.HTTPError as exc:
            return AdapterResult(False, error=f"Recovery agent unreachable: {type(exc).__name__}")
        try:
            data = resp.json()
        except ValueError:
            return AdapterResult(False, error=f"Recovery agent returned HTTP {resp.status_code}")
        if resp.status_code != 200:
            return AdapterResult(
                False,
                output=str(data.get("output", "")),
                error=str(data.get("error") or f"agent HTTP {resp.status_code}"),
            )
        return AdapterResult(
            bool(data.get("ok")),
            str(data.get("output", ""))[:4000],
            data.get("error"),
            simulated=False,
        )


class SimulatedAdapter:
    """No-op adapter. Optionally 'heals' synthetic demo services via an explicit URL map."""

    name = "simulated"

    def __init__(
        self, heal_map: dict[str, str] | None = None, transport: httpx.BaseTransport | None = None
    ) -> None:
        if heal_map is None:
            heal_map = parse_heal_map(get_settings().recovery_simulated_heal_map)
        self.heal_map = heal_map
        self._transport = transport

    def execute(
        self,
        action_type: ActionType,
        target: str,
        *,
        dry_run: bool,
        timeout: float,
        request_id: str,
    ) -> AdapterResult:
        if dry_run:
            return AdapterResult(
                True,
                f"[SIMULATED DRY-RUN] would run {action_type.value} on '{target}'",
                simulated=True,
            )
        out = f"[SIMULATED] {action_type.value} on '{target}' (no host changes were made)"
        url = self.heal_map.get(target)
        if url and action_type in (ActionType.CONTAINER_RESTART, ActionType.SERVICE_RESTART):
            try:
                with httpx.Client(timeout=5, transport=self._transport) as c:
                    c.post(url)
                out += f"; synthetic service healed via {url}"
            except httpx.HTTPError as exc:
                return AdapterResult(
                    False, out, f"heal hook failed: {type(exc).__name__}", simulated=True
                )
        return AdapterResult(True, out, simulated=True)


def parse_heal_map(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in filter(None, (p.strip() for p in raw.split(","))):
        if "=" in part:
            k, v = part.split("=", 1)
            if v.startswith(("http://", "https://")):
                out[k.strip()] = v.strip()
    return out


def get_adapter() -> RecoveryAdapter:
    s = get_settings()
    return AgentAdapter() if s.recovery_adapter == "agent" else SimulatedAdapter()
