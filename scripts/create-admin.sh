#!/usr/bin/env bash
# Creates an administrator inside the running backend container. The password is prompted for
# (never passed on the command line, so it does not show up in the process list).
set -euo pipefail
cd "$(dirname "$0")/.."

read -r -p "Email: " email
read -r -p "Username: " username
exec docker compose exec backend python -m app.cli create-admin --email "$email" --username "$username"
