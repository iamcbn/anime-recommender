# backend/rag_pipeline/helper/budget_guard.py
"""
Daily Token Ceiling and Budget Guard (Sprint 11).

Features:
- Tracks per-layer daily LLM token consumption in Upstash Redis:
  Key format: usage:{layer}:{YYYY-MM-DD}
- 48-hour TTL on Redis keys for automatic expiration.
- In-memory sliding fallback store if Redis is unavailable or unconfigured.
- 150ms timeout protection on all Redis operations with transparent fallback.
- Soft Limit (80% of daily ceiling): triggers warning/telemetry indicator.
- Hard Limit (100% of daily ceiling): signals graceful zero-token degradation.
- Strict Pydantic models for status and metrics reporting.
"""

import os
import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from collections import defaultdict
from pydantic import BaseModel, Field

logger = logging.getLogger("anime_recommender.budget_guard")

DEFAULT_DAILY_TOKEN_LIMITS: Dict[str, int] = {
    "nli": int(os.getenv("DAILY_TOKEN_LIMIT_NLI", "100000")),
    "retrieval": int(os.getenv("DAILY_TOKEN_LIMIT_RETRIEVAL", "200000")),
    "presentation": int(os.getenv("DAILY_TOKEN_LIMIT_PRESENTATION", "300000")),
}

DEFAULT_USAGE_KEY_TTL_SEC: int = 172800  # 48 hours
DEFAULT_REDIS_TIMEOUT_SEC: float = 0.150  # 150 milliseconds
DEFAULT_SOFT_LIMIT_RATIO: float = 0.80

VALID_LAYERS = ("nli", "retrieval", "presentation")


