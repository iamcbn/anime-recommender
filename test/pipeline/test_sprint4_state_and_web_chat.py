"""
test/pipeline/test_sprint4_state_and_web_chat.py

Sprint 4 Consolidated Test Suite:
- Task 4.1: Upstash Redis State Integration (Rolling 5 Turns, 1800s TTL, Cache-aside fallback).
- Task 4.2: Seen/Watched Title Exclusion Filtering (0% Title Recurrence via O(1) set subtraction).
- Task 4.3: Distributed Sliding-Window Rate Limiting (Sorted Sets Lua script, RFC 6585 compliance).
- Task 4.4: Conversational Web MVP Integration & Multi-Turn Session Testing (POST /chat SSE stream).
"""

import sys
import os
import re
import json
import time
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from httpx import ASGITransport

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.main import app, rate_limiter
from backend.rag_pipeline.orchestrator import orchestrator, PipelineOrchestrator
from backend.rag_pipeline.helper.state_manager import StateManager, InMemoryStateStore
from backend.rag_pipeline.helper.rate_limiter import (
    DistributedRateLimiter,
    DualModeRateLimitResult,
)
from backend.rag_pipeline.helper.ranking import Ranker
from backend.rag_pipeline.helper.llm_cache import LLMCache


@pytest.fixture(autouse=True)
def configure_test_environment(monkeypatch):
    """Sets test API key and resets rate limiter state."""
    test_key = "test-secret-sprint4-key"
    monkeypatch.setenv("MY_API_KEY", test_key)
    rate_limiter.reset()
    return test_key



# =============================================================================
# PART 1: DISTRIBUTED SLIDING-WINDOW RATE LIMITING TESTS (TASK 4.3 / AC 4.3)
# =============================================================================

class MockRedisZSetServer:
    """
    In-memory simulation of Redis Sorted Set and Lua sliding window script
    shared across multiple independent container instances.
    """

    def __init__(self):
        self.zsets = {}
        self.lock = asyncio.Lock()

    async def eval(self, script, keys, args):
        key = keys[0]
        window = float(args[0])
        limit = int(args[1])
        nonce = args[2]

        async with self.lock:
            now = time.time()
            if key not in self.zsets:
                self.zsets[key] = []

            # 1. Purge expired entries
            clear_before = now - window
            self.zsets[key] = [
                (score, member) for score, member in self.zsets[key]
                if score > clear_before
            ]

            current_count = len(self.zsets[key])

            if current_count < limit:
                # Allowed: add entry
                member = f"{now}:{nonce}"
                self.zsets[key].append((now, member))
                self.zsets[key].sort(key=lambda x: x[0])
                remaining = limit - current_count - 1
                return [0, remaining, 0]
            else:
                # Over quota: compute retry_after from oldest entry
                oldest_score = self.zsets[key][0][0] if self.zsets[key] else now
                retry_after = max(1, int(oldest_score + window - now))
                return [1, 0, retry_after]


