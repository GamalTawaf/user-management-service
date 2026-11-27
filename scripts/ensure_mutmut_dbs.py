#!/usr/bin/env python3
"""Create user_mgmt_mutmut_0 .. N-1 for parallel mutmut children."""

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
        "postgresql+psycopg://ums:ums@localhost:5433/user_mgmt",
    )
    url = make_url(base)
    admin_url = url.set(database="postgres")
    engine = create_engine(
        admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )

    with engine.connect() as conn:
        for i in range(n):
            name = f"user_mgmt_mutmut_{i}"
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": name},
            ).scalar()
            if exists:
                print(f"exists {name}")
                continue
            conn.execute(text(f'CREATE DATABASE "{name}"'))
            print(f"created {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
