# Architecture

```mermaid
flowchart LR
  user([Operator / Admin / Viewer]) -->|HTTPS or localhost| fe[Frontend - Nginx + React SPA]
  fe -->|/api/v1| be[Backend - FastAPI]
  be --> pg[(PostgreSQL)]
  be -->|PromQL| prom[Prometheus]
  be -->|LogQL| loki[Loki]
  be -->|alerts| am[Alertmanager]
  be -->|synthetic checks| apps[Monitored services]
  be -->|HMAC-signed request| agent[Recovery agent]
  agent -->|restart-only| dsp[docker-socket-proxy]
  dsp --> docker{{Docker Engine}}
  be -->|optional| tg[Telegram Bot API]
  am -->|webhook + bearer token| be
  prom --> ne[node-exporter]
  prom --> cadv[cAdvisor]
  prom --> bb[blackbox-exporter]
  prom -->|rules| am
  promtail[Promtail] --> loki
  promtail -->|read-only| dspro[docker-socket-proxy ro]
  graf[Grafana] --> prom
  graf --> loki
```

## Components

| Component | Role |
| --- | --- |
| Frontend | Nginx serving the React SPA; proxies `/api` to the backend; CSP, rate limits, JSON access log |
| Backend | FastAPI app (`/api/v1`), SQLAlchemy 2 + Alembic, background workers |
| PostgreSQL | System of record (incidents, services, checks, audit log, outbox, recovery executions) |
| Prometheus + exporters | Host (node-exporter), container (cAdvisor) and endpoint (blackbox) metrics; alert rules |
| Alertmanager | Routes alerts to the backend webhook (bearer token) |
| Loki + Promtail | Centralized container logs; Promtail reads Docker through a read-only socket proxy |
| Grafana | Seven provisioned dashboards (see MONITORING.md) |
| Recovery agent | Separate small service that executes allowlisted restarts/scripts for signed requests |
| docker-socket-proxy (x2) | One restart-only for the agent, one read-only for Promtail. The backend has no Docker access |
| Demo services | Five synthetic stdlib services used to demonstrate detection/recovery |

## Networks

`web` and `egress` are routable; `api`, `data`, `mon`, `apps` and `recovery` are internal. Only the
frontend (8080) and Grafana (3000) publish ports, bound to `127.0.0.1` by default.

## Backend layout (`backend/app`)

- `api/v1` routers - thin; authorization via dependencies in `security/deps.py`
- `services`, `repositories` - business logic and data access
- `incidents` - `engine.py` (lifecycle) and `detector.py` (signals from Prometheus and checks)
- `recovery` - policy loader, service (safety checks), adapters (agent / simulated)
- `monitoring` - Prometheus, Loki, Alertmanager clients and the service checker
- `notifications` - outbox dispatcher and Telegram client
- `workers/loops.py` - check, detection, notification and retention loops

## Workers

Workers run as threads inside the backend when `IGUARD_WORKERS_ENABLED=true`. Detection is leader-only,
guarded by a PostgreSQL advisory lock, so several backend replicas cannot double-detect.

## Data model

Users, roles, auth sessions and refresh tokens; servers; services and service checks; incidents and incident
events; recovery actions and executions; notifications and alert configuration; audit logs; system settings.
The initial schema is Alembic migration `0001`.

## Sequence diagrams

Incident detection, recovery execution, authentication, alert webhook and notification delivery:

### incident detection

```mermaid
sequenceDiagram
  participant W as Detector worker
  participant P as Prometheus
  participant C as Service checker
  participant E as Incident engine
  participant DB as PostgreSQL
  participant N as Notification outbox
  W->>W: acquire advisory lock (leader only)
  W->>P: query CPU, memory, disk, targets
  alt Prometheus unreachable or no data
    P--xW: error / empty
    W->>W: skip metric rules (never open or clear)
  else data available
    P-->>W: samples
    W->>E: observe(rule, subject, breached)
  end
  C->>E: observe(availability / latency)
  E->>DB: lookup active incident by fingerprint
  alt none and sustained breach
    E->>DB: INSERT incident (unique partial index guards races)
    E->>N: enqueue INCIDENT_OPENED
  else exists
    E->>DB: occurrences++, last_seen_at
  end
```

### recovery

```mermaid
sequenceDiagram
  actor U as Operator
  participant API as Backend API
  participant S as RecoveryService
  participant A as Adapter
  participant R as Recovery agent
  participant D as Docker (via proxy)
  U->>API: POST /recovery/actions/{id}/dry-run
  API->>S: dry_run (policy, role, breaker checks)
  S-->>U: DRY_RUN_OK (nothing changed)
  U->>API: POST /recovery/actions/{id}/execute (Idempotency-Key)
  API->>S: execute
  S->>S: dry-run within 15 min? cooldown? hourly limit? breaker closed? sensitive needs ADMIN + confirm
  S->>A: run(action)
  A->>R: signed request (HMAC, timestamp, nonce)
  R->>R: verify signature, replay cache, allowlist
  R->>D: restart allowlisted container only
  D-->>R: ok
  R-->>A: result
  loop verification attempts
    S->>S: re-check service health
  end
  S->>S: record SUCCEEDED / VERIFICATION_FAILED, update breaker
  S-->>U: execution record
```

### auth

```mermaid
sequenceDiagram
  participant B as Browser
  participant API as Backend
  B->>API: POST /auth/login (identifier, password)
  API->>API: rate limit, lockout check, Argon2id verify
  API-->>B: access token (body) + CSRF token (body) + refresh cookie (httpOnly)
  B->>API: GET /... Authorization Bearer access token
  Note over B: access token held in memory only
  B->>API: POST /auth/refresh (cookie + X-CSRF-Token)
  API->>API: rotate refresh token, detect reuse
  API-->>B: new access token + new refresh cookie
  alt refresh token reused
    API->>API: revoke whole session
    API-->>B: 401
  end
```

### alert webhook

```mermaid
sequenceDiagram
  participant Pm as Prometheus
  participant Am as Alertmanager
  participant API as Backend webhook
  participant E as Incident engine
  participant N as Outbox
  participant T as Telegram (optional)
  Pm->>Am: firing alert
  Am->>API: POST /alerts/webhook (Bearer token)
  API->>API: constant-time token check
  API->>E: upsert incident by fingerprint (dedup)
  E->>N: enqueue notification
  N->>T: send (retry with backoff, token redacted in logs)
  T-->>N: 200 / failure recorded
```

### notification

```mermaid
sequenceDiagram
  participant E as Incident engine
  participant DB as PostgreSQL
  participant W as Notify worker
  participant T as Telegram
  E->>DB: INSERT notification (PENDING) in same transaction
  W->>DB: select due notifications
  W->>T: sendMessage
  alt success
    W->>DB: status SENT
  else failure
    W->>DB: attempts++, next_attempt_at = backoff
    Note over W,DB: after max retries status FAILED
  end
  Note over E,W: Telegram not configured: status SKIPPED, nothing sent
```
