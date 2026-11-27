from app.db import APP_SCHEMA, ensure_app_schema, migration_advisory_lock
from sqlalchemy import text


def test_app_schema_name():
    assert APP_SCHEMA == "user_mgmt"


def test_ensure_app_schema_idempotent(engine):
    with engine.connect() as conn:
        ensure_app_schema(conn)
        ensure_app_schema(conn)
        conn.commit()
        exists = conn.execute(
            text("SELECT 1 FROM pg_namespace WHERE nspname = :n"),
            {"n": APP_SCHEMA},
        ).scalar()
        assert exists == 1


def test_migration_advisory_lock_roundtrip(engine):
    with engine.connect() as conn:
        with migration_advisory_lock(conn):
            pass
        with migration_advisory_lock(conn):
            pass
