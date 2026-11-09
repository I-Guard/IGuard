#!/usr/bin/env bash
# Probes the running stack. Exit code 0 only if every required check passes.
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; [[ -f .env ]] && . ./.env; set +a
host="${IGUARD_BIND_ADDR:-127.0.0.1}"; [[ "$host" == "0.0.0.0" ]] && host=127.0.0.1
fail=0
check() { # name url
  if curl -fsS -m 5 -o /dev/null "$2"; then echo "OK    $1"; else echo "FAIL  $1 ($2)"; fail=1; fi
}
check "frontend"          "http://$host:${IGUARD_HTTP_PORT:-8080}/"
check "api health"        "http://$host:${IGUARD_HTTP_PORT:-8080}/api/v1/health"
check "api readiness"     "http://$host:${IGUARD_HTTP_PORT:-8080}/api/v1/ready"
check "grafana"           "http://$host:${GRAFANA_PORT:-3000}/api/health"
if docker compose ps --status running >/dev/null 2>&1; then
  not_running=$(docker compose ps --format '{{.Service}} {{.State}}' | awk '$2!="running"{print $1}')
  if [[ -n "$not_running" ]]; then echo "FAIL  containers not running: $not_running"; fail=1; else echo "OK    all containers running"; fi
fi
exit $fail
