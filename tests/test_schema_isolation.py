"""App schema `prior_auth` must stay untouched by the pytest engine fixture."""

from __future__ import annotations

from app.db import APP_SCHEMA
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.conftest import TEST_SCHEMA


def test_pytest_uses_test_prefixed_app_schema():
    assert TEST_SCHEMA.startswith("test_")
    assert TEST_SCHEMA.removeprefix("test_") == APP_SCHEMA
    assert TEST_SCHEMA == "test_prior_auth"
    assert APP_SCHEMA == "prior_auth"


def test_engine_search_path_is_test_schema(engine: Engine):
    with engine.connect() as conn:
        path = conn.execute(text("SHOW search_path")).scalar_one()
    parts = {p.strip().strip('"') for p in path.split(",")}
    assert TEST_SCHEMA in parts


def test_orm_tables_created_in_test_schema(engine: Engine):
    from app.db import Base

    assert Base.metadata.schema == TEST_SCHEMA
    with engine.connect() as conn:
        schemas = (
            conn.execute(
                text(
                    "SELECT table_schema FROM information_schema.tables "
                    "WHERE table_name = 'users' ORDER BY table_schema"
                )
            )
            .scalars()
            .all()
        )
    assert TEST_SCHEMA in schemas


def test_app_schema_not_dropped_by_engine_fixture(engine: Engine):
    """Marker in prior_auth must survive the session-scoped test engine lifecycle."""
    marker = "_pytest_isolation_marker"
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {APP_SCHEMA}"))
        conn.execute(text(f'CREATE TABLE IF NOT EXISTS {APP_SCHEMA}."{marker}" (id int)'))
        conn.commit()
    with engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_name = :name"
            ),
            {"schema": APP_SCHEMA, "name": marker},
        ).scalar_one_or_none()
        conn.execute(text(f'DROP TABLE IF EXISTS {APP_SCHEMA}."{marker}"'))
        conn.commit()
    assert exists == 1
