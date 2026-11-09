# Changelog

Format based on Keep a Changelog; versions follow SemVer.

## [1.0.0] - 2026-11-08

Initial release (first public version of the repository; no earlier releases exist).

### Added
- FastAPI backend (`/api/v1`): auth (Argon2id, JWT + rotating refresh tokens, CSRF), RBAC, servers, services,
  incidents, recovery, logs, alerts, reports, audit logs, users, settings.
- Incident engine (fingerprint dedup, flapping, correlation, escalation) and detector.
- Allowlisted recovery engine with dry run, cooldowns, circuit breaker, idempotency; signed recovery agent.
- Telegram notifications through a transactional outbox.
- React dashboard with 18 pages.
- Docker Compose stack: Prometheus, Alertmanager, Loki, Promtail, Grafana (7 dashboards), exporters, Nginx.
- Operations scripts, CI workflows, documentation.
