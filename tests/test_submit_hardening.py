"""Submit contract hardening: schema 422 shape, size caps, no cross-tenant probing."""

from __future__ import annotations

from app.clock import get_today
from app.intake.models import IntakeRejection
from app.master_data.models import Coverage
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import (
    assert_has_error_code,
    decide_as,
    get_intake_rejection_as,
    role_headers,
    submit_and_claim,
    submit_as_office,
    valid_submit_body,
)


def test_schema_type_error_uses_field_error_contract_and_persists(client: TestClient, db: Session):
    body = valid_submit_body(client.seed)
    body["member_id"] = "not-a-uuid"
    response = client.post(
        "/v1/prior-auths",
        headers=role_headers(client, "office"),
        json=body,
    )
    payload = assert_has_error_code(
        response,
        "invalid_type",
        field="member_id",
    )
    assert payload.get("correlation_id")
    assert isinstance(payload["detail"], str)

    support = get_intake_rejection_as(client, payload["correlation_id"])
    assert support.status_code == 200, support.text
    row = db.scalars(
        select(IntakeRejection).where(IntakeRejection.correlation_id == payload["correlation_id"])
    ).one()
    assert row.practice_id == client.seed["practice"].uuid
    assert any(e["error_code"] == "invalid_type" for e in row.field_errors)


def test_unlinked_member_does_not_leak_coverage(client: TestClient, db: Session):
    """Coverage must not run for unlinked members (error-set must not encode coverage)."""
    today = get_today()
    unlinked_id = str(client.seed["unlinked"].uuid)

    without = submit_as_office(client, member_id=unlinked_id)
    payload_without = assert_has_error_code(
        without,
        "member_not_linked",
        field="member_id",
        message="Member is not linked to this practice",
    )
    codes_without = {e["error_code"] for e in payload_without["errors"]}

    db.add(
        Coverage(
            member_id=client.seed["unlinked"].uuid,
            payer_name="ProbePayer",
            effective_from=today,
            effective_to=today,
        )
    )
    db.flush()
    with_cov = submit_as_office(client, member_id=unlinked_id)
    payload_with = assert_has_error_code(
        with_cov,
        "member_not_linked",
        field="member_id",
        message="Member is not linked to this practice",
    )
    codes_with = {e["error_code"] for e in payload_with["errors"]}

    assert codes_without == {"member_not_linked"}
    assert codes_with == {"member_not_linked"}


def test_clinical_note_max_length_rejected(client: TestClient):
    note = "x" * 10_001
    response = submit_as_office(client, clinical_note=note)
    payload = assert_has_error_code(response, "invalid_type", field="clinical_note")
    assert payload.get("correlation_id")
    assert get_intake_rejection_as(client, payload["correlation_id"]).status_code == 200


def test_procedures_max_length_rejected(client: TestClient):
    procs = [{"code": "99213", "units": 1} for _ in range(51)]
    response = submit_as_office(client, procedures=procs)
    payload = assert_has_error_code(response, "invalid_type", field="procedures")
    assert payload.get("correlation_id")


def test_oversized_body_rejected(client: TestClient):
    huge = "y" * 300_000
    response = client.post(
        "/v1/prior-auths",
        headers={
            **role_headers(client, "office"),
            "Content-Type": "application/json",
        },
        content=(
            f'{{"member_id":"{client.seed["member"].uuid}","diagnosis_icd10":"J06.9",'
            f'"date_of_service":"{get_today().isoformat()}","clinical_note":"{huge}",'
            f'"procedures":[{{"code":"99213","units":1}}]}}'
        ),
    )
    assert response.status_code == 413, response.text[:200]
    assert response.json()["detail"] == "Request body too large"


def test_decide_outcomes_max_length_rejected(client: TestClient):
    data = submit_and_claim(client)
    pid = data["procedures"][0]["uuid"]
    outcomes = [{"procedure_id": pid, "decision": "approved"} for _ in range(51)]
    response = decide_as(client, data["uuid"], outcomes)
    assert_has_error_code(response, "invalid_type", field="outcomes")


def test_office_context_from_request_rejects_non_office(client: TestClient, db: Session):
    import uuid
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt
    from app.config import settings
    from app.identity.auth import mint_token
    from app.identity.models import User, UserRole
    from app.shared.errors import _office_context_from_request
    from starlette.requests import Request

    from tests.conftest import auth

    assert _office_context_from_request(Request({"type": "http", "headers": []}), db) is None

    bad_jwt = Request({"type": "http", "headers": [(b"authorization", b"Bearer not-a-jwt")]})
    assert _office_context_from_request(bad_jwt, db) is None

    reviewer_req = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {client.seed['tokens']['reviewer']}".encode())],
        }
    )
    assert _office_context_from_request(reviewer_req, db) is None

    bogus = pyjwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000000",
            "role": "provider_office",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    unknown = Request({"type": "http", "headers": [(b"authorization", f"Bearer {bogus}".encode())]})
    assert _office_context_from_request(unknown, db) is None

    # Office without practice: schema 422 still shaped, but no IntakeRejection row.
    orphan = User(
        uuid=uuid.uuid4(),
        email=f"orphan-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.provider_office,
        practice_id=None,
        display_name="Orphan",
    )
    db.add(orphan)
    db.flush()
    body = valid_submit_body(client.seed)
    body["member_id"] = "not-a-uuid"
    response = client.post(
        "/v1/prior-auths",
        headers=auth(mint_token(orphan)),
        json=body,
    )
    payload = assert_has_error_code(response, "invalid_type", field="member_id")
    assert get_intake_rejection_as(client, payload["correlation_id"]).status_code == 404
