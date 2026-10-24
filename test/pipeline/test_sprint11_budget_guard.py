"""
test/pipeline/test_sprint11_budget_guard.py

Sprint 11 Task 11.1 Verification Test Suite:
1. Redis Budget Key Convention:
   - Validates key structure `usage:{layer}:{YYYY-MM-DD}` across layers ("nli", "retrieval", "presentation").
   - Validates UTC default date format and invalid layer rejection.
2. Atomic Increment & Usage Tracking:
   - Verifies usage accumulation, layer isolation, and date isolation.
   - Verifies check_budget_status status reporting.
3. Soft Limit Warning & Hard Limit Ceiling:
   - Verifies 80% soft limit warning trigger.
   - Verifies 100% hard limit ceiling trigger.
4. NLI Graceful Degradation:
   - When NLI budget is exceeded, NLIParser bypasses query rewrite
     and passes the raw user query directly ($0 NLI tokens).
   - Orchestrator and QueryGenerator (HyDE) degradation are covered end-to-end in test_sprint11_smoke.py.
5. Presentation Graceful Degradation:
   - When presentation budget is exceeded, RecommendationSynthesizer skips OpenAI
     streaming and yields deterministic fallback pitch ($0 presentation tokens).
   - Orchestrator delivers candidate anime cards in metadata event and fallback pitch in token events.
6. Redis Timeout & Fallback Resilience:
   - Redis operations exceeding 150ms timeout cleanly fall back to InMemoryBudgetStore.
   - Redis network exceptions (ConnectionError) fall back cleanly without raising 500 or crashing.
   - Test isolation via budget_guard.reset().
"""

import os
import sys
import time
import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.rag_pipeline.helper.budget_guard import (
    BudgetGuard,
    InMemoryBudgetStore,
    budget_guard,
    get_budget_key,
    DEFAULT_DAILY_TOKEN_LIMITS,
    DEFAULT_USAGE_KEY_TTL_SEC,
    DEFAULT_REDIS_TIMEOUT_SEC,
)
from backend.rag_pipeline.helper.nli_parser import NLIParser
from backend.rag_pipeline.helper.synthesizer import RecommendationSynthesizer
from backend.rag_pipeline.orchestrator import PipelineOrchestrator


@pytest.fixture(autouse=True)
def reset_budget_state():
    """Resets budget guard in-memory state before and after each test."""
    budget_guard.reset()
    yield
    budget_guard.reset()


# =============================================================================
# PART 1: REDIS KEY STRUCTURE & DATE CONVENTIONS
# =============================================================================

class TestBudgetKeyFormatting:
    """Verifies Redis key structure: usage:{layer}:{YYYY-MM-DD}."""

    def test_key_structure_with_explicit_date(self):
        assert get_budget_key("nli", "2026-10-22") == "usage:nli:2026-10-22"
        assert get_budget_key("retrieval", "2026-10-22") == "usage:retrieval:2026-10-22"
        assert get_budget_key("presentation", "2026-10-22") == "usage:presentation:2026-10-22"
        # Omitting the date defaults to today in UTC
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert get_budget_key("nli") == f"usage:nli:{today_utc}"

    def test_invalid_layer_raises_value_error(self):
        with pytest.raises(ValueError) as excinfo:
            get_budget_key("invalid_layer")
        assert "Invalid layer" in str(excinfo.value)


# =============================================================================
# PART 2: ATOMIC INCREMENT & USAGE TRACKING
# =============================================================================

class TestAtomicIncrementAndUsageTracking:
    """Verifies atomic increment, cumulative usage, and layer isolation."""

    @pytest.mark.asyncio
    async def test_atomic_increment_in_memory(self):
        bg = BudgetGuard()  # In-memory mode (no redis url/token)
        layer = "nli"
        date_str = "2026-10-22"

        # Initially 0
        initial = await bg.get_usage(layer, date_str)
        assert initial == 0

        # Increment by 350
        u1 = await bg.record_usage(layer, 350, date_str)
        assert u1 == 350
        assert await bg.get_usage(layer, date_str) == 350

        # Increment by 150
        u2 = await bg.record_usage(layer, 150, date_str)
        assert u2 == 500
        assert await bg.get_usage(layer, date_str) == 500

    @pytest.mark.asyncio
    async def test_per_layer_isolation(self):
        bg = BudgetGuard()
        date_str = "2026-10-22"

        await bg.record_usage("nli", 100, date_str)
        await bg.record_usage("retrieval", 250, date_str)
        await bg.record_usage("presentation", 400, date_str)

        assert await bg.get_usage("nli", date_str) == 100
        assert await bg.get_usage("retrieval", date_str) == 250
        assert await bg.get_usage("presentation", date_str) == 400

    @pytest.mark.asyncio
    async def test_date_isolation(self):
        bg = BudgetGuard()
        layer = "retrieval"

        await bg.record_usage(layer, 300, "2026-10-21")
        await bg.record_usage(layer, 500, "2026-10-22")

        assert await bg.get_usage(layer, "2026-10-21") == 300
        assert await bg.get_usage(layer, "2026-10-22") == 500

    @pytest.mark.asyncio
    async def test_check_budget_status_details(self, monkeypatch):
        monkeypatch.setenv("DAILY_TOKEN_LIMIT_NLI", "1000")
        monkeypatch.setenv("BUDGET_SOFT_LIMIT_RATIO", "0.8")
        bg = BudgetGuard()
        date_str = "2026-10-22"

        await bg.record_usage("nli", 450, date_str)
        status = await bg.check_budget_status("nli", date_str)

        assert status["layer"] == "nli"
        assert status["date"] == date_str
        assert status["current_usage"] == 450
        assert status["daily_limit"] == 1000
        assert status["soft_limit"] == 800
        assert status["remaining"] == 550
        assert status["percentage"] == 45.0
        assert not status["is_exceeded"]
        assert not status["is_soft_limit_exceeded"]


