# Security policy

## Reporting a vulnerability

Please do **not** open a public issue. Email Matin.alijani@gmail.com with a description, reproduction steps and
impact. Use GitHub's private vulnerability reporting if it is enabled on the repository. You will get an
acknowledgement as soon as the maintainer can respond; there is no guaranteed response-time SLA for this
volunteer project.

## Supported versions

Only the latest release (1.0.x) receives security fixes.

## Scope notes

Design and known limits are described in [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md). Particularly relevant:
the recovery engine (allowlist, signed agent requests, restart-only Docker proxy), authentication/session handling,
and the service checker's SSRF guard.

## Hardening reminders for operators

Generate unique secrets (`scripts/install.sh`), terminate TLS, keep ports bound to localhost behind a proxy,
and never enable the demo control endpoints in production.
