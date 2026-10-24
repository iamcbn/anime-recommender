"""
test/pipeline/test_streaming_synthesis.py

Sprint 3 Recommendation Synthesizer & Circuit Breaker Test Suite:
- AC 3.3: OpenAI 500 / Timeout Circuit Breaker Fallback (cards and fallback pitch remain intact).
- Streaming Synthesis: Token-by-token async delivery with active spoiler scrubbing.
- Client Disconnection: Generator terminates immediately when is_disconnected() is True.
- Context Grounding & Anti-Hallucination: Verifies strict system prompt and candidate context inclusion.
"""

import sys
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx
from openai import InternalServerError, APITimeoutError, APIConnectionError

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.rag_pipeline.helper.synthesizer import RecommendationSynthesizer
from backend.rag_pipeline.helper.guardrails import DomainGuardrails


# Helper to create mock streaming chunks mimicking OpenAI streaming API
def make_mock_chunk(token: str):
    delta = MagicMock()
    delta.content = token
    choice = MagicMock()
    choice.delta = delta
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


async def mock_chunk_generator(tokens: list[str]):
    for t in tokens:
        yield make_mock_chunk(t)


class TestRecommendationSynthesizerStreaming:
    """Tests for normal streaming synthesis and content scrubbing."""

    @pytest.fixture
    def sample_candidates(self):
        return [
            {
                "id": 152802,
                "title_userPreferred": "Dark Gathering",
                "title_romaji": "Dark Gathering",
                "title_english": "Dark Gathering",
                "coverImage_large": "https://example.com/cover1.jpg",
                "description": "Keitarou Gentouga is a college freshman who hates ghosts...",
                "genres": ["Horror", "Supernatural"],
                "studios": ["OLM"],
                "averageScore": 76.5,
                "seasonYear": 2023,
                "cross_encoder_score": 4.85,
            },
            {
                "id": 101759,
                "title_userPreferred": "The Promised Neverland",
                "title_romaji": "Yakusoku no Neverland",
                "description": "Orphans discover a sinister secret about their idyllic orphanage...",
                "genres": ["Mystery", "Psychological", "Thriller"],
                "studios": ["CloverWorks"],
                "averageScore": 84.0,
                "seasonYear": 2019,
                "cross_encoder_score": 3.92,
            },
        ]

    @pytest.mark.asyncio
    async def test_normal_streaming_yields_expected_tokens(self, sample_candidates):
        """Verifies that streaming tokens from OpenAI are yielded seamlessly."""
        mock_tokens = ["If ", "you're ", "seeking ", "dark ", "thrills, ", "Dark Gathering ", "is ", "perfect."]
        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_chunk_generator(mock_tokens)
        )

        synthesizer = RecommendationSynthesizer(async_client=mock_async_client)
        received_chunks = []
        async for chunk in synthesizer.stream_pitch("dark anime", sample_candidates):
            received_chunks.append(chunk)

        full_text = "".join(received_chunks)
        assert "Dark Gathering" in full_text
        assert mock_async_client.chat.completions.create.called

    @pytest.mark.asyncio
    async def test_streaming_scrubs_spoilers_across_tokens(self, sample_candidates):
        """Verifies that plot twists in LLM tokens are actively redacted."""
        spoiler_tokens = [
            "You will love this show because the protagonist ",
            "dies in the end ",
            "which makes it very emotional.",
        ]
        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_chunk_generator(spoiler_tokens)
        )

        synthesizer = RecommendationSynthesizer(async_client=mock_async_client)
        received_chunks = []
        async for chunk in synthesizer.stream_pitch("dark anime", sample_candidates):
            received_chunks.append(chunk)

        full_output = "".join(received_chunks)
        assert "[spoiler redacted]" in full_output
        assert "dies in the end" not in full_output

    @pytest.mark.asyncio
    async def test_client_disconnection_stops_streaming(self, sample_candidates):
        """Verifies that stream terminates immediately if client disconnects."""
        mock_tokens = [f"Token_{i} " for i in range(50)]
        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_chunk_generator(mock_tokens)
        )

        counter = 0
        async def mock_is_disconnected():
            nonlocal counter
            counter += 1
            return counter > 3  # Disconnect after a few iterations

        synthesizer = RecommendationSynthesizer(async_client=mock_async_client)
        yielded_chunks = []
        async for chunk in synthesizer.stream_pitch(
            "test query", sample_candidates, is_disconnected=mock_is_disconnected
        ):
            yielded_chunks.append(chunk)

        # Stream stopped early before exhausting all 50 tokens
        assert len(yielded_chunks) < 20


