# API

Base path `/api/v1`. Interactive OpenAPI is served by the backend at `/docs` (and `/openapi.json`).
Authentication: `Authorization: Bearer <access token>` from `POST /auth/login`. Errors use one envelope:

```json
{"error": {"code": "validation_error", "message": "...", "details": null, "request_id": "..."}}
```

| Area | Endpoints | Minimum role |
| --- | --- | --- |
| System | `GET /health`, `GET /ready`, `GET /version` | public |
| Auth | `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/change-password`; `GET /auth/me` | public / any user |
| Overview | `GET /overview` | VIEWER |
| Servers | `GET/POST /servers`, `GET/PATCH/DELETE /servers/{id}`, `GET /servers/{id}/metrics`, `/metrics/range` | VIEWER read, ADMIN write |
| Services | `GET/POST /services`, `GET/PATCH/DELETE /services/{id}`, `/checks`, `/availability`, `POST /services/{id}/check` | VIEWER read, OPERATOR run check, ADMIN write |
| Incidents | `GET /incidents`, `GET /incidents/{id}`, `/timeline`, `POST .../acknowledge`, `/assign`, `/status`, `/resolve` | VIEWER read, OPERATOR act |
| Recovery | `GET /recovery/actions`, `POST .../dry-run`, `POST .../execute`, `GET /recovery/history[/{id}]` | VIEWER read, OPERATOR run (action may require ADMIN) |
| Logs | `GET /logs`, `GET /logs/search` | VIEWER |
| Alerts | `GET /alerts`, `GET/PATCH /alerts/configuration`, `POST /alerts/test`, `POST /alerts/webhook` | VIEWER read, ADMIN configure, webhook token |
| Reports | `GET /reports/summary|availability|incidents|recovery` | VIEWER |
| Audit | `GET /audit-logs` | ADMIN |
| Users | `GET/POST /users`, `PATCH/DELETE /users/{id}`, `GET /users/assignable`, `PATCH /users/me` | ADMIN (self-service for `/me`) |
| Settings | `GET/PATCH /settings` | VIEWER read, ADMIN write |

List endpoints accept `page`, `page_size`, `sort` (`-field` for descending) and filters. The role matrix is
enforced by `backend/tests/api/test_rbac.py`, which also asserts that every route is covered.

`POST /recovery/actions/{id}/execute` accepts an optional `Idempotency-Key` header; repeating a key returns the
original execution instead of running the action again.
