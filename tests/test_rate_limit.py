"""Token-bucket rate limiter: memory + Redis wiring + HTTP middleware."""

from __future__ import annotations

import asyncio
import time

from app.rate_limit import metrics as rate_metrics
from app.rate_limit.bucket import MemoryTokenBucket, RedisTokenBucket
from app.rate_limit.middleware import RateLimitMiddleware, build_store, client_ip
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeRedis:
    """Minimal hash store for RedisTokenBucket unit tests."""

    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, float]] = {}

    def hmget(self, key: str, *fields: str):
        row = self._hashes.get(key, {})
        return [row.get(field) for field in fields]

    def hset(self, key: str, mapping: dict):
        row = self._hashes.setdefault(key, {})
        for field, value in mapping.items():
            row[str(field)] = float(value)
        return len(mapping)

    def pexpire(self, key: str, _ttl_ms: int):
        return 1 if key in self._hashes else 0


def test_memory_bucket_allows_then_rejects():
    bucket = MemoryTokenBucket(capacity=2, refill_per_second=0.0)
    first = bucket.consume("k")
    second = bucket.consume("k")
    third = bucket.consume("k")
    assert first.allowed and second.allowed
    assert not third.allowed
    assert third.limit == 2
    assert third.retry_after_ms >= 1


def test_memory_bucket_refills():
    bucket = MemoryTokenBucket(capacity=1, refill_per_second=1000.0)
    assert bucket.consume("a").allowed
    denied = bucket.consume("a")
    assert not denied.allowed
    assert denied.retry_after_ms >= 1
    time.sleep(0.005)
    assert bucket.consume("a").allowed


def test_memory_bucket_zero_refill_retry():
    bucket = MemoryTokenBucket(capacity=1, refill_per_second=0.0)
    assert bucket.consume("z").allowed
    denied = bucket.consume("z")
    assert not denied.allowed
    assert denied.retry_after_ms == 60_000


def test_build_store_memory_and_redis_url():
    memory, name = build_store(redis_url="", capacity=10, refill_per_second=1.0)
    assert name == "memory"
    assert isinstance(memory, MemoryTokenBucket)

    redis_bucket = RedisTokenBucket(_FakeRedis(), capacity=5, refill_per_second=1.0)
    result = redis_bucket.consume("rl:1.2.3.4")
    assert result.allowed
    assert result.remaining == 4
    assert result.limit == 5


def test_redis_bucket_reject_path():
    fake = _FakeRedis()
    bucket = RedisTokenBucket(fake, capacity=1, refill_per_second=0.0)
    assert bucket.consume("rl:x").allowed
    denied = bucket.consume("rl:x")
    assert not denied.allowed
    assert denied.remaining == 0
    assert denied.retry_after_ms == 60_000


def test_redis_bucket_refills_and_parses_bytes():
    fake = _FakeRedis()
    bucket = RedisTokenBucket(fake, capacity=1, refill_per_second=1000.0)
    assert bucket.consume("rl:b").allowed
    # Simulate Redis returning byte strings on the next read.
    fake._hashes["rl:b"] = {"tokens": 0.0, "ts": (time.time() * 1000.0) - 5.0}
    # Force hmget to return bytes like decode_responses=False clients.
    original = fake.hmget

    def _hmget_bytes(key: str, *fields: str):
        values = original(key, *fields)
        return [None if v is None else str(v).encode() for v in values]

    fake.hmget = _hmget_bytes  # type: ignore[method-assign]
    assert bucket.consume("rl:b").allowed


def test_build_store_with_redis_url_uses_redis(monkeypatch):
    import redis as redis_lib

    def _fake_from_url(*_a, **_k):
        return _FakeRedis()

    monkeypatch.setattr(redis_lib, "from_url", _fake_from_url)
    store, name = build_store(
        redis_url="redis://localhost:6379/0",
        capacity=10,
        refill_per_second=2.0,
    )
    assert name == "redis"
    assert isinstance(store, RedisTokenBucket)
    assert store.consume("k").allowed


def test_client_ip_from_forwarded_and_fallback():
    assert client_ip({"headers": [(b"x-forwarded-for", b"10.0.0.1, 10.0.0.2")]}) == "10.0.0.1"
    assert client_ip({"headers": [(b"x-forwarded-for", b"  ,")]}) == "unknown"
    assert client_ip({"headers": [], "client": ("127.0.0.1", 9)}) == "127.0.0.1"
    assert client_ip({"headers": []}) == "unknown"


def test_middleware_429_and_headers():
    inner = FastAPI()

    @inner.get("/v1/ping")
    def ping():
        return {"ok": True}

    @inner.get("/v1/health")
    def health():
        return {"status": "ok"}

    store = MemoryTokenBucket(capacity=1, refill_per_second=0.0)
    app = RateLimitMiddleware(inner, store=store, backend_name="memory", key_prefix="t:")
    with TestClient(app) as client:
        ok = client.get("/v1/ping")
        assert ok.status_code == 200
        assert ok.headers["X-RateLimit-Limit"] == "1"
        assert "X-RateLimit-Remaining" in ok.headers

        denied = client.get("/v1/ping")
        assert denied.status_code == 429
        body = denied.json()
        assert body["detail"] == "Rate limit exceeded"
        assert body["errors"][0]["error_code"] == "rate_limited"
        assert denied.headers["Retry-After"]
        assert denied.headers["X-RateLimit-Remaining"] == "0"

        # Health is exempt and does not consume tokens.
        assert client.get("/v1/health").status_code == 200


def test_middleware_disabled_and_non_http():
    inner = FastAPI()

    @inner.get("/v1/ping")
    def ping():
        return {"ok": True}

    store = MemoryTokenBucket(capacity=1, refill_per_second=0.0)
    app = RateLimitMiddleware(inner, store=store, backend_name="memory", enabled=False)
    with TestClient(app) as client:
        assert client.get("/v1/ping").status_code == 200
        assert client.get("/v1/ping").status_code == 200

    async def _noop_receive():
        return {"type": "http.disconnect"}

    async def _noop_send(_message):
        return None

    async def _run_lifespan():
        await app({"type": "lifespan"}, _noop_receive, _noop_send)

    asyncio.run(_run_lifespan())


def test_middleware_custom_exempt_paths():
    inner = FastAPI()

    @inner.get("/skip")
    def skip():
        return {"ok": True}

    store = MemoryTokenBucket(capacity=1, refill_per_second=0.0)
    app = RateLimitMiddleware(
        inner,
        store=store,
        backend_name="memory",
        exempt_paths=frozenset({"/skip"}),
    )
    with TestClient(app) as client:
        assert client.get("/skip").status_code == 200
        assert client.get("/skip").status_code == 200
        assert "X-RateLimit-Limit" not in client.get("/skip").headers


def test_metrics_helpers_do_not_raise():
    rate_metrics.record_decision(allowed=True, backend="memory")
    rate_metrics.record_decision(allowed=False, backend="redis")
    with rate_metrics.start_consume_span(key="rl:test", backend="memory") as span:
        span.set_attribute("rate_limit.allowed", True)


def test_app_attaches_rate_limit_headers(client: TestClient):
    response = client.get(
        "/v1/me", headers={"Authorization": f"Bearer {client.seed['tokens']['admin']}"}
    )
    assert response.status_code == 200
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers


def test_app_health_exempt_from_rate_headers(client: TestClient):
    response = client.get("/v1/health")
    assert response.status_code == 200
    # Exempt path skips the limiter, so rate headers are absent.
    assert "X-RateLimit-Limit" not in response.headers
