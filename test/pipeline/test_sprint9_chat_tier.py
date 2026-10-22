"""
test/pipeline/test_sprint9_chat_tier.py

Sprint 9 Task 9.2 Verification Test Suite:
Dual-Tier Rate Limiting & Auth Header Dispatch on POST /chat

1. Anonymous Visitors Tier:
   - Sliding-window rate limit: 5 queries / 15 minutes (900 seconds) per client IP.
   - 6th query returns HTTP 429 Too Many Requests with Retry-After and rate limit headers.
   - Isolation: Different client IPs maintain independent sliding windows.
2. Authenticated Supabase User Tier:
   - Authenticated via Supabase JWT Bearer token verified with JWKS service.
   - Sliding-window rate limit: 20 queries / 1 hour (3600 seconds) per user ID.
   - 21st query returns HTTP 429 Too Many Requests with Retry-After and rate limit headers.
   - Isolation: Different user IDs maintain independent sliding windows.
   - Invalid and expired tokens return HTTP 401 Unauthorized.
3. Developer API Keys Backward Compatibility:
   - Preserves existing developer key validation (access_token, x-api-key, or Bearer ar_live_... / MY_API_KEY).
   - Enforces developer per-key rate limiting.
4. Negative Genre Constraints (disliked_genres):
   - Request disliked_genres post-filters candidate anime matching negative genres.
   - Case-insensitive matching.
   - Merging with NLI avoid_genres deduplicated case-insensitively.
   - Active avoid_genres list emitted in SSE 'event: metadata' payload.
5. Uniform 429 Error Envelope & Countdown Headers:
   - Standard schema: {"error": {"code": "rate_limit_exceeded", "message": "Rate limit exceeded. Try again later."}}.
   - Countdown accuracy on Retry-After and X-RateLimit-Reset headers.
"""

import sys
import os
import json
import time
import asyncio
from typing import Optional, List, Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from httpx import ASGITransport

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.main import app, rate_limiter
from backend.rag_pipeline.orchestrator import orchestrator, PipelineOrchestrator
from backend.rag_pipeline.helper.guardrails import DomainGuardrails, GuardrailResult
from backend.rag_pipeline.helper.nli_parser import NLIOutput
from backend.auth.supabase_jwt import set_jwks_service, DevUserContext


