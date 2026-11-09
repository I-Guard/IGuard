"""Loki query client with LogQL-injection-safe query construction."""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamUnavailable, ValidationFailed
from app.core.logging import redact_text

_LABEL_VALUE = re.compile(r"^[A-Za-z0-9_.\-:/ ]{1,128}$")
ALLOWED_LABELS = ("service", "container", "job", "level", "environment", "compose_service")
LEVELS = {
    "debug",
    "info",
    "warning",
    "error",
    "critical",
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
}


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def build_query(labels: dict[str, str | None], text: str | None = None, regex: bool = False) -> str:
    matchers: list[str] = []
    for key, val in labels.items():
        if not val:
            continue
        if key not in ALLOWED_LABELS:
            raise ValidationFailed(f"Unsupported log label '{key}'")
        if not _LABEL_VALUE.match(val):
            raise ValidationFailed(f"Invalid value for label '{key}'")
        matchers.append(f"{key}={_quote(val)}")
    if not matchers:
        matchers.append('job=~".+"')  # Loki requires at least one non-empty matcher
    query = "{" + ",".join(matchers) + "}"
    if text:
        if len(text) > 200:
            raise ValidationFailed("Search text too long (max 200 chars)")
        if regex:
            try:
                re.compile(text)
            except re.error as exc:
                raise ValidationFailed("Invalid regular expression") from exc
            query += f" |~ {_quote(text)}"
        else:
            query += f" |= {_quote(text)}"
    return query


class LokiClient:
    def __init__(
        self, base_url: str | None = None, transport: httpx.BaseTransport | None = None
    ) -> None:
        s = get_settings()
        self._client = httpx.Client(
            base_url=(base_url or s.loki_url).rstrip("/"),
            timeout=s.integration_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def query_range(
        self,
        query: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
        direction: str = "backward",
    ) -> list[dict[str, Any]]:
        end_dt = end or datetime.now(UTC)
        start_dt = start or datetime.fromtimestamp(end_dt.timestamp() - 3600, UTC)
        params: dict[str, str | int] = {
            "query": query,
            "start": int(start_dt.timestamp() * 1e9),
            "end": int(end_dt.timestamp() * 1e9),
            "limit": limit,
            "direction": direction,
        }
        try:
            resp = self._client.get("/loki/api/v1/query_range", params=params)
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamUnavailable("Loki is unavailable", details=type(exc).__name__) from exc
        entries: list[dict[str, Any]] = []
        for stream in body.get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            for ts, line in stream.get("values", []):
                entries.append(_entry(ts, line, labels))
        entries.sort(key=lambda e: e["timestamp"], reverse=(direction == "backward"))
        return entries[:limit]

    def is_available(self) -> bool:
        try:
            return self._client.get("/ready").status_code == 200
        except httpx.HTTPError:
            return False


def _entry(ts: str, line: str, labels: dict[str, str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    try:
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            fields = parsed
    except ValueError:
        pass
    when = datetime.fromtimestamp(int(ts) / 1e9, UTC)
    # Defence in depth: redact again on the read path.
    return {"timestamp": when, "line": redact_text(line), "labels": labels, "fields": _safe(fields)}


def _safe(fields: dict[str, Any]) -> dict[str, Any]:
    from app.core.logging import redact

    return redact(fields)


def now_ns() -> int:
    return int(time.time() * 1e9)
