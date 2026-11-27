import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import assert_has_error_code, role_headers


def test_me_and_patch(client: TestClient):
    me = client.get("/v1/me", headers=role_headers(client, "member"))
    assert me.status_code == 200
    assert me.json()["email"] == "member@example.com"

    patched = client.patch(
        "/v1/me",
        headers=role_headers(client, "member"),
        json={"display_name": "Alex Updated"},
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Alex Updated"


def test_create_activate_disable_enable_flow(client: TestClient):
    created = client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={
            "email": "newbie@example.com",
            "display_name": "Newbie",
            "role": "member",
            "status": "invited",
            "org_id": str(client.seed["org"].uuid),
        },
    )
    assert created.status_code == 201, created.text
    uid = created.json()["uuid"]
    assert created.json()["status"] == "invited"

    activated = client.post(
        f"/v1/users/{uid}/activate",
        headers=role_headers(client, "admin"),
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    disabled = client.post(
        f"/v1/users/{uid}/disable",
        headers=role_headers(client, "admin"),
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["disabled_at"] is not None

    enabled = client.post(
        f"/v1/users/{uid}/enable",
        headers=role_headers(client, "admin"),
    )
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "active"


def test_cannot_disable_self(client: TestClient):
    admin_id = str(client.seed["admin"].uuid)
    response = client.post(
        f"/v1/users/{admin_id}/disable",
        headers=role_headers(client, "admin"),
    )
    assert response.status_code == 403


def test_create_validation_and_duplicate_email(client: TestClient):
    bad = client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={"email": "not-an-email", "display_name": "X"},
    )
    assert_has_error_code(bad, "invalid_email", field="email")

    dup = client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={"email": "member@example.com", "display_name": "Dup"},
    )
    assert_has_error_code(dup, "email_taken", field="email")


def test_idempotency_replay(client: TestClient):
    headers = {
        **role_headers(client, "admin"),
        "Idempotency-Key": "create-once",
    }
    body = {"email": "idem@example.com", "display_name": "Idem", "status": "active"}
    first = client.post("/v1/users", headers=headers, json=body)
    assert first.status_code == 201
    second = client.post("/v1/users", headers=headers, json=body)
    assert second.status_code == 201
    assert second.json()["uuid"] == first.json()["uuid"]

    conflict = client.post(
        "/v1/users",
        headers=headers,
        json={"email": "other@example.com", "display_name": "Other", "status": "active"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["errors"][0]["error_code"] == "idempotency_key_reuse"


def test_member_cannot_read_other_user(client: TestClient):
    other = str(client.seed["admin"].uuid)
    response = client.get(f"/v1/users/{other}", headers=role_headers(client, "member"))
    assert response.status_code == 403


def test_auditor_can_read_audit(client: TestClient):
    member_id = str(client.seed["member"].uuid)
    client.patch(
        "/v1/me",
        headers=role_headers(client, "member"),
        json={"display_name": "Audited Name"},
    )
    audit = client.get(
        f"/v1/users/{member_id}/audit",
        headers=role_headers(client, "auditor"),
    )
    assert audit.status_code == 200
    actions = [row["action"] for row in audit.json()]
    assert "me_update" in actions


def test_stats_and_orgs(client: TestClient, db: Session):
    stats = client.get("/v1/users/stats", headers=role_headers(client, "admin"))
    assert stats.status_code == 200
    assert sum(row["count"] for row in stats.json()) >= 4

    orgs = client.get("/v1/orgs", headers=role_headers(client, "admin"))
    assert orgs.status_code == 200
    assert orgs.json()[0]["name"] == "Acme Workspace"

    created = client.post(
        "/v1/orgs",
        headers=role_headers(client, "admin"),
        json={"name": "Beta Co", "notification_email": "hi@beta.example.com"},
    )
    assert created.status_code == 201
    oid = created.json()["uuid"]
    got = client.get(f"/v1/orgs/{oid}", headers=role_headers(client, "auditor"))
    assert got.status_code == 200


def test_outbox_enqueued_on_create(client: TestClient, db: Session):
    from app.outbox.models import OutboxEvent, OutboxKind
    from sqlalchemy import select

    client.post(
        "/v1/users",
        headers=role_headers(client, "admin"),
        json={"email": "mail@example.com", "display_name": "Mail", "status": "active"},
    )
    rows = db.scalars(select(OutboxEvent).where(OutboxEvent.kind == OutboxKind.user_welcome)).all()
    assert len(rows) >= 1


def test_unknown_user_404(client: TestClient):
    missing = uuid.uuid4()
    response = client.get(f"/v1/users/{missing}", headers=role_headers(client, "admin"))
    assert response.status_code == 404
