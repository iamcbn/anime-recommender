# backend/rag_pipeline/helper/rate_limiter.py
"""
Distributed Sliding-Window Rate Limiter using Upstash Redis Sorted Sets (Sprint 4 Task 4.3).

Features:
- Primary Tier: Atomic Lua Script on Upstash Redis Sorted Sets (ZSET).
  - ACID atomicity prevents TOCTOU concurrency race conditions across serverless containers.
  - Server-side redis.call('TIME') eliminates container clock skew.
  - Sub-millisecond sliding window accuracy.
- Secondary Tier: Local in-memory sliding-window fallback with 150ms circuit breaker.
  - Automatically activates when Redis credentials are unset or network exceeds 150ms.
- 100% Backward Compatibility:
  - DualModeRateLimitResult supports synchronous tuple unpacking for legacy tests.
  - In-memory `requests` dictionary preserved for test fixtures.
"""

import os
import time
import uuid
import hashlib
import asyncio
import logging
from collections import defaultdict
from datetime import timedelta, datetime
from typing import Optional, Tuple, Union, Any

logger = logging.getLogger("anime_recommender.rate_limiter")

DEFAULT_REDIS_TIMEOUT_SEC = 0.150  # 150 milliseconds
DEFAULT_LIMIT = 20
DEFAULT_WINDOW_SEC = 60

# Atomic Lua script for distributed sliding-window rate limiting
LUA_SLIDING_WINDOW_SCRIPT = """
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) + (tonumber(redis_time[2]) / 1000000)
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local nonce = ARGV[3]
local member = tostring(now) .. ":" .. nonce
local clear_before = now - window

-- 1. Remove timestamps older than the sliding window
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', clear_before)

-- 2. Count active requests within current window
local current_count = redis.call('ZCARD', KEYS[1])

if current_count < limit then
    -- Allowed: record request timestamp and reset TTL
    redis.call('ZADD', KEYS[1], now, member)
    redis.call('EXPIRE', KEYS[1], math.ceil(window) + 2)
    local remaining = limit - current_count - 1
    return {0, remaining, 0}
else
    -- Over quota: calculate retry_after based on oldest entry in window
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry_after = math.ceil(window)
    if oldest and #oldest >= 2 then
        local oldest_ts = tonumber(oldest[2])
        retry_after = math.max(1, math.ceil(oldest_ts + window - now))
    end
    redis.call('EXPIRE', KEYS[1], math.ceil(window) + 2)
    return {1, 0, retry_after}
end
"""


class DualModeRateLimitResult:
    """
    Dual-mode result supporting both synchronous tuple unpacking
    `(is_limited, remaining)` and asynchronous awaiting `await result`.
    """

    def __init__(self, sync_tuple: Tuple[bool, int, int], async_coro=None):
        self._sync_tuple = sync_tuple
        self._async_coro = async_coro

    def __iter__(self):
        # Unpacks as (is_rate_limited, remaining_tokens) for backward compatibility
        return iter((self._sync_tuple[0], self._sync_tuple[1]))

    def __getitem__(self, index):
        return self._sync_tuple[index]

    def __bool__(self):
        return bool(self._sync_tuple[0])

    def __await__(self):
        if self._async_coro:
            return self._async_coro().__await__()

        async def _passthrough():
            return self._sync_tuple

        return _passthrough().__await__()


