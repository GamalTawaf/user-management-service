"""Assertions that kill high-value service mutants (boundaries, details, audit keys)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.audit.models import AuditEvent
from app.clock import get_today
from app.master_data.models import Coverage, Member, PatientPracticeLink, Practice
from app.prior_auth.models import PriorAuthRequest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import (
    TWO_PROCEDURES,
    assert_has_error_code,
    claim_as,
    decide_as,
    get_as,
    get_audit_as,
    reassign_as,
    submit_and_claim,
    submit_as_office,
    submit_ok,
)


def _assert_detail(response, status: int, detail: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"] == detail


def _aware(value: str | None) -> datetime:
    assert value is not None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    return parsed


def test_submit_boundaries_and_normalization(client: TestClient):
    today = get_today()
    at_max_dos = submit_ok(client, date_of_service=(today + timedelta(days=365)).isoformat())
    assert at_max_dos["status"] == "submitted"

    units_ok = submit_ok(client, procedures=[{"code": "99213", "units": 30}])
    assert units_ok["procedures"][0]["units"] == 30

    normalized = submit_ok(
        client,
        diagnosis_icd10="j06.9",
        procedures=[{"code": "a0213", "units": 1}, {"code": "99214", "units": 2}],
    )
    assert normalized["diagnosis_icd10"] == "J06.9"
    assert normalized["status"] == "submitted"
    codes = [p["code"] for p in normalized["procedures"]]
    assert codes == ["A0213", "99214"]
    sequences = [p["sequence"] for p in normalized["procedures"]]
    assert sequences == [1, 2]


def test_submit_coverage_and_link_filters(client: TestClient, db: Session):
    today = get_today()
    other = Practice(
        uuid=uuid.uuid4(),
        name="Elsewhere",
        notification_email="elsewhere@example.com",
    )
    db.add(other)
    db.flush()
    # Linked only to another practice → office must still get member_not_linked.
    db.add(PatientPracticeLink(member_id=client.seed["unlinked"].uuid, practice_id=other.uuid))
    db.flush()
    assert_has_error_code(
        submit_as_office(client, member_id=str(client.seed["unlinked"].uuid)),
        "member_not_linked",
        field="member_id",
        message="Member is not linked to this practice",
    )

    # Valid coverage on a different member must not satisfy this member's DOS.
    outsider = Member(
        uuid=uuid.uuid4(),
        external_id=f"O-{uuid.uuid4().hex[:6]}",
        full_name="Outsider",
    )
    db.add(outsider)
    db.flush()
    db.add(
        Coverage(
            member_id=outsider.uuid,
            payer_name="OtherPayer",
            effective_from=today - timedelta(days=1),
            effective_to=today + timedelta(days=30),
        )
    )
    cov = db.scalars(select(Coverage).where(Coverage.member_id == client.seed["member"].uuid)).one()
    cov.effective_to = today - timedelta(days=1)
    db.flush()
    assert_has_error_code(
        submit_as_office(client),
        "no_coverage",
        field="member_id",
        message="No active coverage overlapping date of service",
    )

    # Coverage that starts after DOS must not match (effective_from filter).
    cov.effective_from = today + timedelta(days=1)
    cov.effective_to = today + timedelta(days=30)
    db.flush()
    assert_has_error_code(
        submit_as_office(client, date_of_service=today.isoformat()),
        "no_coverage",
        field="member_id",
        message="No active coverage overlapping date of service",
    )

    # Pin coverage to exact DOS bounds (inclusive on both ends).
    cov.effective_from = today
    cov.effective_to = today
    db.flush()
    ok = submit_ok(client, date_of_service=today.isoformat())
    assert ok["date_of_service"] == today.isoformat()


def test_intake_reject_audit_payload(client: TestClient, db: Session):
    response = submit_as_office(client, procedures=[{"code": "99213", "units": 31}])
    payload = assert_has_error_code(
        response,
        "units_likely_typo",
        field="procedures[0].units",
        message="Units > 30 is almost always a typo; hard reject",
    )
    cid = payload["correlation_id"]
    event = db.scalars(
        select(AuditEvent).where(
            AuditEvent.action == "intake_reject",
            AuditEvent.intake_rejection_id.is_not(None),
        )
    ).all()
    match = next(e for e in event if e.payload.get("correlation_id") == cid)
    assert match.intake_rejection_id is not None
    assert match.payload == {
        "correlation_id": cid,
        "fields": ["procedures[0].units"],
        "practice_id": str(client.seed["practice"].uuid),
    }


def test_submit_audit_payload_keys(client: TestClient):
    created = submit_ok(client)
    audit = get_audit_as(client, created["uuid"])
    assert audit.status_code == 200
    submit_event = next(e for e in audit.json() if e["action"] == "submit")
    assert submit_event["payload"] == {
        "request_id": created["uuid"],
        "member_id": str(client.seed["member"].uuid),
        "procedure_codes": ["99213"],
    }


def test_claim_conflict_detail_and_side_effects(client: TestClient):
    first = submit_ok(client)
    second = submit_ok(client)
    claimed = claim_as(client, first["uuid"])
    assert claimed.status_code == 200, claimed.text
    body = claimed.json()
    assert body["claimed_at"] is not None
    _aware(body["claimed_at"])
    assert body["status"] == "in_review"

    again = claim_as(client, first["uuid"], role="reviewer2")
    _assert_detail(again, 409, "Request already claimed or not in submitted state")

    # Claim must be id-scoped: peer submitted request stays unclaimed.
    peer = get_as(client, second["uuid"], "reviewer")
    assert peer.status_code == 200
    assert peer.json()["claimed_by_user_id"] is None
    assert peer.json()["status"] == "submitted"


def test_claim_wrong_status_conflict(client: TestClient, db: Session):
    data = submit_and_claim(client)
    decide_as(
        client,
        data["uuid"],
        [{"procedure_id": data["procedures"][0]["uuid"], "decision": "approved"}],
    )
    # Clear claim fields so only the status predicate blocks a second claim.
    req = db.get(PriorAuthRequest, uuid.UUID(data["uuid"]))
    assert req is not None
    req.claimed_by_user_id = None
    req.claimed_at = None
    db.flush()
    stolen = claim_as(client, data["uuid"], role="reviewer2")
    _assert_detail(stolen, 409, "Request already claimed or not in submitted state")


def test_claim_requires_unclaimed_even_if_submitted(client: TestClient, db: Session):
    data = submit_ok(client)
    req = db.get(PriorAuthRequest, uuid.UUID(data["uuid"]))
    assert req is not None
    # Inconsistent: still submitted but already has a holder — unclaimed predicate must block.
    req.claimed_by_user_id = client.seed["reviewer"].uuid
    db.flush()
    stolen = claim_as(client, data["uuid"], role="reviewer2")
    _assert_detail(stolen, 409, "Request already claimed or not in submitted state")


def test_decide_details_denial_and_audit(client: TestClient):
    data = submit_and_claim(client, procedures=TWO_PROCEDURES)
    rid = data["uuid"]
    p0, p1 = data["procedures"]

    not_holder = decide_as(
        client,
        rid,
        [
            {"procedure_id": p0["uuid"], "decision": "approved"},
            {"procedure_id": p1["uuid"], "decision": "approved"},
        ],
        role="reviewer2",
    )
    _assert_detail(not_holder, 403, "Only the claim holder may decide")

    bad = decide_as(
        client,
        rid,
        [
            {"procedure_id": p0["uuid"], "decision": "maybe"},
            {"procedure_id": p1["uuid"], "decision": "approved"},
        ],
    )
    assert_has_error_code(
        bad,
        "invalid_decision",
        field=f"outcomes[{p0['uuid']}].decision",
        message="Decision must be approved or denied",
    )

    decided = decide_as(
        client,
        rid,
        [
            {"procedure_id": p0["uuid"], "decision": "approved"},
            {
                "procedure_id": p1["uuid"],
                "decision": "denied",
                "denial_reason": "  Not medically necessary  ",
            },
        ],
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["decided_at"] is not None
    _aware(body["decided_at"])
    by_id = {p["uuid"]: p for p in body["procedures"]}
    assert by_id[p0["uuid"]]["decision"] == "approved"
    assert by_id[p0["uuid"]]["denial_reason"] is None
    assert by_id[p1["uuid"]]["decision"] == "denied"
    assert by_id[p1["uuid"]]["denial_reason"] == "Not medically necessary"

    again = decide_as(
        client,
        rid,
        [
            {"procedure_id": p0["uuid"], "decision": "approved"},
            {
                "procedure_id": p1["uuid"],
                "decision": "denied",
                "denial_reason": "x",
            },
        ],
    )
    _assert_detail(again, 409, "Request already decided")

    audit = get_audit_as(client, rid).json()
    decide_event = next(e for e in audit if e["action"] == "decide")
    assert decide_event["payload"]["request_id"] == rid
    outcomes = decide_event["payload"]["outcomes"]
    assert {o["procedure_id"] for o in outcomes} == {p0["uuid"], p1["uuid"]}
    assert all("decision" in o and "denial_reason" in o for o in outcomes)


def test_decide_coi_detail(client: TestClient, db: Session):
    data = submit_and_claim(client)
    # Bypass reassign COI guard so the conflict surfaces on decide.
    req = db.get(PriorAuthRequest, uuid.UUID(data["uuid"]))
    assert req is not None
    req.claimed_by_user_id = client.seed["reviewer_coi"].uuid
    db.flush()
    response = decide_as(
        client,
        data["uuid"],
        [{"procedure_id": data["procedures"][0]["uuid"], "decision": "approved"}],
        role="reviewer_coi",
    )
    _assert_detail(response, 403, "Conflict of interest with this member")


def test_reassign_details_and_audit(client: TestClient, db: Session):
    data = submit_and_claim(client)
    rid = data["uuid"]
    from_id = str(client.seed["reviewer"].uuid)
    to_id = str(client.seed["reviewer2"].uuid)

    # Second in-review request: UPDATE must be id-scoped.
    peer = submit_ok(client)
    assert claim_as(client, peer["uuid"]).status_code == 200
    peer_holder = get_as(client, peer["uuid"], "reviewer").json()["claimed_by_user_id"]

    bad_state = reassign_as(client, submit_ok(client)["uuid"], client.seed["reviewer"].uuid)
    _assert_detail(bad_state, 409, "Request must be in_review to reassign")

    bad_rev = reassign_as(client, rid, client.seed["office"].uuid)
    assert_has_error_code(
        bad_rev,
        "invalid_reviewer",
        field="reviewer_id",
        message="reviewer_id must reference a reviewer user",
    )

    # Force an old claimed_at so omitting claimed_at=now from the UPDATE is visible.
    req = db.get(PriorAuthRequest, uuid.UUID(rid))
    assert req is not None
    req.claimed_at = datetime(2020, 1, 1, tzinfo=UTC)
    db.flush()

    moved = reassign_as(client, rid, client.seed["reviewer2"].uuid)
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["claimed_by_user_id"] == to_id
    assert body["claimed_at"] is not None
    assert not body["claimed_at"].startswith("2020-01-01")
    _aware(body["claimed_at"])

    peer_after = get_as(client, peer["uuid"], "reviewer").json()
    assert peer_after["claimed_by_user_id"] == peer_holder

    audit = get_audit_as(client, rid).json()
    reassign_event = next(e for e in audit if e["action"] == "reassign")
    assert reassign_event["payload"] == {
        "request_id": rid,
        "from": from_id,
        "to": to_id,
    }

    # Terminal conflict detail after decide (hits UPDATE miss → decided branch).
    decide_as(
        client,
        rid,
        [{"procedure_id": body["procedures"][0]["uuid"], "decision": "approved"}],
        role="reviewer2",
    )
    terminal = reassign_as(client, rid, client.seed["reviewer"].uuid)
    _assert_detail(terminal, 409, "Cannot reassign a decided request")
