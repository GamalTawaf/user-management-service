import uuid

import jwt
import pytest
from app.config import settings
from app.identity.auth import mint_token
from fastapi.testclient import TestClient

from tests.conftest import auth, encode_raw_jwt, raw_token, role_headers


def test_admin_can_list_users(client: TestClient):
    response = client.get("/v1/users", headers=role_headers(client, "admin"))
    assert response.status_code == 200
    assert len(response.json()) >= 3


def test_member_forbidden_from_list(client: TestClient):
    response = client.get("/v1/users", headers=role_headers(client, "member"))
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("make_headers", "expected"),
    [
        (lambda _c: None, 401),
        (lambda c: auth("not-a-jwt"), 401),
        (lambda c: auth(raw_token(sub="not-a-uuid")), 401),
        (lambda c: auth(raw_token(sub=str(uuid.uuid4()), role="admin")), 401),
        (lambda c: auth(mint_token(c.seed["admin"], hours=-1)), 401),
        (
            lambda c: auth(encode_raw_jwt({"sub": str(c.seed["admin"].uuid), "role": "admin"})),
            401,
        ),
    ],
)
def test_auth_rejects(client: TestClient, make_headers, expected: int):
    headers = make_headers(client)
    kwargs = {"headers": headers} if headers is not None else {}
    response = client.get("/v1/users", **kwargs)
    assert response.status_code == expected


def test_auth_uses_db_role_not_token_role(client: TestClient):
    forged = encode_raw_jwt(
        {
            "sub": str(client.seed["member"].uuid),
            "role": "admin",
            "exp": 9999999999,
        }
    )
    response = client.get("/v1/users", headers=auth(forged))
    assert response.status_code == 403


def test_invited_cannot_authenticate(client: TestClient):
    token = mint_token(client.seed["invited"])
    response = client.get("/v1/me", headers=auth(token))
    assert response.status_code == 403
    assert response.json()["detail"] == "Account not activated"


def test_minted_tokens_carry_expiry(client: TestClient):
    token = client.seed["tokens"]["admin"]
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert "exp" in claims