class TestDistributedSlidingWindowRateLimiting:
    """Tests AC 4.3 and distributed rate limiter invariants."""

    @pytest.mark.asyncio
    async def test_ac4_3_multi_container_distributed_rate_limiting(self):
        """
        AC 4.3: Generating 21 requests in 60 seconds across 3 independent
        container instances triggers an HTTP 429 response on the 21st request.
        """
        shared_redis_mock = MockRedisZSetServer()
        shared_key = "test-shared-client-key"

        container_a = DistributedRateLimiter(requests_num=20, period=60, redis_client=shared_redis_mock)
        container_b = DistributedRateLimiter(requests_num=20, period=60, redis_client=shared_redis_mock)
        container_c = DistributedRateLimiter(requests_num=20, period=60, redis_client=shared_redis_mock)

        containers = [container_a, container_b, container_c]

        for i in range(20):
            container = containers[i % 3]
            is_limited, remaining, retry_after = await container.check_rate_limit(shared_key, is_api_key=True)
            assert not is_limited, f"Request {i+1} was unexpectedly rate-limited"
            assert remaining == 20 - i - 1
            assert retry_after == 0

        is_limited_21, remaining_21, retry_after_21 = await container_a.check_rate_limit(shared_key, is_api_key=True)
        assert is_limited_21 is True, "AC 4.3 VIOLATION: 21st request across containers must trigger rate limiting"
        assert remaining_21 == 0
        assert retry_after_21 > 0

    @pytest.mark.asyncio
    async def test_ac4_3_http_429_endpoint_response_and_headers(self, monkeypatch):
        test_key = "test-http-api-key-429"
        monkeypatch.setenv("MY_API_KEY", test_key)

        shared_redis_mock = MockRedisZSetServer()
        limiter = DistributedRateLimiter(requests_num=20, period=60, redis_client=shared_redis_mock)

        async def fast_mock_pipeline(*args, **kwargs):
            return [], {}

        with patch("backend.main.rate_limiter", limiter), \
             patch("backend.main.async_rag_pipeline", fast_mock_pipeline):
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                for _ in range(20):
                    res = await client.post(
                        "/recommend",
                        headers={"access_token": test_key},
                        json={"query": "cyberpunk anime"},
                    )
                    assert res.status_code in (200, 400), f"Unexpected status {res.status_code}"

                res_21 = await client.post(
                    "/recommend",
                    headers={"access_token": test_key},
                    json={"query": "cyberpunk anime"},
                )
                assert res_21.status_code == 429
                data = res_21.json()
                assert "Rate limit exceeded" in data["detail"]
                assert "Retry-After" in res_21.headers
                assert "X-RateLimit-Limit" in res_21.headers
                assert res_21.headers["X-RateLimit-Limit"] == "20"
                assert res_21.headers["X-RateLimit-Remaining"] == "0"


class TestRateLimiterResilienceAndFallback:
    """Verifies that rate limiting gracefully degrades if Redis is unavailable or slow."""

    @pytest.mark.asyncio
    async def test_redis_timeout_falls_back_to_in_memory_window(self):
        mock_slow_redis = AsyncMock()

        async def slow_eval(*args, **kwargs):
            await asyncio.sleep(0.300)
            return [0, 19, 0]

        mock_slow_redis.eval = slow_eval

        limiter = DistributedRateLimiter(
            requests_num=20,
            period=60,
            redis_timeout=0.150,
            redis_client=mock_slow_redis,
        )

        t0 = time.perf_counter()
        is_limited, remaining, _ = await limiter.check_rate_limit("fallback-key")
        elapsed = time.perf_counter() - t0

        assert not is_limited
        assert elapsed < 0.250, "Rate check took too long to fall back"
        assert len(limiter.requests["fallback-key"]) == 1

    @pytest.mark.asyncio
    async def test_redis_network_error_falls_back_to_in_memory_window(self):
        mock_err_redis = AsyncMock()
        mock_err_redis.eval.side_effect = ConnectionError("Upstash network down")

        limiter = DistributedRateLimiter(
            requests_num=20,
            period=60,
            redis_client=mock_err_redis,
        )

        is_limited, remaining, _ = await limiter.check_rate_limit("network-error-key")
        assert not is_limited
        assert len(limiter.requests["network-error-key"]) == 1


class TestRateLimiterBackwardCompatibility:
    """Ensures that existing synchronous unit tests continue to pass without modifications."""

    def test_sync_tuple_unpacking(self):
        limiter = DistributedRateLimiter(requests_num=3, period=60)
        key = "test-sync-key"

        is_limited, remaining = limiter.is_rate_limited(key)
        assert not is_limited
        assert remaining == 2

        is_limited, remaining = limiter.is_rate_limited(key)
        assert not is_limited
        assert remaining == 1

        is_limited, remaining = limiter.is_rate_limited(key)
        assert not is_limited
        assert remaining == 0

        is_limited, remaining = limiter.is_rate_limited(key)
        assert is_limited
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_async_await_dual_mode_result(self):
        limiter = DistributedRateLimiter(requests_num=2, period=60)
        key = "test-await-key"

        is_limited, remaining, retry_after = await limiter.is_rate_limited(key)
        assert not is_limited
        assert remaining == 1


# =============================================================================
# PART 2: STATE MANAGER & EXCLUSION FILTERING TESTS (TASKS 4.1, 4.2 / AC 4.1, 4.2)
# =============================================================================

