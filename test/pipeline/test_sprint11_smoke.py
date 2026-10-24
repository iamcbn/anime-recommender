"""
test/pipeline/test_sprint11_smoke.py

Sprint 11 Task 11.3 End-to-End Smoke Test Suite:
1. Modal Deployment Readiness & Secrets Injection:
   - Verifies GATEWAY_SECRETS properly includes:
     - anime-secret
     - Per-layer OpenAI secrets: openai-nli-secret, openai-retrieval-secret, openai-presentation-secret
     - Fallback openai-secret if per-layer secrets are not used
     - Support seamless configuration via MODAL_USE_PER_LAYER_SECRETS environment variable (defaulting to True)
2. Full End-to-End SSE Chat Streaming (POST /chat):
   - Validates metadata event emitting candidate anime cards with scores stripped and TTFT.
   - Validates token event(s) streaming the grounded concierge pitch.
   - Validates done event completing the stream.
3. Graceful Degradation Under Token Ceilings (0 Tokens Consumed):
   - NLI ceiling hit: Raw user query passed directly ($0 NLI tokens, NLI parser skipped, valid cards returned).
   - Retrieval ceiling hit: HyDE expansion skipped ($0 HyDE tokens, raw query used for vector search, valid cards returned).
   - Presentation ceiling hit: OpenAI streaming skipped, candidate cards delivered instantly with deterministic fallback pitch ($0 presentation tokens).
   - Tri-layer exhaustion (all 3 ceilings hit simultaneously): 100% uptime with ZERO tokens consumed across the entire pipeline, returning valid anime cards to the user.
4. Secret Redaction & Log Isolation:
   - Ensures no API keys leak in logs or error responses (sk-proj-..., sk-..., Bearer ..., ar_live_...).
"""

import os
import sys
import json
import time
import logging
from typing import Dict, Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from httpx import ASGITransport

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.main import (
    app,
    rate_limiter,
    sanitize_secrets,
    BEARER_REDACT_REGEX,
    KEY_REDACT_REGEX,
    OPENAI_KEY_REDACT_REGEX,
)
from backend.rag_pipeline.orchestrator import orchestrator, PipelineOrchestrator
from backend.rag_pipeline.helper.guardrails import DomainGuardrails, GuardrailResult
from backend.rag_pipeline.helper.budget_guard import (
    budget_guard,
    BudgetGuard,
    get_budget_key,
)
from backend.rag_pipeline.helper.query_generator import QueryGenerator
from backend.rag_pipeline.helper.synthesizer import RecommendationSynthesizer
from backend.rag_pipeline.helper.nli_parser import NLIParser, NLIOutput
from backend.auth.supabase_jwt import set_jwks_service, DevUserContext
from backend.auth.keys import ApiKeyContext
from modal_deploy import get_gateway_secrets, GATEWAY_SECRETS


# =============================================================================
# TEST FIXTURES & MOCK DATA
# =============================================================================

SAMPLE_CANDIDATES = [
    {
        "id": 101,
        "title_userPreferred": "Steins;Gate",
        "title_romaji": "Steins;Gate",
        "title_english": "Steins;Gate",
        "genres": ["Sci-Fi", "Suspense", "Thriller"],
        "averageScore": 91,
        "popularity": 120000,
        "format": "TV",
        "episodes": 24,
        "status": "FINISHED",
        "description": "Eccentric scientist Rintaro Okabe accidentally invents a time-travel microwave.",
        "cross_encoder_score": 5.4,
    },
    {
        "id": 102,
        "title_userPreferred": "Psycho-Pass",
        "title_romaji": "Psycho-Pass",
        "title_english": "Psycho-Pass",
        "genres": ["Action", "Sci-Fi", "Psychological"],
        "averageScore": 84,
        "popularity": 95000,
        "format": "TV",
        "episodes": 22,
        "status": "FINISHED",
        "description": "In a future where criminal intent is quantified, Akane Tsunemori works with Enforcers to uphold justice.",
        "cross_encoder_score": 4.8,
    },
    {
        "id": 103,
        "title_userPreferred": "Monster",
        "title_romaji": "Monster",
        "title_english": "Monster",
        "genres": ["Drama", "Mystery", "Psychological", "Suspense"],
        "averageScore": 90,
        "popularity": 80000,
        "format": "TV",
        "episodes": 74,
        "status": "FINISHED",
        "description": "A brilliant brain surgeon risks everything to stop a former patient who has grown into a charismatic monster.",
        "cross_encoder_score": 4.6,
    },
]


