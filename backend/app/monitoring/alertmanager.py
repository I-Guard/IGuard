"""Alertmanager API client (read active alerts)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamUnavailable


class AlertmanagerClient:
    def __init__(
        self, base_url: str | None = None, transport: httpx.BaseTransport | None = None
    ) -> None:
        s = get_settings()
        self._client = httpx.Client(
            base_url=(base_url or s.alertmanager_url).rstrip("/"),
            timeout=s.integration_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def active_alerts(self) -> list[dict[str, Any]]:
        try:
            resp = self._client.get(
                "/api/v2/alerts", params={"active": "true", "silenced": "false"}
            )
            resp.raise_for_status()
            raw = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamUnavailable(
                "Alertmanager is unavailable", details=type(exc).__name__
            ) from exc
        out = []
        for a in raw:
            labels = a.get("labels", {})
            ann = a.get("annotations", {})
            starts = a.get("startsAt")
            out.append(
                {
                    "name": labels.get("alertname", "unknown"),
                    "severity": labels.get("severity"),
                    "state": a.get("status", {}).get("state", "active"),
                    "summary": ann.get("summary") or ann.get("description") or "",
                    "started_at": datetime.fromisoformat(starts.replace("Z", "+00:00"))
                    if starts
                    else None,
                    "labels": {k: str(v) for k, v in labels.items()},
                }
            )
        return out
