#!/bin/sh
# Bring schema to head before serving. Seed remains a separate explicit step.
# Retry DB connect: Compose can mark Postgres healthy before Docker DNS
# registers the service hostname inside the API container.
set -eu

python - <<'PY'
import os
import sys
import time

from sqlalchemy import create_engine, text

url = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://prior:prior@db:5432/prior_auth",
)
engine = create_engine(url, pool_pre_ping=True)
deadline = time.monotonic() + 60
last_err = None
while time.monotonic() < deadline:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("database ready", flush=True)
        raise SystemExit(0)
    except Exception as exc:
        last_err = exc
        print(f"waiting for database: {exc}", flush=True)
        time.sleep(1)
print(f"database not reachable within 60s: {last_err}", file=sys.stderr)
raise SystemExit(1)
PY

alembic upgrade head
exec "$@"
