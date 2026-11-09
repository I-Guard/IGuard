#!/usr/bin/env bash
# Logical PostgreSQL backup via pg_dump into ./backups (mode 600). Usage: scripts/backup.sh [outfile]
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p backups && chmod 700 backups
out="${1:-backups/iguard-$(date -u +%Y%m%dT%H%M%SZ).sql.gz}"
umask 077
docker compose exec -T postgres sh -c 'pg_dump --no-owner --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$out"
[[ -s "$out" ]] || { echo "Backup is empty - aborting" >&2; rm -f "$out"; exit 1; }
gzip -t "$out"
echo "Backup written: $out ($(du -h "$out" | cut -f1))"
