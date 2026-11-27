from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import role_headers, submit_ok


@pytest.mark.parametrize(
    ("path", "role"),
    [
        ("/v1/prior-auths", "admin"),
        ("/v1/review-queue", "reviewer"),
        ("/v1/me/prior-auths", "member"),
    ],
)
def test_list_endpoints_honor_limit_and_after_id(client: TestClient, path: str, role: str):
    for _ in range(3):
        submit_ok(client)

    headers = role_headers(client, role)
    full = client.get(path, headers=headers, params={"limit": 100})
    assert full.status_code == 200, full.text
    all_ids = [row["uuid"] for row in full.json()]
    assert len(all_ids) >= 3

    first = client.get(path, headers=headers, params={"limit": 1})
    assert first.status_code == 200, first.text
    assert len(first.json()) == 1
    assert first.json()[0]["uuid"] == all_ids[0]

    second = client.get(
        path,
        headers=headers,
        params={"limit": 1, "after": all_ids[0]},
    )
    assert second.status_code == 200, second.text
    assert len(second.json()) == 1
    assert second.json()[0]["uuid"] == all_ids[1]

    page = client.get(
        path,
        headers=headers,
        params={"limit": 2, "after": all_ids[0]},
    )
    assert page.status_code == 200, page.text
    assert [row["uuid"] for row in page.json()] == all_ids[1:3]


@pytest.mark.parametrize(
    ("path", "role"),
    [
        ("/v1/prior-auths", "admin"),
        ("/v1/review-queue", "reviewer"),
        ("/v1/me/prior-auths", "member"),
    ],
)
def test_list_endpoints_reject_oversized_limit(client: TestClient, path: str, role: str):
    response = client.get(
        path,
        headers=role_headers(client, role),
        params={"limit": 101},
    )
    assert response.status_code == 422, response.text