class DistributedRateLimiter:
    """
    Production-grade distributed sliding-window rate limiter using Upstash Redis.
    Gracefully degrades to an in-memory sliding window when Redis is unavailable or times out.
    """

    def __init__(
        self,
        requests_num: int = DEFAULT_LIMIT,
        period: Union[timedelta, int] = DEFAULT_WINDOW_SEC,
        redis_timeout: float = DEFAULT_REDIS_TIMEOUT_SEC,
        url: Optional[str] = None,
        token: Optional[str] = None,
        redis_client: Optional[Any] = None,
    ):
        self.requests_per_min = requests_num
        self.period = period if isinstance(period, timedelta) else timedelta(seconds=int(period))
        self.window_seconds = int(self.period.total_seconds())
        self.redis_timeout = redis_timeout

        # In-memory storage for test compatibility and local fallback
        self.requests = defaultdict(list)

        self.url = url or os.getenv("UPSTASH_REDIS_REST_URL")
        self.token = token or os.getenv("UPSTASH_REDIS_REST_TOKEN")

        if redis_client is not None:
            self.redis = redis_client
            logger.info("[DistributedRateLimiter] Injected Redis client used.")
        elif self.url and self.token:
            try:
                from upstash_redis.asyncio import Redis
                self.redis = Redis(url=self.url, token=self.token)
                logger.info("[DistributedRateLimiter] Upstash Redis async client initialized successfully.")
            except Exception as e:
                logger.warning(
                    f"[DistributedRateLimiter] Failed to initialize Redis client: {e}. "
                    f"Operating in memory fallback mode."
                )
                self.redis = None
        else:
            self.redis = None
            logger.info("[DistributedRateLimiter] Redis credentials unset; operating in local in-memory mode.")

    @property
    def is_redis_available(self) -> bool:
        return self.redis is not None

    def _in_memory_check(self, key: str) -> Tuple[bool, int, int]:
        """Local sliding-window check."""
        now = time.time()
        start_ts = now - self.window_seconds

        valid_requests = []
        for req in self.requests[key]:
            req_ts = req.timestamp() if isinstance(req, datetime) else float(req)
            if req_ts > start_ts:
                valid_requests.append(req_ts)
        self.requests[key] = valid_requests

        count = len(valid_requests)
        if count >= self.requests_per_min:
            oldest_ts = valid_requests[0] if valid_requests else now
            retry_after = max(1, int(oldest_ts + self.window_seconds - now))
            return True, 0, retry_after

        self.requests[key].append(now)
        remaining = self.requests_per_min - count - 1
        return False, remaining, 0

    async def _redis_check(self, redis_key: str) -> Tuple[bool, int, int]:
        """Executes atomic Lua script with 150ms timeout."""
        nonce = uuid.uuid4().hex[:8]
        raw_res = await asyncio.wait_for(
            self.redis.eval(
                LUA_SLIDING_WINDOW_SCRIPT,
                keys=[redis_key],
                args=[str(self.window_seconds), str(self.requests_per_min), nonce],
            ),
            timeout=self.redis_timeout,
        )

        is_limited = bool(int(raw_res[0]))
        remaining = int(raw_res[1])
        retry_after = int(raw_res[2])
        return is_limited, remaining, retry_after

    async def check_rate_limit(
        self,
        identifier: str,
        is_api_key: bool = True,
    ) -> Tuple[bool, int, int]:
        """
        Primary asynchronous rate check method.
        Returns: (is_limited: bool, remaining: int, retry_after: int)
        """
        if not identifier:
            identifier = "anonymous"

        if is_api_key:
            hashed_id = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]
            redis_key = f"ratelimit:key:{hashed_id}"
            memory_key = identifier
        else:
            redis_key = f"ratelimit:ip:{identifier}"
            memory_key = identifier

        if not self.redis:
            return self._in_memory_check(memory_key)

        try:
            return await self._redis_check(redis_key)
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                f"[DistributedRateLimiter] Redis check failed ({type(exc).__name__}: {exc}). "
                f"Falling back to local in-memory window."
            )
            return self._in_memory_check(memory_key)

    def is_rate_limited(self, api_key: str):
        """
        Backward-compatible dual-mode method for existing synchronous tests and routes.
        Can be used as:
            is_limited, remaining = rate_limiter.is_rate_limited(api_key)
        or:
            is_limited, remaining, retry_after = await rate_limiter.is_rate_limited(api_key)
        """
        if self.redis:
            async def _async_runner():
                return await self.check_rate_limit(api_key, is_api_key=True)
            sync_result = self._in_memory_check(api_key)
            return DualModeRateLimitResult(sync_result, _async_runner)

        sync_result = self._in_memory_check(api_key)
        return DualModeRateLimitResult(sync_result)

    def reset(self):
        """Resets in-memory request history."""
        self.requests.clear()

    @staticmethod
    def extract_client_ip(request: Any) -> str:
        """Extracts client IP from proxy headers or direct socket."""
        if hasattr(request, "headers"):
            cf_ip = request.headers.get("cf-connecting-ip")
            if cf_ip:
                return cf_ip.strip()
            xfwd = request.headers.get("x-forwarded-for")
            if xfwd:
                return xfwd.split(",")[0].strip()
            xreal = request.headers.get("x-real-ip")
            if xreal:
                return xreal.strip()
        if hasattr(request, "client") and request.client:
            return request.client.host
        return "127.0.0.1"


# Default application-wide singleton
rate_limiter = DistributedRateLimiter(requests_num=DEFAULT_LIMIT, period=DEFAULT_WINDOW_SEC)
RateLimiter = DistributedRateLimiter
