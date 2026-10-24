"""
test/pipeline/test_sprint10_citations.py

Sprint 10 Task 10.1 Test Suite: Structured Citations & Tag Validation on Backend.

Covers:
1. Citation Validation & Sanitization:
   - Valid candidate IDs preserved: `[[anime:1]]` -> `[[anime:1]]`.
   - Invalid / hallucinated IDs stripped: `[[anime:9999]]` -> stripped.
   - Multiple tags with mixed valid/invalid IDs.
2. Streaming Citation Chunk Boundary Buffer:
   - Chunk split across tag boundaries (`"Check out [[ani"`, `"me:42]] today!"`) correctly resolves and emits valid tag.
   - Split across invalid tag (`"Check out [[ani"`, `"me:9999]] today!"`) correctly strips invalid tag.
   - Normal text with brackets or non-tags emitted without hanging or buffer leaks.
   - Single-character streaming fragmentation resilience.
3. Candidate Prompt & System Prompt Formatting:
   - Candidate metadata includes `[ID: {id}]` prominently alongside title and synopsis.
   - `SYSTEM_PROMPT` enforces `[[anime:<id>]]` citation instructions and candidate list constraints.
   - Deterministic fallback pitch includes valid `[[anime:<id>]]` tags for candidates.
4. Orchestrator & Dual-Stream SSE End-to-End Integration:
   - `stream_chat` runs token stream through tag citation validation with `valid_candidate_ids`.
   - Persisted session history contains sanitized pitches without hallucinated tags.
"""

import sys
import os
import re
import json
import pytest
from typing import List, Dict, Any
from unittest.mock import AsyncMock, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.rag_pipeline.helper.synthesizer import (
    RecommendationSynthesizer,
    StreamingCitationBuffer,
    StreamingCitationFilter,
    validate_and_sanitize_citations,
    SYSTEM_PROMPT,
    ANIME_CITATION_PATTERN,
)
from backend.rag_pipeline.orchestrator import PipelineOrchestrator
from backend.rag_pipeline.helper.state_manager import StateManager


@pytest.fixture
def sample_candidates() -> List[Dict[str, Any]]:
    return [
        {
            "id": 19,
            "title_userPreferred": "Monster",
            "title_romaji": "Monster",
            "title_english": "Monster",
            "genres": ["Drama", "Mystery", "Psychological", "Suspense"],
            "studios": ["Madhouse"],
            "averageScore": 88,
            "seasonYear": 2004,
            "episodes": 74,
            "description": "Dr. Kenzo Tenma is an elite neurosurgeon whose life unravels after saving a young boy.",
        },
        {
            "id": 42,
            "title_userPreferred": "Cowboy Bebop",
            "title_romaji": "Cowboy Bebop",
            "title_english": "Cowboy Bebop",
            "genres": ["Action", "Sci-Fi"],
            "studios": ["Sunrise"],
            "averageScore": 89,
            "seasonYear": 1998,
            "episodes": 26,
            "description": "Bounty hunters in the year 2071 travel on the Bebop spacecraft.",
        },
        {
            "id": 9253,
            "title_userPreferred": "Steins;Gate",
            "title_romaji": "Steins;Gate",
            "title_english": "Steins;Gate",
            "genres": ["Drama", "Sci-Fi", "Suspense"],
            "studios": ["White Fox"],
            "averageScore": 91,
            "seasonYear": 2011,
            "episodes": 24,
            "description": "A self-proclaimed mad scientist discovers the secret of time travel via microwave.",
        },
    ]


# =============================================================================
# PART 1: STATIC CITATION VALIDATION & SANITIZATION TESTS
# =============================================================================

