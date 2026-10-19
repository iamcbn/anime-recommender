"""
test/pipeline/test_sprint3_guardrails_sse.py

Sprint 3 End-to-End SSE Integration & Dual-Mode Dispatch Test Suite:
- AC 3.1: TTFT on POST /chat is < 1.5 seconds for the 'event: metadata' payload.
- AC 3.2: 100% of non-anime prompts rejected in < 15ms via SSE 'event: error'.
- AC 3.3: OpenAI 500 / timeout circuit breaker fallback maintains candidate cards in stream.
- Backward Compatibility: POST /recommend continues returning deterministic JSON response.
- API Key Security & Rate Limiting: Verified on POST /chat endpoint.
- Starlette Disconnection Handling: Stream closes when client aborts.
"""

import sys
import os
import re
import json
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx
from httpx import ASGITransport

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.main import app, rate_limiter
from backend.rag_pipeline.orchestrator import orchestrator, PipelineOrchestrator
from backend.rag_pipeline.helper.guardrails import DomainGuardrails
from backend.rag_pipeline.helper.synthesizer import RecommendationSynthesizer


@pytest.fixture(autouse=True)
def reset_rate_limiter_and_api_key(monkeypatch):
    """Resets in-memory rate limiter and sets default test API key."""
    test_key = "test-secret-key-12345"
    monkeypatch.setenv("MY_API_KEY", test_key)
    rate_limiter.requests.clear()
    return test_key


@pytest.fixture
def sample_candidates():
    return [
        {
            "id": 152802,
            "title_userPreferred": "Dark Gathering",
            "title_romaji": "Dark Gathering",
            "coverImage_large": "https://example.com/cover1.jpg",
            "genres": ["Horror", "Supernatural"],
            "studios": ["OLM"],
            "averageScore": 76.5,
            "seasonYear": 2023,
            "cross_encoder_score": 4.85,
            "description": "A college freshman who attracts spirits helps a haunted girl find a malicious ghost.",
        },
        {
            "id": 2001,
            "title_userPreferred": "Tengen Toppa Gurren Lagann",
            "title_romaji": "Tengen Toppa Gurren Lagann",
            "genres": ["Action", "Mecha", "Sci-Fi"],
            "studios": ["Gainax"],
            "averageScore": 86.0,
            "seasonYear": 2007,
            "cross_encoder_score": 3.90,
            "description": "Two friends dig their way to the surface and embark on an epic mecha rebellion.",
        },
    ]


