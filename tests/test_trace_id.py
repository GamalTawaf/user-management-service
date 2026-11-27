from fastapi.testclient import TestClient

from tests.conftest import role_headers


def test_health_includes_x_trace_id(client: TestClient):
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.headers.get("X-Trace-Id")


def test_echoes_client_trace_id(client: TestClient):
    response = client.get(
        "/v1/me",
        headers={**role_headers(client, "member"), "X-Trace-Id": "abc123"},
    )
    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == "abc123"
