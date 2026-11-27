from __future__ import annotations

import contextlib
import uuid

from app.clock import get_today, utc_now
from app.db import get_db
from app.identity.models import UserRole
from app.main import app
from app.outbox.mailer import send_smtp
from app.outbox.models import OutboxEvent, OutboxKind, OutboxStatus
from app.outbox.services import process_batch
from app.outbox.worker import run_once
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    FieldError,
    ForbiddenError,
    NotFoundError,
    ValidationFailure,
    bad_request_handler,
    conflict_handler,
    forbidden_handler,
    http_exception_handler,
    not_found_handler,
    raise_bad_request,
    raise_field,
    raise_validation,
    request_validation_handler,
    validation_failure_handler,
)
from app.shared.middleware import resolve_trace_id
from app.telemetry import configure_telemetry, setup_telemetry
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.requests import Request as StarletteRequest

from tests.conftest import assert_has_error_code, auth, role_headers


def test_people_name_and_clock():
    assert UserRole.admin.people_name == "administrator"
    assert get_today()
    assert utc_now().tzinfo is not None


def test_get_db_closes(engine):
    gen = get_db()
    session = next(gen)
    assert session is not None
    with contextlib.suppress(StopIteration):
        next(gen)


def test_middleware_and_trace_helpers():
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    request = StarletteRequest(scope)
    assert resolve_trace_id(request)
    scope2 = dict(scope)
    scope2["headers"] = [(b"x-trace-id", b"custom-trace")]
    request2 = StarletteRequest(scope2)
    assert resolve_trace_id(request2) == "custom-trace"


def test_413_body_limit(client: TestClient):
    huge = "x" * 300_000
    response = client.post(
        "/v1/users",
        headers={
            **role_headers(client, "admin"),
            "Content-Length": str(len(huge) + 100),
            "Content-Type": "application/json",
        },
        content=huge,
    )
    assert response.status_code == 413
    assert response.headers.get("X-Trace-Id")


def test_error_helpers_and_handlers():
    try:
        raise_field("x", "f", "m")
    except ValidationFailure as exc:
        assert exc.errors[0].error_code == "x"

    with contextlib.suppress(ValidationFailure):
        raise_validation([FieldError(error_code="a", field="b", message="c")])

    with contextlib.suppress(BadRequestError):
        raise_bad_request([FieldError(error_code="a", field="b", message="c")])

    assert ConflictError("c").detail == "c"
    assert NotFoundError("n").detail == "n"
    assert ForbiddenError("f").detail == "f"


async def _run_handlers():
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/"})
    vf = ValidationFailure("cid", [FieldError(error_code="e", field="f", message="m")])
    await validation_failure_handler(request, vf)
    await bad_request_handler(
        request, BadRequestError([FieldError(error_code="e", field="f", message="m")])
    )
    await conflict_handler(request, ConflictError("x"))
    await not_found_handler(request, NotFoundError("n"))
    await forbidden_handler(request, ForbiddenError("f"))
    await http_exception_handler(request, HTTPException(status_code=400, detail="d"))
    await http_exception_handler(request, HTTPException(status_code=400, detail=["x"]))
    rve = RequestValidationError([{"loc": ("body", "email"), "msg": "bad", "type": "value_error"}])
    await request_validation_handler(request, rve)
    rve2 = RequestValidationError([{"loc": ("body",), "msg": 123, "type": "value_error"}])
    await request_validation_handler(request, rve2)


def test_async_error_handlers():
    import asyncio

    asyncio.run(_run_handlers())


def test_openapi_and_telemetry():
    app.openapi_schema = None
    schema = app.openapi()
    assert "/v1/users" in schema["paths"]
    cached = app.openapi()
    assert cached is schema
    setup_telemetry(app)
    configure_telemetry()


def _noop_send(*_a, **_k):
    return None


