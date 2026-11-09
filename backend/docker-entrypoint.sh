#!/bin/sh
# Waits for the database, applies migrations (idempotent) and starts the API.
set -eu
python - <<'PY'
import os, sys, time
from sqlalchemy import create_engine, text
url = os.environ["IGUARD_DATABASE_URL"]
for attempt in range(60):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("SELECT 1"))
        break
    except Exception as exc:  # noqa: BLE001
        print(f"waiting for database ({attempt + 1}/60): {type(exc).__name__}", flush=True)
        time.sleep(2)
else:
    sys.exit("database never became available")
PY
alembic upgrade head
if [ "${IGUARD_SEED_DEMO:-false}" = "true" ]; then python -m app.cli seed; fi
python -m app.cli validate-config
exec "$@"
