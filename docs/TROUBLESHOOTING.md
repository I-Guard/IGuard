# Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `docker compose` says a variable is required | Run `scripts/install.sh` or fill the secret in `.env` |
| Backend exits at start in production | `IGUARD_SECRET_KEY` < 32 chars, SQLite URL, or agent secret too short; the log names the problem |
| Cannot log in, "Too many attempts" | Login rate limit (default 5 per 5 min per client); wait, or restart the backend to clear in-memory counters |
| Forced to the Profile page after login | Account is flagged `must_change_password`; change it |
| Overview shows "Prometheus unreachable" | Check `docker compose ps prometheus` and `IGUARD_PROMETHEUS_URL`; metrics display as "no data", not zero |
| Logs page shows an upstream error | Loki is down or unreachable; nothing is lost, Promtail retries |
| Recovery "Execute" disabled | Circuit breaker open, cooldown running, action disabled, or your role is too low (the card says which) |
| Recovery rejected: dry run required | Run a dry run within the last 15 minutes |
| No incidents appear for a failing service | Workers disabled (`IGUARD_WORKERS_ENABLED`), failure count below the retry threshold, or the check is disabled |
| Telegram messages not arriving | Token/chat id unset (status `SKIPPED`), or see Alerts -> history for the recorded failure |
| Session lost after a reload behind a proxy | Cookie `Secure` mismatch: use HTTPS and `IGUARD_COOKIE_SECURE=true`, or HTTP with it false |
