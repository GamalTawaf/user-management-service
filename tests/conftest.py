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

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://prior:prior@localhost:5432/prior_auth")
os.environ.setdefault("JWT_SECRET", "test-secret-32-bytes-minimum!!!!")

from app.audit import models as _audit_models  # noqa: F401
from app.clock import get_today
from app.config import settings
from app.db import APP_SCHEMA, Base, get_db
from app.identity.auth import mint_token
from app.identity.models import User, UserRole
from app.intake import models as _intake_models  # noqa: F401
from app.main import app
from app.master_data.models import (
    Coverage,
    Member,
    PatientPracticeLink,
    Practice,
    ReviewerMemberConflict,
)
from app.outbox import models as _outbox_models  # noqa: F401
from app.prior_auth import idempotency as _idempotency_models  # noqa: F401
from app.prior_auth import models as _pa_models  # noqa: F401

# App/dev data: `prior_auth`. Pytest uses the same name with a `test_` prefix.
TEST_SCHEMA = f"test_{APP_SCHEMA}"

# Held open for the pytest session so flock stays exclusive until teardown.
_MUTMUT_SLOT_LOCK_FD = None


def _bind_metadata_to_test_schema() -> None:
    """Qualify tables + PG enums so empty mutmut DBs need only test_prior_auth."""
    Base.metadata.schema = TEST_SCHEMA
    for table in Base.metadata.tables.values():
        table.schema = TEST_SCHEMA
        for column in table.columns:
            col_type = column.type
            if isinstance(col_type, SAEnum):
                col_type.schema = TEST_SCHEMA


def _claim_mutmut_database_url(base_url: str) -> str:
    """Exclusive slot → prior_auth_mutmut_{i} so parallel mutmut children do not race."""
    global _MUTMUT_SLOT_LOCK_FD
    if os.environ.get("MUTMUT_PARALLEL_DBS") != "1":
        return base_url

    n = int(os.environ.get("MUTMUT_MAX_CHILDREN", "4"))
    lock_dir = Path(tempfile.gettempdir()) / "prior-auth-mutmut-slots"
    lock_dir.mkdir(exist_ok=True)
    url = make_url(base_url)
    for i in range(n):
        lock_path = lock_dir / f"slot_{i}.lock"
        # Keep fd open until session teardown so the flock stays exclusive.
        fd = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fd.close()
            continue
        _MUTMUT_SLOT_LOCK_FD = fd
        return url.set(database=f"prior_auth_mutmut_{i}").render_as_string(hide_password=False)
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
        drop = text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
        create = text(f"CREATE SCHEMA {TEST_SCHEMA}")
        conn.execute(drop)
        conn.execute(create)

    @event.listens_for(eng, "checkout")
    def _set_test_search_path(dbapi_conn, _connection_record, _connection_proxy):
        # Re-apply on every checkout; pool reset can restore the default path.
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
def seed_data(db: Session) -> dict:
    practice = Practice(
        uuid=uuid.uuid4(),
        name="Test Practice",
        notification_email="notify-test@example.com",
    )
    member = Member(
        uuid=uuid.uuid4(),
        external_id=f"M-{uuid.uuid4().hex[:8]}",
        full_name="Pat Member",
    )
    unlinked = Member(
        uuid=uuid.uuid4(), external_id=f"U-{uuid.uuid4().hex[:8]}", full_name="Unlinked"
    )
    db.add_all([practice, member, unlinked])
    db.flush()
    db.add(PatientPracticeLink(member_id=member.uuid, practice_id=practice.uuid))
    today = get_today()
    db.add(
        Coverage(
            member_id=member.uuid,
            payer_name="Payer",
            effective_from=today - timedelta(days=10),
            effective_to=today + timedelta(days=400),
        )
    )
    office = User(
        uuid=uuid.uuid4(),
        email=f"office-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.provider_office,
        practice_id=practice.uuid,
        display_name="Office",
    )
    reviewer = User(
        uuid=uuid.uuid4(),
        email=f"rev-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.reviewer,
        display_name="Reviewer",
    )
    reviewer2 = User(
        uuid=uuid.uuid4(),
        email=f"rev2-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.reviewer,
        display_name="Reviewer2",
    )
    reviewer_coi = User(
        uuid=uuid.uuid4(),
        email=f"coi-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.reviewer,
        display_name="COI Reviewer",
    )
    admin = User(
        uuid=uuid.uuid4(),
        email=f"admin-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.ops_admin,
        display_name="Admin",
    )
    auditor = User(
        uuid=uuid.uuid4(),
        email=f"auditor-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.auditor,
        display_name="Auditor",
    )
    member_user = User(
        uuid=uuid.uuid4(),
        email=f"mem-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.member,
        member_id=member.uuid,
        display_name="Member",
    )
    db.add_all([office, reviewer, reviewer2, reviewer_coi, admin, auditor, member_user])
    db.flush()
    db.add(ReviewerMemberConflict(reviewer_user_id=reviewer_coi.uuid, member_id=member.uuid))
    db.flush()
    return {
        "practice": practice,
        "member": member,
        "unlinked": unlinked,
        "office": office,
        "reviewer": reviewer,
        "reviewer2": reviewer2,
        "reviewer_coi": reviewer_coi,
        "admin": admin,
        "auditor": auditor,
        "member_user": member_user,
        "tokens": {
            "office": mint_token(office),
            "reviewer": mint_token(reviewer),
            "reviewer2": mint_token(reviewer2),
            "reviewer_coi": mint_token(reviewer_coi),
            "admin": mint_token(admin),
            "auditor": mint_token(auditor),
            "member": mint_token(member_user),
        },
    }


