#!/usr/bin/env python3
"""Create prior_auth_mutmut_0 .. N-1 for parallel mutmut children."""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url


def main() -> int:
    n = int(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MUTMUT_MAX_CHILDREN", "4"))
    if n < 1:
        print("MUTMUT_MAX_CHILDREN must be >= 1", file=sys.stderr)
        return 1

    base = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://prior:prior@localhost:5432/prior_auth",
    )
    url = make_url(base)
    # CREATE DATABASE cannot run inside a transaction against the target DB.
    admin_url = url.set(database="postgres")
    engine = create_engine(
        admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )

    with engine.connect() as conn:
        for i in range(n):
            name = f"prior_auth_mutmut_{i}"
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": name},
            ).scalar()
            if exists:
                print(f"exists {name}")
                continue
            # Name is controlled (prefix + digit index only).
            conn.execute(text(f'CREATE DATABASE "{name}"'))
            print(f"created {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
