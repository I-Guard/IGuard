#!/usr/bin/env bash
# Allowlisted recovery script (demo). Receives NO arguments from IGuard and must be idempotent.
# Real deployments would flush an application cache; the demo only reports success.
set -euo pipefail
echo "clear-demo-cache: nothing to clear in the synthetic demo (idempotent no-op)"
