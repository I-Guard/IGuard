import httpx
import pytest
from sqlalchemy import select

from app.core.config import reset_settings_cache
from app.models import Notification
from app.models.enums import NotificationEvent, NotificationStatus, Severity
from app.notifications import dispatcher
from app.notifications.telegram import TelegramClient

TOKEN = "123456:ABC-secretTokenValue"


@pytest.fixture
def tg_env(monkeypatch):
    monkeypatch.setenv("IGUARD_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("IGUARD_TELEGRAM_CHAT_ID", "-1001")
    reset_settings_cache()
    yield
    monkeypatch.delenv("IGUARD_TELEGRAM_BOT_TOKEN")
    monkeypatch.delenv("IGUARD_TELEGRAM_CHAT_ID")
    reset_settings_cache()


def client_for(handler):
    return TelegramClient(transport=httpx.MockTransport(handler))


def test_not_configured_is_skipped_and_system_continues(db):
    reset_settings_cache()
    n = dispatcher.enqueue(
        db, NotificationEvent.INCIDENT_CRITICAL, title="t", severity=Severity.CRITICAL
    )
    assert dispatcher.deliver_pending(db, TelegramClient()) == 1
    assert n.status == NotificationStatus.SKIPPED and "not configured" in n.last_error


def test_successful_delivery_payload(db, tg_env):
    seen = {}

    def handler(req):
        seen["url"], seen["json"] = str(req.url), req.read()
        return httpx.Response(200, json={"ok": True})

    n = dispatcher.enqueue(
        db,
        NotificationEvent.INCIDENT_CRITICAL,
        title="Game API down",
        severity=Severity.CRITICAL,
        description="boom <b>",
    )
    dispatcher.deliver_pending(db, client_for(handler))
    assert n.status == NotificationStatus.SENT and n.sent_at and n.attempts == 1
    assert seen["url"].endswith("/sendMessage") and b'"chat_id":"-1001"' in seen["json"].replace(
        b" ", b""
    )
    assert "&lt;b&gt;" in n.body  # HTML-escaped (no injection into Telegram markup)


def test_retry_with_backoff_then_success(db, tg_env):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

    n = dispatcher.enqueue(
        db, NotificationEvent.INCIDENT_CRITICAL, title="t", severity=Severity.CRITICAL
    )
    c = client_for(handler)
    dispatcher.deliver_pending(db, c)
    assert (
        n.status == NotificationStatus.PENDING and n.next_attempt_at is not None and n.attempts == 1
    )
    assert dispatcher.deliver_pending(db, c) == 0  # backoff: not due yet
    from datetime import timedelta

    from app.database.session import utcnow

    n.next_attempt_at = utcnow() - timedelta(seconds=1)
    db.flush()
    dispatcher.deliver_pending(db, c)
    n.next_attempt_at = utcnow() - timedelta(seconds=1)
    db.flush()
    dispatcher.deliver_pending(db, c)
    assert n.status == NotificationStatus.SENT and n.attempts == 3


def test_gives_up_after_max_retries(db, tg_env, monkeypatch):
    monkeypatch.setenv("IGUARD_TELEGRAM_MAX_RETRIES", "1")
    reset_settings_cache()
    n = dispatcher.enqueue(
        db, NotificationEvent.INCIDENT_CRITICAL, title="t", severity=Severity.CRITICAL
    )
    c = client_for(lambda r: httpx.Response(502))
    from datetime import timedelta

    from app.database.session import utcnow

    for _ in range(3):
        n.next_attempt_at = utcnow() - timedelta(seconds=1)
        db.flush()
        dispatcher.deliver_pending(db, c)
    assert n.status == NotificationStatus.FAILED and n.attempts == 2


def test_client_error_is_not_retried(db, tg_env):
    n = dispatcher.enqueue(
        db, NotificationEvent.INCIDENT_CRITICAL, title="t", severity=Severity.CRITICAL
    )
    dispatcher.deliver_pending(
        db,
        client_for(
            lambda r: httpx.Response(400, json={"ok": False, "description": "chat not found"})
        ),
    )
    assert (
        n.status == NotificationStatus.FAILED
        and "chat not found" in n.last_error
        and n.attempts == 1
    )


def test_rate_limit_honours_retry_after(db, tg_env):
    n = dispatcher.enqueue(
        db, NotificationEvent.INCIDENT_CRITICAL, title="t", severity=Severity.CRITICAL
    )
    dispatcher.deliver_pending(
        db,
        client_for(
            lambda r: httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 30}})
        ),
    )
    from app.database.session import utcnow

    assert (
        n.status == NotificationStatus.PENDING
        and (n.next_attempt_at - utcnow()).total_seconds() > 20
    )


def test_token_never_leaks_into_errors(db, tg_env):
    def handler(req):
        raise httpx.ConnectError(f"failed to reach {req.url}")

    n = dispatcher.enqueue(
        db, NotificationEvent.INCIDENT_CRITICAL, title="t", severity=Severity.CRITICAL
    )
    dispatcher.deliver_pending(db, client_for(handler))
    assert TOKEN not in (n.last_error or "") and "secretTokenValue" not in (n.last_error or "")


def test_severity_floor_and_event_filter(db):
    cfg = dispatcher.get_or_create_config(db)
    assert (
        dispatcher.enqueue(
            db, NotificationEvent.INCIDENT_WARNING, title="info only", severity=Severity.INFO
        )
        is None
    )
    cfg.min_severity = Severity.CRITICAL
    assert (
        dispatcher.enqueue(
            db, NotificationEvent.INCIDENT_WARNING, title="w", severity=Severity.WARNING
        )
        is None
    )
    cfg.min_severity = Severity.WARNING
    cfg.notify_events = ["INCIDENT_CRITICAL"]
    assert (
        dispatcher.enqueue(
            db, NotificationEvent.INCIDENT_WARNING, title="w", severity=Severity.WARNING
        )
        is None
    )
    cfg.enabled = False
    assert (
        dispatcher.enqueue(
            db, NotificationEvent.INCIDENT_CRITICAL, title="c", severity=Severity.CRITICAL
        )
        is None
    )


def test_message_contains_required_fields(db, env, seeded):
    from sqlalchemy import select as sel

    from app.incidents.engine import IncidentEngine, Signal
    from app.models import Service
    from app.models.enums import IncidentCategory
    from app.services import settings_service

    s = db.scalar(sel(Service).where(Service.name == "game-api"))
    inc = (
        IncidentEngine(db, settings_service.effective(db))
        .observe(
            Signal(
                rule="availability",
                category=IncidentCategory.SERVICE_DOWN,
                severity=Severity.CRITICAL,
                title="down",
                description="the api is down",
                server_id=s.server_id,
                service_id=s.id,
            )
        )
        .incident
    )
    n = db.scalar(select(Notification).where(Notification.incident_id == inc.id))
    for needle in (str(inc.id), "CRITICAL", "game-api", "demo-host", "the api is down", "UTC"):
        assert needle in n.body
    msg = dispatcher.format_message(
        NotificationEvent.RECOVERY_FAILED,
        title="x",
        incident=inc,
        recovery_result="verification failed",
    )
    assert "Recovery result" in msg and "verification failed" in msg