class TestCircuitBreakerAndFallbacks:
    """Tests verifying AC 3.3: OpenAI 500 / Timeout resilience."""

    @pytest.fixture
    def sample_candidates(self):
        return [
            {
                "id": 1,
                "title_userPreferred": "Steins;Gate",
                "genres": ["Sci-Fi", "Thriller"],
                "averageScore": 91.0,
                "description": "An eccentric scientist accidentally invents time travel through a microwave.",
                "cross_encoder_score": 6.2,
            },
            {
                "id": 2,
                "title_userPreferred": "Monster",
                "genres": ["Psychological", "Mystery"],
                "averageScore": 88.5,
                "description": "A brilliant brain surgeon pursues an escaped psychopath across post-Cold War Germany.",
                "cross_encoder_score": 5.4,
            },
        ]

    # =========================================================================
    # AC 3.3: OPENAI CIRCUIT BREAKER FALLBACK (500 & TIMEOUT)
    # =========================================================================

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error_factory",
        [
            lambda req: InternalServerError("Internal Server Error from OpenAI", response=httpx.Response(500, request=req), body=None),
            lambda req: APITimeoutError(request=req),
        ],
        ids=["500_server_error", "timeout_error"],
    )
    async def test_ac3_3_openai_circuit_breaker_fallback(self, sample_candidates, error_factory):
        """
        AC 3.3: Verifies that when OpenAI returns an HTTP 500 error or times out,
        the synthesizer catches it and yields a deterministic fallback pitch
        referencing the retrieved candidate cards without crashing.
        """
        mock_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        error_to_raise = error_factory(mock_request)

        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(side_effect=error_to_raise)

        synthesizer = RecommendationSynthesizer(async_client=mock_async_client)
        chunks = []

        async for chunk in synthesizer.stream_pitch("time travel anime", sample_candidates):
            chunks.append(chunk)

        full_fallback = "".join(chunks)
        assert len(chunks) > 0, "Synthesizer failed to yield fallback tokens on OpenAI outage"
        assert "Steins;Gate" in full_fallback, "Fallback pitch must include candidate titles"
        assert "Monster" in full_fallback
        assert "Here are the top-rated anime recommendations" in full_fallback

    @pytest.mark.asyncio
    async def test_unconfigured_api_key_falls_back_gracefully(self, sample_candidates):
        """When OpenAI API key is missing or None, synthesizer immediately yields fallback pitch."""
        synthesizer = RecommendationSynthesizer(api_key="", async_client=None)
        chunks = []
        async for chunk in synthesizer.stream_pitch("query", sample_candidates):
            chunks.append(chunk)

        full_text = "".join(chunks)
        assert "Steins;Gate" in full_text


class TestContextGroundingConstraints:
    """Verifies anti-hallucination and grounding prompts."""

    @pytest.mark.asyncio
    async def test_system_prompt_strictly_enforces_grounding(self):
        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_chunk_generator(["Grounding verified."])
        )

        candidates = [
            {
                "id": 99,
                "title_userPreferred": "Baccano!",
                "genres": ["Action", "Historical"],
                "studios": ["Brain's Base"],
                "averageScore": 82.0,
                "description": "An ensemble cast collides aboard a transcontinental train in 1930s America.",
            }
        ]

        synthesizer = RecommendationSynthesizer(async_client=mock_async_client)
        async for _ in synthesizer.stream_pitch("1930s action", candidates):
            pass

        # Inspect call arguments to OpenAI
        call_kwargs = mock_async_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]

        sys_msg = next(m["content"] for m in messages if m["role"] == "system")
        assert "STRICT GROUNDING CONSTRAINTS" in sys_msg
        assert "ONLY discuss anime present in the retrieved candidates list" in sys_msg
        assert "NEVER reveal major plot twists" in sys_msg

        user_msg = next(m["content"] for m in messages if m["role"] == "user")
        assert "Baccano!" in user_msg
        assert "Brain's Base" in user_msg
        assert "82.0/100" in user_msg