# =============================================================================
# PART 3: SOFT LIMIT WARNING & HARD CEILING
# =============================================================================

class TestSoftAndHardLimits:
    """Verifies soft limit warning (80%) and hard limit ceiling (100%)."""

    @pytest.mark.asyncio
    async def test_soft_limit_warning_trigger(self, monkeypatch, caplog):
        monkeypatch.setenv("DAILY_TOKEN_LIMIT_NLI", "1000")
        monkeypatch.setenv("BUDGET_SOFT_LIMIT_RATIO", "0.8")
        bg = BudgetGuard()
        date_str = "2026-10-22"

        with caplog.at_level(logging.WARNING):
            # Record 799 (under 80% soft limit)
            await bg.record_usage("nli", 799, date_str)
            assert not any("SOFT LIMIT REACHED" in m for m in caplog.messages)

            # Record 1 (reaches 800 -> 80% soft limit)
            await bg.record_usage("nli", 1, date_str)
            assert any("SOFT LIMIT REACHED" in m for m in caplog.messages)
            assert not await bg.is_budget_exceeded("nli", date_str)

    @pytest.mark.asyncio
    async def test_hard_limit_ceiling_trigger(self, monkeypatch, caplog):
        monkeypatch.setenv("DAILY_TOKEN_LIMIT_RETRIEVAL", "1000")
        bg = BudgetGuard()
        date_str = "2026-10-22"

        with caplog.at_level(logging.WARNING):
            await bg.record_usage("retrieval", 999, date_str)
            assert not await bg.is_budget_exceeded("retrieval", date_str)

            # Reaches 1000 -> hard limit
            await bg.record_usage("retrieval", 1, date_str)
            assert await bg.is_budget_exceeded("retrieval", date_str)
            assert any("HARD LIMIT REACHED" in m for m in caplog.messages)


# =============================================================================
# PART 4: NLI LAYER GRACEFUL DEGRADATION
# =============================================================================

class TestNLIGracefulDegradation:
    """Verifies zero-token degradation for NLI when budget ceiling is exceeded."""

    @pytest.mark.asyncio
    async def test_nli_parser_bypasses_llm_when_budget_exceeded(self, monkeypatch):
        monkeypatch.setenv("DAILY_TOKEN_LIMIT_NLI", "100")
        budget_guard.reset()

        # Exhaust NLI daily budget
        await budget_guard.record_usage("nli", 100)
        assert await budget_guard.is_budget_exceeded("nli")

        mock_async_client = MagicMock()
        parser = NLIParser(async_client=mock_async_client)

        result = await parser.parse_async(
            query="tell me more about that one",
            history=[{"role": "user", "content": "cyberpunk anime"}],
        )

        # Must return raw user query directly without calling OpenAI
        assert result.standalone_query == "tell me more about that one"
        assert result.intent == "new_search"
        mock_async_client.beta.chat.completions.parse.assert_not_called()

# =============================================================================
# PART 5: PRESENTATION LAYER GRACEFUL DEGRADATION
# =============================================================================

