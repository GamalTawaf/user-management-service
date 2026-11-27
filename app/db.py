from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# Application data schema (not Postgres' default `public`).
APP_SCHEMA = "user_mgmt"

# Session-level lock so concurrent `alembic upgrade` (api + outbox-worker) serialize.
_MIGRATION_LOCK_KEY = 872_014_01

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"options": f"-csearch_path={APP_SCHEMA}"},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    metadata = MetaData(schema=APP_SCHEMA)


def ensure_app_schema(connection: Connection) -> None:
    """Create APP_SCHEMA; tolerate races (CREATE SCHEMA IF NOT EXISTS is not atomic)."""
    ddl = f"""
        DO $ums$ BEGIN
            CREATE SCHEMA IF NOT EXISTS {APP_SCHEMA};
        EXCEPTION
            WHEN duplicate_schema THEN NULL;
            WHEN unique_violation THEN NULL;
        END $ums$;
        """
    stmt = text(ddl)
    connection.execute(stmt)


@contextmanager
def migration_advisory_lock(connection: Connection) -> Iterator[None]:
    lock_stmt = text(f"SELECT pg_advisory_lock({_MIGRATION_LOCK_KEY})")
    unlock_stmt = text(f"SELECT pg_advisory_unlock({_MIGRATION_LOCK_KEY})")
    connection.execute(lock_stmt)
    connection.commit()
    try:
        yield
    finally:
        connection.execute(unlock_stmt)
        connection.commit()


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
