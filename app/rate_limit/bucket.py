"""Token-bucket rate limiter: Redis hash get/set or in-process memory fallback."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class BucketResult:
    allowed: bool
    remaining: int
    limit: int
    retry_after_ms: int


def _apply_consume(
    *,
    available: float,
    ts_ms: float,
    now_ms: float,
    capacity: float,
    refill_per_ms: float,
    requested: int,
) -> tuple[bool, float, float, int]:
    """Refill from elapsed time, then take `requested` tokens if available."""
    elapsed = max(0.0, now_ms - ts_ms)
    refilled = available + elapsed * refill_per_ms
    available = min(capacity, refilled)
    retry_after_ms = 0
    allowed = available >= requested
    if allowed:
        available = available - requested
    elif refill_per_ms > 0:
        missing = requested - available
        retry_after_ms = int((missing / refill_per_ms) + 0.999)
    else:
        retry_after_ms = 60_000
    return allowed, available, now_ms, retry_after_ms


def _bucket_ttl_ms(*, capacity: float, refill_per_ms: float) -> int:
    if refill_per_ms <= 0:
        return 60_000
    ttl_ms = int((capacity / refill_per_ms) * 2 + 0.999)
    return max(1000, ttl_ms)


class MemoryTokenBucket:
    """Process-local buckets for tests / Redis-less demos."""

    def __init__(self, *, capacity: int, refill_per_second: float) -> None:
        self._capacity = capacity
        self._refill_per_ms = refill_per_second / 1000.0
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}

    def consume(self, key: str, *, tokens: int = 1) -> BucketResult:
        now_ms = time.time() * 1000.0
        with self._lock:
            state = self._buckets.get(key)
            capacity_f = float(self._capacity)
            if state is None:
                available = capacity_f
                ts = now_ms
            else:
                available, ts = state
            allowed, available, ts, retry_after_ms = _apply_consume(
                available=available,
                ts_ms=ts,
                now_ms=now_ms,
                capacity=capacity_f,
                refill_per_ms=self._refill_per_ms,
                requested=tokens,
            )
            self._buckets[key] = (available, ts)
            remaining = int(available)
        return BucketResult(
            allowed=allowed,
            remaining=remaining,
            limit=self._capacity,
            retry_after_ms=retry_after_ms,
        )


class RedisTokenBucket:
    """Distributed token bucket stored as a Redis hash (get → update → set)."""

    def __init__(self, redis_client, *, capacity: int, refill_per_second: float) -> None:
        self._redis = redis_client
        self._capacity = capacity
        self._refill_per_ms = refill_per_second / 1000.0

    def consume(self, key: str, *, tokens: int = 1) -> BucketResult:
        now_ms = time.time() * 1000.0
        capacity_f = float(self._capacity)
        raw = self._redis.hmget(key, "tokens", "ts")
        available = _parse_float(raw[0], default=capacity_f)
        ts = _parse_float(raw[1], default=now_ms)
        allowed, available, ts, retry_after_ms = _apply_consume(
            available=available,
            ts_ms=ts,
            now_ms=now_ms,
            capacity=capacity_f,
            refill_per_ms=self._refill_per_ms,
            requested=tokens,
        )
        ttl_ms = _bucket_ttl_ms(capacity=capacity_f, refill_per_ms=self._refill_per_ms)
        self._redis.hset(key, mapping={"tokens": available, "ts": ts})
        self._redis.pexpire(key, ttl_ms)
        remaining = int(available)
        return BucketResult(
            allowed=allowed,
            remaining=remaining,
            limit=self._capacity,
            retry_after_ms=retry_after_ms,
        )


def _parse_float(value: object, *, default: float) -> float:
    if value is None:
        return default
    text = value.decode() if isinstance(value, bytes) else str(value)
    return float(text)