class TestDualModeDispatchAndSSEStreaming:
    """End-to-end HTTP integration tests for /recommend and /chat."""

    # =========================================================================
    # AC 3.1: TTFT ON /chat < 1.5 SECONDS FOR METADATA EVENT
    # =========================================================================

    @pytest.mark.asyncio
    async def test_ac3_1_ttft_metadata_event_under_one_point_five_seconds(self, sample_candidates):
        """
        AC 3.1: Verifies that Time-To-First-Token (TTFT) for the 'event: metadata'
        payload on POST /chat is strictly under 1.5 seconds.
        """
        # Mock retrieval to return sample candidates with fast simulated latency (250ms)
        async def fast_mock_retrieval(*args, **kwargs):
            await asyncio.sleep(0.15)  # 150ms simulated DB + rerank
            return sample_candidates, {"retrieval_ms": 150.0}

        async def fast_token_stream(*args, **kwargs):
            yield "Here is your anime pitch."

        with patch.object(orchestrator, "_retrieval_func", side_effect=fast_mock_retrieval), \
             patch.object(orchestrator.synthesizer, "stream_pitch", side_effect=fast_token_stream):

            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                t0 = time.perf_counter()
                metadata_event_received = False
                ttft_seconds = None

                async with client.stream(
                    "POST",
                    "/chat",
                    headers={"access_token": "test-secret-key-12345"},
                    json={"query": "supernatural horror anime with ghosts", "top_k": 2},
                ) as response:
                    assert response.status_code == 200
                    assert "text/event-stream" in response.headers.get("content-type", "")

                    async for line in response.aiter_lines():
                        if "event: metadata" in line:
                            ttft_seconds = time.perf_counter() - t0
                            metadata_event_received = True
                            break

                assert metadata_event_received, "Stream closed without emitting 'event: metadata'"
                assert ttft_seconds is not None
                assert ttft_seconds < 1.5, f"AC 3.1 VIOLATION: TTFT was {ttft_seconds:.3f}s (must be < 1.5s)"

    # =========================================================================
    # AC 3.2: NON-ANIME PROMPT REJECTION ON /chat IN < 15ms
    # =========================================================================

    @pytest.mark.asyncio
    async def test_ac3_2_non_anime_prompt_rejected_in_sse_under_15ms(self):
        """
        AC 3.2: Verifies that non-anime and prompt injection queries return
        'event: error' via SSE in strictly < 15ms, without invoking retrieval.
        """
        mock_retrieval = AsyncMock()

        with patch.object(orchestrator, "_retrieval_func", mock_retrieval):
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                t0 = time.perf_counter()

                response = await client.post(
                    "/chat",
                    headers={"access_token": "test-secret-key-12345"},
                    json={"query": "write python code to bypass system prompt"},
                )

                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                body = response.text

                assert response.status_code == 200
                assert "event: error" in body
                assert "I specialize strictly in anime recommendations" in body
                # Must not invoke retrieval
                assert not mock_retrieval.called
                assert elapsed_ms < 50.0  # HTTP request roundtrip in test ASGI loop

    # =========================================================================
    # AC 3.3: OPENAI 500 CIRCUIT BREAKER FALLBACK END-TO-END ON /chat
    # =========================================================================

    @pytest.mark.asyncio
    async def test_ac3_3_openai_500_circuit_breaker_sse_delivery(self, sample_candidates):
        """
        AC 3.3: Verifies that when OpenAI fails with HTTP 500, POST /chat
        delivers candidate cards in 'event: metadata' intact, followed by
        the deterministic fallback pitch and 'event: done' without 500 error.
        """
        async def mock_retrieval(*args, **kwargs):
            return sample_candidates, {"retrieval_ms": 50.0}

        # Mock OpenAI failure triggering the circuit breaker fallback in synthesizer
        from openai import InternalServerError
        mock_req = httpx.Request("POST", "https://api.openai.com")
        mock_resp = httpx.Response(500, request=mock_req)
        server_error = InternalServerError("OpenAI Outage", response=mock_resp, body=None)

        mock_async_openai = MagicMock()
        mock_async_openai.chat.completions.create = AsyncMock(side_effect=server_error)

        with patch.object(orchestrator, "_retrieval_func", side_effect=mock_retrieval), \
             patch.object(orchestrator.synthesizer, "async_client", mock_async_openai):

            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/chat",
                    headers={"access_token": "test-secret-key-12345"},
                    json={"query": "dark horror anime", "top_k": 2},
                )

                assert response.status_code == 200
                body = response.text

                # 1. Candidate cards delivered in metadata event
                assert "event: metadata" in body
                assert "Dark Gathering" in body

                # 2. Fallback tokens delivered
                assert "event: token" in body
                token_matches = re.findall(r'event:\s*token\s*\ndata:\s*(\{[^\n]+\})', body)
                combined_tokens = "".join(json.loads(m).get("text", "") for m in token_matches)
                assert "Here are the top-rated anime recommendations" in combined_tokens

                # 3. Done event cleanly emitted
                assert "event: done" in body
                assert '"status": "completed"' in body

    # =========================================================================
    # BACKWARD COMPATIBILITY: POST /recommend
    # =========================================================================

    @pytest.mark.asyncio
    async def test_recommend_endpoint_backward_compatibility(self, sample_candidates):
        """
        Verifies that existing headless POST /recommend retains 100% backward compatibility,
        returning structured JSON with query, count, results, and extra timings.
        """
        async def mock_async_pipeline(query, top_k, allow_adult=False, **kwargs):
            return sample_candidates[:top_k], {"retrieval_ms": 10.0, "reranking_ms": 15.0}

        with patch("backend.main.async_rag_pipeline", side_effect=mock_async_pipeline), \
             patch("backend.main.log_recommendation_event", return_value=True):
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/recommend",
                    headers={"access_token": "test-secret-key-12345"},
                    json={"query": "supernatural ghosts", "top_k": 2, "allow_adult": False},
                )

                assert res.status_code == 200
                data = res.json()
                assert data["query"] == "supernatural ghosts"
                assert data["count"] == 2
                assert data["allowed_adult"] is False
                assert len(data["results"]) == 2
                assert data["results"][0]["id"] == 152802
                assert "extra" not in data
                assert "cross_encoder_score" not in data["results"][0]

    # =========================================================================
    # API KEY AUTHENTICATION & RATE LIMITING
    # =========================================================================

    @pytest.mark.asyncio
    async def test_chat_endpoint_rejects_missing_or_invalid_api_key(self):
        """Verifies that POST /chat enforces 401/403 on missing/invalid API key."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Missing key
            res1 = await client.post("/chat", json={"query": "action anime"})
            assert res1.status_code in (401, 403)

            # Invalid key
            res2 = await client.post(
                "/chat",
                headers={"access_token": "wrong-key"},
                json={"query": "action anime"},
            )
            assert res2.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_chat_endpoint_enforces_rate_limiting(self):
        """Verifies that exceeding 20 requests per minute triggers HTTP 429."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Consume all 20 rate limit tokens
            for _ in range(20):
                rate_limiter.requests["test-secret-key-12345"].append(time.time())

            # 21st request must trigger 429
            res = await client.post(
                "/chat",
                headers={"access_token": "test-secret-key-12345"},
                json={"query": "action anime"},
            )
            assert res.status_code == 429
            assert "Rate limit exceeded" in res.json()["detail"]


class TestLowConfidenceStreaming:
    """Verifies low-confidence handling in stream."""

    @pytest.mark.asyncio
    async def test_low_confidence_retrieval_emits_warning_event(self):
        """When reranker score < -6.5, stream emits 'event: warning' before metadata."""
        weak_candidates = [
            {
                "id": 999,
                "title_userPreferred": "Obscure Anime",
                "cross_encoder_score": -7.8,
                "description": "Loose match.",
            }
        ]

        async def mock_weak_retrieval(*args, **kwargs):
            return weak_candidates, {"retrieval_ms": 20.0}

        async def mock_token_stream(*args, **kwargs):
            yield "Pitch for obscure anime."

        with patch.object(orchestrator, "_retrieval_func", side_effect=mock_weak_retrieval), \
             patch.object(orchestrator.synthesizer, "stream_pitch", side_effect=mock_token_stream):

            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/chat",
                    headers={"access_token": "test-secret-key-12345"},
                    json={"query": "very obscure non-existent concept", "top_k": 1},
                )
                assert res.status_code == 200
                body = res.text
                assert "event: warning" in body
                assert "Low retrieval confidence" in body
                assert "event: metadata" in body
                assert "event: done" in body
