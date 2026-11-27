from __future__ import annotations

import fcntl
import os
import tempfile
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Enum as SAEnum
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://ums:ums@localhost:5432/user_mgmt")
os.environ.setdefault("JWT_SECRET", "test-secret-32-bytes-minimum!!!!")
# High ceiling so suite traffic never trips the shared in-process bucket.
os.environ.setdefault("RATE_LIMIT_CAPACITY", "100000")
os.environ.setdefault("RATE_LIMIT_REFILL_PER_SECOND", "1000")
os.environ.setdefault("REDIS_URL", "")

from app.audit import models as _audit_models  # noqa: F401
from app.config import settings
from app.db import APP_SCHEMA, Base, get_db
from app.identity.auth import mint_token
from app.identity.models import User, UserRole, UserStatus
from app.main import app
from app.orgs.models import Organization
from app.outbox import models as _outbox_models  # noqa: F401
from app.users import idempotency as _idempotency_models  # noqa: F401

TEST_SCHEMA = f"test_{APP_SCHEMA}"
_MUTMUT_SLOT_LOCK_FD = None


def _bind_metadata_to_test_schema() -> None:
    Base.metadata.schema = TEST_SCHEMA
    for table in Base.metadata.tables.values():
        table.schema = TEST_SCHEMA
        for column in table.columns:
            col_type = column.type
            if isinstance(col_type, SAEnum):
                col_type.schema = TEST_SCHEMA


def _claim_mutmut_database_url(base_url: str) -> str:
    global _MUTMUT_SLOT_LOCK_FD
    if os.environ.get("MUTMUT_PARALLEL_DBS") != "1":
        return base_url

    n = int(os.environ.get("MUTMUT_MAX_CHILDREN", "4"))
    lock_dir = Path(tempfile.gettempdir()) / "ums-mutmut-slots"
    lock_dir.mkdir(exist_ok=True)
    url = make_url(base_url)
    for i in range(n):
        lock_path = lock_dir / f"slot_{i}.lock"
        fd = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fd.close()
            continue
        _MUTMUT_SLOT_LOCK_FD = fd
        return url.set(database=f"user_mgmt_mutmut_{i}").render_as_string(hide_password=False)
    raise RuntimeError(f"could not claim a mutmut DB slot among {n} (all busy)")


def _release_mutmut_slot() -> None:
    global _MUTMUT_SLOT_LOCK_FD
    fd = _MUTMUT_SLOT_LOCK_FD
    _MUTMUT_SLOT_LOCK_FD = None
    if fd is None:
        return
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    finally:
        fd.close()


@pytest.fixture(scope="session")
def engine():
    _bind_metadata_to_test_schema()
    db_url = _claim_mutmut_database_url(settings.database_url)
    eng = create_engine(
        db_url,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={TEST_SCHEMA}"},
    )
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))

    @event.listens_for(eng, "checkout")
    def _set_test_search_path(dbapi_conn, _connection_record, _connection_proxy):
        cursor = dbapi_conn.cursor()
        cursor.execute(f"SET search_path TO {TEST_SCHEMA}")
        cursor.close()

    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        with eng.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        eng.dispose()
        _release_mutmut_slot()


@pytest.fixture
def db(engine) -> Generator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(sess, trans):
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Generator[TestClient]:
    org = Organization(
        uuid=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        name="Acme Workspace",
        notification_email="ops@acme.example.com",
    )
    admin = User(
        uuid=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        email="admin@example.com",
        display_name="Ops Admin",
        role=UserRole.admin,
        status=UserStatus.active,
        org_id=org.uuid,
    )
    member = User(
        uuid=uuid.UUID("66666666-6666-6666-6666-666666666666"),
        email="member@example.com",
        display_name="Alex Member",
        role=UserRole.member,
        status=UserStatus.active,
        org_id=org.uuid,
    )
    auditor = User(
        uuid=uuid.UUID("77777777-7777-7777-7777-777777777777"),
        email="auditor@example.com",
        display_name="Audit Viewer",
        role=UserRole.auditor,
        status=UserStatus.active,
    )
    invited = User(
        uuid=uuid.UUID("88888888-8888-8888-8888-888888888888"),
        email="invited@example.com",
        display_name="Invited User",
        role=UserRole.member,
        status=UserStatus.invited,
        org_id=org.uuid,
    )
    db.add(org)
    db.flush()
    db.add_all([admin, member, auditor, invited])
    db.flush()
    tokens = {
        "admin": mint_token(admin),
        "member": mint_token(member),
        "auditor": mint_token(auditor),
    }

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        test_client.seed = {  # type: ignore[attr-defined]
            "org": org,
            "admin": admin,
            "member": member,
            "auditor": auditor,
            "invited": invited,
            "tokens": tokens,
        }
        try:
            yield test_client
        finally:
            app.dependency_overrides.pop(get_db, None)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def role_headers(client: TestClient, role: str) -> dict[str, str]:
    return auth(client.seed["tokens"][role])  # type: ignore[index]


def assert_has_error_code(
    response,
    code: str,
    *,
    field: str | None = None,
    message: str | None = None,
) -> dict:
    assert response.status_code == 422, response.text
    body = response.json()
    errors = body.get("errors") or []
    match = [e for e in errors if e.get("error_code") == code]
    assert match, body
    if field is not None:
        assert any(e.get("field") == field for e in match), body
    if message is not None:
        assert any(e.get("message") == message for e in match), body
    return body


def assert_detail(response, status_code: int, detail: str) -> dict:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert body.get("detail") == detail, body
    return body


def latest_audit(client, user_id: str, action: str) -> dict:
    audit = client.get(
        f"/v1/users/{user_id}/audit",
        headers=role_headers(client, "auditor"),
    )
    assert audit.status_code == 200, audit.text
    rows = [row for row in audit.json() if row["action"] == action]
    assert rows, audit.json()
    return rows[-1]


def encode_raw_jwt(payload: dict) -> str:
    import jwt

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def raw_token(**claims) -> str:
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    payload = {"exp": expires_at, **claims}
    return encode_raw_jwt(payload)
