# Notifications

Telegram is optional. Set `IGUARD_TELEGRAM_BOT_TOKEN` and `IGUARD_TELEGRAM_CHAT_ID` in the environment (never in
the UI or database). Without them, notifications are recorded with status `SKIPPED` and nothing is sent.

Delivery uses a transactional outbox: the notification row is written in the same transaction as the incident
change, and a worker delivers it with retry and exponential backoff (`PENDING -> SENT | FAILED`). The bot token is
redacted from logs and error messages.

Events: `INCIDENT_CRITICAL`, `INCIDENT_WARNING`, `INCIDENT_ESCALATED`, `INCIDENT_RESOLVED`, `RECOVERY_STARTED`,
`RECOVERY_SUCCEEDED`, `RECOVERY_FAILED`, `TEST`. Minimum severity, enabled events and per-incident cooldown are
configured under Alerts (ADMIN). `POST /alerts/test` sends a test message.
