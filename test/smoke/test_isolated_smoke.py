"""
test/smoke/test_isolated_smoke.py

End-to-End Isolated Smoke Test Suite for the Anime Recommender platform.

Verification Matrix:
- Complete Environment Isolation:
  * LLM cache isolated to a temporary SQLite database file or mocked cache.
  * Database access isolated via mocked or controlled database records.
  * In-process HTTP testing using `httpx.ASGITransport(app=app)` without host port binding.
  * Clean, isolated environment variables.
- Required Verifications:
  1. GET `/` returns 200 and expected welcome message.
  2. POST `/recommend` returns 200, valid RecommendResponse schema, correct candidates, and complete timings.
  3. POST `/recommend` returns 403 on missing or invalid API key.
  4. POST `/recommend` returns 422 on invalid payload (query min_length < 2, empty, missing).
  5. POST `/recommend` rate limiter triggers 429 when quota is exceeded.
  6. `async_rag_pipeline` executes end-to-end returning output and complete timing keys.
  7. Synchronous `rag_pipeline` executes cleanly and returns output and complete timing keys.
  8. `QueryGenerator` generates queries asynchronously and synchronously, and falls back gracefully to [user_query] on exceptions.
  9. `LocalInferenceClient` and `ModalInferenceClient` resolve and execute correctly.
  10. `modal_deploy.py` defines `ModelWorker` and `fastapi_app` with valid Modal decorators and interfaces.
"""

import sys
import os
import json
import time
import sqlite3
import asyncio
from pathlib import Path
from datetime import timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
import pytest_asyncio
import httpx
import modal

# Ensure project root is available in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from psycopg2.pool import PoolError

from backend.main import (
    app,
    rate_limiter,
    RateLimiter,
    RecommendResponse,
    RecommendRequest,
)
from backend.rag_pipeline.rag_pipeline import (
    rag_pipeline,
    async_rag_pipeline,
)
from backend.rag_pipeline.helper.query_generator import (
    QueryGenerator,
    HypotheticalQueries,
)
from backend.rag_pipeline.helper.llm_cache import LLMCache
from backend.rag_pipeline.helper.retrieval import DatabaseManager
from backend.rag_pipeline.inference_client import (
    BaseInferenceClient,
    LocalInferenceClient,
    ModalInferenceClient,
    get_inference_client,
    sanitize_candidates_for_rpc,
)


# =============================================================================
# CONTROLLED MOCK DATA & FIXTURES FOR ISOLATION
# =============================================================================

TEST_API_KEY = "test-smoke-secret-key"
TEST_OPENAI_KEY = "test-smoke-openai-key"

SAMPLE_CANDIDATES = [
    {
        "id": 1,
        "title_romaji": "Cowboy Bebop",
        "title_english": "Cowboy Bebop",
        "title_userPreferred": "Cowboy Bebop",
        "coverImage_large": "https://example.com/bebop.jpg",
        "description": "In 2071, humanity has colonized the solar system...",
        "genres": ["Action", "Sci-Fi"],
        "studios": ["Sunrise"],
        "tags": ["Space", "Bounty Hunter"],
        "averageScore": 89.0,
        "seasonYear": 1998,
        "episodes": 26,
        "status": "FINISHED",
        "popularity": 125000,
        "cross_encoder_score": 5.42,
    },
    {
        "id": 200,
        "title_romaji": "Trigun",
        "title_english": "Trigun",
        "title_userPreferred": "Trigun",
        "coverImage_large": "https://example.com/trigun.jpg",
        "description": "Vash the Stampede is a joyful gunman...",
        "genres": ["Action", "Comedy", "Sci-Fi"],
        "studios": ["Madhouse"],
        "tags": ["Guns", "Wasteland"],
        "averageScore": 82.0,
        "seasonYear": 1998,
        "episodes": 26,
        "status": "FINISHED",
        "popularity": 85000,
        "cross_encoder_score": 4.88,
    },
]