@pytest.fixture
def client(db: Session, seed_data: dict) -> Generator[TestClient]:
    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        c.seed = seed_data  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


TWO_PROCEDURES = [
    {"code": "99213", "units": 1},
    {"code": "99214", "units": 2},
]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def role_headers(client: TestClient, role: str) -> dict[str, str]:
    return auth(client.seed["tokens"][role])


def valid_submit_body(seed: dict, **overrides) -> dict:
    body = {
        "member_id": str(seed["member"].uuid),
        "diagnosis_icd10": "J06.9",
        "date_of_service": get_today().isoformat(),
        "clinical_note": "Patient needs procedure",
        "procedures": [{"code": "99213", "units": 1}],
    }
    body.update(overrides)
    return body


def assert_has_error_code(
    response,
    error_code: str,
    *,
    field: str | None = None,
    message: str | None = None,
    message_contains: str | None = None,
) -> dict:
    assert response.status_code == 422, response.text
    payload = response.json()
    matches = [e for e in payload["errors"] if e["error_code"] == error_code]
    assert matches, payload
    match = matches[0]
    assert isinstance(match.get("message"), str) and match["message"], match
    if field is not None:
        assert match["field"] == field, match
    if message is not None:
        assert match["message"] == message, match
    if message_contains is not None:
        assert message_contains in match["message"], match
    return payload


def submit_as_office(client: TestClient, **overrides):
    response = client.post(
        "/v1/prior-auths",
        headers=role_headers(client, "office"),
        json=valid_submit_body(client.seed, **overrides),
    )
    return response


def submit_with_idempotency_key(client: TestClient, key: str, **overrides):
    headers = {**role_headers(client, "office"), "Idempotency-Key": key}
    return client.post(
        "/v1/prior-auths",
        headers=headers,
        json=valid_submit_body(client.seed, **overrides),
    )


def submit_ok(client: TestClient, **overrides) -> dict:
    response = submit_as_office(client, **overrides)
    assert response.status_code == 201, response.text
    return response.json()


def claim_as(client: TestClient, request_id: str, role: str = "reviewer"):
    return client.post(
        f"/v1/prior-auths/{request_id}/claim",
        headers=role_headers(client, role),
    )


def get_as(client: TestClient, request_id: str, role: str):
    return client.get(
        f"/v1/prior-auths/{request_id}",
        headers=role_headers(client, role),
    )


def decide_as(client: TestClient, request_id: str, outcomes: list[dict], role: str = "reviewer"):
    return client.post(
        f"/v1/prior-auths/{request_id}/decision",
        headers=role_headers(client, role),
        json={"outcomes": outcomes},
    )


def reassign_as(client: TestClient, request_id: str, reviewer_id, role: str = "admin"):
    return client.post(
        f"/v1/prior-auths/{request_id}/reassign",
        headers=role_headers(client, role),
        json={"reviewer_id": str(reviewer_id)},
    )


def submit_and_claim(client: TestClient, **overrides) -> dict:
    created = submit_ok(client, **overrides)
    claimed = claim_as(client, created["uuid"])
    assert claimed.status_code == 200, claimed.text
    return claimed.json()


def approve_all_outcomes(procedures: list[dict]) -> list[dict]:
    return [{"procedure_id": p["uuid"], "decision": "approved"} for p in procedures]


