# Deployment

IGuard ships as a single-host Docker Compose stack. Review everything below before exposing it.

## Checklist

1. `scripts/install.sh` to generate unique secrets; keep `.env` mode 600 and out of version control.
2. Use the production overlay: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.
   It sets `IGUARD_ENV=production` (strict secret validation, PostgreSQL only) and moves the demo services into
   the `demo` profile with their control endpoints disabled.
3. **Terminate TLS** in a reverse proxy in front of the frontend container, then set `IGUARD_COOKIE_SECURE=true`
   and `IGUARD_CORS_ORIGINS` to your real origin. The stack does not provide TLS itself.
4. Keep published ports on `127.0.0.1` (default) and let the reverse proxy reach them; do not publish Prometheus,
   Alertmanager, Loki, PostgreSQL or the recovery agent.
5. Set `IGUARD_RECOVERY_ADAPTER=agent` only after reviewing `recovery/policies/` for your environment.
6. Configure `IGUARD_WEBHOOK_TOKEN` (Alertmanager token is rendered at start) and, optionally, Telegram.
7. Schedule `scripts/backup.sh` and test `scripts/restore.sh` on a non-production copy.

## Upgrades

Back up, pull the new version, `docker compose up -d --build`. The backend container applies Alembic migrations on
start. Read CHANGELOG.md first.

## Limits

Single host, single PostgreSQL, no HA. In-memory login rate limiting is per backend process.
