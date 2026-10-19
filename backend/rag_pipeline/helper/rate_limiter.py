# backend/rag_pipeline/helper/rate_limiter.py
"""
Distributed Sliding-Window Rate Limiter using Upstash Redis Sorted Sets (Sprint 2 & Sprint 4).

Features:
- Primary Tier: Atomic Lua Script on Upstash Redis Sorted Sets (ZSET).
  - Server-side redis.call('TIME') eliminates container clock skew.
  - Sub-millisecond sliding window accuracy.
  - Zero double-counting: requests are counted once in Redis; in-memory store remains untouched.
  - Dynamic per-key rate limit support (ratelimit:key:{api_key_id}).
- Secondary Tier: Local in-memory sliding-window fallback with 150ms circuit breaker.
  - Automatically activates when Redis credentials are unset or network exceeds 150ms.
- Pre-auth Failed Authentication Throttling:
  - Detects and throttles brute-force attempts per IP (ratelimit:auth_fail:{ip}).
- Trusted-Proxy-Aware Client IP Extractor:
  - Validates socket peer against trusted CIDR ranges before parsing forwarding headers.
- Control Plane Resilience:
  - Fail-closed mode for sensitive management endpoints (/dev/*).
- 100% Backward Compatibility:
  - DualModeRateLimitResult supports synchronous tuple unpacking for legacy tests without double counting.
"""

import os
import time
import uuid
import hashlib
import asyncio
import logging
import ipaddress
from collections import defaultdict
from datetime import timedelta, datetime
from typing import Optional, Tuple, Union, Any, List

logger = logging.getLogger("anime_recommender.rate_limiter")

DEFAULT_REDIS_TIMEOUT_SEC = 0.150  # 150 milliseconds
DEFAULT_LIMIT = 20
DEFAULT_WINDOW_SEC = 60
DEFAULT_AUTH_FAIL_LIMIT = 10
DEFAULT_AUTH_FAIL_WINDOW_SEC = 60

# Atomic Lua script for recording requests and enforcing sliding-window rate limit
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

# Read-only peek script to evaluate lockout without incrementing counter
LUA_PEEK_WINDOW_SCRIPT = """
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) + (tonumber(redis_time[2]) / 1000000)
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local clear_before = now - window

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', clear_before)
local current_count = redis.call('ZCARD', KEYS[1])

if current_count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry_after = math.ceil(window)
    if oldest and #oldest >= 2 then
        local oldest_ts = tonumber(oldest[2])
        retry_after = math.max(1, math.ceil(oldest_ts + window - now))
    end
    return {1, 0, retry_after}
else
    local remaining = limit - current_count
    return {0, remaining, 0}
end
"""


class RateLimiterUnavailableError(Exception):
    """Raised when rate limiter is required to fail closed and Redis is unavailable."""
    pass


class DualModeRateLimitResult:
    """
    Dual-mode result supporting both synchronous tuple unpacking
    `(is_limited, remaining)` and asynchronous awaiting `await result`.
    Employs lazy evaluation to guarantee ZERO double-counting between in-memory
    and Redis state stores.
    """

    def __init__(self, sync_evaluator=None, async_coro=None, sync_tuple=None):
        if isinstance(sync_evaluator, tuple):
            self._sync_evaluator = None
            self._evaluated_tuple = sync_evaluator
        else:
            self._sync_evaluator = sync_evaluator
            self._evaluated_tuple = sync_tuple
        self._async_coro = async_coro

    def _get_sync(self) -> Tuple[bool, int, int]:
        if self._evaluated_tuple is None:
            if callable(self._sync_evaluator):
                self._evaluated_tuple = self._sync_evaluator()
            else:
                self._evaluated_tuple = (False, DEFAULT_LIMIT, 0)
        return self._evaluated_tuple

    def __iter__(self):
        t = self._get_sync()
        return iter((t[0], t[1]))

    def __getitem__(self, index):
        t = self._get_sync()
        return t[index]

    def __bool__(self):
        t = self._get_sync()
        return bool(t[0])

    def __await__(self):
        if self._async_coro:
            return self._async_coro().__await__()

        async def _passthrough():
            return self._get_sync()

        return _passthrough().__await__()


