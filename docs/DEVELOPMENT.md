# Development

```bash
make install
make dev            # backend :8000, frontend :5173 (proxying /api)
make lint && make test
```

## Conventions

- Backend: Python 3.12+, ruff (lint + format), mypy, SQLAlchemy 2 typed models, one Alembic migration per schema change
  (`alembic revision --autogenerate`, review, then `alembic check`).
- Frontend: React 18 + TypeScript strict, TanStack Query for server state, React Hook Form + Zod for forms,
  Tailwind. Missing data renders as an em dash or "no data", never `0`.
- Every new route must be added to the RBAC matrix test.
- Never add an endpoint or field that accepts a command, path or URL for execution; extend the recovery policy
  mechanism instead.
- Tests: add them with the change; see TESTING.md.

## Layout

`backend/` API and workers - `frontend/` SPA - `recovery/` policies, scripts, agent - `monitoring/` Prometheus,
Alertmanager, Loki, Promtail, Grafana - `services/demo-service/` synthetic services - `scripts/` operations -
`docs/` documentation - `examples/` sample inputs.
