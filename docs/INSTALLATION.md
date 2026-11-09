# Installation

## Requirements

- Docker with Compose v2 (for the full stack), or Python 3.12+ and Node 22 for development
- Linux host recommended; the recovery agent needs access to the Docker socket **through the proxy only**

## Docker

```bash
scripts/install.sh                 # generates .env with random secrets, mode 600
docker compose up -d --build
scripts/create-admin.sh            # or set IGUARD_BOOTSTRAP_ADMIN_EMAIL/PASSWORD before first start
scripts/health-check.sh
```

`docker compose` refuses to start if a required secret is empty. `scripts/validate-config.sh` checks the
env file, both compose files and the recovery policies without starting anything.

## Local development without Docker

```bash
make install
make dev
```

SQLite is used by default in development; production requires PostgreSQL.

## First login

Create an administrator with `scripts/create-admin.sh` (the password is prompted, not passed as an argument).
Users created by an admin must change their password at first login.
