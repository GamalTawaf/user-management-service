"""Idempotency-Key on POST /v1/prior-auths (feat-011)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import (
    role_headers,
    submit_as_office,
    submit_ok,
    submit_with_idempotency_key,
)


def _office_list(client) -> list[dict]:
    response = client.get("/v1/prior-auths", headers=role_headers(client, "office"))
    assert response.status_code == 200, response.text
    return response.json()


def test_missing_header_creates_two_rows(client):
    first = submit_ok(client)
    second = submit_ok(client)
    assert first["uuid"] != second["uuid"]
    assert len(_office_list(client)) == 2


def test_same_key_same_body_replays_201(client):
    first = submit_with_idempotency_key(client, "retry-1")
    second = submit_with_idempotency_key(client, "retry-1")
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json() == second.json()
    assert len(_office_list(client)) == 1


def test_same_key_different_body_409(client):
    first = submit_with_idempotency_key(client, "reuse-1", clinical_note="alpha")
    assert first.status_code == 201, first.text
    second = submit_with_idempotency_key(client, "reuse-1", clinical_note="beta")
    assert second.status_code == 409, second.text
    payload = second.json()
    assert payload["detail"]
    codes = [e["error_code"] for e in payload["errors"]]
    assert "idempotency_key_reuse" in codes
    assert len(_office_list(client)) == 1


def test_different_keys_create_two_rows(client):
    a = submit_with_idempotency_key(client, "key-a")
    b = submit_with_idempotency_key(client, "key-b")
    assert a.status_code == 201, a.text
    assert b.status_code == 201, b.text
    assert a.json()["uuid"] != b.json()["uuid"]
    assert len(_office_list(client)) == 2


def test_empty_key_400(client):
    response = submit_with_idempotency_key(client, "   ")
    assert response.status_code == 400, response.text
    codes = [e["error_code"] for e in response.json()["errors"]]
    assert "idempotency_key_invalid" in codes
    assert _office_list(client) == []


def test_oversized_key_400(client):
    response = submit_with_idempotency_key(client, "x" * 256)
    assert response.status_code == 400, response.text
    codes = [e["error_code"] for e in response.json()["errors"]]
    assert "idempotency_key_invalid" in codes


def test_openapi_documents_idempotency_key_header(client):
    spec = client.app.openapi()
    post = spec["paths"]["/v1/prior-auths"]["post"]
    params = post.get("parameters") or []
    names = {p.get("name") for p in params}
    assert "Idempotency-Key" in names
    header = next(p for p in params if p["name"] == "Idempotency-Key")
    assert header["in"] == "header"
    assert header.get("required") is not True


def test_openapi_documents_problem_body_for_submit_errors(client):
    """Swagger must match live ConflictError / validation JSON (not HTTPValidationError)."""
    spec = client.app.openapi()
    schemas = spec["components"]["schemas"]
    assert "ProblemBody" in schemas
    assert "FieldError" in schemas
    problem = schemas["ProblemBody"]["properties"]
    assert "detail" in problem
    assert "errors" in problem
    assert "correlation_id" in problem
    field_error = schemas["FieldError"]["properties"]
    assert set(field_error) >= {"error_code", "field", "message"}

    post = spec["paths"]["/v1/prior-auths"]["post"]
    for code in ("400", "401", "403", "404", "409", "422"):
        assert code in post["responses"]
        content = post["responses"][code]["content"]["application/json"]
        ref = content["schema"].get("$ref", "")
        assert ref.endswith("/ProblemBody"), (
            f"{code} should use ProblemBody, got {content['schema']}"
        )

    example = post["responses"]["409"]["content"]["application/json"].get("example")
    assert example is not None
    assert example["errors"][0]["error_code"] == "idempotency_key_reuse"


def test_openapi_partner_routes_use_problem_body_not_http_validation_error(client):
    spec = client.app.openapi()
    error_codes = ("400", "401", "403", "404", "409", "422")
    for path, methods in spec["paths"].items():
        if path == "/v1/health":
            continue
        for method, op in methods.items():
            if method.startswith("x-"):
                continue
            responses = op.get("responses") or {}
            for code in error_codes:
                assert code in responses, f"{method.upper()} {path} missing {code}"
                schema = (
                    responses[code].get("content", {}).get("application/json", {}).get("schema")
                    or {}
                )
                ref = schema.get("$ref", "")
                assert ref.endswith("/ProblemBody"), f"{method.upper()} {path} {code} → {schema}"
            # FastAPI must not leave the default validation schema in place.
            for code, resp in responses.items():
                schema = (resp.get("content") or {}).get("application/json", {}).get("schema") or {}
                ref = schema.get("$ref", "")
                assert not ref.endswith("/HTTPValidationError"), (
                    f"{method.upper()} {path} {code} still HTTPValidationError"
                )


def test_no_header_still_works_alongside_keyed(client):
    keyed = submit_with_idempotency_key(client, "solo-key")
    plain = submit_as_office(client)
    assert keyed.status_code == 201, keyed.text
    assert plain.status_code == 201, plain.text
    assert keyed.json()["uuid"] != plain.json()["uuid"]
    assert len(_office_list(client)) == 2


def test_integrity_error_replays_stored_winner(client, monkeypatch: pytest.MonkeyPatch):
    first = submit_with_idempotency_key(client, "race-win")
    assert first.status_code == 201, first.text
    body = first.json()

    from app.prior_auth.idempotency import IdempotencyRecord, body_hash
    from app.prior_auth.schemas import SubmitPriorAuthIn

    from tests.conftest import valid_submit_body

    payload = valid_submit_body(client.seed)
    submit_in = SubmitPriorAuthIn.model_validate(payload)
    request_hash = body_hash(submit_in)
    winner = IdempotencyRecord(
        practice_id=client.seed["practice"].uuid,
        key="race-win",
        request_hash=request_hash,
        response_status=201,
        response_body=body,
        request_id=body["uuid"],
    )
    lookups = {"n": 0}

    def flaky_get(_db, _practice_id, _key):
        lookups["n"] += 1
        if lookups["n"] == 1:
            return None
        return winner

    def boom(*_args, **_kwargs):
        raise IntegrityError("INSERT", {}, Exception("unique"))

    monkeypatch.setattr("app.prior_auth.router.get_record", flaky_get)
    monkeypatch.setattr("app.prior_auth.router.submit_prior_auth", boom)
    second = submit_with_idempotency_key(client, "race-win")
    assert second.status_code == 201, second.text
    assert second.json() == body


def test_integrity_error_without_key_reraises(client, monkeypatch: pytest.MonkeyPatch):
    def boom(*_args, **_kwargs):
        raise IntegrityError("INSERT", {}, Exception("other"))

    monkeypatch.setattr("app.prior_auth.router.submit_prior_auth", boom)
    with pytest.raises(IntegrityError):
        submit_as_office(client)


def test_integrity_error_missing_record_reraises(client, monkeypatch: pytest.MonkeyPatch):
    def boom(*_args, **_kwargs):
        raise IntegrityError("INSERT", {}, Exception("unique"))

    def no_record(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.prior_auth.router.submit_prior_auth", boom)
    monkeypatch.setattr("app.prior_auth.router.get_record", no_record)
    with pytest.raises(IntegrityError):
        submit_with_idempotency_key(client, "ghost-key")


def test_orphan_office_with_idempotency_key_still_validates(client, db):
    import uuid

    from app.identity.auth import mint_token
    from app.identity.models import User, UserRole

    from tests.conftest import assert_has_error_code, auth, valid_submit_body

    orphan = User(
        uuid=uuid.uuid4(),
        email=f"orphan-idem-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.provider_office,
        practice_id=None,
        display_name="Orphan",
    )
    db.add(orphan)
    db.flush()
    response = client.post(
        "/v1/prior-auths",
        headers={**auth(mint_token(orphan)), "Idempotency-Key": "orphan-key"},
        json=valid_submit_body(client.seed),
    )
    assert_has_error_code(
        response,
        "missing_practice",
        field="actor",
        message="Office user must belong to a practice",
    )


def test_submit_with_key_but_no_hash_skips_store(client, db):
    """Direct service call: key without hash must not write an idempotency row.

    Kills `and`→`or` on the store guard (HTTP always pairs key+hash).
    """
    from app.identity.schemas import UserContext
    from app.prior_auth.idempotency import IdempotencyRecord, get_record
    from app.prior_auth.schemas import SubmitPriorAuthIn
    from app.prior_auth.services.submit import submit_prior_auth
    from sqlalchemy import func, select

    from tests.conftest import valid_submit_body

    office = client.seed["office"]
    ctx = UserContext(
        user_id=office.uuid,
        role=office.role,
        practice_id=office.practice_id,
        email=office.email,
    )
    body = SubmitPriorAuthIn.model_validate(valid_submit_body(client.seed))
    request = submit_prior_auth(
        db,
        ctx,
        body,
        idempotency_key="no-hash-key",
        request_hash=None,
    )
    assert request.uuid is not None
    assert get_record(db, office.practice_id, "no-hash-key") is None
    count = db.scalar(select(func.count()).select_from(IdempotencyRecord))
    assert count == 0


def test_integrity_error_orphan_key_reraises(client, db, monkeypatch: pytest.MonkeyPatch):
    """key set but practice_id missing → request_hash stays None → re-raise."""
    import uuid

    from app.identity.auth import mint_token
    from app.identity.models import User, UserRole

    from tests.conftest import auth, valid_submit_body

    orphan = User(
        uuid=uuid.uuid4(),
        email=f"orphan-race-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.provider_office,
        practice_id=None,
        display_name="Orphan",
    )
    db.add(orphan)
    db.flush()

    def boom(*_args, **_kwargs):
        raise IntegrityError("INSERT", {}, Exception("unique"))

    monkeypatch.setattr("app.prior_auth.router.submit_prior_auth", boom)
    with pytest.raises(IntegrityError):
        client.post(
            "/v1/prior-auths",
            headers={**auth(mint_token(orphan)), "Idempotency-Key": "orphan-race"},
            json=valid_submit_body(client.seed),
        )
