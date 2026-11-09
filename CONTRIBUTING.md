# Contributing to IGuard

Thanks for helping! Please read the [Code of Conduct](CODE_OF_CONDUCT.md).

1. Open an issue first for anything larger than a small fix.
2. Fork, branch from `main`, and keep changes focused.
3. `make install`, then `make lint` and `make test` must pass. Add tests for new behavior.
4. Never commit secrets, tokens or real credentials; CI runs a secret scan.
5. Changes touching authentication, authorization or the recovery engine need a "Security impact" note in the
   pull request and must keep the safety rules in [docs/RECOVERY_ENGINE.md](docs/RECOVERY_ENGINE.md).
6. Update documentation and [CHANGELOG.md](CHANGELOG.md).

Contributions are licensed under Apache-2.0. Vulnerabilities: see [SECURITY.md](SECURITY.md), not public issues.