def get_intake_rejection_as(client: TestClient, correlation_id: str, role: str = "office"):
    return client.get(
        f"/v1/support/intake-rejections/{correlation_id}",
        headers=role_headers(client, role),
    )


def get_audit_as(client: TestClient, request_id: str, role: str = "admin"):
    return client.get(
        f"/v1/prior-auths/{request_id}/audit",
        headers=role_headers(client, role),
    )


def workload_as(client: TestClient, role: str = "admin"):
    return client.get(
        "/v1/reviewers/workload",
        headers=role_headers(client, role),
    )


def race_attempt(fn):
    """Wrap a side-effecting call: success → 'won', ConflictError → 'lost'."""
    from app.shared.errors import ConflictError

    def _run() -> str:
        try:
            fn()
            return "won"
        except ConflictError:
            return "lost"

    return _run


def make_other_office(db: Session, *, name: str = "Other") -> User:
    practice = Practice(
        uuid=uuid.uuid4(),
        name=name,
        notification_email=f"notify-{uuid.uuid4().hex[:6]}@ex.com",
    )
    db.add(practice)
    db.flush()
    office = User(
        uuid=uuid.uuid4(),
        email=f"other-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.provider_office,
        practice_id=practice.uuid,
        display_name=name,
    )
    db.add(office)
    db.flush()
    return office


def encode_raw_jwt(payload: dict) -> str:
    import jwt

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def raw_token(**claims) -> str:
    """Hand-built JWT that is unexpired unless the caller overrides `exp`."""
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    payload = {"exp": expires_at}
    payload.update(claims)
    return encode_raw_jwt(payload)


def seed_race_fixture(
    engine,
    *,
    status,
    claimed_by_reviewer: bool = False,
    name: str = "Race",
) -> dict:
    """Standalone committed graph for concurrency tests (outside the nested-tx fixture)."""
    from app.prior_auth.models import PriorAuthProcedure, PriorAuthRequest

    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with SessionLocal() as db:
        practice = Practice(
            uuid=uuid.uuid4(),
            name=f"{name} Practice",
            notification_email=f"notify-{uuid.uuid4().hex[:6]}@ex.com",
        )
        member = Member(
            uuid=uuid.uuid4(),
            external_id=f"{name[0]}-{uuid.uuid4().hex[:6]}",
            full_name=name,
        )
        db.add_all([practice, member])
        db.flush()
        db.add(PatientPracticeLink(member_id=member.uuid, practice_id=practice.uuid))
        today = get_today()
        db.add(
            Coverage(
                member_id=member.uuid,
                payer_name="P",
                effective_from=today - timedelta(days=1),
                effective_to=today + timedelta(days=30),
            )
        )
        office = User(
            uuid=uuid.uuid4(),
            email=f"o-{uuid.uuid4().hex[:6]}@ex.com",
            role=UserRole.provider_office,
            practice_id=practice.uuid,
            display_name="O",
        )
        r1 = User(
            uuid=uuid.uuid4(),
            email=f"r1-{uuid.uuid4().hex[:6]}@ex.com",
            role=UserRole.reviewer,
            display_name="R1",
        )
        r2 = User(
            uuid=uuid.uuid4(),
            email=f"r2-{uuid.uuid4().hex[:6]}@ex.com",
            role=UserRole.reviewer,
            display_name="R2",
        )
        db.add_all([office, r1, r2])
        db.flush()
        claimed_by = r1.uuid if claimed_by_reviewer else None
        request = PriorAuthRequest(
            uuid=uuid.uuid4(),
            member_id=member.uuid,
            practice_id=practice.uuid,
            submitted_by_user_id=office.uuid,
            diagnosis_icd10="J06.9",
            date_of_service=today,
            status=status,
            claimed_by_user_id=claimed_by,
        )
        proc = PriorAuthProcedure(code="99213", units=1, sequence=1)
        request.procedures.append(proc)
        db.add(request)
        db.commit()
        return {
            "session_factory": SessionLocal,
            "request_id": request.uuid,
            "procedure_id": proc.uuid,
            "reviewer1_id": r1.uuid,
            "reviewer2_id": r2.uuid,
            "office_id": office.uuid,
        }


def run_two_thread_race(targets: list) -> list[str]:
    """Run two callables behind a barrier; each returns 'won' or 'lost'."""
    import threading

    outcomes: list[str] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def wrap(fn) -> None:
        barrier.wait(timeout=5)
        result = fn()
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=wrap, args=(fn,), daemon=True) for fn in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    return outcomes
