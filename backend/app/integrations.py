"""Holder for external integrations so they can be swapped in tests."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.monitoring.alertmanager import AlertmanagerClient
from app.monitoring.loki import LokiClient
from app.monitoring.prometheus import PrometheusClient
from app.notifications.telegram import TelegramClient
from app.recovery.adapters import RecoveryAdapter, get_adapter


@dataclass
class Integrations:
    prometheus: PrometheusClient
    loki: LokiClient
    alertmanager: AlertmanagerClient
    telegram: TelegramClient
    recovery_adapter: RecoveryAdapter
    checker_transport: httpx.BaseTransport | None = field(default=None)

    @classmethod
    def build_default(cls) -> Integrations:
        return cls(
            prometheus=PrometheusClient(),
            loki=LokiClient(),
            alertmanager=AlertmanagerClient(),
            telegram=TelegramClient(),
            recovery_adapter=get_adapter(),
        )

    def close(self) -> None:
        for c in (self.prometheus, self.loki, self.alertmanager):
            c.close()