class TestCitationValidationAndSanitization:
    """Verifies validate_and_sanitize_citations behavior under various conditions."""

    def test_valid_candidate_id_preserved(self):
        text = "Check out [[anime:1]] for an unforgettable experience."
        sanitized = validate_and_sanitize_citations(text, valid_candidate_ids={1})
        assert sanitized == "Check out [[anime:1]] for an unforgettable experience."

    def test_invalid_hallucinated_candidate_id_stripped(self):
        text = "We also recommend [[anime:9999]] which is completely fabricated."
        sanitized = validate_and_sanitize_citations(text, valid_candidate_ids={1, 42})
        assert sanitized == "We also recommend  which is completely fabricated."
        assert "[[anime:9999]]" not in sanitized

    def test_multiple_tags_mixed_valid_and_invalid(self):
        text = (
            "If you want psychological tension, [[anime:19]] (Monster) is unmatched. "
            "Alternatively, [[anime:8888]] offers great action, while [[anime:42]] (Cowboy Bebop) "
            "remains a timeless space western classic. Avoid [[anime:0]]."
        )
        valid_ids = {19, 42}
        sanitized = validate_and_sanitize_citations(text, valid_candidate_ids=valid_ids)

        assert "[[anime:19]]" in sanitized
        assert "[[anime:42]]" in sanitized
        assert "[[anime:8888]]" not in sanitized
        assert "[[anime:0]]" not in sanitized
        assert "(Monster)" in sanitized
        assert "(Cowboy Bebop)" in sanitized

    def test_empty_string_and_falsy_inputs(self):
        assert validate_and_sanitize_citations("", {1, 2}) == ""
        assert validate_and_sanitize_citations(None, {1, 2}) == ""
        assert validate_and_sanitize_citations("Normal text without citations", {1, 2}) == "Normal text without citations"
        assert validate_and_sanitize_citations("[[anime:1]]", set()) == ""
        assert validate_and_sanitize_citations("[[anime:1]]", None) == ""

    def test_coerces_mixed_id_types_gracefully(self):
        # Set containing strings and ints
        valid_ids = {"19", 42, "not_an_id"}
        text = "[[anime:19]] and [[anime:42]] and [[anime:999]]"
        sanitized = validate_and_sanitize_citations(text, valid_ids)
        assert sanitized == "[[anime:19]] and [[anime:42]] and "


# =============================================================================
# PART 2: STREAMING CITATION CHUNK BOUNDARY BUFFER TESTS
# =============================================================================

class TestStreamingCitationBuffer:
    """Verifies chunk boundary assembly, buffering, and sanitization across streamed tokens."""

    def test_chunk_split_across_valid_tag_boundary(self):
        buffer = StreamingCitationBuffer(valid_candidate_ids={42})
        chunk1 = buffer.feed("Check out [[ani")
        chunk2 = buffer.feed("me:42]] today!")
        chunk3 = buffer.flush()

        assert chunk1 == "Check out "
        assert chunk2 == "[[anime:42]] today!"
        assert chunk3 == ""
        assert (chunk1 + chunk2 + chunk3) == "Check out [[anime:42]] today!"

    def test_chunk_split_across_invalid_tag_boundary(self):
        buffer = StreamingCitationBuffer(valid_candidate_ids={42})
        chunk1 = buffer.feed("Check out [[ani")
        chunk2 = buffer.feed("me:9999]] today!")
        chunk3 = buffer.flush()

        assert chunk1 == "Check out "
        assert chunk2 == " today!"
        assert chunk3 == ""
        assert (chunk1 + chunk2 + chunk3) == "Check out  today!"
        assert "[[anime:9999]]" not in (chunk1 + chunk2 + chunk3)

    def test_single_character_streaming_fragmentation(self):
        chars = list("Watch [[anime:19]] now!")
        buffer = StreamingCitationBuffer(valid_candidate_ids={19})
        emitted = []
        for ch in chars:
            out = buffer.feed(ch)
            if out:
                emitted.append(out)
        final = buffer.flush()
        if final:
            emitted.append(final)

        full_result = "".join(emitted)
        assert full_result == "Watch [[anime:19]] now!"

    def test_normal_text_with_brackets_no_hanging_or_leak(self):
        buffer = StreamingCitationBuffer(valid_candidate_ids={42})
        out1 = buffer.feed("Score: [")
        out2 = buffer.feed("9.5/10] is great. ")
        out3 = buffer.feed("1. [ID: 19] Title: Monster. ")
        out4 = buffer.feed("Check out [[character:Guts]]")
        out5 = buffer.flush()

        assert (out1 + out2 + out3 + out4 + out5) == "Score: [9.5/10] is great. 1. [ID: 19] Title: Monster. Check out [[character:Guts]]"

    def test_unclosed_trailing_bracket_flushes_at_end(self):
        buffer = StreamingCitationBuffer(valid_candidate_ids={19})
        out1 = buffer.feed("Draft note [")
        out2 = buffer.flush()
        assert out1 == "Draft note "
        assert out2 == "["
        assert (out1 + out2) == "Draft note ["

    def test_alias_equivalence(self):
        assert StreamingCitationFilter is StreamingCitationBuffer
        buf = StreamingCitationFilter({19})
        assert buf.process_chunk("Hello") == "Hello"
        assert buf.finalize() == ""


# =============================================================================
# PART 3: PROMPT FORMATTING & CITATION SPECIFICATION TESTS
# =============================================================================