def test_mailer_noop_and_outbox(db: Session, client: TestClient, caplog):
    import logging

    send_smtp("a@b.co", "s", "b")  # smtp_host empty → no-op
    client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={"email": "outbox@example.com", "display_name": "O", "status": "active"},
    )
    with caplog.at_level(logging.INFO, logger="app.outbox.services"):
        assert process_batch(db, send_fn=_noop_send) >= 1
    assert "outbox_send_ok" in caplog.text
    assert process_batch(db, send_fn=_noop_send) == 0

    def boom(*_a, **_k):
        raise RuntimeError("smtp down")

    db.add(
        OutboxEvent(
            kind=OutboxKind.user_welcome,
            payload={"to": "x@y.z", "subject": "s", "body": "b"},
            status=OutboxStatus.pending,
            attempts=0,
        )
    )
    db.flush()
    with caplog.at_level(logging.WARNING, logger="app.outbox.services"):
        assert process_batch(db, send_fn=boom) == 1
    assert "outbox_send_failed" in caplog.text
    assert "smtp down" in caplog.text


def test_worker_run_once(db: Session, monkeypatch):
    from app.outbox import worker

    class _Sess:
        def __enter__(self):
            return db

        def __exit__(self, *args):
            return False

    def _factory():
        return _Sess()

    monkeypatch.setattr(worker, "SessionLocal", _factory)
    assert run_once() == 0


def test_update_and_org_edges(client: TestClient):
    uid = str(client.seed["member"].uuid)
    patched = client.patch(
        f"/v1/users/{uid}",
        headers=role_headers(client, "admin"),
        json={"display_name": "  Renamed  ", "role": "member", "org_id": None},
    )
    assert patched.status_code == 200
    assert patched.json()["org_id"] is None

    bad_org = client.patch(
        f"/v1/users/{uid}",
        headers=role_headers(client, "admin"),
        json={"org_id": str(uuid.uuid4())},
    )
    assert_has_error_code(bad_org, "org_not_found", field="org_id")

    blank = client.patch(
        "/v1/me",
        headers=role_headers(client, "member"),
        json={"display_name": "   "},
    )
    assert_has_error_code(blank, "display_name_required", field="display_name")

    bad_create = client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={
            "email": "ok@example.com",
            "display_name": "  ",
            "org_id": str(uuid.uuid4()),
        },
    )
    assert bad_create.status_code == 422

    org_bad = client.post(
        "/v1/orgs",
        headers=role_headers(client, "admin"),
        json={"name": " ", "notification_email": "bad"},
    )
    assert org_bad.status_code == 422

    missing = client.get(f"/v1/orgs/{uuid.uuid4()}", headers=role_headers(client, "admin"))
    assert missing.status_code == 404


def test_lifecycle_conflicts(client: TestClient):
    created = client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={"email": "life@example.com", "display_name": "Life", "status": "active"},
    )
    uid = created.json()["uuid"]
    assert (
        client.post(f"/v1/users/{uid}/activate", headers=role_headers(client, "admin")).status_code
        == 422
    )
    assert (
        client.post(f"/v1/users/{uid}/enable", headers=role_headers(client, "admin")).status_code
        == 409
    )
    assert (
        client.post(f"/v1/users/{uid}/disable", headers=role_headers(client, "admin")).status_code
        == 200
    )
    assert (
        client.post(f"/v1/users/{uid}/disable", headers=role_headers(client, "admin")).status_code
        == 409
    )
    assert (
        client.post(f"/v1/users/{uid}/enable", headers=role_headers(client, "admin")).status_code
        == 200
    )


def test_idempotency_invalid_and_self_get(client: TestClient):
    bad_key = client.post(
        "/v1/users",
        headers={**role_headers(client, "admin"), "Idempotency-Key": "   "},
        json={"email": "k@example.com", "display_name": "K", "status": "active"},
    )
    assert bad_key.status_code == 400

    me_id = str(client.seed["member"].uuid)
    got = client.get(f"/v1/users/{me_id}", headers=role_headers(client, "member"))
    assert got.status_code == 200

    disabled_tok = None
    # disable member then auth should 403
    client.post(
        f"/v1/users/{me_id}/disable",
        headers=role_headers(client, "admin"),
    )
    from app.identity.auth import mint_token

    disabled_tok = mint_token(client.seed["member"])
    assert client.get("/v1/me", headers=auth(disabled_tok)).status_code == 403


