# Testing

| Layer | Command | Notes |
| --- | --- | --- |
| Backend unit + API | `make test-backend` | Schema is built through the real Alembic migration |
| Backend on PostgreSQL | `IGUARD_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host/db make test-backend` | Database must be disposable |
| Frontend | `make test-frontend` | Vitest + React Testing Library, API mocked at `fetch` |
| End-to-end | see below | Playwright against a real backend |
| Lint / types | `make lint` | ruff, mypy, eslint, tsc |

## What the tests cover

Security primitives; incident engine (dedup, flapping, escalation, reopen); detector (including "no data" behavior);
recovery safety (dry-run, cooldown, breaker, idempotency, sensitive confirm, policy rejection); notifications and
retry; Loki query-injection safety; SSRF guard; the recovery agent module; every API route against every role.

## Running E2E locally

```bash
cd backend
export IGUARD_DATABASE_URL=sqlite:////tmp/e2e.db IGUARD_WEBHOOK_TOKEN=$(openssl rand -hex 24)
alembic upgrade head
python -m app.cli create-admin --email e2e@example.com --username e2eadmin   # prompts for password
uvicorn app.main:app --port 8000 &
cd ../frontend && npm run build && npx vite preview --host 127.0.0.1 &
E2E_USER=e2eadmin E2E_PASSWORD=... E2E_WEBHOOK_TOKEN=$IGUARD_WEBHOOK_TOKEN npx playwright test
```

Set `E2E_CHROMIUM_PATH` to use an already-installed Chromium.

## Not covered

Docker image builds and the full container stack (Prometheus, Loki, Grafana, Alertmanager, Promtail, the recovery
agent against a real Docker daemon) are exercised by CI only; see DEVELOPMENT_STATUS.md for what has been run.