class TestPresentationGracefulDegradation:
    """Verifies deterministic fallback pitch and candidate cards when presentation budget is exceeded."""

    @pytest.mark.asyncio
    async def test_synthesizer_yields_fallback_pitch_when_budget_exceeded(self, monkeypatch):
        monkeypatch.setenv("DAILY_TOKEN_LIMIT_PRESENTATION", "300")
        budget_guard.reset()

        await budget_guard.record_usage("presentation", 300)
        assert await budget_guard.is_budget_exceeded("presentation")

        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock()

        synthesizer = RecommendationSynthesizer(async_client=mock_async_client)
        candidates = [
            {"id": 1, "title_userPreferred": "Death Note", "averageScore": 90, "genres": ["Mystery", "Thriller"]}
        ]

        chunks = []
        async for chunk in synthesizer.stream_pitch(query="mind games", candidates=candidates):
            chunks.append(chunk)

        full_pitch = "".join(chunks)
        # Should contain Death Note and formatted fallback pitch
        assert "Death Note" in full_pitch
        # OpenAI client should NOT have been called
        mock_async_client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_orchestrator_presentation_degradation_delivers_cards_and_fallback(self, monkeypatch):
        monkeypatch.setenv("DAILY_TOKEN_LIMIT_PRESENTATION", "300")
        budget_guard.reset()
        await budget_guard.record_usage("presentation", 300)

        mock_retrieval = AsyncMock(return_value=([
            {"id": 10, "title_userPreferred": "Monster", "averageScore": 91, "genres": ["Drama", "Mystery"]}
        ], {"retrieval_ms": 12.0}))

        mock_synthesizer = RecommendationSynthesizer(async_client=MagicMock())
        # Ensure OpenAI chat is never called
        mock_synthesizer.async_client.chat.completions.create = AsyncMock()

        orchestrator = PipelineOrchestrator(
            retrieval_func=mock_retrieval,
            synthesizer=mock_synthesizer,
        )

        metadata_received = False
        token_texts = []

        async for sse_chunk in orchestrator.stream_chat(query="psychological masterpieces"):
            if "event: metadata" in sse_chunk:
                metadata_received = True
                assert "Monster" in sse_chunk
            elif "event: token" in sse_chunk:
                token_texts.append(sse_chunk)

        assert metadata_received, "Metadata event with anime cards must be delivered instantly"
        assert len(token_texts) > 0, "Deterministic fallback tokens must be streamed"
        mock_synthesizer.async_client.chat.completions.create.assert_not_called()


# =============================================================================
# PART 6: REDIS TIMEOUT & FALLBACK STORE RESILIENCE
# =============================================================================

class TestRedisResilienceAndTimeoutFallback:
    """Verifies 150ms timeout and transparent fallback to InMemoryBudgetStore."""

    @pytest.mark.asyncio
    async def test_redis_timeout_activates_fallback_without_raising(self, caplog):
        mock_redis = AsyncMock()

        async def _slow_incrby(*args, **kwargs):
            await asyncio.sleep(0.3)  # Exceeds 150ms timeout
            return 9999

        mock_redis.incrby = AsyncMock(side_effect=_slow_incrby)
        mock_redis.get = AsyncMock(side_effect=_slow_incrby)

        bg = BudgetGuard(
            redis_client=mock_redis,
            timeout=DEFAULT_REDIS_TIMEOUT_SEC,
        )

        with caplog.at_level(logging.WARNING):
            # Must complete without throwing asyncio.TimeoutError
            total = await bg.record_usage("retrieval", 250, "2026-10-22")
            assert total == 250
            # Warning should indicate timeout and fallback activation
            assert any("timed out" in m and "Activating fallback store" in m for m in caplog.messages)

        # Subsequent in-memory check works seamlessly
        usage = await bg.get_usage("retrieval", "2026-10-22")
        assert usage == 250

    @pytest.mark.asyncio
    async def test_redis_connection_error_activates_fallback_without_raising(self, caplog):
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = ConnectionError("Upstash REST API network partition")

        bg = BudgetGuard(
            redis_client=mock_redis,
            timeout=DEFAULT_REDIS_TIMEOUT_SEC,
        )

        with caplog.at_level(logging.WARNING):
            usage = await bg.get_usage("nli", "2026-10-22")
            assert usage == 0
            assert any("failed with ConnectionError" in m for m in caplog.messages)

    @pytest.mark.asyncio
    async def test_redis_atomic_increment_and_ttl_set(self):
        mock_redis = AsyncMock()
        mock_redis.incrby = AsyncMock(return_value=1250)
        mock_redis.expire = AsyncMock(return_value=1)

        bg = BudgetGuard(
            redis_client=mock_redis,
            timeout=DEFAULT_REDIS_TIMEOUT_SEC,
            ttl_seconds=DEFAULT_USAGE_KEY_TTL_SEC,
        )

        total = await bg.record_usage("presentation", 250, "2026-10-22")
        assert total == 1250
        mock_redis.incrby.assert_called_once_with("usage:presentation:2026-10-22", 250)
        mock_redis.expire.assert_called_once_with("usage:presentation:2026-10-22", DEFAULT_USAGE_KEY_TTL_SEC)