class MockJWKSService:
    """In-memory mock for Supabase JWKS verification service."""

    def __init__(self):
        self._tokens: Dict[str, DevUserContext] = {}

    def register(self, token: str, user_ctx: DevUserContext):
        self._tokens[token] = user_ctx

    def verify_token(self, token: str, require_fresh: bool = False) -> DevUserContext:
        if not token:
            raise ValueError("Token missing.")
        if "expired" in token.lower():
            raise ValueError("Token has expired.")
        if "stale" in token.lower():
            raise ValueError("Session is older than 15 minutes. Re-authentication required.")
        if token in self._tokens:
            return self._tokens[token]
        raise ValueError("Invalid token signature or unknown key identifier.")


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Sets up deterministic in-memory rate limiting and mock auth environment."""
    test_dev_key = "test-secret-sprint9-devkey"
    monkeypatch.setenv("MY_API_KEY", test_dev_key)
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,::1")

    # Enforce in-memory mode for fast, deterministic sliding window testing
    rate_limiter.redis = None
    rate_limiter.reset()

    # Configure mock JWKS service
    mock_jwks = MockJWKSService()
    set_jwks_service(mock_jwks)

    yield mock_jwks

    rate_limiter.reset()
    set_jwks_service(None)


@pytest.fixture
def mock_pipeline_fast():
    """Mocks RAG retrieval and pitch synthesis for rapid, isolated HTTP testing."""
    default_candidates = [
        {
            "id": 101,
            "title_userPreferred": "Gundam Iron-Blooded Orphans",
            "title_romaji": "Kidou Senshi Gundam: Tekketsu no Orphans",
            "genres": ["Action", "Drama", "Mecha", "Sci-Fi"],
            "cross_encoder_score": 4.5,
        },
        {
            "id": 102,
            "title_userPreferred": "Steins;Gate",
            "title_romaji": "Steins;Gate",
            "genres": ["Sci-Fi", "Suspense", "Thriller"],
            "cross_encoder_score": 5.2,
        },
        {
            "id": 103,
            "title_userPreferred": "Another",
            "title_romaji": "Another",
            "genres": ["Horror", "Mystery", "Supernatural"],
            "cross_encoder_score": 3.8,
        },
        {
            "id": 104,
            "title_userPreferred": "KonoSuba",
            "title_romaji": "Kono Subarashii Sekai ni Shukufuku wo!",
            "genres": ["Adventure", "Comedy", "Fantasy"],
            "cross_encoder_score": 4.9,
        },
    ]

    async def _mock_retrieval(*args, **kwargs):
        return default_candidates, {"retrieval_ms": 2.0}

    async def _mock_pitch(*args, **kwargs):
        yield "Here is your personalized anime recommendation pitch."

    with patch.object(orchestrator, "_retrieval_func", side_effect=_mock_retrieval), \
         patch.object(orchestrator.synthesizer, "stream_pitch", side_effect=_mock_pitch), \
         patch.object(orchestrator.guardrails, "validate_intent", return_value=GuardrailResult(True, "valid")), \
         patch("backend.telemetry.logger.log_recommendation_event"):
        yield default_candidates


# =============================================================================
# SUITE 1: ANONYMOUS VISITORS TIER (5 queries / 15 minutes per IP)
# =============================================================================

class TestAnonymousSlidingWindowRateLimit:
    """Verifies anonymous visitor sliding window rate limiting (5 queries / 15 minutes per IP)."""

    @pytest.mark.asyncio
    async def test_anonymous_visitor_allows_5_queries_within_15_minutes(self, mock_pipeline_fast):
        """Anonymous visitor from a given IP successfully makes 5 requests within 15 min."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client_ip = "198.51.100.10"
            headers = {"X-Forwarded-For": client_ip}

            for i in range(5):
                res = await client.post(
                    "/chat",
                    headers=headers,
                    json={"query": f"recommend sci-fi anime turn {i}"},
                )
                assert res.status_code == 200, f"Query {i + 1} should succeed, got {res.status_code}"
                assert "text/event-stream" in res.headers.get("content-type", "")
                assert res.headers.get("X-RateLimit-Limit") == "5"
                expected_remaining = str(5 - 1 - i)
                assert res.headers.get("X-RateLimit-Remaining") == expected_remaining

    @pytest.mark.asyncio
    async def test_anonymous_visitor_blocks_6th_query_with_429_and_retry_after(self, mock_pipeline_fast):
        """Anonymous visitor's 6th query returns HTTP 429 with uniform error and headers."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client_ip = "198.51.100.11"
            headers = {"X-Forwarded-For": client_ip}

            # Exhaust quota of 5 queries
            for i in range(5):
                res = await client.post("/chat", headers=headers, json={"query": f"anime query {i}"})
                assert res.status_code == 200

            # 6th query MUST trigger 429 Too Many Requests
            res6 = await client.post("/chat", headers=headers, json={"query": "one query too many"})
            assert res6.status_code == 429

            # Validate uniform JSON error envelope
            data = res6.json()
            assert "error" in data
            assert data["error"]["code"] == "rate_limit_exceeded"
            assert "Rate limit exceeded" in data["error"]["message"]

            # Validate headers
            assert "Retry-After" in res6.headers
            retry_after = int(res6.headers["Retry-After"])
            assert 0 < retry_after <= 900
            assert res6.headers.get("X-RateLimit-Limit") == "5"
            assert res6.headers.get("X-RateLimit-Remaining") == "0"
            assert res6.headers.get("X-RateLimit-Reset") == str(retry_after)

    @pytest.mark.asyncio
    async def test_anonymous_rate_limit_is_isolated_per_client_ip(self, mock_pipeline_fast):
        """Exhausting quota on IP A does not throttle a separate client IP B."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ip_a = "198.51.100.21"
            ip_b = "198.51.100.22"

            # Exhaust IP A (5 queries)
            for i in range(5):
                r = await client.post("/chat", headers={"X-Forwarded-For": ip_a}, json={"query": "test query"})
                assert r.status_code == 200

            # IP A is blocked
            blocked_res = await client.post("/chat", headers={"X-Forwarded-For": ip_a}, json={"query": "blocked"})
            assert blocked_res.status_code == 429

            # IP B is fresh and succeeds
            fresh_res = await client.post("/chat", headers={"X-Forwarded-For": ip_b}, json={"query": "fresh"})
            assert fresh_res.status_code == 200
            assert fresh_res.headers.get("X-RateLimit-Remaining") == "4"


# =============================================================================
# SUITE 2: AUTHENTICATED SUPABASE USER TIER (20 queries / 1 hour per user ID)
# =============================================================================