def get_budget_key(layer: str, date_str: Optional[str] = None) -> str:
    """
    Constructs the canonical Redis usage key: `usage:{layer}:{YYYY-MM-DD}`.
    Validates layer and defaults to current UTC date.
    """
    norm_layer = (layer or "").strip().lower()
    if norm_layer not in VALID_LAYERS:
        raise ValueError(f"Invalid layer '{layer}'. Must be one of: {VALID_LAYERS}")

    d = (date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
    return f"usage:{norm_layer}:{d}"


class InMemoryBudgetStore:
    """Thread-safe in-memory store for fallback and local test isolation."""

    def __init__(self):
        self._usage: Dict[str, int] = defaultdict(int)

    def get(self, key: str) -> int:
        return self._usage.get(key, 0)

    def incr(self, key: str, amount: int) -> int:
        self._usage[key] += amount
        return self._usage[key]

    def set(self, key: str, amount: int) -> None:
        self._usage[key] = max(0, amount)

    def reset(self) -> None:
        self._usage.clear()


class LayerBudgetStatus(BaseModel):
    """Live status of daily token ceilings for a specific layer."""
    layer: str = Field(..., description="Layer name: nli, retrieval, or presentation")
    current_usage: int = Field(..., ge=0, description="Tokens consumed today")
    limit: int = Field(..., ge=0, description="Configured daily token ceiling")
    remaining: int = Field(..., ge=0, description="Remaining tokens before hard limit")
    soft_limit_hit: bool = Field(..., description="True if usage >= 80% of limit")
    hard_limit_hit: bool = Field(..., description="True if usage >= 100% of limit")
    usage_ratio: float = Field(..., ge=0.0, description="Current consumption ratio (usage / limit)")


class BudgetGuard:
    """
    Guards daily token budgets across NLI, Retrieval, and Presentation layers.
    Enforces soft warning at 80% and hard ceiling degradation at 100%.
    """

    def __init__(
        self,
        limits: Optional[Dict[str, int]] = None,
        redis_client: Optional[Any] = None,
        timeout: float = DEFAULT_REDIS_TIMEOUT_SEC,
        ttl_seconds: int = DEFAULT_USAGE_KEY_TTL_SEC,
    ):
        self.limits: Dict[str, int] = dict(limits or DEFAULT_DAILY_TOKEN_LIMITS)
        self.redis = redis_client
        self.timeout: float = timeout
        self.ttl_seconds: int = ttl_seconds
        self.fallback_store = InMemoryBudgetStore()

        if self.redis is None:
            redis_url = os.getenv("UPSTASH_REDIS_REST_URL")
            redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
            if redis_url and redis_token:
                try:
                    from upstash_redis.asyncio import Redis
                    self.redis = Redis(url=redis_url, token=redis_token)
                except Exception as exc:
                    logger.debug(f"[BudgetGuard] Redis initialization skipped: {exc}")
                    self.redis = None

    def get_limit(self, layer: str) -> int:
        """Dynamically reads environment variable or falls back to configured limit."""
        norm_layer = layer.strip().lower()
        env_limit = os.getenv(f"DAILY_TOKEN_LIMIT_{norm_layer.upper()}")
        if env_limit:
            try:
                return int(env_limit)
            except ValueError:
                pass
        return self.limits.get(norm_layer, DEFAULT_DAILY_TOKEN_LIMITS.get(norm_layer, 100000))

    def get_soft_limit_ratio(self) -> float:
        """Reads configurable soft limit ratio (default: 0.80)."""
        env_val = os.getenv("BUDGET_SOFT_LIMIT_RATIO")
        if env_val:
            try:
                return float(env_val)
            except ValueError:
                pass
        return DEFAULT_SOFT_LIMIT_RATIO

    async def get_usage(self, layer: str, target_date: Optional[str] = None) -> int:
        """Fetches token usage for the given layer and date."""
        key = get_budget_key(layer, target_date)

        if self.redis is not None:
            try:
                val = await asyncio.wait_for(self.redis.get(key), timeout=self.timeout)
                if val is not None:
                    return max(0, int(val))
            except asyncio.TimeoutError:
                logger.warning(
                    f"[BudgetGuard] Redis GET timed out after {self.timeout}s for {key}. "
                    "Activating fallback store."
                )
            except Exception as exc:
                exc_name = exc.__class__.__name__
                logger.warning(
                    f"[BudgetGuard] Redis GET failed with {exc_name}: {exc}. "
                    "Activating fallback store."
                )

        return self.fallback_store.get(key)

    async def record_usage(
        self,
        layer: str,
        tokens: int,
        target_date: Optional[str] = None,
    ) -> int:
        """
        Increments token usage for a layer and sets 48h TTL on Redis key.
        Logs warning if 80% soft limit or 100% hard limit is reached.
        """
        if tokens <= 0:
            return await self.get_usage(layer, target_date)

        key = get_budget_key(layer, target_date)
        prev_usage = await self.get_usage(layer, target_date)
        limit = self.get_limit(layer)
        soft_threshold = int(limit * self.get_soft_limit_ratio())

        # Update fallback store
        new_val = self.fallback_store.incr(key, tokens)

        if self.redis is not None:
            try:
                pipe_res = await asyncio.wait_for(
                    self.redis.incrby(key, tokens),
                    timeout=self.timeout,
                )
                await asyncio.wait_for(
                    self.redis.expire(key, self.ttl_seconds),
                    timeout=self.timeout,
                )
                if isinstance(pipe_res, int):
                    new_val = pipe_res
            except asyncio.TimeoutError:
                logger.warning(
                    f"[BudgetGuard] Redis operation timed out after {self.timeout}s for {key}. "
                    "Activating fallback store."
                )
            except Exception as exc:
                exc_name = exc.__class__.__name__
                logger.warning(
                    f"[BudgetGuard] Redis operation failed with {exc_name}: {exc}. "
                    "Activating fallback store."
                )

        # Soft and Hard ceiling triggers & warnings
        if prev_usage < soft_threshold <= new_val:
            logger.warning(
                f"[BudgetGuard] SOFT LIMIT REACHED: {layer.upper()} token usage {new_val} >= {soft_threshold} "
                f"(80% of daily limit {limit})."
            )
        if prev_usage < limit <= new_val:
            logger.warning(
                f"[BudgetGuard] HARD LIMIT REACHED: {layer.upper()} token usage {new_val} >= {limit}. "
                "Activating graceful zero-token degradation."
            )

        return new_val

    def record_usage_sync(
        self,
        layer: str,
        tokens: int,
        target_date: Optional[str] = None,
    ) -> int:
        """Synchronous wrapper for background telemetry logging."""
        if tokens <= 0:
            key = get_budget_key(layer, target_date)
            return self.fallback_store.get(key)

        key = get_budget_key(layer, target_date)
        new_val = self.fallback_store.incr(key, tokens)

        if self.redis is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.redis.incrby(key, tokens))
                loop.create_task(self.redis.expire(key, self.ttl_seconds))
            except RuntimeError:
                pass

        return new_val

    def set_usage(self, layer: str, tokens: int, target_date: Optional[str] = None) -> None:
        """Explicitly sets usage in fallback store (useful for test fixtures)."""
        key = get_budget_key(layer, target_date)
        self.fallback_store.set(key, tokens)

    def reset(self) -> None:
        """Resets all in-memory usage (for test isolation)."""
        self.fallback_store.reset()

    async def check_budget_status(
        self,
        layer: str,
        date_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Returns full detailed budget status dictionary for Task 11.1 and 11.2.
        """
        norm_layer = layer.strip().lower()
        d = (date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
        usage = await self.get_usage(norm_layer, d)
        limit = self.get_limit(norm_layer)
        soft_threshold = int(limit * self.get_soft_limit_ratio())
        remaining = max(0, limit - usage)
        percentage = round((usage / limit) * 100, 2) if limit > 0 else 0.0
        is_exceeded = (usage >= limit) and limit > 0
        is_soft_exceeded = (usage >= soft_threshold) and limit > 0
        usage_ratio = round(usage / limit, 4) if limit > 0 else 0.0

        return {
            "layer": norm_layer,
            "date": d,
            "current_usage": usage,
            "daily_limit": limit,
            "limit": limit,
            "soft_limit": soft_threshold,
            "remaining": remaining,
            "percentage": percentage,
            "is_exceeded": is_exceeded,
            "is_soft_limit_exceeded": is_soft_exceeded,
            "soft_limit_hit": is_soft_exceeded,
            "hard_limit_hit": is_exceeded,
            "usage_ratio": usage_ratio,
        }

    async def is_budget_exceeded(self, layer: str, date_str: Optional[str] = None) -> bool:
        """Returns True if daily token ceiling has been exhausted."""
        status = await self.check_budget_status(layer, date_str)
        return status["is_exceeded"]

    def is_budget_exceeded_sync(self, layer: str, date_str: Optional[str] = None) -> bool:
        """
        Synchronous check if daily token ceiling has been exhausted.
        Single source of truth for non-async callers (such as sync query generation and NLI fallback).
        Reads from in-memory fallback store to ensure zero latency and avoid blocking threads.
        """
        norm_layer = (layer or "").strip().lower()
        key = get_budget_key(norm_layer, date_str)
        usage = self.fallback_store.get(key)
        limit = self.get_limit(norm_layer)
        return (usage >= limit) and limit > 0


    async def is_soft_limit_exceeded(self, layer: str, date_str: Optional[str] = None) -> bool:
        status = await self.check_budget_status(layer, date_str)
        return status["is_soft_limit_exceeded"]

    async def get_layer_budget(
        self,
        layer: str,
        target_date: Optional[str] = None,
    ) -> LayerBudgetStatus:
        """Returns Pydantic LayerBudgetStatus model for Task 11.2 API responses."""
        status = await self.check_budget_status(layer, target_date)
        return LayerBudgetStatus(
            layer=status["layer"],
            current_usage=status["current_usage"],
            limit=status["limit"],
            remaining=status["remaining"],
            soft_limit_hit=status["soft_limit_hit"],
            hard_limit_hit=status["hard_limit_hit"],
            usage_ratio=status["usage_ratio"],
        )

    async def get_all_budgets(
        self,
        target_date: Optional[str] = None,
    ) -> Dict[str, LayerBudgetStatus]:
        """Returns budget status map across all three pipeline layers."""
        return {
            layer: await self.get_layer_budget(layer, target_date)
            for layer in VALID_LAYERS
        }


# Global singleton instance
budget_guard = BudgetGuard()
