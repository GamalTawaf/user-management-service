from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings


def test_health(client: TestClient):
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready(client: TestClient):
    response = client.get("/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"


def test_ready_with_redis_ok(client: TestClient, monkeypatch):
    fake_client = MagicMock()
    fake_client.ping.return_value = True

    def _from_url(*_a, **_k):
        return fake_client

    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr("redis.from_url", _from_url)
    response = client.get("/v1/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["redis"] == "ok"
    fake_client.close.assert_called_once()


def test_ready_redis_down(client: TestClient, monkeypatch):
    fake_client = MagicMock()
    fake_client.ping.side_effect = OSError("down")

    def _from_url(*_a, **_k):
        return fake_client

    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr("redis.from_url", _from_url)
    response = client.get("/v1/ready")
    assert response.status_code == 503


def test_ready_database_down(client: TestClient, monkeypatch):
    class _Boom:
        def __enter__(self):
            raise OSError("db down")

        def __exit__(self, *args):
            return False

    def _connect():
        return _Boom()

    monkeypatch.setattr("app.main.engine.connect", _connect)
    response = client.get("/v1/ready")
    assert response.status_code == 503


def test_jwt_secret_guard_rejects_short_secret():
    short = Settings(jwt_secret="too-short", allow_insecure_defaults=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        short.validate_security()


def test_jwt_secret_guard_allows_insecure_override():
    short = Settings(jwt_secret="x", allow_insecure_defaults=True)
    short.validate_security()


def test_jwt_secret_guard_accepts_long_secret():
    Settings(
        jwt_secret="test-secret-32-bytes-minimum!!!!",
        allow_insecure_defaults=False,
    ).validate_security()
