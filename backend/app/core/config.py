"""Application configuration loaded from environment variables (prefix ``IGUARD_``)."""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_WEAK_SECRETS = {"", "change-me", "changeme", "secret", "replace-me", "replace-with-random-secret"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IGUARD_", env_file=".env", extra="ignore", case_sensitive=False
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    service_name: str = "iguard-backend"

    # --- Database ---
    database_url: str = "sqlite:///./iguard-dev.db"
    db_pool_size: int = 10
    db_echo: bool = False

    # --- Security ---
    secret_key: SecretStr = SecretStr("")
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    refresh_token_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=300)
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "strict"
    cors_origins: str = "http://localhost:8080,http://localhost:5173"
    login_rate_limit_attempts: int = Field(default=5, ge=1)
    login_rate_limit_window_seconds: int = Field(default=300, ge=1)
    account_lockout_threshold: int = Field(default=10, ge=3)
    account_lockout_seconds: int = Field(default=900, ge=1)
    password_min_length: int = Field(default=12, ge=8)
    webhook_token: SecretStr = SecretStr("")

    # --- Bootstrap (optional, only used when no user exists) ---
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    # --- Monitoring integrations ---
    prometheus_url: str = "http://prometheus:9090"
    alertmanager_url: str = "http://alertmanager:9093"
    loki_url: str = "http://loki:3100"
    integration_timeout_seconds: float = Field(default=5.0, gt=0)
    # Hosts that service checks may never target (SSRF guard). Link-local/metadata always blocked.
    check_blocked_hosts: str = ""

    # --- Workers ---
    workers_enabled: bool = False
    worker_tick_seconds: float = Field(default=5.0, gt=0)

    # --- Recovery ---
    recovery_adapter: Literal["agent", "simulated"] = "simulated"
    recovery_agent_url: str = "http://recovery-agent:8088"
    recovery_agent_secret: SecretStr = SecretStr("")
    recovery_policies_dir: str = "../recovery/policies"
    recovery_scripts_dir: str = "../recovery/scripts"
    # Demo/test only: "target=url,target2=url2". With the simulated adapter, a "restart" of the
    # target POSTs to exactly these URLs (synthetic demo services' /_demo/heal endpoint).
    recovery_simulated_heal_map: str = ""

    # --- Telegram ---
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    telegram_max_retries: int = Field(default=3, ge=0, le=10)

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _finalize(self) -> Settings:
        key = self.secret_key.get_secret_value()
        if self.env == "production":
            problems = []
            if key in _WEAK_SECRETS or len(key) < 32:
                problems.append("IGUARD_SECRET_KEY must be set to a random value of >= 32 chars")
            if (
                self.recovery_adapter == "agent"
                and len(self.recovery_agent_secret.get_secret_value()) < 16
            ):
                problems.append("IGUARD_RECOVERY_AGENT_SECRET must be >= 16 chars")
            if self.database_url.startswith("sqlite"):
                problems.append("SQLite is not supported in production; use PostgreSQL")
            if problems:
                raise ValueError("; ".join(problems))
        elif key in _WEAK_SECRETS or len(key) < 32:
            # Ephemeral key for dev/test: tokens do not survive restarts.
            self.secret_key = SecretStr(secrets.token_urlsafe(48))
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def blocked_host_list(self) -> list[str]:
        return [h.strip().lower() for h in self.check_blocked_hosts.split(",") if h.strip()]

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token.get_secret_value() and self.telegram_chat_id)

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