class TestStateManagerFallbackAndUnsetCredentials:
    """Verifies that StateManager operates reliably without Redis credentials."""

    @pytest.mark.asyncio
    async def test_init_without_credentials_defaults_to_in_memory(self):
        sm = StateManager(redis_url=None, redis_token=None)
        assert not sm.is_redis_available
        assert isinstance(sm.memory_store, InMemoryStateStore)

        history = await sm.get_session_history("sess_test_fresh")
        assert history == []

        await sm.append_session_turn("sess_test_fresh", {"role": "user", "content": "cyberpunk anime"})
        history = await sm.get_session_history("sess_test_fresh")
        assert len(history) == 1
        assert history[0]["content"] == "cyberpunk anime"

    @pytest.mark.asyncio
    async def test_rolling_five_turns_eviction(self):
        sm = StateManager(redis_url=None, redis_token=None)
        session_id = "sess_rolling_window"

        for i in range(8):
            await sm.append_session_turn(
                session_id,
                {"turn": i, "role": "user", "content": f"query {i}"}
            )

        history = await sm.get_session_history(session_id)
        assert len(history) == 5, f"Expected 5 turns, found {len(history)}"
        assert history[0]["turn"] == 3
        assert history[-1]["turn"] == 7

    @pytest.mark.asyncio
    async def test_in_memory_session_ttl_expiration(self):
        sm = StateManager(redis_url=None, redis_token=None)
        session_id = "sess_ttl_expiry"

        await sm.append_session_turn(session_id, {"role": "user", "content": "test"}, ttl=1)
        history = await sm.get_session_history(session_id)
        assert len(history) == 1

        await asyncio.sleep(1.1)
        expired_history = await sm.get_session_history(session_id)
        assert len(expired_history) == 0, "Session should have expired after 1.1s"


class TestStateManagerTimeoutAndResilience:
    """Verifies 150ms circuit breaker timeout and graceful fallback."""

    @pytest.mark.asyncio
    async def test_redis_call_timeout_triggers_fallback_within_150ms(self):
        sm = StateManager(
            redis_url="https://mock.upstash.io",
            redis_token="mock-token",
            timeout=0.150,
        )
        sm.redis = AsyncMock()

        async def slow_get(*args, **kwargs):
            await asyncio.sleep(0.350)
            return "[]"

        sm.redis.get.side_effect = slow_get

        t0 = time.perf_counter()
        history = await sm.get_session_history("sess_slow_network")
        elapsed_sec = time.perf_counter() - t0

        assert history == []
        assert elapsed_sec < 0.250, f"Fallback took too long: {elapsed_sec:.3f}s (must be < 0.25s)"

    @pytest.mark.asyncio
    async def test_redis_network_exception_falls_back_cleanly(self):
        sm = StateManager(
            redis_url="https://mock.upstash.io",
            redis_token="mock-token",
        )
        sm.redis = AsyncMock()
        sm.redis.get.side_effect = ConnectionError("Upstash REST gateway unreachable")

        history = await sm.get_session_history("sess_network_error")
        assert history == []

        sm.redis.set.side_effect = ConnectionError("Upstash REST gateway unreachable")
        await sm.append_session_turn("sess_network_error", {"role": "user", "content": "resilient query"})


class TestExclusionFilteringIntegration:
    """Verifies Task 4.2 & AC 4.2: Seen titles are 100% excluded via O(1) set subtraction."""

    @pytest.mark.asyncio
    async def test_seen_ids_deduplication_in_ranker(self):
        sm = StateManager(redis_url=None, redis_token=None)
        user_id = "user_eval_exclusion"

        await sm.record_seen_ids(user_id, [101, 102])
        seen = await sm.get_excluded_ids(user_id)
        assert seen == {101, 102}

        raw_candidates = [
            [
                {"id": 101, "title_userPreferred": "Seen Anime A", "description": "desc A"},
                {"id": 102, "title_userPreferred": "Seen Anime B", "description": "desc B"},
                {"id": 103, "title_userPreferred": "Fresh Anime C", "description": "desc C"},
                {"id": 104, "title_userPreferred": "Fresh Anime D", "description": "desc D"},
            ]
        ]

        ranker = Ranker.__new__(Ranker)
        deduped_df = ranker.merge_deduplicate(raw_candidates, seen_ids=seen)

        output_ids = deduped_df["id"].tolist()
        assert 101 not in output_ids, "Anime 101 was seen and should have been excluded"
        assert 102 not in output_ids, "Anime 102 was seen and should have been excluded"
        assert 103 in output_ids, "Fresh Anime 103 must be present"
        assert 104 in output_ids, "Fresh Anime 104 must be present"
        assert len(output_ids) == 2


