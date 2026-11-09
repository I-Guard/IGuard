# Incident engine

## Lifecycle

`DETECTED -> ACKNOWLEDGED -> INVESTIGATING -> RECOVERING -> RESOLVED`. Operators can acknowledge, assign,
change status and resolve (resolution summary required). Every transition is recorded as an incident event.

## Fingerprinting and deduplication

`fingerprint = sha256(rule | server | service | subject)`. A partial unique index
(`uq_incidents_active_fingerprint`, `status <> 'RESOLVED'`) guarantees at most one active incident per
fingerprint even under concurrent writers; repeat observations only increment `occurrences` and `last_seen_at`.

## Detection

Signals: host CPU, memory, disk (Prometheus), service availability/latency (synthetic checks), container
failures and restarts, down scrape targets, and Alertmanager webhooks. A rule must breach for
`sustained_evaluations` consecutive evaluations before an incident opens, and be healthy for
`clear_evaluations` before it auto-resolves.

**Missing data is not a signal.** If Prometheus is unreachable or a metric returns no samples, metric rules are
skipped: nothing is opened and nothing is cleared.

## Reopen, flapping, correlation, escalation

- Re-occurrence within `incident_cooldown_seconds` of resolution reopens the previous incident.
- More than `flap_threshold` state changes within `flap_window_seconds` marks it flapping and suppresses
  repeated notifications.
- Incidents on the same server within a short window are linked as correlated.
- Unacknowledged incidents escalate after `escalation_after_seconds` (maximum level 3) and notify.

## Leader election

Only one backend instance runs detection, using a PostgreSQL advisory lock.