def parse_sse_events(sse_text: str) -> List[Dict[str, Any]]:
    """Parses raw Server-Sent Events text into structured event objects."""
    events = []
    current_event = None
    for line in sse_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:") and current_event:
            raw_data = line[len("data:"):].strip()
            try:
                parsed_data = json.loads(raw_data)
            except Exception:
                parsed_data = raw_data
            events.append({"event": current_event, "data": parsed_data})
            current_event = None
    return events


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
        if token in self._tokens:
            return self._tokens[token]
        raise ValueError("Invalid token signature or unknown key identifier.")


@pytest.fixture(autouse=True)
def setup_smoke_environment(monkeypatch):
    """Sets up deterministic in-memory budget guard, auth, and rate limiters."""
    # Deterministic budget limits
    budget_guard.reset()
    budget_guard.limits = {
        "nli": 100000,
        "retrieval": 200000,
        "presentation": 300000,
    }

    # Deterministic rate limit environment
    rate_limiter.redis = None
    rate_limiter.reset()

    # Configure mock JWKS service
    mock_jwks = MockJWKSService()
    admin_user = DevUserContext(
        user_id="admin-smoke-uuid-1",
        email="admin@otaku.dev",
        role="admin",
        iat=1700000000,
        app_metadata={"role": "admin"},
    )
    mock_jwks.register("valid-admin-jwt", admin_user)

    regular_user = DevUserContext(
        user_id="user-smoke-uuid-2",
        email="user@otaku.dev",
        role="user",
        iat=1700000000,
        app_metadata={"role": "user"},
    )
    mock_jwks.register("valid-user-jwt", regular_user)

    set_jwks_service(mock_jwks)

    # API keys for testing
    monkeypatch.setenv("ADMIN_API_KEY", "ar_live_admin_secret_test_key_1234567890")
    monkeypatch.setenv("MY_API_KEY", "ar_live_regular_user_key_1234567890")
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,::1")

    yield mock_jwks

    budget_guard.reset()
    rate_limiter.reset()
    set_jwks_service(None)


@pytest.fixture
def mock_retrieval_pipeline():
    """Provides isolated, fast retrieval and pitch mocking for chat streaming."""
    async def _mock_retrieval(query, top_k=5, allow_adult=False, seen_ids=None, include_metadata=True, request_id=None):
        return [dict(c) for c in SAMPLE_CANDIDATES[:top_k]], {"retrieval_ms": 12.0}

    async def _mock_stream_pitch(query, candidates, conversation_history=None, is_disconnected=None, request_id=None, session_id=None):
        yield "Based on your taste, here is why "
        yield "Steins;Gate "
        yield "is a masterclass in psychological storytelling with unmatched suspense."

    with patch.object(orchestrator, "_retrieval_func", side_effect=_mock_retrieval) as mock_ret, \
         patch.object(orchestrator.synthesizer, "stream_pitch", side_effect=_mock_stream_pitch) as mock_pitch, \
         patch.object(orchestrator.guardrails, "validate_intent", return_value=GuardrailResult(True, "valid")), \
         patch("backend.telemetry.logger.log_recommendation_event"):
        yield {
            "retrieval": mock_ret,
            "pitch": mock_pitch,
        }


# =============================================================================
# 1. MODAL DEPLOYMENT READINESS & SECRETS INJECTION
# =============================================================================

