"""
test/pipeline/test_sprint8_nli.py

Sprint 8 Verification Test Suite:
1. Cost Safeguard Heuristic Skip Rule:
   - Turn 1 bypass: history is empty or None -> returns True ($0 spent, 0 LLM calls).
   - Standalone prompt bypass: turn 2+ with no conversational cues and long query -> returns True.
   - Conversational cues trigger: relative cues ("less", "similar", "more", "not") -> returns False.
   - Short ambiguous follow-ups trigger NLI -> returns False.
2. Follow-Up NLI Parsing:
   - Standalone query resolution, avoid_genres extraction, avoid_tropes extraction, intent classification.
   - Dependency injection of clients and model parameters (max_tokens=120, temp=0.1, timeout=3.0s).
3. Negative Constraint Filtering:
   - In-memory post-filtering candidate anime matching avoid_genres (case-insensitive).
   - Multi-format genres support (lists, stringified JSON, comma-separated strings).
   - Avoid tropes filtering on tags and descriptions.
4. NLI Timeout & Error Fallback:
   - Clean handling of 3.0s timeout and API exceptions.
   - Returns safe fallback NLIOutput(standalone_query=raw_query, intent="new_search").
   - Records status="fallback" to telemetry.
5. Token Usage Logging:
   - Usage events logged to telemetry.llm_usage with layer="nli", prompt/completion tokens, latency, status="ok".
6. Orchestrator Integration:
   - Step 2.5 NLI invocation, effective_query propagation into retrieval, and step 3.5 post-filtering.
"""

import os
import sys
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.rag_pipeline.helper.nli_parser import (
    NLIOutput,
    NLIParser,
    should_bypass_nli,
    CONVERSATIONAL_CUES_REGEX,
)
from backend.rag_pipeline.helper.ranking import (
    filter_candidates_by_negative_constraints,
    Ranker,
)
from backend.rag_pipeline.orchestrator import PipelineOrchestrator


# =============================================================================
# PART 1: HEURISTIC SKIP RULE TESTS (COST SAFEGUARD)
# =============================================================================

class TestHeuristicSkipRule:
    """Verifies AC 8.1: Heuristic bypass saves 100% LLM cost on Turn 1 & standalone queries."""

    def test_turn_1_bypass_empty_or_none_history(self):
        """Turn 1 queries must always bypass NLI ($0 cost)."""
        assert should_bypass_nli("psychological thriller with mystery", None) is True
        assert should_bypass_nli("psychological thriller with mystery", []) is True
        # Even queries with conversational-sounding words bypass if history is empty
        assert should_bypass_nli("Give me something similar to Death Note", None) is True
        assert should_bypass_nli("anime not too slow or boring", []) is True

    def test_turn_2_conversational_cues_trigger_nli(self):
        """Cues indicating conversational references or negative constraints must run NLI."""
        history = [
            {"role": "user", "content": "I like Monster and Death Note"},
            {"role": "assistant", "content": "Here is Psycho-Pass and Steins;Gate"},
        ]

        # Indicators tested: similar, less, more, another, instead, not, without, exclude, too, also, like that
        cue_queries = [
            "Give me something similar but less gory",
            "more like that one",
            "show me another recommendation instead",
            "not horror please",
            "something without romance",
            "exclude mecha from the suggestions",
            "that was too dark, give me something lighter",
            "also recommend me movies",
            "earlier one was better",
            "previous recommendation was great",
            "first one sounded interesting",
            "second one was awesome",
        ]

        for q in cue_queries:
            assert should_bypass_nli(q, history) is False, f"Query '{q}' should trigger NLI"

    def test_turn_2_long_standalone_query_bypasses(self):
        """If user enters a completely fresh, detailed query in turn 2, bypass NLI."""
        history = [
            {"role": "user", "content": "sports anime like Haikyuu"},
            {"role": "assistant", "content": "Here is Kuroko no Basket"},
        ]

        standalone_query = "I want a cyberpunk dystopian sci-fi anime with robots and neon city"
        assert should_bypass_nli(standalone_query, history) is True

    def test_turn_2_short_ambiguous_query_triggers_nli(self):
        """Short follow-up queries (<4 words, <20 chars) without cues should run NLI."""
        history = [{"role": "user", "content": "action"}]
        assert should_bypass_nli("comedy", history) is False
        assert should_bypass_nli("romance", history) is False


# =============================================================================
# PART 2: NLI PARSER & SCHEMA TESTS
# =============================================================================

