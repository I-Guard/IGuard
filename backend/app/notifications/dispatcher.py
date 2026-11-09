"""Notification outbox: rows are written in the caller's transaction and delivered by a worker
with retry/backoff, so a slow or failing Telegram never blocks incident handling."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import utcnow
from app.models import AlertConfiguration, Incident, Notification
from app.models.enums import (
    SEVERITY_RANK,
    NotificationEvent,
    NotificationStatus,
    Severity,
)
from app.notifications.telegram import SendResult, TelegramClient, esc

log = get_logger(__name__)

CHANNEL = "TELEGRAM"
DEFAULT_EVENTS = [
    NotificationEvent.INCIDENT_CRITICAL.value,
    NotificationEvent.INCIDENT_WARNING.value,
    NotificationEvent.INCIDENT_ESCALATED.value,
    NotificationEvent.RECOVERY_STARTED.value,
    NotificationEvent.RECOVERY_SUCCEEDED.value,
    NotificationEvent.RECOVERY_FAILED.value,
    NotificationEvent.INCIDENT_RESOLVED.value,
]
_ICONS = {
    NotificationEvent.INCIDENT_CRITICAL: "🔴",
    NotificationEvent.INCIDENT_WARNING: "🟠",
    NotificationEvent.INCIDENT_ESCALATED: "🚨",
    NotificationEvent.RECOVERY_STARTED: "🛠",
    NotificationEvent.RECOVERY_SUCCEEDED: "✅",
    NotificationEvent.RECOVERY_FAILED: "❌",
    NotificationEvent.INCIDENT_RESOLVED: "🟢",
    NotificationEvent.TEST: "🔔",
}


def get_or_create_config(db: Session) -> AlertConfiguration:
    cfg = db.scalar(select(AlertConfiguration).where(AlertConfiguration.channel == CHANNEL))
    if cfg is None:
        cfg = AlertConfiguration(
            channel=CHANNEL,
            enabled=True,
            min_severity=Severity.WARNING,
            notify_events=list(DEFAULT_EVENTS),
            cooldown_seconds=300,
        )
        db.add(cfg)
        db.flush()
    return cfg


def format_message(
    event: NotificationEvent,
    *,
    title: str,
    incident: Incident | None = None,
    description: str | None = None,
    recovery_result: str | None = None,
) -> str:
    lines = [
        f"{_ICONS.get(event, '•')} <b>{esc(event.value.replace('_', ' ').title())}</b>",
        f"<b>{esc(title)}</b>",
    ]
    if incident is not None:
        lines += [
            f"Incident: <code>{incident.id}</code>",
            f"Severity: {esc(incident.severity.value)}",
            f"Service: {esc(incident.service.name if incident.service else '-')}",
            f"Server: {esc(incident.server.name if incident.server else '-')}",
            f"Status: {esc(incident.status.value)}",
        ]
    desc = description if description is not None else (incident.description if incident else "")
    if desc:
        lines.append(f"Description: {esc(desc[:600])}")
    if recovery_result:
        lines.append(f"Recovery result: {esc(recovery_result[:400])}")
    lines.append(f"Time: {utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    return "\n".join(lines)


def enqueue(
    db: Session,
    event: NotificationEvent,
    *,
    title: str,
    incident: Incident | None = None,
    severity: Severity | None = None,
    description: str | None = None,
    recovery_result: str | None = None,
) -> Notification | None:
    """Queue a notification honoring alert configuration (severity floor, event filter, cooldown)."""
    cfg = get_or_create_config(db)
    sev = severity or (incident.severity if incident else Severity.INFO)
    if (
        incident is not None
        and incident.is_flapping
        and event != NotificationEvent.INCIDENT_RESOLVED
    ):
        return None  # flapping incidents are suppressed to avoid alert storms
    if not cfg.enabled or event.value not in (cfg.notify_events or []):
        return None
    if event != NotificationEvent.TEST and SEVERITY_RANK[sev] < SEVERITY_RANK[cfg.min_severity]:
        return None
    if (
        incident is not None
        and cfg.cooldown_seconds > 0
        and event
        in (
            NotificationEvent.INCIDENT_CRITICAL,
            NotificationEvent.INCIDENT_WARNING,
            NotificationEvent.INCIDENT_ESCALATED,
        )
    ):
        since = utcnow() - timedelta(seconds=cfg.cooldown_seconds)
        dup = db.scalar(
            select(Notification.id)
            .where(
                Notification.incident_id == incident.id,
                Notification.event_type == event.value,
                Notification.created_at >= since,
            )
            .limit(1)
        )
        if dup is not None:
            return None
    body = format_message(
        event,
        title=title,
        incident=incident,
        description=description,
        recovery_result=recovery_result,
    )
    n = Notification(
        channel=CHANNEL,
        event_type=event.value,
        incident_id=incident.id if incident else None,
        severity=sev.value,
        title=title[:255],
        body=body,
        status=NotificationStatus.PENDING,
        next_attempt_at=utcnow(),
    )
    db.add(n)
    db.flush()
    return n


def _apply(n: Notification, result: SendResult, max_attempts: int) -> None:
    n.attempts += 1
    now = utcnow()
    if result.ok:
        n.status = NotificationStatus.SENT
        n.sent_at = now
        n.last_error = None
        n.next_attempt_at = None
        return
    n.last_error = (result.error or "unknown error")[:1000]
    if not result.retryable or n.attempts >= max_attempts:
        n.status = NotificationStatus.FAILED
        n.next_attempt_at = None
    else:
        delay = result.retry_after if result.retry_after else min(2**n.attempts, 60)
        n.next_attempt_at = now + timedelta(seconds=delay)


def deliver_pending(db: Session, client: TelegramClient | None = None, limit: int = 20) -> int:
    """Send queued notifications. Returns the number processed."""
    settings = get_settings()
    client = client or TelegramClient()
    now = utcnow()
    rows = list(
        db.scalars(
            select(Notification)
            .where(
                Notification.status == NotificationStatus.PENDING,
                (Notification.next_attempt_at.is_(None)) | (Notification.next_attempt_at <= now),
            )
            .order_by(Notification.created_at)
            .limit(limit)
        )
    )
    max_attempts = settings.telegram_max_retries + 1
    for n in rows:
        if not client.configured:
            n.status = NotificationStatus.SKIPPED
            n.last_error = "Telegram is not configured (set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)"
            continue
        _apply(n, client.send(n.body), max_attempts)
        if n.status == NotificationStatus.FAILED:
            log.warning(
                "notification delivery failed",
                extra={"notification_id": str(n.id), "error": n.last_error},
            )
    db.flush()
    return len(rows)


def send_test(db: Session, message: str, client: TelegramClient | None = None) -> dict[str, Any]:
    """Synchronous test message used by POST /alerts/test (immediate operator feedback)."""
    client = client or TelegramClient()
    n = Notification(
        channel=CHANNEL,
        event_type=NotificationEvent.TEST.value,
        severity=Severity.INFO.value,
        title="Test notification",
        body=format_message(NotificationEvent.TEST, title="Test notification", description=message),
        status=NotificationStatus.PENDING,
        attempts=0,
    )
    db.add(n)
    if not client.configured:
        n.status = NotificationStatus.SKIPPED
        n.last_error = "Telegram is not configured (set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)"
    else:
        _apply(n, client.send(n.body), max_attempts=1)
    db.flush()
    return {"notification_id": n.id, "status": n.status.value, "error": n.last_error}
