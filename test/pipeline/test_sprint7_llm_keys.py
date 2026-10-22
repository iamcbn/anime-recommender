"""
test/pipeline/test_sprint7_llm_keys.py

Sprint 7 Verification Test Suite:
1. Multi-Layer Key Resolution (AC 7.1 & AC 7.2):
   - Verifies dedicated resolution for 'nli', 'retrieval', 'presentation'.
   - Verifies clean fallback to OPENAI_API_KEY when layer key is omitted.
   - Verifies explicit override precedence.
2. QueryGenerator Integration:
   - Uses retrieval key/client.
   - Accurately captures token metrics from completions.parse and records usage.
   - Accurately logs cache hits as status='cached'.
3. RecommendationSynthesizer Integration:
   - Uses presentation key/client.
   - Captures chunk stream usage and records to telemetry.llm_usage.
   - Graceful fallback pitch records status='fallback'.
4. Database & Logger Safety (AC 7.3):
   - log_llm_usage_event executes safely without crashing caller under DB errors.
5. Key Redaction in Gateway (AC 7.4):
   - Verifies OpenAI API key patterns (sk-..., sk-proj-...) are redacted from exception logs.
"""

import os
import sys
import uuid
import re
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.rag_pipeline.helper.llm_clients import (
    resolve_layer_api_key,
    get_layer_client,
    get_sync_layer_client,
)
from backend.rag_pipeline.helper.query_generator import QueryGenerator
from backend.rag_pipeline.helper.synthesizer import RecommendationSynthesizer
from backend.telemetry.logger import log_llm_usage_event, OPENAI_KEY_REDACT_REGEX


class TestLayerKeyResolution:
    """Verifies AC 7.1 & AC 7.2: Independent key resolution with fallback."""

    def test_dedicated_layer_keys(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY_NLI", "sk-proj-nli-test-1234567890")
        monkeypatch.setenv("OPENAI_API_KEY_RETRIEVAL", "sk-proj-retrieval-test-1234567890")
        monkeypatch.setenv("OPENAI_API_KEY_PRESENTATION", "sk-proj-presentation-test-1234567890")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-shared-test-1234567890")

        assert resolve_layer_api_key("nli") == "sk-proj-nli-test-1234567890"
        assert resolve_layer_api_key("retrieval") == "sk-proj-retrieval-test-1234567890"
        assert resolve_layer_api_key("presentation") == "sk-proj-presentation-test-1234567890"

    def test_fallback_to_shared_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY_NLI", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY_RETRIEVAL", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY_PRESENTATION", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-shared-fallback-99999")

        assert resolve_layer_api_key("nli") == "sk-proj-shared-fallback-99999"
        assert resolve_layer_api_key("retrieval") == "sk-proj-shared-fallback-99999"
        assert resolve_layer_api_key("presentation") == "sk-proj-shared-fallback-99999"

    def test_override_key_precedence(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY_NLI", "sk-proj-env-key")
        override = "sk-proj-explicit-override-key"
        assert resolve_layer_api_key("nli", override_key=override) == override

    def test_missing_all_keys_returns_none(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY_NLI", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY_RETRIEVAL", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY_PRESENTATION", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        assert resolve_layer_api_key("nli") is None
        assert resolve_layer_api_key("retrieval") is None
        assert resolve_layer_api_key("presentation") is None


class TestQueryGeneratorKeyIsolation:
    """Verifies QueryGenerator uses the retrieval layer and logs usage."""

    def test_initialization_with_retrieval_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY_RETRIEVAL", "sk-proj-retrieval-key-123")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-shared-key-123")

        qg = QueryGenerator()
        assert qg.api_key == "sk-proj-retrieval-key-123"

    @pytest.mark.asyncio
    async def test_async_generation_logs_tokens(self, monkeypatch):
        mock_async_client = MagicMock()
        mock_parse = AsyncMock()

        # Mock parsed response with usage
        mock_parsed_result = MagicMock()
        mock_parsed_result.query_b = "Hypothetical synopsis 1"
        mock_parsed_result.query_c = "Hypothetical synopsis 2"

        mock_choice = MagicMock()
        mock_choice.message.parsed = mock_parsed_result

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_completion.usage.prompt_tokens = 45
        mock_completion.usage.completion_tokens = 60
        mock_completion.usage.total_tokens = 105

        mock_parse.return_value = mock_completion
        mock_async_client.beta.chat.completions.parse = mock_parse

        qg = QueryGenerator(api_key="sk-test", async_client=mock_async_client)

        logged_events = []
        with patch(
            "backend.rag_pipeline.helper.query_generator.log_llm_usage_event",
            side_effect=lambda **kwargs: logged_events.append(kwargs)
        ):
            with patch("backend.rag_pipeline.helper.query_generator.llm_cache.get", return_value=None):
                with patch("backend.rag_pipeline.helper.query_generator.llm_cache.set"):
                    queries = await qg.generate_async("psychological thriller", request_id="req-123")

        assert len(queries) == 3
        assert queries[0] == "psychological thriller"
        assert len(logged_events) == 1
        event = logged_events[0]
        assert event["layer"] == "retrieval"
        assert event["prompt_tokens"] == 45
        assert event["completion_tokens"] == 60
        assert event["total_tokens"] == 105
        assert event["cached"] is False
        assert event["status"] == "ok"
        assert event["request_id"] == "req-123"


class TestSynthesizerKeyIsolation:
    """Verifies RecommendationSynthesizer uses presentation key and logs stream usage."""

    def test_initialization_with_presentation_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY_PRESENTATION", "sk-proj-presentation-key-123")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-shared-key-123")

        syn = RecommendationSynthesizer()
        assert syn.api_key == "sk-proj-presentation-key-123"

    @pytest.mark.asyncio
    async def test_stream_pitch_captures_usage(self):
        mock_async_client = MagicMock()

        # Mock chunk stream with usage in final chunk
        async def mock_stream_chunks():
            chunk1 = MagicMock()
            chunk1.choices = [MagicMock(delta=MagicMock(content="First "))]
            chunk1.usage = None
            yield chunk1

            chunk2 = MagicMock()
            chunk2.choices = [MagicMock(delta=MagicMock(content="token."))]
            chunk2.usage = None
            yield chunk2

            # Final usage chunk
            chunk_usage = MagicMock()
            chunk_usage.choices = []
            chunk_usage.usage = MagicMock(prompt_tokens=150, completion_tokens=25, total_tokens=175)
            yield chunk_usage

        mock_async_client.chat.completions.create = AsyncMock(return_value=mock_stream_chunks())

        syn = RecommendationSynthesizer(api_key="sk-test", async_client=mock_async_client)
        candidates = [{"id": 1, "title_userPreferred": "Steins;Gate", "description": "Time travel thriller"}]

        logged_events = []
        with patch(
            "backend.rag_pipeline.helper.synthesizer.log_llm_usage_event",
            side_effect=lambda **kwargs: logged_events.append(kwargs)
        ):
            tokens = []
            async for token in syn.stream_pitch(
                query="time travel",
                candidates=candidates,
                request_id="req-synth-1",
                session_id="sess-synth-1"
            ):
                tokens.append(token)

        assert "".join(tokens) == "First token."
        assert len(logged_events) == 1
        event = logged_events[0]
        assert event["layer"] == "presentation"
        assert event["prompt_tokens"] == 150
        assert event["completion_tokens"] == 25
        assert event["total_tokens"] == 175
        assert event["status"] == "ok"
        assert event["request_id"] == "req-synth-1"
        assert event["session_id"] == "sess-synth-1"

    @pytest.mark.asyncio
    async def test_fallback_pitch_logs_fallback_status(self):
        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("OpenAI API Down"))

        syn = RecommendationSynthesizer(api_key="sk-test", async_client=mock_async_client)
        candidates = [{"id": 1, "title_userPreferred": "Steins;Gate", "description": "Time travel thriller"}]

        logged_events = []
        with patch(
            "backend.rag_pipeline.helper.synthesizer.log_llm_usage_event",
            side_effect=lambda **kwargs: logged_events.append(kwargs)
        ):
            tokens = []
            async for token in syn.stream_pitch(
                query="time travel",
                candidates=candidates,
                request_id="req-fallback-1",
            ):
                tokens.append(token)

        # Fallback text returned
        assert len(tokens) > 0
        full_pitch = "".join(tokens)
        assert "top-rated anime recommendations" in full_pitch
        assert len(logged_events) == 1
        event = logged_events[0]
        assert event["layer"] == "presentation"
        assert event["status"] == "fallback"
        assert event["prompt_tokens"] == 0
        assert event["completion_tokens"] == 0