class TestNLIParser:
    """Verifies structured output parsing, message construction, and model arguments."""

    def test_schema_defaults_and_validation(self):
        output = NLIOutput(
            standalone_query="psychological thriller anime",
            avoid_genres=["Horror", "Gore"],
            intent="refine",
        )
        assert output.standalone_query == "psychological thriller anime"
        assert output.avoid_genres == ["Horror", "Gore"]
        assert output.avoid_tropes == []
        assert output.intent == "refine"

    @pytest.mark.asyncio
    async def test_parse_async_success(self):
        mock_async_client = MagicMock()
        mock_completion = MagicMock()

        parsed_data = NLIOutput(
            standalone_query="psychological thriller with mystery and suspense",
            avoid_genres=["Horror", "Gore"],
            avoid_tropes=["jump scares"],
            intent="refine",
        )
        mock_completion.choices = [MagicMock(message=MagicMock(parsed=parsed_data))]
        mock_completion.usage = MagicMock(prompt_tokens=55, completion_tokens=25, total_tokens=80)

        mock_async_client.beta.chat.completions.parse = AsyncMock(return_value=mock_completion)

        parser = NLIParser(async_client=mock_async_client, model="gpt-5.4-mini")
        history = [
            {"role": "user", "content": "Recommend psychological horror"},
            {"role": "assistant", "content": "Try Higurashi and Another."},
        ]

        with patch("backend.rag_pipeline.helper.nli_parser.log_llm_usage_event") as mock_log:
            result = await parser.parse_async(
                query="Give me something similar but less gory",
                history=history,
                request_id="req-test-123",
                session_id="sess-test-456",
            )

            assert result.standalone_query == "psychological thriller with mystery and suspense"
            assert result.avoid_genres == ["Horror", "Gore"]
            assert result.avoid_tropes == ["jump scares"]
            assert result.intent == "refine"

            # Verify client arguments
            mock_async_client.beta.chat.completions.parse.assert_called_once()
            call_kwargs = mock_async_client.beta.chat.completions.parse.call_args[1]
            assert call_kwargs["model"] == "gpt-5.4-mini"
            assert call_kwargs["response_format"] == NLIOutput
            assert call_kwargs["max_tokens"] == 120
            assert call_kwargs["temperature"] == 0.1

            # Verify telemetry logged
            mock_log.assert_called_once()
            log_kwargs = mock_log.call_args[1]
            assert log_kwargs["layer"] == "nli"
            assert log_kwargs["model"] == "gpt-5.4-mini"
            assert log_kwargs["prompt_tokens"] == 55
            assert log_kwargs["completion_tokens"] == 25
            assert log_kwargs["total_tokens"] == 80
            assert log_kwargs["status"] == "ok"
            assert log_kwargs["request_id"] == "req-test-123"
            assert log_kwargs["session_id"] == "sess-test-456"

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error_to_raise",
        [
            asyncio.TimeoutError("Exceeded 3.0s timeout"),
            Exception("OpenAI 500 Internal Server Error"),
        ],
        ids=["timeout", "api_exception"],
    )
    async def test_parse_async_fallback_on_errors(self, error_to_raise):
        """Verifies 3.0s timeout and unexpected API exceptions return safe raw query without crashing."""
        mock_async_client = MagicMock()
        mock_async_client.beta.chat.completions.parse = AsyncMock(side_effect=error_to_raise)
        parser = NLIParser(async_client=mock_async_client)

        raw_query = "Give me something similar but less gory"
        with patch("backend.rag_pipeline.helper.nli_parser.log_llm_usage_event") as mock_log:
            result = await parser.parse_async(
                query=raw_query,
                history=[{"role": "user", "content": "horror"}],
                request_id="req-fallback-test",
            )

            assert result.standalone_query == raw_query
            assert result.intent == "new_search"
            assert result.avoid_genres == []

            mock_log.assert_called_once()
            log_kwargs = mock_log.call_args[1]
            assert log_kwargs["layer"] == "nli"
            assert log_kwargs["status"] == "fallback"
            assert log_kwargs["prompt_tokens"] == 0

    def test_sync_parse_success_and_fallback(self):
        """Verifies synchronous parse method works with sync client."""
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(parsed=NLIOutput(standalone_query="mystery anime", intent="refine")))
        ]
        mock_completion.usage = MagicMock(prompt_tokens=40, completion_tokens=10, total_tokens=50)
        mock_client.beta.chat.completions.parse.return_value = mock_completion

        parser = NLIParser(client=mock_client)
        res = parser.parse("mystery", history=[{"role": "user", "content": "thriller"}])
        assert res.standalone_query == "mystery anime"

        # Fallback test
        mock_client.beta.chat.completions.parse.side_effect = RuntimeError("Sync failure")
        fallback_res = parser.parse("mystery", history=[{"role": "user", "content": "thriller"}])
        assert fallback_res.standalone_query == "mystery"


