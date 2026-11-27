import uuid

import jwt
import pytest
from app.config import settings
from app.identity.auth import mint_token, require_role
from app.identity.models import UserRole
from app.main import app
from fastapi.testclient import TestClient

from tests.conftest import (
    auth,
    encode_raw_jwt,
    get_audit_as,
    raw_token,
    role_headers,
    submit_ok,
)


def test_user_role_people_names():
    assert UserRole.member.people_name == "patient"
    assert UserRole.provider_office.people_name == "doctors' office"
    assert UserRole.reviewer.people_name == "nurse or physician"
    assert UserRole.ops_admin.people_name == "operations admin"
    assert UserRole.auditor.people_name == "auditor"


def test_seed_jwt_authorizes_protected_list(client: TestClient):
    response = client.get("/v1/prior-auths", headers=role_headers(client, "office"))
    assert response.status_code == 200
    assert response.json() == []


def _no_headers(_client: TestClient):
    return None


def _member_headers(client: TestClient):
    return role_headers(client, "member")


def _expired_headers(client: TestClient):
    return auth(mint_token(client.seed["office"], hours=-1))


def _garbage_headers(_client: TestClient):
    return auth("not-a-jwt")


def _bad_sub_headers(_client: TestClient):
    return auth(raw_token(sub="not-a-uuid"))


def _missing_sub_headers(_client: TestClient):
    return auth(raw_token(role="provider_office"))


def _ghost_user_headers(_client: TestClient):
    return auth(raw_token(sub=str(uuid.uuid4()), role="provider_office"))


def _no_exp_headers(client: TestClient):
    office_id = str(client.seed["office"].uuid)
    return auth(encode_raw_jwt({"sub": office_id, "role": "provider_office"}))


@pytest.mark.parametrize(
    ("make_headers", "expected"),
    [
        (_no_headers, 401),
        (_member_headers, 403),
        (_expired_headers, 401),
        (_garbage_headers, 401),
        (_bad_sub_headers, 401),
        (_missing_sub_headers, 401),
        (_ghost_user_headers, 401),
        (_no_exp_headers, 401),
    ],
)
def test_auth_rejects(client: TestClient, make_headers, expected: int):
    headers = make_headers(client)
    kwargs = {"headers": headers} if headers is not None else {}
    response = client.get("/v1/prior-auths", **kwargs)
    assert response.status_code == expected


def test_require_role_helper_rejects(client: TestClient):
    response = client.get("/v1/review-queue", headers=role_headers(client, "office"))
    assert response.status_code == 403
    assert require_role(UserRole.reviewer)
    assert app.title
    _ = mint_token(client.seed["office"])


def test_minted_tokens_carry_an_expiry(client: TestClient):
    """Seed/demo tokens come from mint_token; `exp` is now required to authenticate."""
    token = client.seed["tokens"]["office"]
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert "exp" in claims


def test_auth_uses_db_role_not_token_role(client: TestClient):
    forged = encode_raw_jwt(
        {
            "sub": str(client.seed["office"].uuid),
            "role": "ops_admin",
            "exp": 9999999999,
        }
    )
    response = client.get("/v1/prior-auths", headers=auth(forged))
    assert response.status_code == 200

    rid = submit_ok(client)["uuid"]
    audit = get_audit_as(client, rid)
    # forged token claims admin but DB role is office — use forged header directly
    forged_audit = client.get(f"/v1/prior-auths/{rid}/audit", headers=auth(forged))
    assert forged_audit.status_code == 403
    assert audit.status_code == 200
