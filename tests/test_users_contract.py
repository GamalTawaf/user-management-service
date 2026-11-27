"""Outside-in contract tests that lock error_code/field/message, audit payloads, and locks."""

from __future__ import annotations

import uuid

from app.audit.models import AuditEvent
from app.outbox.models import OutboxEvent, OutboxKind
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from tests.conftest import (
    assert_detail,
    assert_has_error_code,
    latest_audit,
    role_headers,
)


def test_create_validation_messages_and_org(client: TestClient):
    blank = client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={"email": "ok@example.com", "display_name": "   "},
    )
    assert_has_error_code(
        blank,
        "display_name_required",
        field="display_name",
        message="Display name is required",
    )

    missing_org = client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={
            "email": "need-org@example.com",
            "display_name": "Need Org",
            "org_id": str(uuid.uuid4()),
        },
    )
    assert_has_error_code(
        missing_org,
        "org_not_found",
        field="org_id",
        message="Organization not found",
    )

    dup = client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={"email": "member@example.com", "display_name": "Dup"},
    )
    assert_has_error_code(
        dup,
        "email_taken",
        field="email",
        message="Email is already registered",
    )


def test_create_normalizes_email_and_writes_audit(client: TestClient):
    org_id = str(client.seed["org"].uuid)
    created = client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={
            "email": "  Mixed.Case@Example.COM ",
            "display_name": "  Casey  ",
            "role": "auditor",
            "status": "invited",
            "org_id": org_id,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == "mixed.case@example.com"
    assert body["display_name"] == "Casey"
    assert body["role"] == "auditor"
    assert body["status"] == "invited"
    assert body["org_id"] == org_id

    row = latest_audit(client, body["uuid"], "user_create")
    assert row["subject_user_id"] == body["uuid"]
    assert row["payload"] == {
        "user_id": body["uuid"],
        "email": "mixed.case@example.com",
        "role": "auditor",
        "status": "invited",
    }


def test_org_create_contract_and_audit(client: TestClient, db: Session):
    bad = client.post(
        "/v1/orgs",
        headers=role_headers(client, "admin"),
        json={"name": " ", "notification_email": "bad"},
    )
    assert_has_error_code(
        bad,
        "name_required",
        field="name",
        message="Organization name is required",
    )
    assert_has_error_code(bad, "invalid_email", field="notification_email")

    created = client.post(
        "/v1/orgs",
        headers=role_headers(client, "admin"),
        json={"name": "  Gamma Co  ", "notification_email": "  Ops@Gamma.Example.COM "},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Gamma Co"
    assert body["notification_email"] == "ops@gamma.example.com"

    rows = db.scalars(select(AuditEvent).where(AuditEvent.action == "org_create")).all()
    match = [r for r in rows if r.payload.get("org_id") == body["uuid"]]
    assert match, rows
    assert match[0].payload == {"org_id": body["uuid"], "name": "Gamma Co"}


def test_update_and_me_audit_payloads(client: TestClient):
    uid = str(client.seed["member"].uuid)
    org_id = str(client.seed["org"].uuid)

    blank = client.patch(
        f"/v1/users/{uid}",
        headers=role_headers(client, "admin"),
        json={"display_name": "   "},
    )
    assert_has_error_code(
        blank,
        "display_name_required",
        field="display_name",
        message="Display name is required",
    )

    bad_org = client.patch(
        f"/v1/users/{uid}",
        headers=role_headers(client, "admin"),
        json={"org_id": str(uuid.uuid4())},
    )
    assert_has_error_code(
        bad_org,
        "org_not_found",
        field="org_id",
        message="Organization not found",
    )

    patched = client.patch(
        f"/v1/users/{uid}",
        headers=role_headers(client, "admin"),
        json={"display_name": "  Renamed Member  ", "role": "auditor", "org_id": org_id},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["display_name"] == "Renamed Member"
    assert patched.json()["role"] == "auditor"
    assert patched.json()["org_id"] == org_id

    update_row = latest_audit(client, uid, "user_update")
    assert update_row["payload"] == {
        "user_id": uid,
        "changes": {
            "display_name": "Renamed Member",
            "role": "auditor",
            "org_id": org_id,
        },
    }

    cleared = client.patch(
        f"/v1/users/{uid}",
        headers=role_headers(client, "admin"),
        json={"org_id": None},
    )
    assert cleared.status_code == 200
    clear_row = latest_audit(client, uid, "user_update")
    assert clear_row["payload"]["changes"] == {"org_id": ""}

    me_blank = client.patch(
        "/v1/me",
        headers=role_headers(client, "member"),
        json={"display_name": "   "},
    )
    assert_has_error_code(
        me_blank,
        "display_name_required",
        field="display_name",
        message="Display name is required",
    )

    me = client.patch(
        "/v1/me",
        headers=role_headers(client, "member"),
        json={"display_name": "  Self Name  "},
    )
    assert me.status_code == 200
    assert me.json()["display_name"] == "Self Name"
    me_row = latest_audit(client, uid, "me_update")
    assert me_row["payload"] == {"user_id": uid, "display_name": "Self Name"}


def test_lifecycle_details_audit_and_outbox(client: TestClient, db: Session):
    admin_id = str(client.seed["admin"].uuid)
    assert_detail(
        client.post(f"/v1/users/{admin_id}/disable", headers=role_headers(client, "admin")),
        403,
        "Cannot disable your own account",
    )

    invited_id = str(client.seed["invited"].uuid)
    active_first = client.post(
        f"/v1/users/{invited_id}/activate",
        headers=role_headers(client, "admin"),
    )
    assert active_first.status_code == 200
    assert active_first.json()["status"] == "active"

    activate_row = latest_audit(client, invited_id, "user_activate")
    assert activate_row["payload"] == {
        "user_id": invited_id,
        "from": "invited",
        "to": "active",
    }

    notices = db.scalars(
        select(OutboxEvent).where(
            OutboxEvent.kind == OutboxKind.user_status,
            OutboxEvent.subject_user_id == client.seed["invited"].uuid,
        )
    ).all()
    assert notices
    assert "from invited to active" in notices[-1].payload["body"]

    assert_has_error_code(
        client.post(f"/v1/users/{invited_id}/activate", headers=role_headers(client, "admin")),
        "invalid_status",
        field="status",
        message="Only invited users can be activated",
    )
    assert_detail(
        client.post(f"/v1/users/{invited_id}/enable", headers=role_headers(client, "admin")),
        409,
        "User is not disabled",
    )

    disabled = client.post(
        f"/v1/users/{invited_id}/disable",
        headers=role_headers(client, "admin"),
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["disabled_at"] is not None
    disable_row = latest_audit(client, invited_id, "user_disable")
    assert disable_row["payload"] == {
        "user_id": invited_id,
        "from": "active",
        "to": "disabled",
    }
    disable_notices = db.scalars(
        select(OutboxEvent).where(
            OutboxEvent.kind == OutboxKind.user_status,
            OutboxEvent.subject_user_id == client.seed["invited"].uuid,
        )
    ).all()
    assert "from active to disabled" in disable_notices[-1].payload["body"]

    assert_detail(
        client.post(f"/v1/users/{invited_id}/disable", headers=role_headers(client, "admin")),
        409,
        "User already disabled",
    )

    enabled = client.post(
        f"/v1/users/{invited_id}/enable",
        headers=role_headers(client, "admin"),
    )
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "active"
    assert enabled.json()["disabled_at"] is None
    enable_row = latest_audit(client, invited_id, "user_enable")
    assert enable_row["payload"] == {
        "user_id": invited_id,
        "from": "disabled",
        "to": "active",
    }
    enable_notices = db.scalars(
        select(OutboxEvent).where(
            OutboxEvent.kind == OutboxKind.user_status,
            OutboxEvent.subject_user_id == client.seed["invited"].uuid,
        )
    ).all()
    assert "from disabled to active" in enable_notices[-1].payload["body"]


def test_mutations_use_row_lock(client: TestClient, db: Session):
    statements: list[str] = []

    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    bind = db.get_bind()
    event.listen(bind, "before_cursor_execute", _capture)
    try:
        uid = str(client.seed["member"].uuid)
        assert (
            client.patch(
                f"/v1/users/{uid}",
                headers=role_headers(client, "admin"),
                json={"display_name": "Locked Update"},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                "/v1/me",
                headers=role_headers(client, "member"),
                json={"display_name": "Locked Me"},
            ).status_code
            == 200
        )
        invited = str(client.seed["invited"].uuid)
        assert (
            client.post(
                f"/v1/users/{invited}/activate",
                headers=role_headers(client, "admin"),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/v1/users/{invited}/disable",
                headers=role_headers(client, "admin"),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/v1/users/{invited}/enable",
                headers=role_headers(client, "admin"),
            ).status_code
            == 200
        )
    finally:
        event.remove(bind, "before_cursor_execute", _capture)

    locked = [s for s in statements if "FOR UPDATE" in s.upper()]
    assert len(locked) >= 5, statements