# =============================================================================
# PART 3: NEGATIVE CONSTRAINT FILTERING TESTS
# =============================================================================

class TestNegativeConstraintFiltering:
    """Verifies in-memory post-filtering candidate anime with negative constraints."""

    @pytest.fixture
    def sample_candidates(self):
        return [
            {
                "id": 1,
                "title_romaji": "Higurashi no Naku Koro ni",
                "genres": ["Horror", "Mystery", "Psychological"],
                "tags": ["gore", "paranoia"],
                "description": "A dark psychological mystery set in a quiet village.",
            },
            {
                "id": 2,
                "title_romaji": "Monster",
                "genres": ["Mystery", "Psychological", "Thriller"],
                "tags": ["detective", "mind games"],
                "description": "A brilliant brain surgeon pursues an enigmatic psychopath.",
            },
            {
                "id": 3,
                "title_romaji": "Neon Genesis Evangelion",
                "genres": ["Action", "Mecha", "Psychological"],
                "tags": ["giant robots", "depression"],
                "description": "Teenagers pilot massive bio-mechanical mecha against angels.",
            },
            {
                "id": 4,
                "title_romaji": "Another",
                "genres": '["Horror", "Supernatural"]',  # Stringified JSON format
                "tags": ["curse"],
                "description": "Classmates die in mysterious and brutal accidents.",
            },
            {
                "id": 5,
                "title_romaji": "Death Note",
                "genres": "Mystery, Supernatural, Thriller",  # Comma-separated format
                "tags": ["shinigami", "rivalry"],
                "description": "A high school prodigy discovers a notebook that kills anyone whose name is written in it.",
            },
        ]

    def test_filter_by_avoid_genres_case_insensitive(self, sample_candidates):
        # Exclude 'horror' (lowercase input vs 'Horror' in candidates)
        filtered = filter_candidates_by_negative_constraints(
            sample_candidates, avoid_genres=["horror"]
        )

        remaining_ids = [c["id"] for c in filtered]
        # IDs 1 (Higurashi) and 4 (Another) must be excluded
        assert 1 not in remaining_ids
        assert 4 not in remaining_ids
        assert remaining_ids == [2, 3, 5]

    def test_filter_by_multiple_avoid_genres(self, sample_candidates):
        # Exclude 'Mecha' and 'Horror'
        filtered = filter_candidates_by_negative_constraints(
            sample_candidates, avoid_genres=["Mecha", "Horror"]
        )

        remaining_ids = [c["id"] for c in filtered]
        assert remaining_ids == [2, 5]  # Only Monster and Death Note remain

    def test_filter_by_avoid_tropes(self, sample_candidates):
        # Exclude trope 'giant robots'
        filtered = filter_candidates_by_negative_constraints(
            sample_candidates, avoid_tropes=["giant robots"]
        )

        remaining_ids = [c["id"] for c in filtered]
        assert 3 not in remaining_ids  # Evangelion excluded
        assert 1 in remaining_ids
        assert 2 in remaining_ids

    def test_filter_empty_constraints_returns_all(self, sample_candidates):
        filtered = filter_candidates_by_negative_constraints(
            sample_candidates, avoid_genres=[], avoid_tropes=[]
        )
        assert len(filtered) == len(sample_candidates)

    def test_ranker_execute_applies_negative_filtering(self):
        """Verifies Ranker.filter_candidates_by_negative_constraints staticmethod."""
        candidates = [
            {"id": 10, "genres": ["Action", "Horror"]},
            {"id": 20, "genres": ["Action", "Sci-Fi"]},
        ]
        filtered = Ranker.filter_candidates_by_negative_constraints(
            candidates, avoid_genres=["Horror"]
        )
        assert len(filtered) == 1
        assert filtered[0]["id"] == 20


# =============================================================================
# PART 4: ORCHESTRATOR END-TO-END SPRINT 8 INTEGRATION
# =============================================================================

