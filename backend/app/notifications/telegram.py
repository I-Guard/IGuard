"""Telegram Bot API client. The bot token never appears in logs or errors."""

from __future__ import annotations

import html
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.core.logging import redact_text


@dataclass
class SendResult:
    ok: bool
    error: str | None = None
    retry_after: float | None = None  # seconds, when Telegram rate-limits us
    retryable: bool = True


class TelegramClient:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = get_settings()
        self._transport = transport

    @property
    def configured(self) -> bool:
        return self.settings.telegram_configured

    def send(self, text: str) -> SendResult:
        s = self.settings
        if not self.configured:
            return SendResult(False, "Telegram is not configured", retryable=False)
        url = f"{s.telegram_api_base.rstrip('/')}/bot{s.telegram_bot_token.get_secret_value()}/sendMessage"
        payload = {
            "chat_id": s.telegram_chat_id,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            with httpx.Client(
                timeout=s.integration_timeout_seconds, transport=self._transport
            ) as c:
                resp = c.post(url, json=payload)
        except httpx.HTTPError as exc:
            # str(exc) can contain the request URL (and so the token) - sanitise.
            return SendResult(False, redact_text(f"{type(exc).__name__}: {exc}"))
        if resp.status_code == 200 and resp.json().get("ok"):
            return SendResult(True)
        retry_after = None
        description = ""
        try:
            body = resp.json()
            description = str(body.get("description", ""))
            retry_after = body.get("parameters", {}).get("retry_after")
        except ValueError:
            pass
        retryable = resp.status_code == 429 or resp.status_code >= 500
        return SendResult(
            False,
            redact_text(f"HTTP {resp.status_code}: {description}"),
            retry_after=float(retry_after) if retry_after else None,
            retryable=retryable,
        )


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else "-"), quote=False)
