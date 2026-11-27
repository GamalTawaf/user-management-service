import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.identity.models import User
from tests.conftest import SEED_PASSWORD, assert_detail, auth


def test_login_success(client: TestClient):
    response = client.post(
        "/v1/auth/login",
        json={"email": "member@example.com", "password": SEED_PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    me = client.get("/v1/me", headers=auth(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "member@example.com"


def test_login_wrong_password(client: TestClient):
    response = client.post(
        "/v1/auth/login",
        json={"email": "member@example.com", "password": "wrong-password"},
    )
    assert_detail(response, 401, "Invalid credentials")


def test_login_unknown_user(client: TestClient):
    response = client.post(
        "/v1/auth/login",
        json={"email": "missing@example.com", "password": SEED_PASSWORD},
    )
    assert_detail(response, 401, "Invalid credentials")


def test_login_invited_forbidden(client: TestClient):
    # Give invited a password so auth reaches status checks.
    invited = client.seed["invited"]
    from app.identity.passwords import hash_password

    invited.password_hash = hash_password(SEED_PASSWORD)
    response = client.post(
        "/v1/auth/login",
        json={"email": "invited@example.com", "password": SEED_PASSWORD},
    )
    assert_detail(response, 403, "Account not activated")


def test_login_disabled_forbidden(client: TestClient):
    member_id = str(client.seed["member"].uuid)
    client.post(f"/v1/users/{member_id}/disable", headers=auth(client.seed["tokens"]["admin"]))
    response = client.post(
        "/v1/auth/login",
        json={"email": "member@example.com", "password": SEED_PASSWORD},
    )
    assert_detail(response, 403, "Account disabled")


def test_create_user_with_password_can_login(client: TestClient):
    created = client.post(
        "/v1/users",
        headers=auth(client.seed["tokens"]["admin"]),
        json={
            "email": "loginable@example.com",
            "display_name": "Loginable",
            "status": "active",
            "password": "create-pass-99",
        },
    )
    assert created.status_code == 201
    response = client.post(
        "/v1/auth/login",
        json={"email": "loginable@example.com", "password": "create-pass-99"},
    )
    assert response.status_code == 200


def test_create_user_without_password_stores_null_hash(client: TestClient, db: Session):
    created = client.post(
        "/v1/users",
        headers=auth(client.seed["tokens"]["admin"]),
        json={
            "email": "nopass@example.com",
            "display_name": "No Pass",
            "status": "active",
        },
    )
    assert created.status_code == 201
    user_id = uuid.UUID(created.json()["uuid"])
    user = db.get(User, user_id)
    assert user is not None
    assert user.password_hash is None
    assert_detail(
        client.post(
            "/v1/auth/login",
            json={"email": "nopass@example.com", "password": SEED_PASSWORD},
        ),
        401,
        "Invalid credentials",
    )
