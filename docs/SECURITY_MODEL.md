# Security model

## Authentication

- Passwords: Argon2id; policy of >= 12 chars with upper, lower and digit.
- Login: per-client rate limit, per-account lockout, uniform error messages (no user enumeration).
- Access token: short-lived JWT (HS256) carrying a session id so sessions can be revoked; kept **in memory** by the SPA.
- Refresh token: opaque, stored hashed, rotated on every use; reuse of an old token revokes the session.
  Delivered as an httpOnly cookie; refresh/logout require a double-submit CSRF token (`X-CSRF-Token`).

## Authorization

Roles `ADMIN > OPERATOR > VIEWER`, enforced server-side by dependencies on every route (verified by an
endpoint x role matrix test). UI hiding of controls is cosmetic only.

## Recovery safety

See RECOVERY_ENGINE.md. In short: allowlist, no shell, no arbitrary commands, dry-run first, cooldowns, circuit
breaker, signed agent requests, restart-only Docker proxy, critical targets excluded.

## Other controls

- Security headers and CSP (Nginx and backend); CORS allowlist.
- Service checker SSRF guard: link-local and cloud-metadata addresses are always blocked.
- Loki queries are built from allowlisted labels with escaped values (no LogQL injection).
- Structured JSON logs with redaction of tokens, passwords and authorization headers.
- Audit log of logins, configuration/user changes and recovery runs; secrets are never recorded.
- Production start-up refuses weak secrets and SQLite.
- Containers: `no-new-privileges`, dropped capabilities, resource limits, internal networks.

## Known limits

- No built-in TLS: terminate TLS in front of Nginx (see DEPLOYMENT.md).
- Login rate limiting is in-memory per backend process.
- The default compose file is a single-host deployment; it is not a high-availability setup.