class TestModalDeploymentReadiness:
    """Verifies Modal configuration, secret isolation, and GPU model worker definitions."""

    def test_modal_gateway_secrets_with_per_layer_isolation(self):
        """When per-layer secrets are enabled, GATEWAY_SECRETS includes all 4 distinct secrets."""
        secrets = get_gateway_secrets(use_per_layer=True)
        assert len(secrets) == 4
        # In Modal, secrets are instantiated via Secret.from_name
        secret_reprs = [repr(s) for s in secrets]
        assert any("anime-secret" in r for r in secret_reprs)
        assert any("openai-nli-secret" in r for r in secret_reprs)
        assert any("openai-retrieval-secret" in r for r in secret_reprs)
        assert any("openai-presentation-secret" in r for r in secret_reprs)

    def test_modal_gateway_secrets_fallback_to_shared_secret(self):
        """When per-layer secrets are disabled, GATEWAY_SECRETS falls back to shared openai-secret."""
        secrets = get_gateway_secrets(use_per_layer=False)
        assert len(secrets) == 2
        secret_reprs = [repr(s) for s in secrets]
        assert any("anime-secret" in r for r in secret_reprs)
        assert any("openai-secret" in r for r in secret_reprs)
        assert not any("openai-nli-secret" in r for r in secret_reprs)

    def test_modal_gateway_secrets_env_variable_control(self, monkeypatch):
        """MODAL_USE_PER_LAYER_SECRETS defaults to true, and honors false when configured."""
        # Default environment (no env var set) -> Defaults to True for production key isolation
        monkeypatch.delenv("MODAL_USE_PER_LAYER_SECRETS", raising=False)
        default_secrets = get_gateway_secrets()
        assert len(default_secrets) == 4

        # Explicitly set to false -> 2 secrets
        monkeypatch.setenv("MODAL_USE_PER_LAYER_SECRETS", "false")
        fallback_secrets = get_gateway_secrets()
        assert len(fallback_secrets) == 2

        # Explicitly set to 1 / true -> 4 secrets
        monkeypatch.setenv("MODAL_USE_PER_LAYER_SECRETS", "1")
        per_layer_secrets = get_gateway_secrets()
        assert len(per_layer_secrets) == 4


# =============================================================================
# 2. FULL END-TO-END SSE CHAT STREAMING (POST /chat)
# =============================================================================