class TestHybridLLMCache:
    """Verifies that LLMCache supports both synchronous and asynchronous operations."""

    def test_sqlite_fallback_sync_operations(self, tmp_path):
        db_file = tmp_path / "test_cache.db"
        cache = LLMCache(db_path=db_file)
        assert cache.backend == "sqlite"

        cache.set("test:key:1", {"expansions": ["query1", "query2"]})
        result = cache.get("test:key:1")
        assert result == {"expansions": ["query1", "query2"]}
        assert cache.get("test:key:missing") is None

    @pytest.mark.asyncio
    async def test_sqlite_fallback_async_operations(self, tmp_path):
        db_file = tmp_path / "test_cache_async.db"
        cache = LLMCache(db_path=db_file)

        await cache.aset("async:key:1", ["val1", "val2"])
        result = await cache.aget("async:key:1")
        assert result == ["val1", "val2"]


# =============================================================================
# PART 3: CONVERSATIONAL WEB MVP INTEGRATION TESTS (TASK 4.4 / AC 4.4)
# =============================================================================

@pytest.fixture
def catalog_candidates():
    """Sample candidate catalog spanning different anime."""
    return [
        {
            "id": 101,
            "title_userPreferred": "Ghost in the Shell: Stand Alone Complex",
            "title_romaji": "Koukaku Kidoutai: Stand Alone Complex",
            "genres": ["Action", "Sci-Fi", "Cyberpunk"],
            "studios": ["Production I.G"],
            "averageScore": 84.0,
            "seasonYear": 2002,
            "cross_encoder_score": 5.2,
            "description": "In a cybernetic future, Section 9 combats high-profile cyber crimes and terrorism.",
        },
        {
            "id": 102,
            "title_userPreferred": "Psycho-Pass",
            "title_romaji": "Psycho-Pass",
            "genres": ["Action", "Sci-Fi", "Psychological"],
            "studios": ["Production I.G"],
            "averageScore": 83.5,
            "seasonYear": 2012,
            "cross_encoder_score": 4.9,
            "description": "Enforcers and Inspectors enforce the will of the all-knowing Sibyl System.",
        },
        {
            "id": 103,
            "title_userPreferred": "Ergo Proxy",
            "title_romaji": "Ergo Proxy",
            "genres": ["Mystery", "Sci-Fi", "Psychological"],
            "studios": ["Manglobe"],
            "averageScore": 79.0,
            "seasonYear": 2006,
            "cross_encoder_score": 4.5,
            "description": "In a domed post-apocalyptic city, humans and android AutoReivs coexist until a virus emerges.",
        },
        {
            "id": 104,
            "title_userPreferred": "Texhnolyze",
            "title_romaji": "Texhnolyze",
            "genres": ["Action", "Drama", "Psychological", "Sci-Fi"],
            "studios": ["Madhouse"],
            "averageScore": 77.0,
            "seasonYear": 2003,
            "cross_encoder_score": 4.1,
            "description": "In the underground city of Lux, factions war for control of prosthetic Texhnolyze technology.",
        },
    ]


