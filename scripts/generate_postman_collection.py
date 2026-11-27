#!/usr/bin/env -S uv run python
"""Build Postman Collection v2.1 + environment from live FastAPI OpenAPI."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.clock import get_today
from app.identity.auth import mint_token
from app.identity.models import User, UserRole
from app.main import app

from scripts.seed import (
    ADMIN_ID,
    AUDITOR_ID,
    MEMBER_ID,
    MEMBER_UNLINKED_ID,
    MEMBER_USER_ID,
    OFFICE_ID,
    PRACTICE_ID,
    REVIEWER_COI_ID,
    REVIEWER_ID,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "postman"

# Tokens use a fixed exp so env JSON is stable; DOS must be "today" for submit to pass.
_POSTMAN_TOKEN_EXP = datetime(2099, 1, 1, tzinfo=UTC)

_PATH_PARAM = re.compile(r"\{([^}/]+)\}")

# Ready-to-send demo payloads. Env vars are prefilled from seed; paste ids after submit.
_DEMO_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("post", "/v1/prior-auths"): {
        "member_id": "{{member_id}}",
        "diagnosis_icd10": "J06.9",
        "date_of_service": "{{date_of_service}}",
        "clinical_note": "Demo clinical note for Postman",
        "procedures": [{"code": "99213", "units": 1}],
    },
    ("post", "/v1/prior-auths/{request_id}/decision"): {
        "outcomes": [
            {
                "procedure_id": "{{procedure_id}}",
                "decision": "approved",
            }
        ],
    },
    ("post", "/v1/prior-auths/{request_id}/reassign"): {
        "reviewer_id": "{{reviewer_id}}",
    },
}

# Bearer env var per operationId / path+method (seed role that can call the route).
_TOKEN_FOR: dict[tuple[str, str], str] = {
    ("post", "/v1/prior-auths"): "{{office_token}}",
    ("get", "/v1/prior-auths"): "{{office_token}}",
    ("get", "/v1/prior-auths/{request_id}"): "{{office_token}}",
    ("get", "/v1/review-queue"): "{{reviewer_token}}",
    ("post", "/v1/prior-auths/{request_id}/claim"): "{{reviewer_token}}",
    ("post", "/v1/prior-auths/{request_id}/decision"): "{{reviewer_token}}",
    ("post", "/v1/prior-auths/{request_id}/reassign"): "{{admin_token}}",
    ("get", "/v1/prior-auths/{request_id}/audit"): "{{auditor_token}}",
    ("get", "/v1/reviewers/workload"): "{{admin_token}}",
    ("get", "/v1/me/prior-auths"): "{{member_token}}",
    ("get", "/v1/me/prior-auths/{request_id}"): "{{member_token}}",
    ("get", "/v1/support/intake-rejections/{correlation_id}"): "{{office_token}}",
}

_PATH_VAR_DEFAULTS: dict[str, str] = {
    "request_id": "{{request_id}}",
    "correlation_id": "{{correlation_id}}",
}

# Postman "Tests" (post-response) scripts — keep as plain JS lines for collection JSON.
_SET_ENV_HELPER = """
function setEnv(key, value) {
  if (value === undefined || value === null || value === "") return;
  const s = String(value);
  pm.environment.set(key, s);
  pm.collectionVariables.set(key, s);
}
function capturePriorAuth(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return;
  if (body.uuid) setEnv("request_id", body.uuid);
  const procs = body.procedures;
  if (Array.isArray(procs) && procs.length && procs[0] && procs[0].uuid) {
    setEnv("procedure_id", procs[0].uuid);
  }
}
function captureCorrelation(body) {
  if (body && body.correlation_id) setEnv("correlation_id", body.correlation_id);
}
function parseBody() {
  try { return pm.response.json(); } catch (e) { return null; }
}
""".strip().splitlines()

_CAPTURE_PRIOR_AUTH_TEST = [
    *_SET_ENV_HELPER,
    "const body = parseBody();",
    "if (!body) return;",
    "if (Array.isArray(body) && body.length) {",
    "  capturePriorAuth(body[0]);",
    "} else {",
    "  capturePriorAuth(body);",
    "  captureCorrelation(body);",
    "}",
]

_CAPTURE_CORRELATION_TEST = [
    *_SET_ENV_HELPER,
    "const body = parseBody();",
    "captureCorrelation(body);",
]

_SUBMIT_PRE_REQUEST = [
    "// Fresh key each Send so Submit creates a new prior auth (happy-path testing).",
    "pm.environment.set('idempotency_key', pm.variables.replaceIn('{{$guid}}'));",
    "pm.collectionVariables.set('idempotency_key', pm.environment.get('idempotency_key'));",
    "// DOS must be today-or-later for intake; refresh on each Send.",
    "const dos = new Date().toISOString().slice(0, 10);",
    "pm.environment.set('date_of_service', dos);",
    "pm.collectionVariables.set('date_of_service', dos);",
]

# (method, path) → post-response Tests script lines
_TEST_SCRIPTS: dict[tuple[str, str], list[str]] = {
    ("post", "/v1/prior-auths"): [
        *_SET_ENV_HELPER,
        "const body = parseBody();",
        "capturePriorAuth(body);",
        "captureCorrelation(body);",
    ],
    ("post", "/v1/prior-auths/{request_id}/claim"): _CAPTURE_PRIOR_AUTH_TEST,
    ("post", "/v1/prior-auths/{request_id}/decision"): _CAPTURE_PRIOR_AUTH_TEST,
    ("post", "/v1/prior-auths/{request_id}/reassign"): _CAPTURE_PRIOR_AUTH_TEST,
    ("get", "/v1/prior-auths/{request_id}"): _CAPTURE_PRIOR_AUTH_TEST,
    ("get", "/v1/prior-auths"): _CAPTURE_PRIOR_AUTH_TEST,
    ("get", "/v1/review-queue"): _CAPTURE_PRIOR_AUTH_TEST,
    ("get", "/v1/me/prior-auths"): _CAPTURE_PRIOR_AUTH_TEST,
    ("get", "/v1/me/prior-auths/{request_id}"): _CAPTURE_PRIOR_AUTH_TEST,
    ("get", "/v1/support/intake-rejections/{correlation_id}"): _CAPTURE_CORRELATION_TEST,
}

_PRE_REQUEST_SCRIPTS: dict[tuple[str, str], list[str]] = {
    ("post", "/v1/prior-auths"): _SUBMIT_PRE_REQUEST,
}


def _event(listen: str, lines: list[str]) -> dict[str, Any]:
    return {
        "listen": listen,
        "script": {
            "type": "text/javascript",
            "exec": lines,
        },
    }


def _bearer(token_expr: str) -> dict[str, Any]:
    return {
        "type": "bearer",
        "bearer": [{"key": "token", "value": token_expr, "type": "string"}],
    }


def _postman_url(path: str) -> dict[str, Any]:
    """Turn `/v1/foo/{id}` into Postman path segments + variables."""
    segments: list[str] = []
    variables: list[dict[str, str]] = []
    raw_parts: list[str] = []
    for part in path.strip("/").split("/"):
        if not part:
            continue
        match = _PATH_PARAM.fullmatch(part)
        if match:
            name = match.group(1)
            segments.append(f":{name}")
            raw_parts.append("{{" + name + "}}")
            variables.append(
                {
                    "key": name,
                    "value": _PATH_VAR_DEFAULTS.get(name, "{{" + name + "}}"),
                }
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


def _example_from_schema(schema: dict[str, Any], components: dict[str, Any]) -> Any:
    """Best-effort JSON example from an OpenAPI schema (for unknown bodies)."""
    if "$ref" in schema:
        ref = schema["$ref"].rsplit("/", 1)[-1]
        return _example_from_schema(components.get("schemas", {}).get(ref, {}), components)
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    schema_type = schema.get("type")
    if schema.get("enum"):
        return schema["enum"][0]
    if schema_type == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        out: dict[str, Any] = {}
        for key, prop in props.items():
            if key in required or prop.get("type") in {"object", "array"}:
                out[key] = _example_from_schema(prop, components)
            elif "default" in prop:
                out[key] = prop["default"]
            elif key in required:
                out[key] = _example_from_schema(prop, components)
        for key in required:
            out.setdefault(key, _example_from_schema(props.get(key, {}), components))
        return out
    if schema_type == "array":
        item = _example_from_schema(schema.get("items") or {}, components)
        return [item]
    if schema_type == "string":
        fmt = schema.get("format")
        if fmt == "uuid":
            return str(MEMBER_ID)
        if fmt == "date":
            return get_today().isoformat()
        if fmt == "date-time":
            return f"{get_today().isoformat()}T12:00:00Z"
        return "string"
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    if schema_type == "boolean":
        return True
    return None


def _body_for(method: str, path: str, op: dict[str, Any], components: dict[str, Any]) -> str:
    key = (method.lower(), path)
    if key in _DEMO_BODIES:
        return json.dumps(_DEMO_BODIES[key], indent=2)
    body = op.get("requestBody") or {}
    content = body.get("content") or {}
    app_json = content.get("application/json") or next(iter(content.values()), None)
    if not app_json:
        return "{}"
    if "example" in app_json:
        return json.dumps(app_json["example"], indent=2)
    examples = app_json.get("examples") or {}
    if examples:
        first = next(iter(examples.values()))
        if isinstance(first, dict) and "value" in first:
            return json.dumps(first["value"], indent=2)
    schema = app_json.get("schema") or {}
    generated = _example_from_schema(schema, components)
    return json.dumps(generated if generated is not None else {}, indent=2)


def _query_defaults(path: str, method: str) -> list[dict[str, Any]]:
    """Optional query params pre-filled for list endpoints."""
    if method.lower() != "get":
        return []
    if path in {"/v1/prior-auths", "/v1/review-queue", "/v1/me/prior-auths"}:
        return [
            {"key": "limit", "value": "20", "enabled": True},
            {"key": "after", "value": "", "description": "optional cursor id", "enabled": False},
        ]
    return []


def _items_from_openapi(spec: dict[str, Any]) -> list[dict[str, Any]]:
    components = spec.get("components") or {}
    items: list[dict[str, Any]] = []
    for path, methods in (spec.get("paths") or {}).items():
        for method, op in methods.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            name = op.get("summary") or f"{method.upper()} {path}"
            token = _TOKEN_FOR.get((method.lower(), path), "{{token}}")
            headers: list[dict[str, Any]] = [
                {"key": "Content-Type", "value": "application/json"},
            ]
            if method.lower() == "post" and path == "/v1/prior-auths":
                headers.append(
                    {
                        "key": "Idempotency-Key",
                        "value": "{{idempotency_key}}",
                        "description": "Optional; same key+body replays 201",
                    }
                )
            route = (method.lower(), path)
            request: dict[str, Any] = {
                "method": method.upper(),
                "header": headers,
                "url": _postman_url(path),
                "auth": _bearer(token),
                "description": (
                    op.get("description")
                    or (
                        "Generated demo request. Tests scripts write request_id / procedure_id / "
                        "correlation_id into the active environment from the response."
                    )
                ),
            }
            query = _query_defaults(path, method)
            if query:
                request["url"]["query"] = query
            if "requestBody" in op:
                request["body"] = {
                    "mode": "raw",
                    "raw": _body_for(method, path, op, components),
                    "options": {"raw": {"language": "json"}},
                }
            events: list[dict[str, Any]] = []
            pre = _PRE_REQUEST_SCRIPTS.get(route)
            if pre:
                events.append(_event("prerequest", pre))
            test = _TEST_SCRIPTS.get(route)
            if test:
                events.append(_event("test", test))
            item: dict[str, Any] = {"name": name, "request": request}
            if events:
                item["event"] = events
            items.append(item)
    return items


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    spec = app.openapi()
    items = _items_from_openapi(spec)
    collection = {
        "info": {
            "name": "Prior Auth API",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": (
                "Generated from FastAPI OpenAPI with seed demo bodies. "
                "Run `scripts/seed.py`, import env, then Submit → Claim → Decide. "
                "Tests scripts auto-set request_id / procedure_id / correlation_id. "
                "Do not hand-edit; regenerate."
            ),
        },
        "item": items,
        "auth": _bearer("{{token}}"),
        "variable": [
            {
                "key": "request_id",
                "value": "00000000-0000-4000-8000-000000000001",
            },
            {
                "key": "procedure_id",
                "value": "00000000-0000-4000-8000-000000000002",
            },
            {"key": "correlation_id", "value": "demo-correlation"},
            {"key": "idempotency_key", "value": "demo-submit-1"},
            {"key": "date_of_service", "value": get_today().isoformat()},
        ],
    }

    users = {
        "office_token": User(
            uuid=OFFICE_ID,
            email="office@example.com",
            role=UserRole.provider_office,
            practice_id=PRACTICE_ID,
            display_name="o",
        ),
        "reviewer_token": User(
            uuid=REVIEWER_ID, email="reviewer@example.com", role=UserRole.reviewer, display_name="r"
        ),
        "reviewer_coi_token": User(
            uuid=REVIEWER_COI_ID,
            email="reviewer.coi@example.com",
            role=UserRole.reviewer,
            display_name="c",
        ),
        "admin_token": User(
            uuid=ADMIN_ID, email="admin@example.com", role=UserRole.ops_admin, display_name="a"
        ),
        "auditor_token": User(
            uuid=AUDITOR_ID,
            email="auditor@example.com",
            role=UserRole.auditor,
            display_name="au",
        ),
        "member_token": User(
            uuid=MEMBER_USER_ID,
            email="member@example.com",
            role=UserRole.member,
            member_id=MEMBER_ID,
            display_name="m",
        ),
    }
    env_values = [
        {"key": "base_url", "value": "http://localhost:8000", "enabled": True},
        {"key": "token", "value": "{{office_token}}", "enabled": True},
        {"key": "member_id", "value": str(MEMBER_ID), "enabled": True},
        {"key": "member_unlinked_id", "value": str(MEMBER_UNLINKED_ID), "enabled": True},
        {"key": "practice_id", "value": str(PRACTICE_ID), "enabled": True},
        {"key": "reviewer_id", "value": str(REVIEWER_ID), "enabled": True},
        {
            "key": "request_id",
            "value": "00000000-0000-4000-8000-000000000001",
            "enabled": True,
            "description": "Auto-set by Submit/Claim/GET Tests scripts",
        },
        {
            "key": "procedure_id",
            "value": "00000000-0000-4000-8000-000000000002",
            "enabled": True,
            "description": "Auto-set to procedures[0].uuid by Tests scripts",
        },
        {
            "key": "idempotency_key",
            "value": "demo-submit-1",
            "enabled": True,
            "description": "Refreshed on each Submit via pre-request script",
        },
        {
            "key": "date_of_service",
            "value": get_today().isoformat(),
            "enabled": True,
            "description": "Refreshed to today on each Submit via pre-request",
        },
        {
            "key": "correlation_id",
            "value": "demo-correlation",
            "enabled": True,
            "description": "Auto-set from failed submit / validation body",
        },
    ]
    for key, user in users.items():
        env_values.append(
            {"key": key, "value": mint_token(user, exp=_POSTMAN_TOKEN_EXP), "enabled": True}
        )

    environment = {
        "id": "prior-auth-local",
        "name": "Prior Auth Local",
        "values": env_values,
    }

    (OUT / "Prior_Auth_API.postman_collection.json").write_text(
        json.dumps(collection, indent=2) + "\n"
    )
    (OUT / "Prior_Auth_API.postman_environment.json").write_text(
        json.dumps(environment, indent=2) + "\n"
    )

    submit = next(
        i
        for i in items
        if i["request"]["method"] == "POST" and i["request"]["url"]["path"] == ["v1", "prior-auths"]
    )
    assert "J06.9" in submit["request"]["body"]["raw"], submit["request"]["body"]["raw"]
    assert "{{member_id}}" in submit["request"]["body"]["raw"]
    assert "{{date_of_service}}" in submit["request"]["body"]["raw"]
    assert any(
        "date_of_service" in line
        for line in next(e for e in submit["event"] if e["listen"] == "prerequest")["script"][
            "exec"
        ]
    )
    decide = next(i for i in items if "/decision" in i["request"]["url"]["raw"])
    assert "{{procedure_id}}" in decide["request"]["body"]["raw"]
    reassign = next(i for i in items if "/reassign" in i["request"]["url"]["raw"])
    assert "{{reviewer_id}}" in reassign["request"]["body"]["raw"]
    claim = next(i for i in items if i["request"]["url"]["raw"].endswith("/claim"))
    assert claim["request"]["auth"]["bearer"][0]["value"] == "{{reviewer_token}}"
    assert any(e["listen"] == "test" for e in submit.get("event", [])), "submit needs Tests script"
    assert any(e["listen"] == "prerequest" for e in submit.get("event", [])), (
        "submit needs pre-request"
    )
    submit_test = next(e for e in submit["event"] if e["listen"] == "test")
    assert any("request_id" in line for line in submit_test["script"]["exec"])
    assert any("procedure_id" in line for line in submit_test["script"]["exec"])
    claim_test = next(e for e in claim["event"] if e["listen"] == "test")
    assert any("capturePriorAuth" in line for line in claim_test["script"]["exec"])

    paths = {item["request"]["url"]["raw"] for item in items}
    required = [
        "{{base_url}}/v1/prior-auths",
        "{{base_url}}/v1/prior-auths/{{request_id}}/claim",
        "{{base_url}}/v1/prior-auths/{{request_id}}/decision",
        "{{base_url}}/v1/me/prior-auths",
        "{{base_url}}/v1/support/intake-rejections/{{correlation_id}}",
    ]
    for req in required:
        assert any(req == p or req in p for p in paths), (req, paths)
    print(f"Wrote {len(items)} requests to {OUT}")


if __name__ == "__main__":
    main()
