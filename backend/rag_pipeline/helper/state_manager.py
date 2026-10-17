# backend/rag_pipeline/helper/state_manager.py
"""
Distributed State Manager for Multi-Turn Sessions and User Exclusion Filtering (Sprint 4).

Features:
- Primary Tier: Upstash Redis Serverless REST API (asyncio).
- Secondary Tier: Thread-safe, TTL-aware local in-memory fallback store for local dev,
  tests, or cloud network latency degradation.
- Strict 150ms circuit breaker: Never allows Redis network latency to block user requests.
- O(1) Seen IDs tracking via Redis Sets.
- Rolling 5-turn dialogue history with 30-minute rolling TTL.
"""

import os
import json
import time
import logging
import asyncio
from typing import Optional, List, Dict, Any, Set, Union
from collections import defaultdict

logger = logging.getLogger("anime_recommender.state_manager")

DEFAULT_REDIS_TIMEOUT_SEC = 0.150  # 150 milliseconds
DEFAULT_SESSION_TTL_SEC = 1800     # 30 minutes (1800 seconds)
MAX_SESSION_TURNS = 5              # Rolling 5 conversational turns (10 messages max)


class InMemoryStateStore:
    """Thread-safe, TTL-aware local in-memory fallback store."""

    def __init__(self):
        self._sessions: Dict[str, tuple[float, int, List[Dict[str, Any]]]] = {}
        self._seen_ids: Dict[str, Set[int]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def get_session(self, session_id: str) -> List[Dict[str, Any]]:
        async with self._lock:
            if session_id not in self._sessions:
                return []
            updated_at, ttl, history = self._sessions[session_id]
            if time.time() - updated_at > ttl:
                del self._sessions[session_id]
                return []
            return [dict(t) for t in history]

    async def append_turns(
        self,
        session_id: str,
        turns: List[Dict[str, Any]],
        ttl: int = DEFAULT_SESSION_TTL_SEC,
    ):
        async with self._lock:
            history = []
            if session_id in self._sessions:
                updated_at, old_ttl, existing = self._sessions[session_id]
                if time.time() - updated_at <= old_ttl:
                    history = list(existing)
            history.extend(turns)
            history = history[-MAX_SESSION_TURNS:]
            self._sessions[session_id] = (time.time(), ttl, history)

    async def get_seen_ids(self, user_id: str) -> Set[int]:
        async with self._lock:
            return set(self._seen_ids[user_id])

    async def add_seen_ids(self, user_id: str, anime_ids: List[int]):
        async with self._lock:
            self._seen_ids[user_id].update(anime_ids)

    async def clear_session(self, session_id: str):
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def clear_seen_ids(self, user_id: str):
        async with self._lock:
            self._seen_ids.pop(user_id, None)

    async def clear(self):
        async with self._lock:
            self._sessions.clear()
            self._seen_ids.clear()


class StateManager:
    """
    Production-grade distributed state manager with cache-aside resilience.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_token: Optional[str] = None,
        timeout: float = DEFAULT_REDIS_TIMEOUT_SEC,
        enable_fallback: bool = True,
    ):
        self.url = redis_url or os.getenv("UPSTASH_REDIS_REST_URL")
        self.token = redis_token or os.getenv("UPSTASH_REDIS_REST_TOKEN")
        self.timeout = timeout
        self.enable_fallback = enable_fallback
        self.memory_store = InMemoryStateStore()

        self.redis = None
        if self.url and self.token:
            try:
                from upstash_redis.asyncio import Redis
                self.redis = Redis(url=self.url, token=self.token)
                logger.info("[StateManager] Upstash Redis async client initialized successfully.")
            except Exception as e:
                logger.warning(
                    f"[StateManager] Failed to initialize Upstash Redis ({e}). Operating in memory fallback mode."
                )
                self.redis = None
        else:
            logger.info("[StateManager] Redis credentials unset. Operating in local in-memory fallback mode.")

    @property
    def is_redis_available(self) -> bool:
        return self.redis is not None

    # -------------------------------------------------------------------------
    # RESILIENCE EXECUTION WRAPPER
    # -------------------------------------------------------------------------
    async def _safe_execute(self, redis_op, fallback_op, op_name: str):
        """
        Executes a Redis operation with a strict 150ms timeout.
        If timeout or network exception occurs, cleanly falls back without raising.
        redis_op and fallback_op can be either a coroutine or an async callable.
        """
        if self.redis is None:
            return await fallback_op() if callable(fallback_op) else await fallback_op

        t0 = time.perf_counter()
        try:
            coro = redis_op() if callable(redis_op) else redis_op
            result = await asyncio.wait_for(coro, timeout=self.timeout)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.debug(f"[StateManager] {op_name} completed in {elapsed_ms:.2f}ms")
            return result
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.warning(
                f"[StateManager] {op_name} timed out after {elapsed_ms:.2f}ms "
                f"(threshold: {self.timeout * 1000:.0f}ms). Activating fallback store."
            )
            return await fallback_op() if callable(fallback_op) else await fallback_op
        except Exception as e:
            logger.warning(
                f"[StateManager] {op_name} failed with {type(e).__name__}: {e}. "
                f"Activating fallback store."
            )
            return await fallback_op() if callable(fallback_op) else await fallback_op

    # -------------------------------------------------------------------------
    # MULTI-TURN DIALOGUE CONTEXT (Task 4.1)
    # -------------------------------------------------------------------------
    async def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves the last 5 turns of conversation for the given session.
        Returns an empty list on cache miss, timeout, or error.
        """
        if not session_id:
            return []

        async def _redis_op():
            key = f"session:{session_id}"
            data = await self.redis.get(key)
            if not data:
                return []
            if isinstance(data, str):
                try:
                    return json.loads(data)
                except Exception:
                    return []
            elif isinstance(data, list):
                return data
            return []

        async def _fallback_op():
            return await self.memory_store.get_session(session_id)

        return await self._safe_execute(_redis_op, _fallback_op, f"get_session_history({session_id})")

    async def append_session_turn(
        self,
        session_id: str,
        turn: Union[Dict[str, Any], List[Dict[str, Any]]],
        ttl: int = DEFAULT_SESSION_TTL_SEC,
    ) -> None:
        """
        Appends one or more dialogue turns, retains rolling 5 turns, and resets the 30-minute TTL.
        """
        if not session_id or not turn:
            return

        turn_list = [turn] if isinstance(turn, dict) else list(turn)

        async def _redis_op():
            # Read existing history
            key = f"session:{session_id}"
            raw = await self.redis.get(key)
            existing = []
            if raw:
                if isinstance(raw, str):
                    try:
                        existing = json.loads(raw)
                    except Exception:
                        existing = []
                elif isinstance(raw, list):
                    existing = raw

            existing.extend(turn_list)
            history = existing[-MAX_SESSION_TURNS:]
            await self.redis.set(key, json.dumps(history), ex=ttl)

        async def _fallback_op():
            await self.memory_store.append_turns(session_id, turn_list, ttl=ttl)

        await self._safe_execute(_redis_op, _fallback_op, f"append_session_turn({session_id})")

    # -------------------------------------------------------------------------
    # SEEN / WATCHED ANIME EXCLUSION FILTERING (Task 4.2)
    # -------------------------------------------------------------------------
    async def get_excluded_ids(self, user_id: str) -> Set[int]:
        """
        Fetches the complete set of anime IDs seen or recommended to the user.
        """
        if not user_id:
            return set()

        async def _redis_op():
            key = f"user:{user_id}:seen_ids"
            members = await self.redis.smembers(key)
            if not members:
                return set()
            clean = set()
            for x in members:
                try:
                    clean.add(int(x))
                except (ValueError, TypeError):
                    pass
            return clean

        async def _fallback_op():
            return await self.memory_store.get_seen_ids(user_id)

        result = await self._safe_execute(_redis_op, _fallback_op, f"get_excluded_ids({user_id})")
        return set(result or [])

    async def record_seen_ids(self, user_id: str, anime_ids: List[int]) -> None:
        """
        Adds newly recommended or user-marked anime IDs to the exclusion set.
        """
        if not user_id or not anime_ids:
            return

        clean_ids = []
        for aid in anime_ids:
            try:
                clean_ids.append(int(aid))
            except (ValueError, TypeError):
                pass

        if not clean_ids:
            return

        async def _redis_op():
            key = f"user:{user_id}:seen_ids"
            await self.redis.sadd(key, *clean_ids)

        async def _fallback_op():
            await self.memory_store.add_seen_ids(user_id, clean_ids)

        await self._safe_execute(_redis_op, _fallback_op, f"record_seen_ids({user_id})")

    async def clear_session(self, session_id: str):
        """Clears a session from both Redis and memory store."""
        if not session_id:
            return

        async def _redis_op():
            await self.redis.delete(f"session:{session_id}")

        async def _fallback_op():
            await self.memory_store.clear_session(session_id)

        await self._safe_execute(_redis_op, _fallback_op, f"clear_session({session_id})")

    async def clear_user_seen(self, user_id: str):
        """Clears seen IDs for a user from both Redis and memory store."""
        if not user_id:
            return

        async def _redis_op():
            await self.redis.delete(f"user:{user_id}:seen_ids")

        async def _fallback_op():
            await self.memory_store.clear_seen_ids(user_id)

        await self._safe_execute(_redis_op, _fallback_op, f"clear_user_seen({user_id})")

    # -------------------------------------------------------------------------
    # CLEANUP
    # -------------------------------------------------------------------------
    async def aclose(self):
        """Cleanly releases underlying Redis HTTP client resources."""
        if self.redis is not None and hasattr(self.redis, "close"):
            try:
                await self.redis.close()
            except Exception:
                pass

    def close(self):
        """Synchronous cleanup alias."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.aclose())
            else:
                loop.run_until_complete(self.aclose())
        except Exception:
            pass


# Module singleton for application-wide injection
state_manager = StateManager()