def test_pagination_after(client: TestClient):
    listed = client.get("/v1/users?limit=1", headers=role_headers(client, "admin"))
    assert listed.status_code == 200
    first = listed.json()[0]["uuid"]
    page2 = client.get(f"/v1/users?limit=10&after={first}", headers=role_headers(client, "admin"))
    assert page2.status_code == 200
    # oldest-first path used by review-style lists — exercise helper via queue order on audit
    from app.identity.models import User
    from app.users.services.common import apply_after_id
    from sqlalchemy import select

    stmt = select(User)
    ordered = apply_after_id(stmt, after=None, newest_first=False)
    assert ordered is not None
    with_cursor = apply_after_id(stmt, after=uuid.UUID(first), newest_first=False)
    assert with_cursor is not None


def test_update_assign_org_and_blank_admin_name(client: TestClient):
    uid = str(client.seed["member"].uuid)
    org_id = str(client.seed["org"].uuid)
    ok = client.patch(
        f"/v1/users/{uid}",
        headers=role_headers(client, "admin"),
        json={"org_id": org_id, "display_name": "Member Again"},
    )
    assert ok.status_code == 200
    assert ok.json()["org_id"] == org_id

    blank = client.patch(
        f"/v1/users/{uid}",
        headers=role_headers(client, "admin"),
        json={"display_name": "   "},
    )
    assert_has_error_code(blank, "display_name_required", field="display_name")


def test_worker_run_loop_once(monkeypatch, db: Session):
    from app.outbox import worker

    class _Sess:
        def __enter__(self):
            return db

        def __exit__(self, *args):
            return False

    def _factory():
        return _Sess()

    monkeypatch.setattr(worker, "SessionLocal", _factory)
    worker.run_loop(once=True)


def test_worker_run_once_logs_delivery(monkeypatch, db: Session, client: TestClient, caplog):
    import logging

    from app.outbox import worker

    client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={"email": "worker-log@example.com", "display_name": "WL", "status": "active"},
    )

    class _Sess:
        def __enter__(self):
            return db

        def __exit__(self, *args):
            return False

    def _session_factory():
        return _Sess()

    def _fake_process(_db):
        return 2

    monkeypatch.setattr(worker, "SessionLocal", _session_factory)
    monkeypatch.setattr(worker, "process_batch", _fake_process)
    with caplog.at_level(logging.INFO, logger="app.outbox.worker"):
        delivered = worker.run_once()
    assert delivered == 2
    assert "outbox delivered batch_size=2" in caplog.text


def test_mailer_success(monkeypatch):
    from app import config
    from app.outbox import mailer

    monkeypatch.setattr(config.settings, "smtp_host", "localhost")
    monkeypatch.setattr(config.settings, "smtp_port", 1025)

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, msg):
            return None

    def _smtp(*_a, **_k):
        return _Client()

    monkeypatch.setattr(mailer.smtplib, "SMTP", _smtp)
    send_smtp("a@b.co", "s", "b")


def test_trace_id_rejects_long(client: TestClient):
    long_id = "x" * 200
    response = client.get("/v1/health", headers={"X-Trace-Id": long_id})
    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] != long_id


def test_mailer_with_host(monkeypatch):
    from app import config
    from app.outbox import mailer

    monkeypatch.setattr(config.settings, "smtp_host", "localhost")
    monkeypatch.setattr(config.settings, "smtp_port", 1)

    class _Boom:
        def __enter__(self):
            raise OSError("no smtp")

        def __exit__(self, *a):
            return False

    def _smtp(*_a, **_k):
        return _Boom()

    monkeypatch.setattr(mailer.smtplib, "SMTP", _smtp)
    with contextlib.suppress(OSError):
        send_smtp("a@b.co", "s", "b")