class TestOrchestratorSprint8Integration:
    """Verifies pipeline orchestrator step 2.5 NLI query rewrite and step 3.5 filtering."""

    @pytest.mark.asyncio
    async def test_turn_1_orchestrator_bypasses_nli(self):
        """Turn 1 in stream_chat must skip NLI and report nli_ms == 0.0."""
        mock_retrieval = AsyncMock(return_value=([{"id": 101, "title_romaji": "Steins;Gate", "genres": ["Sci-Fi"]}], {}))
        mock_synth = MagicMock()

        async def mock_pitch(**kwargs):
            yield "Great time travel sci-fi."

        mock_synth.stream_pitch = mock_pitch

        mock_nli = MagicMock()
        mock_nli.parse_async = AsyncMock()

        orch = PipelineOrchestrator(
            retrieval_func=mock_retrieval,
            synthesizer=mock_synth,
            nli_parser=mock_nli,
        )

        events = []
        async for sse in orch.stream_chat(query="time travel sci-fi anime", conversation_history=None):
            events.append(sse)

        # Verify NLI parse_async was NOT called (bypassed)
        mock_nli.parse_async.assert_not_called()

        # Check metadata event
        meta_event = next(e for e in events if "event: metadata" in e)
        meta_json = json.loads(meta_event.split("data: ")[1])
        assert meta_json["timings"]["nli_ms"] == 0.0
        assert meta_json["avoid_genres"] == []
        mock_retrieval.assert_called_once()
        assert mock_retrieval.call_args[1]["query"] == "time travel sci-fi anime"

    @pytest.mark.asyncio
    async def test_turn_2_orchestrator_runs_nli_and_filters_negative_genres(self):
        """Turn 2 with refinement calls NLI, uses effective_query for retrieval, and applies post-filtering."""
        raw_candidates = [
            {"id": 1, "title_romaji": "Tokyo Ghoul", "genres": ["Action", "Horror"]},
            {"id": 2, "title_romaji": "Psycho-Pass", "genres": ["Action", "Sci-Fi", "Psychological"]},
        ]

        mock_retrieval = AsyncMock(return_value=(raw_candidates, {"retrieval_ms": 12.5}))
        mock_synth = MagicMock()

        async def mock_pitch(**kwargs):
            yield "Here is Psycho-Pass."

        mock_synth.stream_pitch = mock_pitch

        mock_nli = MagicMock()
        mock_nli.parse_async = AsyncMock(return_value=NLIOutput(
            standalone_query="psychological cyberpunk anime with mystery",
            avoid_genres=["Horror"],
            intent="refine",
        ))

        orch = PipelineOrchestrator(
            retrieval_func=mock_retrieval,
            synthesizer=mock_synth,
            nli_parser=mock_nli,
        )

        history = [
            {"role": "user", "content": "I like dark psychological anime"},
            {"role": "assistant", "content": "Here is Tokyo Ghoul"},
        ]

        events = []
        async for sse in orch.stream_chat(
            query="give me something similar but not horror",
            conversation_history=history,
        ):
            events.append(sse)

        # Verify NLI parse_async was called
        mock_nli.parse_async.assert_called_once()

        # Verify retrieval ran with effective query
        mock_retrieval.assert_called_once()
        assert mock_retrieval.call_args[1]["query"] == "psychological cyberpunk anime with mystery"

        # Check metadata event
        meta_event = next(e for e in events if "event: metadata" in e)
        meta_json = json.loads(meta_event.split("data: ")[1])

        # Step 3.5: Tokyo Ghoul (Horror) must be filtered out!
        candidate_ids = [c["id"] for c in meta_json["candidates"]]
        assert 1 not in candidate_ids
        assert 2 in candidate_ids
        assert meta_json["avoid_genres"] == ["Horror"]
        assert meta_json["timings"]["nli_ms"] >= 0.0

    @pytest.mark.asyncio
    async def test_turn_2_orchestrator_nli_failure_gracefully_falls_back(self):
        """If NLI fails or times out, orchestrator continues with raw query and produces response."""
        mock_retrieval = AsyncMock(return_value=([{"id": 5, "title_romaji": "Monster", "genres": ["Mystery"]}], {}))
        mock_synth = MagicMock()

        async def mock_pitch(**kwargs):
            yield "Recommendations."

        mock_synth.stream_pitch = mock_pitch

        mock_nli = MagicMock()
        # NLI parser returns fallback
        mock_nli.parse_async = AsyncMock(return_value=NLIOutput(
            standalone_query="give me more like that",
            avoid_genres=[],
            intent="new_search",
        ))

        orch = PipelineOrchestrator(
            retrieval_func=mock_retrieval,
            synthesizer=mock_synth,
            nli_parser=mock_nli,
        )

        history = [{"role": "user", "content": "mystery"}]
        events = []
        async for sse in orch.stream_chat(query="give me more like that", conversation_history=history):
            events.append(sse)

        assert any("event: metadata" in e for e in events)
        assert any("event: done" in e for e in events)
        mock_retrieval.assert_called_once()
        assert mock_retrieval.call_args[1]["query"] == "give me more like that"