class TrustedProxyIPExtractor:
    """
    Secure client IP extraction verifying socket peer against trusted proxy networks
    before inspecting forwarding headers (Cloudflare, X-Forwarded-For).
    """

    def __init__(self, trusted_proxies: Optional[Union[str, List[str]]] = None):
        if trusted_proxies is None:
            raw = os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1")
            trusted_list = [p.strip() for p in raw.split(",") if p.strip()]
        elif isinstance(trusted_proxies, str):
            trusted_list = [p.strip() for p in trusted_proxies.split(",") if p.strip()]
        else:
            trusted_list = trusted_proxies

        self.trusted_networks = []
        for entry in trusted_list:
            try:
                if "/" in entry:
                    self.trusted_networks.append(ipaddress.ip_network(entry, strict=False))
                else:
                    self.trusted_networks.append(
                        ipaddress.ip_network(f"{entry}/32" if ":" not in entry else f"{entry}/128")
                    )
            except ValueError:
                logger.warning(f"[TrustedProxyIPExtractor] Invalid CIDR or IP in TRUSTED_PROXIES: {entry}")

    def is_trusted_proxy(self, ip_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
            return any(ip in net for net in self.trusted_networks)
        except ValueError:
            return False

    def extract_ip(self, request: Any) -> str:
        peer_ip = "127.0.0.1"
        if hasattr(request, "client") and request.client and request.client.host:
            peer_ip = request.client.host

        if not self.is_trusted_proxy(peer_ip):
            return peer_ip

        headers = getattr(request, "headers", None)
        if not headers:
            return peer_ip

        # 1. Cloudflare header
        cf_ip = headers.get("cf-connecting-ip")
        if cf_ip:
            cf_ip = cf_ip.strip()
            try:
                ipaddress.ip_address(cf_ip)
                return cf_ip
            except ValueError:
                pass

        # 2. X-Forwarded-For right-to-left traversal (RFC 7239)
        xfwd = headers.get("x-forwarded-for")
        if xfwd:
            parts = [p.strip() for p in xfwd.split(",") if p.strip()]
            for ip_cand in reversed(parts):
                try:
                    ipaddress.ip_address(ip_cand)
                    if not self.is_trusted_proxy(ip_cand):
                        return ip_cand
                except ValueError:
                    continue

        # 3. X-Real-IP fallback
        xreal = headers.get("x-real-ip")
        if xreal:
            xreal = xreal.strip()
            try:
                ipaddress.ip_address(xreal)
                return xreal
            except ValueError:
                pass

        return peer_ip


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
        trusted_proxies: Optional[Union[str, List[str]]] = None,
    ):
        self.requests_per_min = requests_num
        self.period = period if isinstance(period, timedelta) else timedelta(seconds=int(period))
        self.window_seconds = int(self.period.total_seconds())
        self.redis_timeout = redis_timeout

        # In-memory storage for test compatibility and local fallback
        self.requests = defaultdict(list)

        self.url = url or os.getenv("UPSTASH_REDIS_REST_URL")
        self.token = token or os.getenv("UPSTASH_REDIS_REST_TOKEN")

        self.ip_extractor = TrustedProxyIPExtractor(trusted_proxies)

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

    def _in_memory_check(
        self,
        key: str,
        limit: Optional[int] = None,
        window: Optional[int] = None,
    ) -> Tuple[bool, int, int]:
        """Local sliding-window check."""
        now = time.time()
        win = window if window is not None else self.window_seconds
        lim = limit if limit is not None else self.requests_per_min
        start_ts = now - win

        valid_requests = []
        for req in self.requests[key]:
            req_ts = req.timestamp() if isinstance(req, datetime) else float(req)
            if req_ts > start_ts:
                valid_requests.append(req_ts)
        self.requests[key] = valid_requests

        count = len(valid_requests)
        if count >= lim:
            oldest_ts = valid_requests[0] if valid_requests else now
            retry_after = max(1, int(oldest_ts + win - now))
            return True, 0, retry_after

        self.requests[key].append(now)
        remaining = lim - count - 1
        return False, remaining, 0

    async def _redis_check(
        self,
        redis_key: str,
        limit: Optional[int] = None,
        window: Optional[int] = None,
    ) -> Tuple[bool, int, int]:
        """Executes atomic Lua script with 150ms timeout."""
        nonce = uuid.uuid4().hex[:8]
        win = window if window is not None else self.window_seconds
        lim = limit if limit is not None else self.requests_per_min
        raw_res = await asyncio.wait_for(
            self.redis.eval(
                LUA_SLIDING_WINDOW_SCRIPT,
                keys=[redis_key],
                args=[str(win), str(lim), nonce],
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
        limit: Optional[Union[int, bool]] = None,
        window: Optional[int] = None,
        is_api_key: bool = True,
        fail_closed: bool = False,
        key_prefix: Optional[str] = None,
    ) -> Tuple[bool, int, int]:
        """
        Primary asynchronous rate check method.
        Supports dynamic per-key limits and keying by ratelimit:key:{api_key_id}.
        """
        if isinstance(limit, bool):
            is_api_key = limit
            limit = None

        if not identifier:
            identifier = "anonymous"

        if key_prefix:
            redis_key = f"{key_prefix}:{identifier}"
            memory_key = f"{key_prefix}:{identifier}"
        elif is_api_key:
            # If already a UUID or key id, use directly
            if len(identifier) == 36 and "-" in identifier:
                redis_key = f"ratelimit:key:{identifier}"
            else:
                hashed_id = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]
                redis_key = f"ratelimit:key:{hashed_id}"
            memory_key = identifier
        else:
            redis_key = f"ratelimit:ip:{identifier}"
            memory_key = identifier

        if not self.redis:
            if fail_closed and (self.url or os.getenv("ENFORCE_REDIS_FAIL_CLOSED", "false").lower() == "true"):
                raise RateLimiterUnavailableError("Redis rate limiter unavailable; fail-closed policy enforced.")
            return self._in_memory_check(memory_key, limit=limit, window=window)

        try:
            return await self._redis_check(redis_key, limit=limit, window=window)
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                f"[DistributedRateLimiter] Redis check failed ({type(exc).__name__}: {exc}). "
                f"Policy: {'fail-closed' if fail_closed else 'in-memory fallback'}."
            )
            if fail_closed:
                raise RateLimiterUnavailableError(
                    "Redis rate limiter timed out or failed; fail-closed policy enforced."
                ) from exc
            return self._in_memory_check(memory_key, limit=limit, window=window)

    async def check_auth_failure_rate(
        self,
        client_ip: str,
        limit: int = DEFAULT_AUTH_FAIL_LIMIT,
        window: int = DEFAULT_AUTH_FAIL_WINDOW_SEC,
    ) -> Tuple[bool, int, int]:
        """Checks if client_ip has exceeded failed authentication threshold without recording."""
        redis_key = f"ratelimit:auth_fail:{client_ip}"
        if not self.redis:
            now = time.time()
            start_ts = now - window
            valid = [t for t in self.requests.get(redis_key, []) if t > start_ts]
            if len(valid) >= limit:
                retry_after = max(1, int(valid[0] + window - now))
                return True, 0, retry_after
            return False, limit - len(valid), 0

        try:
            raw_res = await asyncio.wait_for(
                self.redis.eval(
                    LUA_PEEK_WINDOW_SCRIPT,
                    keys=[redis_key],
                    args=[str(window), str(limit)],
                ),
                timeout=self.redis_timeout,
            )
            return bool(int(raw_res[0])), int(raw_res[1]), int(raw_res[2])
        except Exception as e:
            logger.warning(f"[DistributedRateLimiter] Pre-auth failure check fallback: {e}")
            return False, limit, 0

    async def record_auth_failure(
        self,
        client_ip: str,
        limit: int = DEFAULT_AUTH_FAIL_LIMIT,
        window: int = DEFAULT_AUTH_FAIL_WINDOW_SEC,
    ) -> Tuple[bool, int, int]:
        """Records an authentication failure for client_ip."""
        redis_key = f"ratelimit:auth_fail:{client_ip}"
        if not self.redis:
            return self._in_memory_check(redis_key, limit=limit, window=window)

        try:
            return await self._redis_check(redis_key, limit=limit, window=window)
        except Exception as e:
            logger.warning(f"[DistributedRateLimiter] Record auth failure fallback: {e}")
            return self._in_memory_check(redis_key, limit=limit, window=window)

    def is_rate_limited(
        self,
        api_key: str,
        limit: Optional[int] = None,
    ) -> DualModeRateLimitResult:
        """
        Backward-compatible dual-mode method for existing tests and routes.
        Uses lazy evaluation:
        - When awaited (`await rate_limiter.is_rate_limited(key)`), ONLY Redis runs.
          Zero in-memory double-counting.
        - When unpacked synchronously (`is_lim, rem = rate_limiter.is_rate_limited(key)`),
          the in-memory check is evaluated on demand.
        """
        if self.redis:
            async def _async_runner():
                return await self.check_rate_limit(api_key, limit=limit, is_api_key=True)

            def _sync_runner():
                return self._in_memory_check(api_key, limit=limit)

            return DualModeRateLimitResult(sync_evaluator=_sync_runner, async_coro=_async_runner)

        def _sync_runner():
            return self._in_memory_check(api_key, limit=limit)

        return DualModeRateLimitResult(sync_evaluator=_sync_runner)

    def reset(self):
        """Resets in-memory request history."""
        self.requests.clear()

    @staticmethod
    def extract_client_ip(request: Any, trusted_proxies: Optional[Union[str, List[str]]] = None) -> str:
        """
        Extracts client IP using trusted-proxy aware extractor.
        Compatible with both class-level (DistributedRateLimiter.extract_client_ip(req))
        and instance-level (rate_limiter.extract_client_ip(req)) calls.
        """
        if trusted_proxies is not None:
            return TrustedProxyIPExtractor(trusted_proxies).extract_ip(request)
        if "rate_limiter" in globals() and hasattr(rate_limiter, "ip_extractor"):
            return rate_limiter.ip_extractor.extract_ip(request)
        return TrustedProxyIPExtractor().extract_ip(request)


# Default application-wide singleton
rate_limiter = DistributedRateLimiter(requests_num=DEFAULT_LIMIT, period=DEFAULT_WINDOW_SEC)
RateLimiter = DistributedRateLimiter