class TestConversationalSessionLifecycle:
    """Verifies session ID handling, response headers, and SSE schema formatting."""

    @pytest.mark.asyncio
    async def test_chat_auto_generates_session_id_when_not_provided(self, catalog_candidates):
        async def mock_retrieval(*args, **kwargs):
            return catalog_candidates[:2], {"retrieval_ms": 20.0}

        async def mock_token_stream(*args, **kwargs):
            yield "Here is your cyberpunk recommendation pitch."

        with patch.object(orchestrator, "_retrieval_func", side_effect=mock_retrieval), \
             patch.object(orchestrator.synthesizer, "stream_pitch", side_effect=mock_token_stream):

            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/chat",
                    headers={"access_token": "test-secret-sprint4-key"},
                    json={"query": "recommend intense cyberpunk anime", "top_k": 2},
                )

                assert res.status_code == 200
                assert "X-Session-ID" in res.headers
                assigned_session_id = res.headers["X-Session-ID"]
                assert len(assigned_session_id) > 10

                body = res.text
                assert f'"session_id": "{assigned_session_id}"' in body
                assert "event: metadata" in body
                assert "Ghost in the Shell" in body
                assert "event: done" in body


class TestAC41MultiTurnPersistenceAcrossContainers:
    """
    AC 4.1: Multi-turn session persistence: When Turn 1 is processed by Container A
    and Turn 2 is processed by Container B, Turn 2 successfully accesses the query history
    and recommended IDs from Turn 1.
    """

    @pytest.mark.asyncio
    async def test_ac4_1_session_persistence_across_decoupled_containers(self, catalog_candidates):
        shared_state_manager = StateManager(redis_url=None, redis_token=None)

        container_a_orch = PipelineOrchestrator(state_manager=shared_state_manager)
        container_b_orch = PipelineOrchestrator(state_manager=shared_state_manager)

        session_id = "sess_decoupled_container_eval_1"
        user_id = "user_cross_container_1"

        async def container_a_retrieval(*args, **kwargs):
            return catalog_candidates[:2], {"retrieval_ms": 15.0}

        async def container_a_pitch(*args, **kwargs):
            yield "Pitch from Container A: Ghost in the Shell and Psycho-Pass."

        container_a_orch._retrieval_func = container_a_retrieval
        container_a_orch.synthesizer.stream_pitch = container_a_pitch

        turn1_events = []
        async for sse_chunk in container_a_orch.stream_chat(
            query="cyberpunk anime with detective mystery",
            top_k=2,
            session_id=session_id,
            user_id=user_id,
        ):
            turn1_events.append(sse_chunk)

        turn1_text = "".join(turn1_events)
        assert "event: metadata" in turn1_text
        assert "Ghost in the Shell" in turn1_text

        stored_history = await shared_state_manager.get_session_history(session_id)
        assert len(stored_history) >= 2
        assert stored_history[0]["content"] == "cyberpunk anime with detective mystery"

        stored_seen = await shared_state_manager.get_excluded_ids(user_id)
        assert 101 in stored_seen
        assert 102 in stored_seen

        captured_history = []

        async def container_b_retrieval(query, top_k, seen_ids=None, **kwargs):
            remaining = [c for c in catalog_candidates if c["id"] not in (seen_ids or set())]
            return remaining[:top_k], {"retrieval_ms": 15.0}

        async def container_b_pitch(query, candidates, conversation_history=None, **kwargs):
            nonlocal captured_history
            captured_history = list(conversation_history or [])
            yield "Pitch from Container B: Ergo Proxy fits your previous tastes."

        container_b_orch._retrieval_func = container_b_retrieval
        container_b_orch.synthesizer.stream_pitch = container_b_pitch

        turn2_events = []
        async for sse_chunk in container_b_orch.stream_chat(
            query="give me something darker from the same vibe",
            top_k=2,
            session_id=session_id,
            user_id=user_id,
        ):
            turn2_events.append(sse_chunk)

        assert len(captured_history) >= 2, "Container B did not receive Turn 1 conversation history"
        assert captured_history[0]["content"] == "cyberpunk anime with detective mystery"


