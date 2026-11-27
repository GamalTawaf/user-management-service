#!/usr/bin/env -S uv run python
"""Build Postman Collection v2.1 + environment from live FastAPI OpenAPI."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.identity.auth import mint_token
from app.identity.models import User, UserRole, UserStatus
from app.main import app

from scripts.seed import ADMIN_ID, AUDITOR_ID, INVITED_ID, MEMBER_ID, ORG_ID

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "postman"
_POSTMAN_TOKEN_EXP = datetime(2099, 1, 1, tzinfo=UTC)
_PATH_PARAM = re.compile(r"\{([^}/]+)\}")

_DEMO_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("post", "/v1/users"): {
        "email": "new.user@example.com",
        "display_name": "New User",
        "role": "member",
        "status": "invited",
        "org_id": "{{org_id}}",
    },
    ("patch", "/v1/me"): {"display_name": "Updated Name"},
    ("patch", "/v1/users/{user_id}"): {"display_name": "Patched User"},
    ("post", "/v1/orgs"): {
        "name": "New Org",
        "notification_email": "ops@neworg.example.com",
    },
}

_TOKEN_FOR: dict[tuple[str, str], str] = {
    ("get", "/v1/me"): "{{member_token}}",
    ("patch", "/v1/me"): "{{member_token}}",
    ("get", "/v1/users"): "{{admin_token}}",
    ("post", "/v1/users"): "{{admin_token}}",
    ("get", "/v1/users/stats"): "{{admin_token}}",
    ("get", "/v1/users/{user_id}"): "{{admin_token}}",
    ("patch", "/v1/users/{user_id}"): "{{admin_token}}",
    ("post", "/v1/users/{user_id}/disable"): "{{admin_token}}",
    ("post", "/v1/users/{user_id}/enable"): "{{admin_token}}",
    ("post", "/v1/users/{user_id}/activate"): "{{admin_token}}",
    ("get", "/v1/users/{user_id}/audit"): "{{auditor_token}}",
    ("get", "/v1/orgs"): "{{admin_token}}",
    ("post", "/v1/orgs"): "{{admin_token}}",
    ("get", "/v1/orgs/{org_id}"): "{{admin_token}}",
}

_PATH_VAR_DEFAULTS = {
    "user_id": "{{user_id}}",
    "org_id": "{{org_id}}",
}

_SET_ENV = """
function setEnv(key, value) {
  if (value === undefined || value === null || value === "") return;
  const s = String(value);
  pm.environment.set(key, s);
  pm.collectionVariables.set(key, s);
}
function parseBody() {
  try { return pm.response.json(); } catch (e) { return null; }
}
""".strip().splitlines()

_CAPTURE_USER = [
    *_SET_ENV,
    "const body = parseBody();",
    "if (body && body.uuid) setEnv('user_id', body.uuid);",
]

_TEST_SCRIPTS: dict[tuple[str, str], list[str]] = {
    ("post", "/v1/users"): _CAPTURE_USER,
    ("get", "/v1/users/{user_id}"): _CAPTURE_USER,
    ("post", "/v1/users/{user_id}/activate"): _CAPTURE_USER,
}

_PRE_REQUEST = {
    ("post", "/v1/users"): [
        "pm.environment.set('idempotency_key', pm.variables.replaceIn('{{$guid}}'));",
        "pm.collectionVariables.set('idempotency_key', pm.environment.get('idempotency_key'));",
    ],
}


def _event(listen: str, lines: list[str]) -> dict[str, Any]:
    return {"listen": listen, "script": {"type": "text/javascript", "exec": lines}}


def _bearer(token_expr: str) -> dict[str, Any]:
    return {"type": "bearer", "bearer": [{"key": "token", "value": token_expr, "type": "string"}]}


def _postman_url(path: str) -> dict[str, Any]:
    segments: list[str] = []
    variables: list[dict[str, str]] = []
    raw_parts: list[str] = []
    for part in path.strip("/").split("/"):
        match = _PATH_PARAM.fullmatch(part)
        if match:
            name = match.group(1)
            segments.append(f":{name}")
            raw_parts.append("{{" + name + "}}")
            variables.append(
                {"key": name, "value": _PATH_VAR_DEFAULTS.get(name, "{{" + name + "}}")}
            )
        else:
            segments.append(part)
            raw_parts.append(part)
    url: dict[str, Any] = {
        "raw": "{{base_url}}/" + "/".join(raw_parts),
        "host": ["{{base_url}}"],
        "path": segments,
    }
    if variables:
        url["variable"] = variables
    return url


def _body_for(method: str, path: str) -> str:
    key = (method.lower(), path)
    if key in _DEMO_BODIES:
        return json.dumps(_DEMO_BODIES[key], indent=2)
    return "{}"


def _items_from_openapi(spec: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path, methods in (spec.get("paths") or {}).items():
        for method, op in methods.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            name = op.get("summary") or f"{method.upper()} {path}"
            token = _TOKEN_FOR.get((method.lower(), path), "{{admin_token}}")
            headers = [{"key": "Content-Type", "value": "application/json"}]
            if method.lower() == "post" and path == "/v1/users":
                headers.append(
                    {"key": "Idempotency-Key", "value": "{{idempotency_key}}", "type": "text"}
                )
            request: dict[str, Any] = {
                "auth": _bearer(token),
                "method": method.upper(),
                "header": headers,
                "url": _postman_url(path),
            }
            if method.lower() in {"post", "patch", "put"}:
                request["body"] = {
                    "mode": "raw",
                    "raw": _body_for(method, path),
                    "options": {"raw": {"language": "json"}},
                }
            item: dict[str, Any] = {"name": name, "request": request}
            events = []
            if (method.lower(), path) in _PRE_REQUEST:
                events.append(_event("prerequest", _PRE_REQUEST[(method.lower(), path)]))
            if (method.lower(), path) in _TEST_SCRIPTS:
                events.append(_event("test", _TEST_SCRIPTS[(method.lower(), path)]))
            if events:
                item["event"] = events
            items.append(item)
    items.sort(key=lambda i: i["name"])
    return items


def _fake_user(user_id, email, role, status=UserStatus.active, org_id=None) -> User:
    return User(
        uuid=user_id,
        email=email,
        display_name=email.split("@")[0],
        role=role,
        status=status,
        org_id=org_id,
    )


def _environment() -> dict[str, Any]:
    admin = _fake_user(ADMIN_ID, "admin@example.com", UserRole.admin, org_id=ORG_ID)
    member = _fake_user(MEMBER_ID, "member@example.com", UserRole.member, org_id=ORG_ID)
    auditor = _fake_user(AUDITOR_ID, "auditor@example.com", UserRole.auditor)
    values = [
        {"key": "base_url", "value": "http://localhost:8000"},
        {"key": "org_id", "value": str(ORG_ID)},
        {"key": "user_id", "value": str(MEMBER_ID)},
        {"key": "invited_id", "value": str(INVITED_ID)},
        {"key": "idempotency_key", "value": "postman-demo-key"},
        {"key": "admin_token", "value": mint_token(admin, exp=_POSTMAN_TOKEN_EXP)},
        {"key": "member_token", "value": mint_token(member, exp=_POSTMAN_TOKEN_EXP)},
        {"key": "auditor_token", "value": mint_token(auditor, exp=_POSTMAN_TOKEN_EXP)},
        {"key": "token", "value": "{{admin_token}}"},
    ]
    return {
        "id": "ums-local-env",
        "name": "User Management Local",
        "values": [{"key": v["key"], "value": v["value"], "enabled": True} for v in values],
        "_postman_variable_scope": "environment",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    spec = app.openapi()
    collection = {
        "info": {
            "name": "User Management API",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": spec.get("description") or "",
        },
        "item": _items_from_openapi(spec),
        "variable": [
            {"key": "base_url", "value": "http://localhost:8000"},
            {"key": "user_id", "value": str(MEMBER_ID)},
            {"key": "org_id", "value": str(ORG_ID)},
            {"key": "idempotency_key", "value": "postman-demo-key"},
        ],
    }
    coll_path = OUT / "User_Management_API.postman_collection.json"
    env_path = OUT / "User_Management_API.postman_environment.json"
    coll_path.write_text(json.dumps(collection, indent=2) + "\n")
    env_path.write_text(json.dumps(_environment(), indent=2) + "\n")
    print(f"Wrote {len(collection['item'])} requests to {OUT}")


if __name__ == "__main__":
    main()
