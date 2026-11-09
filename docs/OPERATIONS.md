# Operations

## Health

`scripts/health-check.sh` probes the frontend, `/api/v1/health`, `/api/v1/ready` and Grafana and checks that
containers are running. `/ready` fails if the database is unreachable; Prometheus/Loki/Alertmanager reachability
is reported in the Overview page and does not fail readiness.

## Backup and restore

```bash
scripts/backup.sh                          # backups/iguard-<UTC timestamp>.sql.gz (mode 600)
scripts/restore.sh backups/iguard-....sql.gz   # destructive; asks for confirmation
```

Backups contain user hashes and audit data: store them encrypted and access-controlled. Grafana, Prometheus and
Loki data live in separate Docker volumes and are not part of this backup.

## Logs

`docker compose logs -f backend`. Backend logs are JSON with `request_id`/`correlation_id`; secrets are redacted.

## Retention

Service-check history is pruned according to `check_retention_days` (Settings).

## Users

Create admins with `scripts/create-admin.sh`; manage the rest in the UI. Disabling a user revokes their sessions.
