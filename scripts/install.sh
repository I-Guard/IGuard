#!/usr/bin/env bash
# Generates .env from .env.example with random url-safe secrets. Never overwrites an existing .env.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -e .env ]]; then
  echo ".env already exists - not touching it. Delete it first if you really want new secrets." >&2
  exit 1
fi
command -v openssl >/dev/null || { echo "openssl is required to generate secrets" >&2; exit 1; }

rand() { openssl rand -hex 32; }
cp .env.example .env
chmod 600 .env
for k in IGUARD_SECRET_KEY IGUARD_WEBHOOK_TOKEN RECOVERY_AGENT_SECRET POSTGRES_PASSWORD GRAFANA_ADMIN_PASSWORD; do
  sed -i "s|^${k}=.*|${k}=$(rand)|" .env
done

echo "Created .env (mode 600) with freshly generated secrets."
echo "Grafana admin password is stored in .env (GRAFANA_ADMIN_PASSWORD); it is not printed here."
echo
echo "Next steps:"
echo "  1. docker compose up -d --build"
echo "  2. scripts/create-admin.sh        # or set IGUARD_BOOTSTRAP_ADMIN_* in .env before first start"
echo "  3. open http://localhost:8080"
