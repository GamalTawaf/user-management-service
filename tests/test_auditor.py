"""Auditor role: read audit + list/get; no mutations."""

from fastapi.testclient import TestClient

from tests.conftest import (
    claim_as,
    decide_as,
    get_as,
    get_audit_as,
    reassign_as,
    role_headers,
    submit_and_claim,
    submit_ok,
    valid_submit_body,
    workload_as,
)


def test_auditor_reads_audit_and_admin_still_works(client: TestClient):
    rid = submit_ok(client)["uuid"]
    claim_as(client, rid)

    auditor = get_audit_as(client, rid, role="auditor")
    assert auditor.status_code == 200, auditor.text
    actions = {e["action"] for e in auditor.json()}
    assert "submit" in actions
    assert "claim" in actions

    admin = get_audit_as(client, rid, role="admin")
    assert admin.status_code == 200, admin.text
    assert {e["action"] for e in admin.json()} == actions


def test_auditor_list_and_get_read_all(client: TestClient):
    rid = submit_ok(client)["uuid"]

    listed = client.get("/v1/prior-auths", headers=role_headers(client, "auditor"))
    assert listed.status_code == 200, listed.text
    assert any(r["uuid"] == rid for r in listed.json())

    got = get_as(client, rid, "auditor")
    assert got.status_code == 200, got.text
    assert got.json()["uuid"] == rid


def test_auditor_forbidden_on_writes_and_restricted_reads(client: TestClient):
    data = submit_and_claim(client)
    rid = data["uuid"]
    procedure_id = data["procedures"][0]["uuid"]

    submit = client.post(
        "/v1/prior-auths",
        headers=role_headers(client, "auditor"),
        json=valid_submit_body(client.seed),
    )
    assert submit.status_code == 403, submit.text

    claim = claim_as(client, rid, role="auditor")
    assert claim.status_code == 403, claim.text

    decide = decide_as(
        client,
        rid,
        [{"procedure_id": procedure_id, "decision": "approved"}],
        role="auditor",
    )
    assert decide.status_code == 403, decide.text

    reassign = reassign_as(client, rid, client.seed["reviewer"].uuid, role="auditor")
    assert reassign.status_code == 403, reassign.text

    workload = workload_as(client, role="auditor")
    assert workload.status_code == 403, workload.text

    me = client.get("/v1/me/prior-auths", headers=role_headers(client, "auditor"))
    assert me.status_code == 403, me.text
