"""Token-bucket rate limiter: Redis (atomic Lua) or in-process memory fallback."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# Atomic consume: refill by elapsed time, then take `requested` tokens if available.
_LUA_CONSUME = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil then
  tokens = capacity
  ts = now_ms
end

local elapsed = now_ms - ts
if elapsed < 0 then
  elapsed = 0
end
tokens = math.min(capacity, tokens + (elapsed * refill_per_ms))
ts = now_ms

local allowed = 0
local retry_after_ms = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  local missing = requested - tokens
  if refill_per_ms > 0 then
    retry_after_ms = math.ceil(missing / refill_per_ms)
  else
    retry_after_ms = 60000
  end
end

redis.call('HSET', key, 'tokens', tokens, 'ts', ts)
local ttl_ms = 1
if refill_per_ms > 0 then
  ttl_ms = math.ceil((capacity / refill_per_ms) * 2)
end
if ttl_ms < 1000 then
  ttl_ms = 1000
end
redis.call('PEXPIRE', key, ttl_ms)

return {allowed, math.floor(tokens), retry_after_ms}
"""


@dataclass(frozen=True)
class BucketResult:
    allowed: bool
    remaining: int
    limit: int
    retry_after_ms: int


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
            elapsed = max(0.0, now_ms - ts)
            refilled = available + elapsed * self._refill_per_ms
            available = min(capacity_f, refilled)
            retry_after_ms = 0
            allowed = available >= tokens
            if allowed:
                available = available - tokens
            elif self._refill_per_ms > 0:
                missing = tokens - available
                retry_after_ms = int((missing / self._refill_per_ms) + 0.999)
            else:
                retry_after_ms = 60_000
            self._buckets[key] = (available, now_ms)
            remaining = int(available)
        return BucketResult(
            allowed=allowed,
            remaining=remaining,
            limit=self._capacity,
            retry_after_ms=retry_after_ms,
        )


class RedisTokenBucket:
    """Distributed token bucket via a single Redis Lua script."""

    def __init__(self, redis_client, *, capacity: int, refill_per_second: float) -> None:
        self._redis = redis_client
        self._capacity = capacity
        self._refill_per_ms = refill_per_second / 1000.0
        self._script = redis_client.register_script(_LUA_CONSUME)

    def consume(self, key: str, *, tokens: int = 1) -> BucketResult:
        now_ms = int(time.time() * 1000)
        raw = self._script(
            keys=[key],
            args=[self._capacity, self._refill_per_ms, now_ms, tokens],
        )
        allowed_flag = int(raw[0])
        remaining = int(raw[1])
        retry_after_ms = int(raw[2])
        return BucketResult(
            allowed=allowed_flag == 1,
            remaining=remaining,
            limit=self._capacity,
            retry_after_ms=retry_after_ms,
        )