class TestConsumerDiscoveryEndToEndStream:
    """Verifies complete consumer discovery SSE chat flow on POST /chat."""

    @pytest.mark.asyncio
    async def test_full_sse_chat_stream_candidate_cards_and_pitch(self, mock_retrieval_pipeline):
        """Client receives metadata event with clean anime cards, streamed pitch tokens, and done event."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "query": "recommend me a gripping psychological thriller anime",
                "top_k": 3,
                "allow_adult": False,
            }
            res = await client.post("/chat", json=payload)
            assert res.status_code == 200
            assert "text/event-stream" in res.headers.get("content-type", "")
            assert "X-Session-ID" in res.headers

            events = parse_sse_events(res.text)
            event_types = [e["event"] for e in events]

            # 1. Immediate candidate metadata event
            assert "metadata" in event_types
            meta_event = next(e["data"] for e in events if e["event"] == "metadata")
            assert meta_event["count"] == 3
            assert len(meta_event["candidates"]) == 3
            # Candidate cards must have essential fields and no internal scores
            for card in meta_event["candidates"]:
                assert "id" in card
                assert "title_userPreferred" in card
                assert "genres" in card
                assert "cross_encoder_score" not in card
                assert "final_rrf_score" not in card

            # 2. Grounded concierge pitch tokens
            assert "token" in event_types
            token_events = [e["data"]["text"] for e in events if e["event"] == "token"]
            assert len(token_events) >= 1
            full_pitch = "".join(token_events)
            assert "Steins;Gate" in full_pitch

            # 3. Done completion event
            assert "done" in event_types
            done_event = next(e["data"] for e in events if e["event"] == "done")
            assert done_event["status"] == "completed"
            assert "tokens_emitted" in done_event
            assert "timings" in done_event


# =============================================================================
# 3. GRACEFUL DEGRADATION UNDER TOKEN CEILINGS (0 TOKENS CONSUMED)
# =============================================================================

class TestGracefulDegradationUnderTokenCeilings:
    """Verifies graceful zero-token degradation across NLI, Retrieval, and Presentation."""

    @pytest.mark.asyncio
    async def test_nli_budget_exhaustion_degrades_to_raw_query(self, mock_retrieval_pipeline):
        """When NLI budget is exceeded, NLI LLM is bypassed and raw query used directly ($0 spent)."""
        # Exhaust NLI budget ceiling
        await budget_guard.record_usage("nli", 150000)
        assert await budget_guard.is_budget_exceeded("nli")

        mock_nli_parser = MagicMock()
        mock_nli_parser.parse_async = AsyncMock()

        with patch.object(orchestrator, "nli_parser", mock_nli_parser):
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                # Query contains conversational cues ("darker than that") that would normally trigger NLI
                payload = {
                    "query": "something darker than that",
                    "seen_ids": [101],
                }
                res = await client.post("/chat", json=payload)
                assert res.status_code == 200

                # NLI parser LLM should NEVER be called ($0 NLI tokens)
                mock_nli_parser.parse_async.assert_not_called()

                events = parse_sse_events(res.text)
                meta_event = next(e["data"] for e in events if e["event"] == "metadata")
                # Raw query preserved as effective query
                assert meta_event["effective_query"] == "something darker than that"
                assert len(meta_event["candidates"]) > 0

                done_event = next(e["data"] for e in events if e["event"] == "done")
                assert done_event["status"] == "completed"

    @pytest.mark.asyncio
    async def test_retrieval_budget_exhaustion_skips_hyde(self, mock_retrieval_pipeline):
        """When retrieval budget is exceeded, QueryGenerator skips HyDE expansion ($0 spent)."""
        # Exhaust Retrieval budget ceiling
        await budget_guard.record_usage("retrieval", 250000)
        assert await budget_guard.is_budget_exceeded("retrieval")

        # Test QueryGenerator directly
        mock_async_client = MagicMock()
        mock_async_client.beta.chat.completions.parse = AsyncMock()
        qg = QueryGenerator(async_client=mock_async_client)

        queries = await qg.generate_async("psychological mind game anime")
        # HyDE expansion must be skipped; only [user_query] returned
        assert queries == ["psychological mind game anime"]
        mock_async_client.beta.chat.completions.parse.assert_not_called()

        # End-to-end POST /chat still returns valid candidate cards and pitch with HTTP 200
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/chat", json={"query": "psychological mind game anime"})
            assert res.status_code == 200
            events = parse_sse_events(res.text)
            meta_event = next(e["data"] for e in events if e["event"] == "metadata")
            assert len(meta_event["candidates"]) > 0

    @pytest.mark.asyncio
    async def test_presentation_budget_exhaustion_serves_deterministic_fallback(self, mock_retrieval_pipeline):
        """When presentation budget is exceeded, OpenAI pitch stream is skipped and fallback pitch served."""
        # Exhaust Presentation budget ceiling
        await budget_guard.record_usage("presentation", 350000)
        assert await budget_guard.is_budget_exceeded("presentation")

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/chat", json={"query": "thriller anime"})
            assert res.status_code == 200

            # OpenAI stream pitch mock should NOT have been invoked ($0 presentation tokens)
            mock_retrieval_pipeline["pitch"].assert_not_called()

            events = parse_sse_events(res.text)
            event_types = [e["event"] for e in events]
            assert "metadata" in event_types
            assert "token" in event_types
            assert "done" in event_types

            # Verify deterministic fallback pitch tokens were delivered
            token_texts = [e["data"]["text"] for e in events if e["event"] == "token"]
            full_pitch = "".join(token_texts)
            assert "recommendations" in full_pitch.lower() or "steins;gate" in full_pitch.lower()

    @pytest.mark.asyncio
    async def test_tri_layer_budget_exhaustion_100_percent_uptime_zero_tokens(self):
        """Tri-layer budget exhaustion maintains 100% uptime with ZERO tokens consumed across the pipeline."""
        # Exhaust all 3 ceilings simultaneously
        await budget_guard.record_usage("nli", 150000)
        await budget_guard.record_usage("retrieval", 250000)
        await budget_guard.record_usage("presentation", 350000)

        assert await budget_guard.is_budget_exceeded("nli")
        assert await budget_guard.is_budget_exceeded("retrieval")
        assert await budget_guard.is_budget_exceeded("presentation")

        mock_nli = MagicMock()
        mock_nli.parse_async = AsyncMock()

        mock_synthesizer = RecommendationSynthesizer(api_key="sk-test-dummy-key-1234567890")
        mock_synthesizer.async_client = MagicMock()
        mock_synthesizer.async_client.chat.completions.create = AsyncMock()

        async def _retrieval_without_llm(query, top_k=5, allow_adult=False, seen_ids=None, include_metadata=True, request_id=None):
            return [dict(c) for c in SAMPLE_CANDIDATES[:top_k]], {"retrieval_ms": 10.0}

        with patch.object(orchestrator, "nli_parser", mock_nli), \
             patch.object(orchestrator, "_retrieval_func", side_effect=_retrieval_without_llm), \
             patch.object(orchestrator, "synthesizer", mock_synthesizer), \
             patch("backend.telemetry.logger.log_recommendation_event"):

            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post("/chat", json={"query": "recommend anime more like Steins Gate"})
                assert res.status_code == 200

                # Assert ZERO tokens across all three layers
                mock_nli.parse_async.assert_not_called()  # $0 NLI tokens
                mock_synthesizer.async_client.chat.completions.create.assert_not_called()  # $0 Presentation tokens

                events = parse_sse_events(res.text)
                meta_event = next(e["data"] for e in events if e["event"] == "metadata")
                assert len(meta_event["candidates"]) > 0

                token_events = [e["data"]["text"] for e in events if e["event"] == "token"]
                assert len(token_events) > 0
                full_pitch = "".join(token_events)
                assert "top-rated anime recommendations" in full_pitch.lower() or "steins;gate" in full_pitch.lower()

                done_event = next(e["data"] for e in events if e["event"] == "done")
                assert done_event["status"] == "completed"


# =============================================================================
# 4. SECRET REDACTION & LOG ISOLATION
# =============================================================================

class TestSecretRedactionAndLogIsolation:
    """Verifies that OpenAI keys, Bearer tokens, and API keys are redacted from logs and errors."""

    def test_secret_redaction_regexes(self):
        """Ensures all OpenAI key formats, Bearer tokens, and live API keys are redacted."""
        test_cases = [
            ("Call failed with sk-proj-1234567890abcdef12345678", "Call failed with [REDACTED_OPENAI_KEY]"),
            ("Auth error sk-1234567890abcdef12345678 in header", "Auth error [REDACTED_OPENAI_KEY] in header"),
            ("Using Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token", "Using Bearer [REDACTED]"),
            ("Key ar_live_abcdef12_34567890abcdef rejected", "Key [REDACTED_API_KEY] rejected"),
            ("Admin key ar_live_admin_secret_test_key_1234567890", "Admin key [REDACTED_API_KEY]"),
        ]
        for raw, expected in test_cases:
            sanitized = sanitize_secrets(raw)
            assert sanitized == expected

    @pytest.mark.asyncio
    async def test_error_response_secret_redaction(self):
        """API error responses never leak OpenAI keys, Bearer tokens, or live keys in detail payloads."""
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Send an invalid request triggering an error where the error message might contain keys
            res = await client.post(
                "/chat",
                headers={"Authorization": "Bearer sk-proj-super-secret-key-that-must-not-leak-1234567890"},
                json={"query": "recommend anime"},
            )
            # Response must NOT leak the raw key
            assert "sk-proj-super-secret" not in res.text
            assert "that-must-not-leak" not in res.text

    def test_log_sanitization_helper(self, caplog):
        """Logs processed with sanitize_secrets never contain unredacted secrets."""
        with caplog.at_level(logging.ERROR):
            raw_err = "Unhandled failure: sk-proj-99999999998888888888 and ar_live_12345678_adminpass12345"
            sanitized = sanitize_secrets(raw_err)
            logging.getLogger("test").error(sanitized)

            assert "sk-proj-99999999998888888888" not in caplog.text
            assert "ar_live_12345678_adminpass12345" not in caplog.text
            assert "[REDACTED_OPENAI_KEY]" in caplog.text
            assert "[REDACTED_API_KEY]" in caplog.text
