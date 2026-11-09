#!/usr/bin/env bash
# Restores a backup produced by scripts/backup.sh. DESTRUCTIVE: replaces current database contents.
# Usage: scripts/restore.sh backups/iguard-XXXX.sql.gz [--yes]
set -euo pipefail
cd "$(dirname "$0")/.."

file="${1:-}"
[[ -n "$file" && -f "$file" ]] || { echo "Usage: $0 <backup.sql.gz> [--yes]" >&2; exit 2; }
gzip -t "$file"
if [[ "${2:-}" != "--yes" ]]; then
  read -r -p "This REPLACES the current IGuard database with $file. Type 'restore' to continue: " ans
  [[ "$ans" == "restore" ]] || { echo "Aborted."; exit 1; }
fi
docker compose stop backend
gunzip -c "$file" | docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose start backend
echo "Restore complete."