class TestAC42WatchedTitleExclusionZeroRecurrence:
    """
    AC 4.2: Watched title exclusion: Titles recommended in Turn 1 are strictly excluded
    from Turn 2 candidates (0% recurrence).
    """

    @pytest.mark.asyncio
    async def test_ac4_2_watched_title_exclusion_zero_recurrence(self, catalog_candidates):
        shared_state_manager = StateManager(redis_url=None, redis_token=None)
        orch = PipelineOrchestrator(state_manager=shared_state_manager)

        session_id = "sess_exclusion_eval_42"
        user_id = "user_exclusion_eval_42"

        async def dynamic_retrieval(query, top_k, seen_ids=None, **kwargs):
            active_seen = set(seen_ids or [])
            available = [c for c in catalog_candidates if c["id"] not in active_seen]
            return available[:top_k], {"retrieval_ms": 10.0}

        async def simple_pitch(*args, **kwargs):
            yield "Tailored pitch."

        orch._retrieval_func = dynamic_retrieval
        orch.synthesizer.stream_pitch = simple_pitch

        turn1_candidates = []
        async for chunk in orch.stream_chat(
            query="recommend cyberpunk",
            top_k=2,
            session_id=session_id,
            user_id=user_id,
        ):
            if "event: metadata" in chunk:
                match = re.search(r'data:\s*(\{.*\})', chunk)
                if match:
                    payload = json.loads(match.group(1))
                    turn1_candidates = payload.get("candidates", [])

        assert len(turn1_candidates) == 2
        turn1_ids = {c["id"] for c in turn1_candidates}
        assert turn1_ids == {101, 102}

        turn2_candidates = []
        async for chunk in orch.stream_chat(
            query="give me something else, I saw those already",
            top_k=2,
            session_id=session_id,
            user_id=user_id,
        ):
            if "event: metadata" in chunk:
                match = re.search(r'data:\s*(\{.*\})', chunk)
                if match:
                    payload = json.loads(match.group(1))
                    turn2_candidates = payload.get("candidates", [])

        assert len(turn2_candidates) == 2
        turn2_ids = {c["id"] for c in turn2_candidates}
        assert turn2_ids == {103, 104}

        overlap = turn1_ids.intersection(turn2_ids)
        assert len(overlap) == 0, f"AC 4.2 VIOLATION: Candidate recurrence detected: {overlap}"


class TestAC44WebConversationalIntegrationSSEStreaming:
    """
    AC 4.4: Web conversational integration test verifies valid multi-turn SSE streaming
    with card rendering and token streaming end-to-end via HTTP.
    """

    @pytest.mark.asyncio
    async def test_ac4_4_web_conversational_integration_sse_streaming(self, catalog_candidates):
        async def mock_retrieval(*args, **kwargs):
            return catalog_candidates[:2], {"retrieval_ms": 30.0}

        async def mock_token_stream(*args, **kwargs):
            yield "Ghost in the Shell provides deep philosophical cybernetics. "
            yield "Psycho-Pass investigates the morality of predictive law enforcement."

        with patch.object(orchestrator, "_retrieval_func", side_effect=mock_retrieval), \
             patch.object(orchestrator.synthesizer, "stream_pitch", side_effect=mock_token_stream):

            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/chat",
                    headers={"access_token": "test-secret-sprint4-key"},
                    json={
                        "query": "philosophical sci-fi anime",
                        "top_k": 2,
                        "session_id": "sess_integration_44",
                    },
                )

                assert response.status_code == 200
                assert "text/event-stream" in response.headers.get("content-type", "")
                assert response.headers.get("X-Session-ID") == "sess_integration_44"

                body = response.text
                assert "event: metadata" in body
                assert "Ghost in the Shell: Stand Alone Complex" in body
                assert "Psycho-Pass" in body
                assert "event: token" in body
                assert "philosophical cybernetics" in body
                assert "event: done" in body
                assert '"status": "completed"' in body


class TestClientDisconnectionHandling:
    """Verifies that client disconnection aborts the generator cleanly without unhandled leaks."""

    @pytest.mark.asyncio
    async def test_client_disconnect_aborts_stream_cleanly(self, catalog_candidates):
        is_client_connected = True

        async def disconnect_checker():
            return not is_client_connected

        async def mock_retrieval(*args, **kwargs):
            return catalog_candidates, {"retrieval_ms": 20.0}

        orch = PipelineOrchestrator(retrieval_func=mock_retrieval)

        events_received = 0
        gen = orch.stream_chat(
            query="action anime",
            top_k=2,
            is_disconnected=disconnect_checker,
        )

        async for _ in gen:
            events_received += 1
            is_client_connected = False

        assert events_received >= 1
