"""Demo seed: synthetic servers/services/users only. No fabricated metrics or incidents.

Passwords are never hardcoded: they come from IGUARD_SEED_PASSWORD or are generated randomly and
printed once to stdout.
"""

from __future__ import annotations

import os
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Server, Service, User
from app.models.enums import CheckType, RoleName
from app.recovery.policies import sync_policies
from app.services import auth_service, settings_service

DEMO_SERVICES = [
    ("game-api", "Synthetic game API", "http://game-api:8080/health", "iguard-game-api", 800),
    (
        "game-web",
        "Synthetic game web frontend",
        "http://game-web:8080/health",
        "iguard-game-web",
        1000,
    ),
    (
        "wallet-mock",
        "Synthetic wallet (mock, no real funds)",
        "http://wallet-mock:8080/health",
        "iguard-wallet-mock",
        800,
    ),
    (
        "authentication-service",
        "Synthetic authentication service",
        "http://authentication-service:8080/health",
        "iguard-authentication-service",
        600,
    ),
    (
        "leaderboard-service",
        "Synthetic leaderboard",
        "http://leaderboard-service:8080/health",
        "iguard-leaderboard-service",
        1000,
    ),
]


def seed_demo(db: Session) -> dict[str, object]:
    s = get_settings()
    users: list[dict[str, str | None]] = []
    report: dict[str, object] = {"users": users}
    for role in RoleName:
        auth_service.get_role(db, role)

    shared = os.environ.get("IGUARD_SEED_PASSWORD")
    for role in (RoleName.ADMIN, RoleName.OPERATOR, RoleName.VIEWER):
        username = f"demo-{role.value.lower()}"
        if db.scalar(select(User.id).where(User.username == username)) is not None:
            continue
        pw = shared or (secrets.token_urlsafe(12) + "aA1")
        auth_service.create_user(
            db,
            email=f"{username}@example.invalid",
            username=username,
            password=pw,
            role=role,
            full_name=f"Demo {role.value.title()}",
        )
        users.append({"username": username, "password": None if shared else pw})

    server = db.scalar(select(Server).where(Server.name == "demo-host"))
    if server is None:
        server = Server(
            name="demo-host",
            hostname="node-exporter",
            environment="demo",
            description="Docker host running the IGuard demo stack",
            prometheus_instance="node-exporter:9100",
            tags=["demo", "docker"],
        )
        db.add(server)
        db.flush()
    for name, desc, url, container, latency in DEMO_SERVICES:
        if db.scalar(select(Service).where(Service.name == name)) is None:
            db.add(
                Service(
                    name=name,
                    description=desc,
                    server_id=server.id,
                    check_type=CheckType.HTTP,
                    url=url,
                    expected_status_codes=[200],
                    interval_seconds=15,
                    timeout_seconds=3.0,
                    retry_threshold=3,
                    latency_threshold_ms=latency,
                    container_name=container,
                )
            )
    db.flush()
    settings_service.effective(db)
    report["recovery_policies"] = sync_policies(db, s.recovery_policies_dir)
    return report