class TestPromptFormattingAndCitations:
    """Verifies synthesizer prompt formatting, system prompt rules, and fallback pitches."""

    def test_candidate_prompt_formatting_includes_id(self, sample_candidates):
        synthesizer = RecommendationSynthesizer(async_client=MagicMock())
        grounding_context = synthesizer.format_grounding_context(sample_candidates)

        assert "[ID: 19]" in grounding_context
        assert "[ID: 42]" in grounding_context
        assert "[ID: 9253]" in grounding_context
        assert "Title: Monster" in grounding_context
        assert "Title: Cowboy Bebop" in grounding_context

    def test_system_prompt_instructs_structured_citations(self):
        assert "[[anime:<id>]]" in SYSTEM_PROMPT
        assert "[ID: <id>]" in SYSTEM_PROMPT or "[ID:" in SYSTEM_PROMPT
        assert "Never invent or hallucinate candidate IDs" in SYSTEM_PROMPT

    def test_deterministic_fallback_pitch_includes_valid_tags(self, sample_candidates):
        synthesizer = RecommendationSynthesizer(async_client=MagicMock())
        pitch = synthesizer.generate_fallback_pitch("recommend classic anime", sample_candidates)

        assert "[[anime:19]]" in pitch
        assert "[[anime:42]]" in pitch
        assert "[[anime:9253]]" in pitch
        assert "**Monster**" in pitch
        assert "**Cowboy Bebop**" in pitch

        # Validate that sanitizing the fallback pitch preserves all tags
        valid_ids = {c["id"] for c in sample_candidates}
        sanitized = validate_and_sanitize_citations(pitch, valid_ids)
        assert sanitized == pitch


# =============================================================================
# PART 4: ORCHESTRATOR & DUAL-STREAM SSE INTEGRATION TESTS
# =============================================================================

class TestOrchestratorCitationIntegration:
    """Verifies end-to-end token filtering during orchestrator stream_chat."""

    @pytest.mark.asyncio
    async def test_orchestrator_stream_chat_preserves_valid_and_strips_hallucinated_tags(self, sample_candidates):
        async def mock_retrieval(*args, **kwargs):
            return sample_candidates[:2], {"retrieval_ms": 15.0}  # IDs 19 and 42

        async def mock_token_stream(*args, **kwargs):
            # Model outputs valid tag [[anime:19]], split hallucinated tag [[ani + me:9999]], and valid tag [[anime:42]]
            yield "For intense suspense, [[anime:19]] (Monster) is unmatched. "
            yield "You should also watch [[ani"
            yield "me:9999]] (Hallucination). "
            yield "Finally, [[anime:42]] is a masterpiece."

        mock_state = StateManager(redis_url=None, redis_token=None)
        orch = PipelineOrchestrator(
            state_manager=mock_state,
            retrieval_func=mock_retrieval,
        )
        orch.synthesizer.stream_pitch = mock_token_stream

        token_texts = []
        async for sse_chunk in orch.stream_chat(
            query="psychological suspense and sci-fi",
            session_id="sess_citations_test",
        ):
            if "event: token" in sse_chunk:
                match = re.search(r'data:\s*(\{.*\})', sse_chunk)
                if match:
                    payload = json.loads(match.group(1))
                    token_texts.append(payload.get("text", ""))

        full_pitch = "".join(token_texts)

        # Valid tags preserved
        assert "[[anime:19]]" in full_pitch
        assert "[[anime:42]]" in full_pitch
        assert "(Monster)" in full_pitch

        # Hallucinated tag stripped
        assert "[[anime:9999]]" not in full_pitch
        assert "(Hallucination)" in full_pitch

        # Verify state manager turn persistence
        history = await mock_state.get_session_history("sess_citations_test")
        assert len(history) == 2
        assistant_turn = history[1]
        assert "[[anime:19]]" in assistant_turn["content"]
        assert "[[anime:42]]" in assistant_turn["content"]
        assert "[[anime:9999]]" not in assistant_turn["content"]

    @pytest.mark.asyncio
    async def test_synthesizer_stream_dual_sse_validates_citations(self, sample_candidates):
        async def mock_pitch(*args, **kwargs):
            yield "Check out [[ani"
            yield "me:19]] and [[ani"
            yield "me:8888]]."

        synthesizer = RecommendationSynthesizer(async_client=MagicMock())
        synthesizer.stream_pitch = mock_pitch

        tokens = []
        async for sse_chunk in synthesizer.stream_dual_sse(
            query="recommend",
            candidates=sample_candidates[:1],  # ID 19 is valid, 8888 is invalid
        ):
            if "event: token" in sse_chunk:
                match = re.search(r'data:\s*(\{.*\})', sse_chunk)
                if match:
                    payload = json.loads(match.group(1))
                    tokens.append(payload.get("text", ""))

        full_text = "".join(tokens)
        assert "[[anime:19]]" in full_text
        assert "[[anime:8888]]" not in full_text