SAMPLE_TIMINGS = {
    "self_query_ms": 0.0,
    "query_generation_ms": 14.5,
    "embedding_ms": 6.2,
    "retrieval_ms": 22.0,
    "reranking_ms": 11.8,
}

EXPECTED_TIMING_KEYS = {
    "self_query_ms",
    "query_generation_ms",
    "embedding_ms",
    "retrieval_ms",
    "reranking_ms",
}


@pytest.fixture(autouse=True)
def isolate_environment(tmp_path, monkeypatch):
    """
    Guarantees that every test runs with an isolated environment:
    - Sets clean API keys.
    - Sets isolated SQLite cache path in tmp_path.
    - Clears rate limiter request history between tests.
    """
    temp_cache_db = tmp_path / "smoke_llm_cache.db"
    monkeypatch.setenv("MY_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("OPENAI_API_KEY", TEST_OPENAI_KEY)
    monkeypatch.setenv("LLM_CACHE_PATH", str(temp_cache_db))
    monkeypatch.setenv("INFERENCE_MODE", "local")

    # Clear rate limiter state so tests do not interfere with each other
    rate_limiter.requests.clear()

    yield temp_cache_db

    rate_limiter.requests.clear()


@pytest_asyncio.fixture
async def async_client():
    """
    Isolated in-process HTTP client using httpx.ASGITransport without binding network ports.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# =============================================================================
# 0. ISOLATED COMPONENT TESTS: SQLITE CACHE & DATABASE MOCKS
# =============================================================================

class TestIsolationFixturesAndMocks:
    """Verifies that cache and database mocks behave in complete isolation."""

    def test_llm_cache_isolated_crud(self, tmp_path):
        """Verifies that LLMCache writes and reads only to the isolated temp sqlite database."""
        db_path = tmp_path / "isolated_cache.db"
        cache = LLMCache(db_path=db_path)

        assert db_path.exists(), "Cache SQLite database file was not created"
        assert cache.get("nonexistent_key") is None

        test_data = ["orig query", "hyde 1", "hyde 2"]
        cache.set("test_key", test_data)

        fetched = cache.get("test_key")
        assert fetched == test_data

    def test_llm_cache_disabled_flag(self, tmp_path, monkeypatch):
        """Verifies that DISABLE_LLM_CACHE=true renders LLMCache a complete no-op."""
        monkeypatch.setenv("DISABLE_LLM_CACHE", "true")
        cache = LLMCache(db_path=tmp_path / "disabled_cache.db")

        cache.set("some_key", ["value"])
        assert cache.get("some_key") is None

    def test_database_manager_pool_saturation_and_vitality(self):
        """
        Verifies that DatabaseManager gracefully handles pool checkout timeout
        and closes broken connections without live PostgreSQL dependencies.
        """
        mock_pool = MagicMock()
        mock_pool.getconn.side_effect = PoolError("pool exhausted")

        db_mgr = DatabaseManager.__new__(DatabaseManager)
        db_mgr._pool = mock_pool
        db_mgr.min_conn = 2
        db_mgr.max_conn = 10

        with pytest.raises(TimeoutError) as exc_info:
            with db_mgr.get_cursor(timeout=0.08):
                pass
        assert "timed out" in str(exc_info.value).lower()

        # Test broken connection cleanup
        broken_conn = MagicMock()
        broken_conn.closed = 1
        mock_pool.getconn.side_effect = None
        mock_pool.getconn.return_value = broken_conn

        with db_mgr.get_cursor(timeout=0.5):
            pass
        mock_pool.putconn.assert_called_with(broken_conn, close=True)


# =============================================================================
# 1. GET / RETURNS 200 AND WELCOME MESSAGE
# =============================================================================

class TestGetRootEndpoint:
    """Smoke test for GET / endpoint."""

    @pytest.mark.asyncio
    async def test_get_root_returns_200_and_welcome_message(self, async_client):
        """GET / must return HTTP 200 and the canonical welcome message."""
        response = await async_client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert "message" in data
        assert "Anime Recommendation API" in data["message"]
        assert "/recommend" in data["message"]


# =============================================================================
# 2. POST /RECOMMEND RETURNS 200, VALID SCHEMA, CANDIDATES & TIMINGS
# =============================================================================

class TestPostRecommendSuccess:
    """Smoke test for POST /recommend success flow."""

    @pytest.mark.asyncio
    async def test_post_recommend_returns_200_valid_schema(self, async_client):
        """
        POST /recommend with valid payload and access_token must return 200,
        conform strictly to RecommendResponse schema, and provide full timings.
        """
        payload = {
            "query": "space bounty hunter",
            "top_k": 5,
            "allow_adult": False,
        }
        headers = {"access_token": TEST_API_KEY}

        with patch("backend.main.async_rag_pipeline", new_callable=AsyncMock) as mock_pipe:
            mock_pipe.return_value = (SAMPLE_CANDIDATES, SAMPLE_TIMINGS)

            response = await async_client.post("/recommend", json=payload, headers=headers)

            assert response.status_code == 200
            data = response.json()

            # Schema validation via Pydantic model
            validated = RecommendResponse.model_validate(data)
            assert validated.query == "space bounty hunter"
            assert validated.count == len(SAMPLE_CANDIDATES)
            assert validated.allowed_adult is False
            assert len(validated.results) == 2
            assert validated.results[0]["title_romaji"] == "Cowboy Bebop"

            # Timing verification
            timings = validated.extra.get("timings", {})
            assert EXPECTED_TIMING_KEYS.issubset(timings.keys())
            expected_total = sum(SAMPLE_TIMINGS.values())
            assert abs(validated.extra.get("total_ms", 0.0) - expected_total) < 1e-4

            mock_pipe.assert_awaited_once_with(
                query="space bounty hunter",
                top_k=5,
                allow_adult=False,
            )


# =============================================================================
# 3. POST /RECOMMEND RETURNS 403 ON MISSING / INVALID API KEY
# =============================================================================

class TestPostRecommendAuthentication:
    """Smoke test for API key security enforcement."""

    @pytest.mark.asyncio
    async def test_post_recommend_missing_api_key_returns_403(self, async_client):
        """POST /recommend without access_token header must return HTTP 403."""
        payload = {"query": "cyberpunk anime", "top_k": 5}
        response = await async_client.post("/recommend", json=payload)
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_post_recommend_invalid_api_key_returns_403(self, async_client):
        """POST /recommend with incorrect access_token header must return HTTP 403."""
        payload = {"query": "cyberpunk anime", "top_k": 5}
        headers = {"access_token": "incorrect-api-key"}
        response = await async_client.post("/recommend", json=payload, headers=headers)
        assert response.status_code == 403
        data = response.json()
        assert "Invalid or missing API key" in data.get("detail", "")


# =============================================================================
# 4. POST /RECOMMEND RETURNS 422 ON INVALID PAYLOAD
# =============================================================================

class TestPostRecommendValidation:
    """Smoke test for request validation rules (min_length < 2)."""

    @pytest.mark.asyncio
    async def test_post_recommend_query_too_short_returns_422(self, async_client):
        """POST /recommend with query length < 2 must trigger 422 Unprocessable Entity."""
        headers = {"access_token": TEST_API_KEY}
        payload = {"query": "a", "top_k": 5}
        response = await async_client.post("/recommend", json=payload, headers=headers)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_post_recommend_empty_query_returns_422(self, async_client):
        """POST /recommend with empty string query must trigger 422."""
        headers = {"access_token": TEST_API_KEY}
        payload = {"query": "", "top_k": 5}
        response = await async_client.post("/recommend", json=payload, headers=headers)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_post_recommend_missing_query_field_returns_422(self, async_client):
        """POST /recommend missing query field completely must trigger 422."""
        headers = {"access_token": TEST_API_KEY}
        payload = {"top_k": 5}
        response = await async_client.post("/recommend", json=payload, headers=headers)
        assert response.status_code == 422


# =============================================================================
# 5. POST /RECOMMEND RATE LIMITER TRIGGERS 429 WHEN QUOTA EXCEEDED
# =============================================================================

class TestPostRecommendRateLimiter:
    """Smoke test for rate limiting enforcement."""

    def test_rate_limiter_logic_unit(self):
        """Unit verification of the RateLimiter sliding window calculation."""
        rl = RateLimiter(requests_num=3, period=timedelta(seconds=5))
        key = "unit-test-key"

        is_limited, remaining = rl.is_rate_limited(key)
        assert not is_limited and remaining == 2

        is_limited, remaining = rl.is_rate_limited(key)
        assert not is_limited and remaining == 1

        is_limited, remaining = rl.is_rate_limited(key)
        assert not is_limited and remaining == 0

        # Exceeded limit
        is_limited, remaining = rl.is_rate_limited(key)
        assert is_limited and remaining == 0

    @pytest.mark.asyncio
    async def test_post_recommend_rate_limiter_triggers_429(self, async_client):
        """Verifies that /recommend responds with 429 when RateLimiter limit is exceeded."""
        headers = {"access_token": TEST_API_KEY}
        payload = {"query": "rate limited query", "top_k": 2}

        # Configure small quota of 2 requests
        small_limiter = RateLimiter(requests_num=2, period=timedelta(minutes=1))

        with patch("backend.main.rate_limiter", small_limiter), \
             patch("backend.main.async_rag_pipeline", new_callable=AsyncMock, return_value=(SAMPLE_CANDIDATES, SAMPLE_TIMINGS)):

            # 1st request -> 200
            resp1 = await async_client.post("/recommend", json=payload, headers=headers)
            assert resp1.status_code == 200

            # 2nd request -> 200
            resp2 = await async_client.post("/recommend", json=payload, headers=headers)
            assert resp2.status_code == 200

            # 3rd request -> 429 Too Many Requests
            resp3 = await async_client.post("/recommend", json=payload, headers=headers)
            assert resp3.status_code == 429
            assert "Rate limit exceeded" in resp3.json().get("detail", "")


# =============================================================================
# 6. ASYNC_RAG_PIPELINE EXECUTES END-TO-END RETURNING OUTPUT & COMPLETE TIMINGS
# =============================================================================

class TestAsyncRagPipelineSmoke:
    """Smoke test for non-blocking async_rag_pipeline execution."""

    @pytest.mark.asyncio
    async def test_async_rag_pipeline_execution_and_timings(self):
        """
        Runs async_rag_pipeline in complete isolation (mocked LLM, Embedder, Retriever, Ranker)
        and verifies candidate output along with all 5 timing keys.
        """
        with patch("backend.rag_pipeline.rag_pipeline.query_generator") as mock_qg, \
             patch("backend.rag_pipeline.rag_pipeline.embedding") as mock_emb, \
             patch("backend.rag_pipeline.rag_pipeline.retriever") as mock_ret, \
             patch("backend.rag_pipeline.rag_pipeline.reranker") as mock_rank:

            # Query generator generates 3 queries
            mock_qg.generate_async = AsyncMock(return_value=["orig", "hyde1", "hyde2"])

            # Mock backward-compatible embedding and reranker mocks
            mock_emb.execute.return_value = [([0.1]*384, [0.1]*300)] * 3
            mock_ret.execute.return_value = [SAMPLE_CANDIDATES]
            mock_rank.execute.return_value = SAMPLE_CANDIDATES

            results, timings = await async_rag_pipeline(
                query="psychological suspense",
                top_k=2,
                allow_adult=False,
            )

            assert len(results) == 2
            assert results[0]["title_romaji"] == "Cowboy Bebop"

            assert EXPECTED_TIMING_KEYS.issubset(timings.keys()), (
                f"Missing timing keys: {EXPECTED_TIMING_KEYS - set(timings.keys())}"
            )
            for k in EXPECTED_TIMING_KEYS:
                assert isinstance(timings[k], (int, float))
                assert timings[k] >= 0.0

    @pytest.mark.asyncio
    async def test_async_rag_pipeline_via_inference_client_path(self):
        """
        Runs async_rag_pipeline through the direct inference_client path
        (when embedding and reranker are not MagicMocks).
        """
        mock_inf = MagicMock()
        mock_inf.embed_queries = AsyncMock(return_value=[([0.1]*384, [0.1]*300)] * 3)
        mock_inf.rerank_candidates = AsyncMock(return_value=SAMPLE_CANDIDATES)

        with patch("backend.rag_pipeline.rag_pipeline.query_generator") as mock_qg, \
             patch("backend.rag_pipeline.rag_pipeline.inference_client", mock_inf), \
             patch("backend.rag_pipeline.rag_pipeline.embedding", None), \
             patch("backend.rag_pipeline.rag_pipeline.reranker", None), \
             patch("backend.rag_pipeline.rag_pipeline.retriever") as mock_ret:

            mock_qg.generate_async = AsyncMock(return_value=["cyberpunk", "h1", "h2"])
            mock_ret.execute.return_value = [SAMPLE_CANDIDATES]

            results, timings = await async_rag_pipeline("cyberpunk", top_k=2)

            assert len(results) == 2
            assert EXPECTED_TIMING_KEYS.issubset(timings.keys())
            mock_inf.embed_queries.assert_awaited_once()
            mock_inf.rerank_candidates.assert_awaited_once()


# =============================================================================
# 7. SYNCHRONOUS RAG_PIPELINE EXECUTES CLEANLY AND RETURNS COMPLETE TIMINGS
# =============================================================================

class TestSyncRagPipelineSmoke:
    """Smoke test for synchronous rag_pipeline backward compatibility."""

    def test_sync_rag_pipeline_execution_and_timings(self):
        """
        Runs synchronous rag_pipeline with mocked external dependencies and verifies
        output and timing metrics completeness.
        """
        with patch("backend.rag_pipeline.rag_pipeline.query_generator") as mock_qg, \
             patch("backend.rag_pipeline.rag_pipeline.embedding") as mock_emb, \
             patch("backend.rag_pipeline.rag_pipeline.retriever") as mock_ret, \
             patch("backend.rag_pipeline.rag_pipeline.reranker") as mock_rank:

            mock_qg.generate.return_value = ["orig", "hyde1", "hyde2"]
            mock_emb.execute.return_value = [([0.1]*384, [0.1]*300)] * 3
            mock_ret.execute.return_value = [SAMPLE_CANDIDATES]
            mock_rank.execute.return_value = SAMPLE_CANDIDATES

            results, timings = rag_pipeline(
                query="post-apocalyptic wasteland",
                top_k=2,
                allow_adult=False,
            )

            assert len(results) == 2
            assert results[0]["title_romaji"] == "Cowboy Bebop"

            assert EXPECTED_TIMING_KEYS.issubset(timings.keys()), (
                f"Missing timing keys in sync pipeline: {EXPECTED_TIMING_KEYS - set(timings.keys())}"
            )
            for k in EXPECTED_TIMING_KEYS:
                assert isinstance(timings[k], (int, float))
                assert timings[k] >= 0.0

    def test_sync_rag_pipeline_via_inference_client_path(self):
        """
        Runs synchronous rag_pipeline through the direct inference_client path
        (when embedding and reranker are not MagicMocks).
        """
        mock_inf = MagicMock()
        mock_inf.embed_queries_sync.return_value = [([0.1]*384, [0.1]*300)] * 3
        mock_inf.rerank_candidates_sync.return_value = SAMPLE_CANDIDATES

        with patch("backend.rag_pipeline.rag_pipeline.query_generator") as mock_qg, \
             patch("backend.rag_pipeline.rag_pipeline.inference_client", mock_inf), \
             patch("backend.rag_pipeline.rag_pipeline.embedding", None), \
             patch("backend.rag_pipeline.rag_pipeline.reranker", None), \
             patch("backend.rag_pipeline.rag_pipeline.retriever") as mock_ret:

            mock_qg.generate.return_value = ["orig", "h1", "h2"]
            mock_ret.execute.return_value = [SAMPLE_CANDIDATES]

            results, timings = rag_pipeline("mecha anime", top_k=2)

            assert len(results) == 2
            assert EXPECTED_TIMING_KEYS.issubset(timings.keys())
            mock_inf.embed_queries_sync.assert_called_once()
            mock_inf.rerank_candidates_sync.assert_called_once()


# =============================================================================
# 8. QUERYGENERATOR ASYNC, SYNC, RETRY AND FALLBACK TO [USER_QUERY]
# =============================================================================

class TestQueryGeneratorSmoke:
    """Smoke test for QueryGenerator async/sync methods and fallback paths."""

    @pytest.fixture
    def generator(self):
        """Creates a QueryGenerator with dummy API key."""
        with patch("backend.rag_pipeline.helper.query_generator.llm_cache.get", return_value=None):
            gen = QueryGenerator(api_key=TEST_OPENAI_KEY)
            yield gen
            gen.close()

    @pytest.mark.asyncio
    async def test_generate_async_success(self, generator):
        """generate_async generates 3 queries via AsyncOpenAI parse."""
        mock_parsed = HypotheticalQueries(
            query_b="An android searching for identity in an abandoned city.",
            query_c="Rival bounty hunters chasing an elusive fugitive.",
        )
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(parsed=mock_parsed))]

        generator.async_client.beta.chat.completions.parse = AsyncMock(return_value=mock_completion)

        queries = await generator.generate_async("android bounty hunter")
        assert len(queries) == 3
        assert queries[0] == "android bounty hunter"
        assert queries[1] == mock_parsed.query_b
        assert queries[2] == mock_parsed.query_c

    @pytest.mark.asyncio
    async def test_generate_async_fallback_on_exception(self, generator):
        """generate_async falls back gracefully to [user_query] on timeout or error."""
        generator.async_client.beta.chat.completions.parse = AsyncMock(
            side_effect=httpx.ConnectTimeout("OpenAI connection timed out")
        )

        queries = await generator.generate_async("solitary swordsman")
        assert queries == ["solitary swordsman"], "Must fallback to [user_query] on exception"

    def test_generate_sync_success(self, generator):
        """generate (sync) generates 3 queries via OpenAI parse."""
        mock_parsed = HypotheticalQueries(
            query_b="A wanderer wielding a cursed blade across medieval lands.",
            query_c="Demonic forces clash with an exiled warrior in the mountains.",
        )
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(parsed=mock_parsed))]

        generator.client.beta.chat.completions.parse = MagicMock(return_value=mock_completion)

        queries = generator.generate("ronin demons")
        assert len(queries) == 3
        assert queries[0] == "ronin demons"
        assert queries[1] == mock_parsed.query_b
        assert queries[2] == mock_parsed.query_c

    def test_generate_sync_fallback_on_exception(self, generator):
        """generate (sync) falls back gracefully to [user_query] on exception."""
        generator.client.beta.chat.completions.parse = MagicMock(
            side_effect=RuntimeError("OpenAI API 500 error")
        )

        queries = generator.generate("epic journey")
        assert queries == ["epic journey"], "Must fallback to [user_query] on sync exception"

    @pytest.mark.asyncio
    async def test_generate_cache_hit_bypasses_openai(self, generator):
        """If queries are cached in LLMCache, OpenAI is never invoked."""
        cached_val = ["cyberpunk", "cached synopsis 1", "cached synopsis 2"]
        with patch("backend.rag_pipeline.helper.query_generator.llm_cache.get", return_value=cached_val):
            generator.async_client.beta.chat.completions.parse = AsyncMock()
            generator.client.beta.chat.completions.parse = MagicMock()

            async_res = await generator.generate_async("cyberpunk")
            assert async_res == cached_val
            generator.async_client.beta.chat.completions.parse.assert_not_called()

            sync_res = generator.generate("cyberpunk")
            assert sync_res == cached_val
            generator.client.beta.chat.completions.parse.assert_not_called()

    def test_query_generator_requires_api_key(self, monkeypatch):
        """QueryGenerator raises EnvironmentError if no API key is provided or present in env."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(EnvironmentError):
            QueryGenerator(api_key=None)


# =============================================================================
# 9. INFERENCE CLIENT (LOCAL, MODAL, FACTORY & SERIALIZATION)
# =============================================================================

class TestInferenceClientsSmoke:
    """Smoke test for LocalInferenceClient, ModalInferenceClient, and factory."""

    def test_factory_get_inference_client_resolution(self, monkeypatch):
        """Verifies factory resolution for local and modal modes."""
        monkeypatch.delenv("INFERENCE_MODE", raising=False)
        monkeypatch.delenv("MODAL_IS_REMOTE", raising=False)
        monkeypatch.delenv("MODAL_ENVIRONMENT", raising=False)

        client = get_inference_client()
        assert isinstance(client, LocalInferenceClient)

        monkeypatch.setenv("INFERENCE_MODE", "modal")
        client_modal = get_inference_client()
        assert isinstance(client_modal, ModalInferenceClient)

        monkeypatch.delenv("INFERENCE_MODE", raising=False)
        monkeypatch.setenv("MODAL_IS_REMOTE", "1")
        client_remote = get_inference_client()
        assert isinstance(client_remote, ModalInferenceClient)

    @pytest.mark.asyncio
    async def test_local_inference_client_execution(self):
        """Verifies LocalInferenceClient sync and async interfaces."""
        client = LocalInferenceClient()
        mock_embedder = MagicMock()
        mock_ranker = MagicMock()

        mock_embedder.execute.return_value = [([0.1]*384, [0.1]*300)]
        mock_ranker.execute.return_value = SAMPLE_CANDIDATES

        client._embedder = mock_embedder
        client._ranker = mock_ranker

        # Test sync
        sync_emb = client.embed_queries_sync(["query"])
        assert len(sync_emb) == 1
        sync_rank = client.rerank_candidates_sync("query", SAMPLE_CANDIDATES, top_k=2)
        assert len(sync_rank) == 2

        # Test async (uses asyncio.to_thread)
        async_emb = await client.embed_queries(["query"])
        assert len(async_emb) == 1
        async_rank = await client.rerank_candidates("query", SAMPLE_CANDIDATES, top_k=2)
        assert len(async_rank) == 2

    @pytest.mark.asyncio
    async def test_modal_inference_client_remote_and_fallback(self):
        """Verifies ModalInferenceClient RPC invocation and fallback to LocalInferenceClient."""
        client = ModalInferenceClient()

        # Mock remote worker actor
        mock_worker_cls = MagicMock()
        mock_worker = mock_worker_cls.return_value
        mock_worker.embed_queries.aio = AsyncMock(return_value=[([0.2]*384, [0.2]*300)])
        mock_worker.rerank_candidates.aio = AsyncMock(return_value=SAMPLE_CANDIDATES)
        mock_worker.embed_queries.remote = MagicMock(return_value=[([0.2]*384, [0.2]*300)])
        mock_worker.rerank_candidates.remote = MagicMock(return_value=SAMPLE_CANDIDATES)

        client._worker_cls = mock_worker_cls

        # Async execution via Modal RPC
        emb = await client.embed_queries(["query"])
        assert len(emb) == 1
        ranked = await client.rerank_candidates("query", SAMPLE_CANDIDATES, top_k=2)
        assert len(ranked) == 2

        # Sync execution via Modal RPC
        emb_sync = client.embed_queries_sync(["query"])
        assert len(emb_sync) == 1
        ranked_sync = client.rerank_candidates_sync("query", SAMPLE_CANDIDATES, top_k=2)
        assert len(ranked_sync) == 2

        # Test fallback on RPC error
        mock_worker.embed_queries.aio.side_effect = RuntimeError("Modal RPC timeout")
        client._local_fallback = MagicMock()
        client._local_fallback.embed_queries = AsyncMock(return_value=[([0.5]*384, [0.5]*300)])

        fallback_emb = await client.embed_queries(["query"])
        assert fallback_emb == [([0.5]*384, [0.5]*300)]

    def test_sanitize_candidates_for_rpc(self):
        """Verifies that sanitize_candidates_for_rpc prepares database rows cleanly."""
        assert sanitize_candidates_for_rpc(None) == []
        assert sanitize_candidates_for_rpc([]) == []

        raw_candidates = [
            [
                {
                    "id": 10,
                    "title": "Anime",
                    "embedding_text": "huge string to be stripped",
                },
                ("tuple_item_1", "tuple_item_2"),
            ]
        ]
        sanitized = sanitize_candidates_for_rpc(raw_candidates)
        assert len(sanitized) == 1
        first_group = sanitized[0]
        assert len(first_group) == 2
        assert "embedding_text" not in first_group[0]
        assert first_group[0]["title"] == "Anime"
        assert isinstance(first_group[1], list)


# =============================================================================
# 10. MODAL DEPLOYMENT SCRIPT STRUCTURE & INTERFACE CONTRACTS
# =============================================================================

class TestModalDeploySmoke:
    """Smoke test for modal_deploy.py configuration and interface contracts."""

    def test_modal_deploy_app_and_worker_interface(self):
        """
        Validates modal_deploy.py:
        - Defines `app` with valid Modal App instance.
        - Defines `ModelWorker` class with required methods (`initialize_runtime`, `embed_queries`, `rerank_candidates`).
        - Defines `fastapi_app` ASGI gateway entrypoint.
        """
        import modal_deploy

        # 1. App verification
        assert hasattr(modal_deploy, "app"), "modal_deploy missing 'app' definition"
        assert isinstance(modal_deploy.app, modal.App), "modal_deploy.app must be a modal.App"
        assert modal_deploy.app.name == "anime-recommender-api"

        # 2. ModelWorker Actor verification
        assert hasattr(modal_deploy, "ModelWorker"), "modal_deploy missing 'ModelWorker'"
        worker_cls = modal_deploy.ModelWorker

        # Verify interface methods
        assert hasattr(worker_cls, "initialize_runtime"), "ModelWorker missing 'initialize_runtime'"
        assert hasattr(worker_cls, "embed_queries"), "ModelWorker missing 'embed_queries'"
        assert hasattr(worker_cls, "rerank_candidates"), "ModelWorker missing 'rerank_candidates'"

        # 3. Gateway FastAPI ASGI application entrypoint verification
        assert hasattr(modal_deploy, "fastapi_app"), "modal_deploy missing 'fastapi_app'"
        assert isinstance(modal_deploy.fastapi_app, modal.Function), "fastapi_app must be a modal.Function"

        # Calling fastapi_app.local() executes the wrapped function locally and returns the FastAPI app
        web_app = modal_deploy.fastapi_app.local()
        assert web_app is app, "fastapi_app.local() must return the backend.main FastAPI instance"
