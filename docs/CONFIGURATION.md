# Configuration

All backend settings are environment variables with the prefix `IGUARD_` (see `backend/app/core/config.py`).
Compose-level variables are documented in `.env.example`.

| Variable | Default | Notes |
| --- | --- | --- |
| `IGUARD_ENV` | `development` | `production` rejects weak secrets and SQLite |
| `IGUARD_DATABASE_URL` | SQLite file | Use `postgresql+psycopg://...` in production |
| `IGUARD_SECRET_KEY` | random per start (dev) | **Required, >= 32 chars in production** |
| `IGUARD_WEBHOOK_TOKEN` | empty | Bearer token for `/alerts/webhook`; empty disables it |
| `IGUARD_ACCESS_TOKEN_TTL_SECONDS` | 900 | |
| `IGUARD_REFRESH_TOKEN_TTL_SECONDS` | 604800 | |
| `IGUARD_COOKIE_SECURE` | false | Must be true behind HTTPS |
| `IGUARD_COOKIE_SAMESITE` | strict | |
| `IGUARD_CORS_ORIGINS` | localhost origins | Comma separated |
| `IGUARD_LOGIN_RATE_LIMIT_ATTEMPTS` / `_WINDOW_SECONDS` | 5 / 300 | Per client |
| `IGUARD_ACCOUNT_LOCKOUT_THRESHOLD` / `_SECONDS` | 10 / 900 | |
| `IGUARD_PASSWORD_MIN_LENGTH` | 12 | Plus upper, lower, digit |
| `IGUARD_PROMETHEUS_URL` / `LOKI_URL` / `ALERTMANAGER_URL` | compose service URLs | |
| `IGUARD_CHECK_BLOCKED_HOSTS` | empty | Extra hosts service checks must not target |
| `IGUARD_WORKERS_ENABLED` | false | Compose enables it for the backend |
| `IGUARD_RECOVERY_ADAPTER` | simulated | `agent` performs real restarts via the recovery agent |
| `IGUARD_RECOVERY_AGENT_URL` / `_SECRET` | | Secret >= 16 chars when adapter is `agent` in production |
| `IGUARD_TELEGRAM_BOT_TOKEN` / `_CHAT_ID` | empty | Optional |
| `IGUARD_BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` | unset | Used only when no user exists |

## Runtime settings (UI -> Settings, ADMIN)

Stored in the database with validated bounds: CPU/memory/disk warning and critical thresholds,
`latency_critical_multiplier`, `container_restart_threshold`, `sustained_evaluations`, `clear_evaluations`,
`incident_cooldown_seconds`, `flap_window_seconds`, `flap_threshold`, `escalation_after_seconds`,
`auto_recovery_enabled`, `detection_interval_seconds`, `check_retention_days`.
Defaults and ranges are returned by `GET /api/v1/settings`.

Secrets are never returned by any API and never stored in the settings table.
