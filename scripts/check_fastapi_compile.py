#!/usr/bin/env python3
"""Compile-check the FastAPI app: bytecode + OpenAPI generation + route inventory."""

from __future__ import annotations

import compileall
import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    app_dir = root / "app"

    print("=== compileall app/ ===")
    ok = compileall.compile_dir(str(app_dir), quiet=1, force=True)
    if not ok:
        print("compileall failed")
        return 1
    print("compileall ok")

    print("=== import app.main:app ===")
    from app.main import app

    print(f"title={app.title!r} version={app.version!r}")

    print("=== app.openapi() ===")
    schema = app.openapi()
    paths = schema.get("paths") or {}
    if not paths:
        print("OpenAPI paths empty")
        return 1
    required = (
        "/v1/health",
        "/v1/prior-auths",
        "/v1/review-queue",
        "/v1/me/prior-auths",
        "/v1/support/intake-rejections/{correlation_id}",
    )
    missing = [p for p in required if p not in paths]
    if missing:
        print(f"missing OpenAPI paths: {missing}")
        return 1

    route_count = 0
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            route_count += 1
            endpoint = getattr(route, "endpoint", None)
            if endpoint is None or not callable(endpoint):
                print(f"non-callable endpoint for {methods} {path}")
                return 1

    print(f"openapi paths={len(paths)} http_routes={route_count}")
    print(json.dumps({"openapi": schema.get("openapi"), "path_count": len(paths)}, indent=2))
    print("fastapi compile checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
