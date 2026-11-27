from datetime import timedelta

import pytest
from app.audit.models import AuditEvent
from app.clock import get_today
from app.master_data.models import Coverage
from app.prior_auth.models import PriorAuthRequest, RequestStatus
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import (
    assert_has_error_code,
    get_as,
    role_headers,
    submit_as_office,
    submit_ok,
)


def test_submit_happy_path(client: TestClient, db: Session):
    response = submit_as_office(client)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "submitted"
    assert data["clinical_note"] == "Patient needs procedure"
    assert len(data["procedures"]) == 1

    request = db.get(PriorAuthRequest, data["uuid"])
    assert request is not None
    assert request.status == RequestStatus.submitted
    audit = db.scalars(
        select(AuditEvent).where(
            AuditEvent.request_id == request.uuid, AuditEvent.action == "submit"
        )
    ).first()
    assert audit is not None


@pytest.mark.parametrize(
    ("overrides", "error_code", "field", "message"),
    [
        (
            {"member_id": "UNLINKED"},
            "member_not_linked",
            "member_id",
            "Member is not linked to this practice",
        ),
        (
            {"date_of_service": "PAST"},
            "dos_in_past",
            "date_of_service",
            "Date of service must be today or later",
        ),
        (
            {"date_of_service": "FAR"},
            "dos_too_far",
            "date_of_service",
            "Date of service must be within 365 days",
        ),
        (
            {"procedures": [{"code": "99213", "units": 31}]},
            "units_likely_typo",
            "procedures[0].units",
            "Units > 30 is almost always a typo; hard reject",
        ),
        (
            {"diagnosis_icd10": "!!!"},
            "invalid_icd10",
            "diagnosis_icd10",
            "ICD-10 format looks invalid",
        ),
        (
            {"procedures": [{"code": "9921!", "units": 1}]},
            "invalid_procedure_code",
            "procedures[0].code",
            "CPT/HCPCS code must be 5 alphanumeric characters",
        ),
        (
            {"procedures": []},
            "procedures_required",
            "procedures",
            "At least one procedure is required",
        ),
        (
            {"procedures": [{"code": "99213", "units": 0}]},
            "units_too_low",
            "procedures[0].units",
            "Units must be at least 1",
        ),
    ],
)
def test_submit_validation_errors(
    client: TestClient,
    overrides: dict,
    error_code: str,
    field: str,
    message: str,
):
    resolved = dict(overrides)
    if resolved.get("member_id") == "UNLINKED":
        resolved["member_id"] = str(client.seed["unlinked"].uuid)
    if resolved.get("date_of_service") == "PAST":
        resolved["date_of_service"] = (get_today() - timedelta(days=1)).isoformat()
    if resolved.get("date_of_service") == "FAR":
        resolved["date_of_service"] = (get_today() + timedelta(days=366)).isoformat()

    response = submit_as_office(client, **resolved)
    payload = assert_has_error_code(response, error_code, field=field, message=message)
    assert payload.get("correlation_id")


def test_no_coverage(client: TestClient, db: Session):
    cov = db.scalars(select(Coverage).where(Coverage.member_id == client.seed["member"].uuid)).one()
    cov.effective_to = get_today() - timedelta(days=1)
    db.flush()
    assert_has_error_code(
        submit_as_office(client),
        "no_coverage",
        field="member_id",
        message="No active coverage overlapping date of service",
    )


def test_office_list_and_get_practice_scoped(client: TestClient):
    rid = submit_ok(client)["uuid"]
    listed = client.get("/v1/prior-auths", headers=role_headers(client, "office"))
    assert listed.status_code == 200
    assert any(r["uuid"] == rid for r in listed.json())
    got = get_as(client, rid, "office")
    assert got.status_code == 200
    assert got.json()["uuid"] == rid