class TestAuthenticatedUserTierRateLimit:
    """Verifies authenticated Supabase user sliding window rate limiting (20 queries / 1 hour per user ID)."""

    @pytest.mark.asyncio
    async def test_authenticated_user_allows_20_queries_within_1_hour(self, mock_pipeline_fast, setup_test_environment):
        """Authenticated user successfully makes 20 queries within 1 hour."""
        mock_jwks = setup_test_environment
        user_id = "user_auth_sprint9_001"
        jwt_token = "valid-supabase-jwt-token-001"
        mock_jwks.register(jwt_token, DevUserContext(
            user_id=user_id,
            email="otaku@example.com",
            role="authenticated",
            iat=int(time.time()),
            app_metadata={"provider": "email", "role": "user"},
        ))

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {jwt_token}"}

            for i in range(20):
                res = await client.post(
                    "/chat",
                    headers=headers,
                    json={"query": f"recommend me fantasy anime query {i}"},
                )
                assert res.status_code == 200, f"Query {i + 1} should succeed, got {res.status_code}"
                assert res.headers.get("X-RateLimit-Limit") == "20"
                expected_remaining = str(20 - 1 - i)
                assert res.headers.get("X-RateLimit-Remaining") == expected_remaining

    @pytest.mark.asyncio
    async def test_authenticated_user_blocks_21st_query_with_429(self, mock_pipeline_fast, setup_test_environment):
        """Authenticated user's 21st query returns HTTP 429 with 1-hour window retry-after."""
        mock_jwks = setup_test_environment
        user_id = "user_auth_sprint9_002"
        jwt_token = "valid-supabase-jwt-token-002"
        mock_jwks.register(jwt_token, DevUserContext(
            user_id=user_id,
            email="otaku2@example.com",
            role="authenticated",
            iat=int(time.time()),
            app_metadata={"provider": "email", "role": "user"},
        ))

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {jwt_token}"}

            # Exhaust quota of 20 queries
            for i in range(20):
                res = await client.post("/chat", headers=headers, json={"query": f"query {i}"})
                assert res.status_code == 200

            # 21st query MUST trigger 429 Too Many Requests
            res21 = await client.post("/chat", headers=headers, json={"query": "21st over quota"})
            assert res21.status_code == 429

            # Validate uniform JSON envelope
            data = res21.json()
            assert "error" in data
            assert data["error"]["code"] == "rate_limit_exceeded"
            assert "Rate limit exceeded" in data["error"]["message"]

            # Validate headers
            assert "Retry-After" in res21.headers
            retry_after = int(res21.headers["Retry-After"])
            assert 0 < retry_after <= 3600
            assert res21.headers.get("X-RateLimit-Limit") == "20"
            assert res21.headers.get("X-RateLimit-Remaining") == "0"
            assert res21.headers.get("X-RateLimit-Reset") == str(retry_after)

    @pytest.mark.asyncio
    async def test_authenticated_rate_limit_is_isolated_per_user_id(self, mock_pipeline_fast, setup_test_environment):
        """Quota consumption on User A does not throttle a separate User B on the same IP."""
        mock_jwks = setup_test_environment
        token_a = "token-user-a"
        token_b = "token-user-b"
        mock_jwks.register(token_a, DevUserContext("usr_a", "a@test.com", "authenticated", int(time.time()), {}))
        mock_jwks.register(token_b, DevUserContext("usr_b", "b@test.com", "authenticated", int(time.time()), {}))

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Same IP for both users
            same_ip_header = {"X-Forwarded-For": "198.51.100.50"}

            # Exhaust User A (20 queries)
            for i in range(20):
                r = await client.post(
                    "/chat",
                    headers={"Authorization": f"Bearer {token_a}", **same_ip_header},
                    json={"query": "test query"},
                )
                assert r.status_code == 200

            # User A is blocked
            res_blocked = await client.post(
                "/chat",
                headers={"Authorization": f"Bearer {token_a}", **same_ip_header},
                json={"query": "blocked"},
            )
            assert res_blocked.status_code == 429

            # User B on the SAME IP is NOT blocked
            res_user_b = await client.post(
                "/chat",
                headers={"Authorization": f"Bearer {token_b}", **same_ip_header},
                json={"query": "user b query"},
            )
            assert res_user_b.status_code == 200
            assert res_user_b.headers.get("X-RateLimit-Remaining") == "19"

    @pytest.mark.asyncio
    async def test_invalid_or_expired_supabase_token_returns_401(self, mock_pipeline_fast):
        """Invalid or expired Supabase JWT returns HTTP 401 Unauthorized."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Unknown / invalid signature token
            res_invalid = await client.post(
                "/chat",
                headers={"Authorization": "Bearer unrecognized-jwt-token"},
                json={"query": "action anime"},
            )
            assert res_invalid.status_code == 401
            assert res_invalid.json()["error"]["code"] == "invalid_token"

            # Expired token
            res_expired = await client.post(
                "/chat",
                headers={"Authorization": "Bearer expired-token-sample"},
                json={"query": "action anime"},
            )
            assert res_expired.status_code == 401
            assert res_expired.json()["error"]["code"] == "token_expired"


# =============================================================================
# SUITE 3: DEVELOPER API KEYS BACKWARD COMPATIBILITY
# =============================================================================

class TestDeveloperApiKeyBackwardCompatibility:
    """Verifies developer API key support (access_token, x-api-key, Bearer ar_live_... / MY_API_KEY)."""

    @pytest.mark.asyncio
    async def test_developer_key_via_access_token_header(self, mock_pipeline_fast):
        """Developer key via legacy access_token header authenticates successfully."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/chat",
                headers={"access_token": "test-secret-sprint9-devkey"},
                json={"query": "cyberpunk anime"},
            )
            assert res.status_code == 200
            assert "text/event-stream" in res.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_developer_key_via_authorization_bearer(self, mock_pipeline_fast):
        """Developer key via Authorization: Bearer <MY_API_KEY> authenticates successfully."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/chat",
                headers={"Authorization": "Bearer test-secret-sprint9-devkey"},
                json={"query": "cyberpunk anime"},
            )
            assert res.status_code == 200
            assert "text/event-stream" in res.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_invalid_developer_key_returns_401(self, mock_pipeline_fast):
        """Invalid developer key via access_token returns 401 Unauthorized."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/chat",
                headers={"access_token": "wrong-dev-key-123"},
                json={"query": "cyberpunk anime"},
            )
            assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_developer_key_enforces_rate_limiting(self, mock_pipeline_fast):
        """Developer key quota exhaustion triggers HTTP 429."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            dev_key = "test-secret-sprint9-devkey"
            # Consume all 20 default per-min tokens in rate limiter for this key
            for _ in range(20):
                rate_limiter.requests[dev_key].append(time.time())

            # 21st request triggers 429
            res = await client.post(
                "/chat",
                headers={"access_token": dev_key},
                json={"query": "action anime"},
            )
            assert res.status_code == 429
            assert res.json()["error"]["code"] == "rate_limit_exceeded"


# =============================================================================
# SUITE 4: NEGATIVE GENRE CONSTRAINTS (disliked_genres)
# =============================================================================

class TestDislikedGenresFiltering:
    """Verifies ChatRequest disliked_genres parameter filtering and metadata propagation."""

    @pytest.mark.asyncio
    async def test_disliked_genres_filters_matching_candidate_cards(self, mock_pipeline_fast):
        """Candidate anime matching disliked_genres are excluded from SSE metadata event."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # We want to avoid Mecha and Horror:
            # Candidates in mock:
            # 101: Gundam (Mecha, Action) -> MUST be filtered out
            # 102: Steins;Gate (Sci-Fi, Thriller) -> MUST remain
            # 103: Another (Horror, Mystery) -> MUST be filtered out
            # 104: KonoSuba (Adventure, Comedy, Fantasy) -> MUST remain
            payload = {
                "query": "recommend great anime with gripping story",
                "disliked_genres": ["Mecha", "Horror"],
            }
            res = await client.post("/chat", json=payload)
            assert res.status_code == 200

            # Parse SSE lines
            metadata_event = None
            for line in res.text.split("\n"):
                if line.startswith("data: ") and '"candidates":' in line:
                    metadata_event = json.loads(line[6:])
                    break

            assert metadata_event is not None, "SSE metadata event must be present"
            remaining_ids = [c["id"] for c in metadata_event["candidates"]]

            # Candidates 101 (Mecha) and 103 (Horror) MUST be excluded
            assert 101 not in remaining_ids
            assert 103 not in remaining_ids

            # Candidates 102 (Steins;Gate) and 104 (KonoSuba) MUST remain
            assert 102 in remaining_ids
            assert 104 in remaining_ids

            # Active avoid_genres in metadata payload
            assert "Mecha" in metadata_event["avoid_genres"]
            assert "Horror" in metadata_event["avoid_genres"]

    @pytest.mark.asyncio
    async def test_disliked_genres_case_insensitive_matching(self, mock_pipeline_fast):
        """Negative genre matching is strictly case-insensitive."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "query": "recommend anime",
                "disliked_genres": ["mecha", "HORROR"],
            }
            res = await client.post("/chat", json=payload)
            assert res.status_code == 200

            metadata_event = None
            for line in res.text.split("\n"):
                if line.startswith("data: ") and '"candidates":' in line:
                    metadata_event = json.loads(line[6:])
                    break

            assert metadata_event is not None
            remaining_ids = [c["id"] for c in metadata_event["candidates"]]
            assert 101 not in remaining_ids
            assert 103 not in remaining_ids
            assert 102 in remaining_ids

    @pytest.mark.asyncio
    async def test_disliked_genres_merged_with_nli_avoid_genres(self, mock_pipeline_fast):
        """Request disliked_genres are merged with NLI avoid_genres deduplicated case-insensitively."""
        # Mock NLI parser to return avoid_genres=["Horror", "comedy"]
        mock_nli = MagicMock()
        mock_nli.parse_async = AsyncMock(return_value=NLIOutput(
            standalone_query="recommend great anime",
            avoid_genres=["Horror", "comedy"],
            intent="refine",
        ))

        # Request disliked_genres has ["horror", "Mecha"]
        # Merged list should be deduplicated: ["horror", "Mecha", "comedy"]
        orch = PipelineOrchestrator(
            retrieval_func=orchestrator._retrieval_func,
            synthesizer=orchestrator.synthesizer,
            nli_parser=mock_nli,
        )

        history = [{"role": "user", "content": "I want anime"}]
        events = []
        async for sse in orch.stream_chat(
            query="give me something similar instead",
            conversation_history=history,
            avoid_genres=["horror", "Mecha"],
        ):
            events.append(sse)

        meta_event = next(e for e in events if "event: metadata" in e)
        meta_json = json.loads(meta_event.split("data: ")[1])

        # Verify active avoid_genres
        norm_active = [g.lower() for g in meta_json["avoid_genres"]]
        assert "horror" in norm_active
        assert "mecha" in norm_active
        assert "comedy" in norm_active
        # Deduplication check: "horror" appears only once
        assert norm_active.count("horror") == 1

        # Candidates filtered:
        # 101: Mecha -> filtered
        # 103: Horror -> filtered
        # 104: Comedy -> filtered
        # 102: Steins;Gate -> retained
        remaining_ids = [c["id"] for c in meta_json["candidates"]]
        assert 101 not in remaining_ids
        assert 103 not in remaining_ids
        assert 104 not in remaining_ids
        assert 102 in remaining_ids


# =============================================================================
# SUITE 5: UNIFORM 429 ERROR ENVELOPE & RETRY-AFTER COUNTDOWN HEADERS
# =============================================================================

class TestRateLimitEnvelopeAndCountdown:
    """Verifies HTTP 429 uniform JSON envelope and countdown header accuracy."""

    @pytest.mark.asyncio
    async def test_uniform_429_error_envelope_schema(self, mock_pipeline_fast):
        """HTTP 429 responses match the uniform API error schema."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-Forwarded-For": "198.51.100.99"}

            # Exhaust anonymous quota (5)
            for _ in range(5):
                await client.post("/chat", headers=headers, json={"query": "test query"})

            res = await client.post("/chat", headers=headers, json={"query": "overflow"})
            assert res.status_code == 429

            body = res.json()
            assert isinstance(body, dict)
            assert "error" in body
            assert body["error"]["code"] == "rate_limit_exceeded"
            assert body["error"]["message"] == "Rate limit exceeded. Try again later."
            assert body["detail"] == "Rate limit exceeded. Try again later."

    @pytest.mark.asyncio
    async def test_retry_after_countdown_reflects_sliding_window_progress(self, mock_pipeline_fast):
        """Retry-After header counts down as time advances toward window expiration."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client_ip = "198.51.100.88"
            headers = {"X-Forwarded-For": client_ip}
            key = f"ratelimit:chat:anon:{client_ip}"

            now = time.time()
            # Simulate 5 requests placed at 'now'
            rate_limiter.requests[key] = [now] * 5

            # Immediate 6th request: Retry-After should be ~900s
            res_immediate = await client.post("/chat", headers=headers, json={"query": "overflow 1"})
            assert res_immediate.status_code == 429
            retry_immediate = int(res_immediate.headers["Retry-After"])
            assert 895 <= retry_immediate <= 900

            # Simulate 300 seconds passing: shift the recorded timestamps back by 300s
            rate_limiter.requests[key] = [now - 300] * 5

            # Subsequent request: Retry-After should have counted down by ~300s (approx 600s remaining)
            res_later = await client.post("/chat", headers=headers, json={"query": "overflow 2"})
            assert res_later.status_code == 429
            retry_later = int(res_later.headers["Retry-After"])
            assert 595 <= retry_later <= 601
            assert retry_later < retry_immediate
            assert res_later.headers["X-RateLimit-Reset"] == str(retry_later)
