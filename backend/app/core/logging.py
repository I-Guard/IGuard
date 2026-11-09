"""Structured JSON logging with request/correlation ids and secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

REDACTED = "***REDACTED***"
_SENSITIVE_KEYS = re.compile(
    r"(pass(word)?|secret|token|authorization|api[_-]?key|cookie|csrf|credential|bot_token)",
    re.IGNORECASE,
)
# Redact "Bearer xxx", "password=xxx", "token: xxx" inside free text and bot tokens in URLs.
_TEXT_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1" + REDACTED),
    (
        re.compile(r"(?i)((?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*)[^\s,;&\"']+"),
        r"\1" + REDACTED,
    ),
    (re.compile(r"/bot\d+:[A-Za-z0-9_-]+/"), "/bot" + REDACTED + "/"),
]


def redact_text(text: str) -> str:
    for pattern, repl in _TEXT_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively redact sensitive keys/values from dicts, lists and strings."""
    if _depth > 8:
        return REDACTED
    if isinstance(value, dict):
        return {
            k: (REDACTED if _SENSITIVE_KEYS.search(str(k)) else redact(v, _depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v, _depth + 1) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "service": self.service,
            "environment": self.environment,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "correlation_id": correlation_id_var.get(),
            "message": redact_text(record.getMessage()),
        }
        for key, val in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = redact({key: val})[key]
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str, service: str, environment: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service, environment))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Uvicorn access logs are replaced by our request middleware logs.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
