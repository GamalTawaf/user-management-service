from fastapi.testclient import TestClient


def test_health(client: TestClient):
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
