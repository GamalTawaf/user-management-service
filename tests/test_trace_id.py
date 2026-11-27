from __future__ import annotations

from app.main import app
from app.shared.middleware import TRACE_ID_HEADER
from fastapi.testclient import TestClient

from tests.conftest import role_headers


def test_health_includes_x_trace_id():
    client = TestClient(app)
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.headers.get(TRACE_ID_HEADER)


def test_echoes_client_provided_x_trace_id():
    client = TestClient(app)
    response = client.get("/v1/health", headers={TRACE_ID_HEADER: "partner-retry-42"})
    assert response.headers.get(TRACE_ID_HEADER) == "partner-retry-42"


def test_blank_or_oversized_x_trace_id_is_replaced():
    client = TestClient(app)
    blank = client.get("/v1/health", headers={TRACE_ID_HEADER: "   "})
    assert blank.headers.get(TRACE_ID_HEADER)
    assert blank.headers.get(TRACE_ID_HEADER) != "   "

    huge = "x" * 200
    replaced = client.get("/v1/health", headers={TRACE_ID_HEADER: huge})
    assert replaced.headers.get(TRACE_ID_HEADER) != huge
    assert len(replaced.headers.get(TRACE_ID_HEADER, "")) <= 128


def test_413_still_includes_x_trace_id(client: TestClient):
    from app.clock import get_today

    huge = "y" * 300_000
    response = client.post(
        "/v1/prior-auths",
        headers={
            **role_headers(client, "office"),
            "Content-Type": "application/json",
            TRACE_ID_HEADER: "body-too-large",
        },
        content=(
            f'{{"member_id":"{client.seed["member"].uuid}","diagnosis_icd10":"J06.9",'
            f'"date_of_service":"{get_today().isoformat()}","clinical_note":"{huge}",'
            f'"procedures":[{{"code":"99213","units":1}}]}}'
        ),
    )
    assert response.status_code == 413
    assert response.headers.get(TRACE_ID_HEADER) == "body-too-large"


def test_openapi_documents_x_trace_id_on_responses():
    # Fresh schema (other tests may cache on app).
    app.openapi_schema = None
    spec = app.openapi()
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            for code, resp in (op.get("responses") or {}).items():
                headers = resp.get("headers") or {}
                assert TRACE_ID_HEADER in headers, f"{method.upper()} {path} {code}"
