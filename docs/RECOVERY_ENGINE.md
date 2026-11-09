# Recovery engine

## Principles

1. **Allowlist only.** Actions are declared in YAML under `recovery/policies/`. There is no endpoint, field or
   parameter that accepts a command string.
2. **No shell.** Scripts run without a shell, without arguments, with a timeout; shell metacharacters in policies
   are rejected at load time.
3. **Critical targets are excluded** (databases etc.) by pattern; policies naming them fail validation.
4. **Sensitive actions** are never automatic, need ADMIN and an explicit `confirm`.
5. **The backend has no Docker access.** It sends HMAC-signed requests (timestamp + nonce, replay cache) to the
   recovery agent, which talks to Docker only through a restart-only socket proxy.

## Execution flow

dry run (valid for 15 minutes) -> execute -> checks (role, enabled, cooldown, hourly limit, circuit breaker,
running guard, idempotency key) -> adapter -> verification loop (service health re-checked) -> record result,
update breaker, append incident event, audit log, notify.

Statuses: `DRY_RUN_OK`, `RUNNING`, `SUCCEEDED`, `FAILED`, `VERIFICATION_FAILED`, `REJECTED`.

## Automatic recovery

Off unless `auto_recovery_enabled` is turned on in Settings **and** the action is `auto_trigger` in its policy.
A failed verification keeps the incident open and counts toward the circuit breaker.

## Adapters

- `agent` - real restarts through the recovery agent (production).
- `simulated` - default for development/tests; performs no host changes. With `IGUARD_RECOVERY_SIMULATED_HEAL_MAP`
  it can call the demo services' `/_demo/heal` endpoint to demonstrate end-to-end recovery.

Executions run with the `simulated` flag visible in the UI so a simulation is never mistaken for a real restart.

## Policy format

See `recovery/policies/demo-services.yaml` and `examples/sample-recovery/`. Validate with `make validate-config`.
