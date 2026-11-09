"""Shared fixtures. The schema is built with the real Alembic migration (so migrations are tested).

Backend selection: IGUARD_TEST_DATABASE_URL (PostgreSQL) or a temporary SQLite file.
"""

from __future__ import annotations

import os
import secrets
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

_TMP = tempfile.mkdtemp(prefix="iguard-tests-")
TEST_DB_URL = os.environ.get("IGUARD_TEST_DATABASE_URL") or f"sqlite:///{_TMP}/test.db"
os.environ.update(
    {
        "IGUARD_ENV": "test",
        "IGUARD_DATABASE_URL": TEST_DB_URL,
        "IGUARD_SECRET_KEY": secrets.token_urlsafe(48),  # random per run; never a fixed value
        "IGUARD_WEBHOOK_TOKEN": "test-webhook-token-123456",
        "IGUARD_RECOVERY_POLICIES_DIR": str(
            Path(__file__).resolve().parents[2] / "recovery" / "policies"
        ),
        "IGUARD_RECOVERY_ADAPTER": "simulated",
        "IGUARD_TELEGRAM_BOT_TOKEN": "",
        "IGUARD_TELEGRAM_CHAT_ID": "",
        "IGUARD_LOGIN_RATE_LIMIT_ATTEMPTS": "5",
        "IGUARD_ACCOUNT_LOCKOUT_THRESHOLD": "10",
        "IGUARD_WORKERS_ENABLED": "false",
    }
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import reset_settings_cache  # noqa: E402
from app.database import session as dbsession  # noqa: E402
from app.database.session import Base, init_engine, session_scope  # noqa: E402
from app.integrations import Integrations  # noqa: E402
from app.models.enums import RoleName  # noqa: E402
from app.monitoring.alertmanager import AlertmanagerClient  # noqa: E402
from app.monitoring.loki import LokiClient  # noqa: E402
from app.monitoring.prometheus import PrometheusClient  # noqa: E402
from app.notifications.telegram import TelegramClient  # noqa: E402
from app.recovery.adapters import SimulatedAdapter  # noqa: E402
from app.recovery.policies import sync_policies  # noqa: E402
from app.services import auth_service  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "Str0ngPassw0rd!xyz"


def pytest_configure(config: pytest.Config) -> None:
    reset_settings_cache()


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    reset_settings_cache()
    engine = init_engine(TEST_DB_URL)
    with engine.begin() as conn:  # start from a clean slate (PostgreSQL may hold old state)
        if engine.dialect.name == "postgresql":
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    engine = dbsession.get_engine()
    with engine.begin() as conn:
        names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        if engine.dialect.name == "postgresql":
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        else:
            for t in reversed(Base.metadata.sorted_tables):
                conn.execute(t.delete())
    auth_service.reset_limiter()
    from app.incidents import detector

    detector.reset_streaks()
    yield


class FakeProm:
    """Programmable Prometheus: maps a substring of the query to a result list."""

    def __init__(self) -> None:
        self.responses: dict[str, list[dict[str, Any]]] = {}
        self.down = False
        self.queries: list[str] = []

    def set_vector(self, contains: str, values: dict[str, float], label: str = "instance") -> None:
        self.responses[contains] = [
            {"metric": {label: k}, "value": [1700000000, str(v)]} for k, v in values.items()
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down")
        if request.url.path == "/-/healthy":
            return httpx.Response(200, text="ok")
        q = request.url.params.get("query", "")
        self.queries.append(q)
        for key, result in self.responses.items():
            if key in q:
                return httpx.Response(
                    200,
                    json={"status": "success", "data": {"resultType": "vector", "result": result}},
                )
        return httpx.Response(
            200, json={"status": "success", "data": {"resultType": "vector", "result": []}}
        )


class FakeHttp:
    """Programmable target for service checks and the heal hook."""

    def __init__(self) -> None:
        self.status: dict[str, int] = {}
        self.delay = 0.0
        self.healed: list[str] = []
        self.heals_fix = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.method == "POST" and request.url.path == "/_demo/heal":
            self.healed.append(host)
            if self.heals_fix:
                self.status[host] = 200
            return httpx.Response(200, json={"ok": True})
        code = self.status.get(host, 200)
        if code == 0:
            raise httpx.ConnectError("refused")
        return httpx.Response(code, json={"status": "x"})


class TelegramRecorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responses: list[httpx.Response] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else httpx.Response(200, json={"ok": True})


class Env:
    def __init__(self) -> None:
        self.prom = FakeProm()
        self.http = FakeHttp()
        self.telegram = TelegramRecorder()
        self.loki_lines: list[Any] = []
        self.alerts: list[dict[str, Any]] = []
        self.loki_requests: list[httpx.Request] = []

        def loki(request: httpx.Request) -> httpx.Response:
            self.loki_requests.append(request)
            if request.url.path == "/ready":
                return httpx.Response(200, text="ready")
            return httpx.Response(200, json={"data": {"result": self.loki_lines}})

        def am(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=self.alerts)

        self.integrations = Integrations(
            prometheus=PrometheusClient(
                "http://prom", transport=httpx.MockTransport(self.prom.handler)
            ),
            loki=LokiClient("http://loki", transport=httpx.MockTransport(loki)),
            alertmanager=AlertmanagerClient("http://am", transport=httpx.MockTransport(am)),
            telegram=TelegramClient(transport=httpx.MockTransport(self.telegram.handler)),
            recovery_adapter=SimulatedAdapter(
                heal_map={
                    "iguard-game-api": "http://game-api/_demo/heal",
                    "iguard-wallet-mock": "http://wallet-mock/_demo/heal",
                    "iguard-game-web": "http://game-web/_demo/heal",
                },
                transport=httpx.MockTransport(self.http.handler),
            ),
            checker_transport=httpx.MockTransport(self.http.handler),
        )


@pytest.fixture
def env() -> Env:
    return Env()


@pytest.fixture
def db() -> Iterator[Session]:
    with session_scope() as s:
        yield s


@pytest.fixture
def client(env: Env) -> Iterator[TestClient]:
    from app.main import create_app

    reset_settings_cache()
    app = create_app(env.integrations, run_startup=False)
    with TestClient(app, base_url="http://testserver") as c:  # runs lifespan (startup_sync)
        yield c


def _make_user(role: RoleName) -> str:
    name = f"{role.value.lower()}-user"
    with session_scope() as s:
        auth_service.create_user(
            s,
            email=f"{name}@example.test",
            username=name,
            password=PASSWORD,
            role=role,
            full_name=name,
        )
    return name


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"identifier": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    return _login(client, _make_user(RoleName.ADMIN))


@pytest.fixture
def operator(client: TestClient) -> dict[str, str]:
    return _login(client, _make_user(RoleName.OPERATOR))


@pytest.fixture
def viewer(client: TestClient) -> dict[str, str]:
    return _login(client, _make_user(RoleName.VIEWER))


@pytest.fixture
def seeded(client: TestClient, admin: dict[str, str]) -> dict[str, Any]:
    """Demo server + services + recovery policies (without creating demo users)."""
    from app.core.config import get_settings
    from app.database.seed import DEMO_SERVICES
    from app.models import Server, Service
    from app.models.enums import CheckType

    with session_scope() as s:
        server = Server(
            name="demo-host", hostname="node-exporter", prometheus_instance="node-exporter:9100"
        )
        s.add(server)
        s.flush()
        for name, _d, _u, container, lat in DEMO_SERVICES:
            s.add(
                Service(
                    name=name,
                    server_id=server.id,
                    check_type=CheckType.HTTP,
                    url=f"http://{name}/health",
                    container_name=container,
                    retry_threshold=2,
                    latency_threshold_ms=lat,
                    timeout_seconds=2.0,
                )
            )
        s.flush()
        sync_policies(s, get_settings().recovery_policies_dir)
        return {"server_id": str(server.id)}


Factory = Callable[..., Any]
