"""ASGI middleware: token-bucket per client IP before auth."""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.rate_limit import metrics
from app.rate_limit.bucket import BucketResult, MemoryTokenBucket, RedisTokenBucket

_EXEMPT_PATHS = frozenset({"/v1/health", "/openapi.json", "/docs", "/redoc"})


def client_ip(scope: Scope) -> str:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        first_hop = forwarded.split(",")[0].strip()
        if first_hop:
            return first_hop
        return "unknown"
    client = scope.get("client")
    if client and client[0]:
        return str(client[0])
    return "unknown"


def _rate_headers(result: BucketResult) -> dict[str, str]:
    remaining = max(0, result.remaining)
    headers = {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(remaining),
    }
    if not result.allowed:
        retry_s = max(1, (result.retry_after_ms + 999) // 1000)
        headers["Retry-After"] = str(retry_s)
    return headers


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        store: MemoryTokenBucket | RedisTokenBucket,
        backend_name: str,
        key_prefix: str = "rl:",
        enabled: bool = True,
        exempt_paths: frozenset[str] | None = None,
    ) -> None:
        self.app = app
        self._store = store
        self._backend = backend_name
        self._prefix = key_prefix
        self._enabled = enabled
        if exempt_paths is None:
            self._exempt = _EXEMPT_PATHS
        else:
            self._exempt = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if path in self._exempt:
            await self.app(scope, receive, send)
            return

        ip = client_ip(scope)
        bucket_key = f"{self._prefix}{ip}"
        with metrics.start_consume_span(key=bucket_key, backend=self._backend) as span:
            result = await asyncio.to_thread(self._store.consume, bucket_key)
            span.set_attribute("rate_limit.allowed", result.allowed)
            span.set_attribute("rate_limit.remaining", result.remaining)
        metrics.record_decision(allowed=result.allowed, backend=self._backend)

        if not result.allowed:
            body = {
                "detail": "Rate limit exceeded",
                "errors": [
                    {
                        "error_code": "rate_limited",
                        "field": "request",
                        "message": "Too many requests; retry after the Retry-After header",
                    }
                ],
            }
            denied_headers = _rate_headers(result)
            response = JSONResponse(body, status_code=429, headers=denied_headers)
            await response(scope, receive, send)
            return

        rate_headers = _rate_headers(result)

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                existing = message.get("headers")
                raw_headers = [] if existing is None else list(existing)
                for name, value in rate_headers.items():
                    raw_headers.append((name.lower().encode(), value.encode()))
                message = {**message, "headers": raw_headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def build_store(
    *,
    redis_url: str,
    capacity: int,
    refill_per_second: float,
) -> tuple[MemoryTokenBucket | RedisTokenBucket, str]:
    url = redis_url.strip()
    if url:
        import redis as redis_lib

        client = redis_lib.from_url(url, decode_responses=False)
        store = RedisTokenBucket(client, capacity=capacity, refill_per_second=refill_per_second)
        return store, "redis"
    memory = MemoryTokenBucket(capacity=capacity, refill_per_second=refill_per_second)
    return memory, "memory"
