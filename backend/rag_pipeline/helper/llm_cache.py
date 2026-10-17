# backend/rag_pipeline/helper/llm_cache.py
"""
Hybrid LLM Response Cache (Sprint 4).

Execution modes:
1. Production Cloud (Modal): Upstash Redis REST Key-Value store with 7-day TTL
   when credentials exist and DISABLE_LLM_CACHE=false.
2. Local Development / Eval: SQLite database (test/data/llm_cache.db).
3. Disabled: DISABLE_LLM_CACHE=true (All methods become safe no-ops).
"""

import os
import json
import hashlib
import sqlite3
import logging
import time
import asyncio
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger("anime_recommender.llm_cache")

# Default database path for local / evaluation cache
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "test" / "data" / "llm_cache.db"
DEFAULT_CACHE_TTL_SEC = 604800  # 7 days (604,800 seconds)


class LLMCache:
    """
    Resilient multi-backend cache for HyDE query expansions and LLM syntheses.
    Supports both synchronous and asynchronous invocations.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._disabled = os.getenv("DISABLE_LLM_CACHE", "false").lower() == "true"
        self._redis_url = os.getenv("UPSTASH_REDIS_REST_URL")
        self._redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")

        self.backend = "disabled" if self._disabled else "sqlite"
        self._sync_redis = None
        self._async_redis = None
        self.sqlite_conn = None

        if self._disabled:
            logger.info("[LLMCache] LLM cache disabled (DISABLE_LLM_CACHE=true)")
            return

        # Attempt Upstash Redis client instantiation if credentials exist
        if self._redis_url and self._redis_token:
            try:
                from upstash_redis import Redis as SyncRedis
                from upstash_redis.asyncio import Redis as AsyncRedis

                self._sync_redis = SyncRedis(url=self._redis_url, token=self._redis_token)
                self._async_redis = AsyncRedis(url=self._redis_url, token=self._redis_token)
                self.backend = "redis"
                logger.info("[LLMCache] Cloud Upstash Redis cache backend initialized.")
                return
            except Exception as e:
                logger.warning(f"[LLMCache] Redis initialization failed ({e}); falling back to SQLite.")

        # Fallback to local SQLite backend
        db_path = Path(db_path or os.getenv("LLM_CACHE_PATH") or _DEFAULT_DB_PATH)
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.sqlite_conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self.sqlite_conn.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)"
            )
            self.sqlite_conn.commit()
            self.backend = "sqlite"
            logger.info(f"[LLMCache] SQLite cache backend initialized at {db_path}")
        except Exception:
            logger.warning("[LLMCache] SQLite cache unavailable; running with caching disabled.", exc_info=True)
            self.backend = "disabled"

    @staticmethod
    def _normalize_key(key: str) -> str:
        """Sanitizes query strings for Redis key safety."""
        hashed = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        clean_prefix = "".join(c if c.isalnum() else "_" for c in key[:24]).strip("_")
        return f"llm:cache:{clean_prefix}_{hashed}"

    # -------------------------------------------------------------------------
    # SYNCHRONOUS API (Compatible with legacy QueryGenerator.generate)
    # -------------------------------------------------------------------------
    def get(self, key: str) -> Optional[Any]:
        if self.backend == "disabled":
            return None

        norm_key = self._normalize_key(key)
        if self.backend == "redis" and self._sync_redis is not None:
            try:
                val = self._sync_redis.get(norm_key)
                if val is None:
                    return None
                return json.loads(val) if isinstance(val, str) else val
            except Exception as e:
                logger.warning(f"[LLMCache] Redis read failed ({e}); treating as cache miss.")
                return None

        if self.backend == "sqlite" and self.sqlite_conn is not None:
            try:
                cur = self.sqlite_conn.execute("SELECT value FROM cache WHERE key = ?", (norm_key,))
                row = cur.fetchone()
                return json.loads(row[0]) if row else None
            except Exception as e:
                logger.warning(f"[LLMCache] SQLite read failed ({e}); treating as cache miss.")
                return None

        return None

    def set(self, key: str, value: Any, ttl: int = DEFAULT_CACHE_TTL_SEC) -> None:
        if self.backend == "disabled":
            return

        norm_key = self._normalize_key(key)
        serialized = json.dumps(value)

        if self.backend == "redis" and self._sync_redis is not None:
            try:
                self._sync_redis.set(norm_key, serialized, ex=ttl)
                return
            except Exception as e:
                logger.warning(f"[LLMCache] Redis write failed ({e}); skipping cache set.")
                return

        if self.backend == "sqlite" and self.sqlite_conn is not None:
            try:
                self.sqlite_conn.execute(
                    "INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)",
                    (norm_key, serialized),
                )
                self.sqlite_conn.commit()
            except Exception as e:
                logger.warning(f"[LLMCache] SQLite write failed ({e}); skipping cache set.")

    # -------------------------------------------------------------------------
    # ASYNCHRONOUS API (For Non-Blocking async pipelines)
    # -------------------------------------------------------------------------
    async def aget(self, key: str) -> Optional[Any]:
        if self.backend == "disabled":
            return None

        norm_key = self._normalize_key(key)
        if self.backend == "redis" and self._async_redis is not None:
            try:
                val = await asyncio.wait_for(self._async_redis.get(norm_key), timeout=0.150)
                if val is None:
                    return None
                return json.loads(val) if isinstance(val, str) else val
            except Exception as e:
                logger.warning(f"[LLMCache] Async Redis read failed ({e}); treating as cache miss.")
                return None

        # Fallback to sync get in thread if on sqlite
        return self.get(key)

    async def aset(self, key: str, value: Any, ttl: int = DEFAULT_CACHE_TTL_SEC) -> None:
        if self.backend == "disabled":
            return

        norm_key = self._normalize_key(key)
        serialized = json.dumps(value)

        if self.backend == "redis" and self._async_redis is not None:
            try:
                await asyncio.wait_for(
                    self._async_redis.set(norm_key, serialized, ex=ttl),
                    timeout=0.150,
                )
                return
            except Exception as e:
                logger.warning(f"[LLMCache] Async Redis write failed ({e}); skipping cache set.")
                return

        self.set(key, value, ttl=ttl)


# Global singleton
llm_cache = LLMCache()