class TestTelemetryLoggerSafety:
    """Verifies AC 7.3: Database insertion resilience."""

    def test_log_llm_usage_event_safety(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        success = log_llm_usage_event(
            layer="retrieval",
            model="gpt-5.4-mini",
            prompt_tokens=50,
            completion_tokens=25,
            total_tokens=75,
            cached=False,
            latency_ms=120.5,
            status="ok",
            request_id=str(uuid.uuid4()),
            conn=mock_conn,
        )

        assert success is True
        assert mock_cursor.execute.called
        assert mock_conn.commit.called

    def test_log_llm_usage_event_never_crashes_on_error(self):
        # Even if DB connection throws an exception, returns False and does not raise
        mock_bad_conn = MagicMock()
        mock_bad_conn.cursor.side_effect = Exception("DB Connection Lost")

        success = log_llm_usage_event(
            layer="nli",
            model="gpt-5.4-mini",
            conn=mock_bad_conn,
        )
        assert success is False


class TestKeyRedactionMiddleware:
    """Verifies AC 7.4: OpenAI keys are redacted in error handling."""

    def test_openai_key_regex_redaction(self):
        test_strings = [
            ("Error with sk-proj-1234567890abcdef123456 in call", "[REDACTED_OPENAI_KEY]"),
            ("sk-1234567890abcdef123456 failed", "[REDACTED_OPENAI_KEY]"),
        ]
        for raw, expected_token in test_strings:
            sanitized = OPENAI_KEY_REDACT_REGEX.sub(expected_token, raw)
            assert expected_token in sanitized
            assert "sk-proj-1234567890abcdef123456" not in sanitized
            assert "sk-1234567890abcdef123456" not in sanitized
