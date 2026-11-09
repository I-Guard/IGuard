#!/usr/bin/env bash
# Static validation that needs no running stack: env file, compose files, recovery policies.
set -euo pipefail
cd "$(dirname "$0")/.."
rc=0
if [[ -f .env ]]; then
  for k in IGUARD_SECRET_KEY IGUARD_WEBHOOK_TOKEN RECOVERY_AGENT_SECRET POSTGRES_PASSWORD GRAFANA_ADMIN_PASSWORD; do
    v=$(grep -E "^${k}=" .env | head -1 | cut -d= -f2-)
    if [[ -z "$v" ]]; then echo "FAIL  $k is empty in .env"; rc=1; fi
  done
  perms=$(stat -c %a .env); [[ "$perms" == "600" ]] || echo "WARN  .env permissions are $perms (expected 600)"
else
  echo "WARN  no .env found (run scripts/install.sh)"
fi
if command -v docker >/dev/null && [[ -f .env ]]; then
  docker compose config -q && echo "OK    docker-compose.yml" || rc=1
  docker compose -f docker-compose.yml -f docker-compose.prod.yml config -q && echo "OK    docker-compose.prod.yml overlay" || rc=1
fi
if [[ -x backend/.venv/bin/python ]]; then
  (cd backend && .venv/bin/python -m app.cli validate-config) || rc=1
else
  echo "SKIP  recovery policy validation (backend venv missing; run: make install)"
fi
exit $rc