class TestDualStreamSSEProtocol:
    """Verifies Task 3.2: Dual-Stream SSE format, event sequencing, and timing telemetry."""

    @pytest.fixture
    def sample_candidates(self):
        return [
            {
                "id": 19,
                "title_romaji": "Monster",
                "title_english": "Monster",
                "coverImage_large": "https://example.com/monster.jpg",
                "averageScore": 88.0,
                "genres": ["Drama", "Mystery", "Psychological"],
                "studios": ["Madhouse"],
                "seasonYear": 2004,
                "episodes": 74,
                "description": "Dr. Kenzo Tenma risks everything to track down an escaped sociopath.",
            }
        ]

    @pytest.mark.asyncio
    async def test_dual_stream_sse_event_sequencing(self, sample_candidates):
        """
        Verifies:
        - Event 1: event: metadata with anime cards (~1.2s TTFT)
        - Event 2..N: event: token with streamed tokens
        - Event Final: event: done with timing stats and completion status
        """
        import json

        mock_tokens = ["A ", "chilling ", "cat-and-mouse ", "thriller."]
        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(
            return_value=mock_chunk_generator(mock_tokens)
        )

        synthesizer = RecommendationSynthesizer(async_client=mock_async_client)
        timings_input = {
            "query_generation_ms": 310.0,
            "embedding_ms": 95.0,
            "retrieval_ms": 420.0,
            "reranking_ms": 260.0,
        }

        frames = []
        async for frame in synthesizer.stream_dual_sse(
            query="dark psychological",
            candidates=sample_candidates,
            timings=timings_input,
        ):
            frames.append(frame)

        # Parse SSE frames
        raw_text = "".join(frames)
        events = []
        for block in raw_text.split("\n\n"):
            if not block.strip():
                continue
            lines = block.strip().split("\n")
            ev_name = None
            ev_data = None
            for l in lines:
                if l.startswith("event: "):
                    ev_name = l[len("event: "):]
                elif l.startswith("data: "):
                    ev_data = json.loads(l[len("data: "):])
            if ev_name and ev_data is not None:
                events.append((ev_name, ev_data))

        assert len(events) >= 3
        # Event 1: metadata
        assert events[0][0] == "metadata"
        assert events[0][1]["count"] == 1
        assert events[0][1]["candidates"][0]["title_romaji"] == "Monster"

        # Event 2..N: token
        token_events = [e for e in events if e[0] == "token"]
        assert len(token_events) == 4
        assert "".join(e[1]["text"] for e in token_events) == "A chilling cat-and-mouse thriller."

        # Event Final: done
        assert events[-1][0] == "done"
        assert events[-1][1]["status"] == "completed"
        assert "timings" in events[-1][1]
        assert events[-1][1]["timings"]["query_generation_ms"] == 310.0
        assert "metadata_emission_ms" in events[-1][1]["timings"]
        assert "synthesis_total_ms" in events[-1][1]["timings"]
        assert events[-1][1]["tokens"]["chunks"] == 4

    @pytest.mark.asyncio
    async def test_dual_stream_sse_circuit_breaker_preserves_cards(self, sample_candidates):
        """
        AC 3.3 verification in Dual-Stream context:
        When OpenAI fails with 500, metadata cards are still emitted immediately in Event 1,
        and Event 2..N stream the deterministic fallback pitch without 500 crash.
        """
        import json

        mock_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        mock_response = httpx.Response(500, request=mock_request)
        server_error = InternalServerError("OpenAI 500", response=mock_response, body=None)

        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(side_effect=server_error)

        synthesizer = RecommendationSynthesizer(async_client=mock_async_client)

        frames = []
        async for frame in synthesizer.stream_dual_sse(
            query="mystery thriller",
            candidates=sample_candidates,
        ):
            frames.append(frame)

        raw_text = "".join(frames)
        assert "event: metadata" in raw_text
        assert "Monster" in raw_text
        assert "event: token" in raw_text

        token_texts = [
            json.loads(f.split("data: ")[1].strip()).get("text", "")
            for f in frames
            if f.startswith("event: token")
        ]
        combined_tokens = "".join(token_texts)
        assert "Here are the top-rated anime recommendations" in combined_tokens
        assert "event: done" in raw_text

