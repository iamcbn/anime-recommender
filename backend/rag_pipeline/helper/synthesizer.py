# backend/rag_pipeline/helper/synthesizer.py
"""
Recommendation Synthesizer & Dual-Stream SSE Protocol Engine.

Implements:
1. Dual-Stream SSE Protocol: Immediate emission of reranked candidate metadata cards
   (`event: metadata`) for sub-1.5s TTFT, followed immediately by token-by-token
   streaming taste concierge rationale (`event: token`), and finalized by timings & token
   telemetry (`event: done`).
2. Taste Concierge Prompt Engineering: Grounded strictly in candidate metadata (synopses,
   genres, studios, average scores) with low temperature (0.3) and anti-hallucination / zero-lore rules.
3. OpenAI Circuit Breaker & Fallback: Async tenacity retry with timeout catching 429, 500,
   and timeouts, yielding deterministic high-quality grounded pitches without crashing the stream (AC 3.3).
4. Client Disconnect Handling: Inspects `request.is_disconnected()` per-chunk to abort early
   and prevent connection/socket leaks.
"""

import os
import re
import html
import json
import time
import logging
import asyncio
from typing import List, Dict, Any, Optional, AsyncGenerator, Callable, Awaitable, Union

import httpx
from openai import AsyncOpenAI
from openai import (
    OpenAIError,
    RateLimitError,
    APIConnectionError,
    InternalServerError,
    APITimeoutError,
    APIStatusError,
)
from tenacity import (
    AsyncRetrying,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logger = logging.getLogger(__name__)

# Configurable OpenAI model with fallback
DEFAULT_MODEL = os.getenv("OPENAI_RECOMMENDATION_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini"

# Strict taste concierge system prompt enforcing grounding & anti-hallucination constraints
SYSTEM_PROMPT = """You are an elite anime taste concierge and personalized recommendation curator.
Your mission is to craft a compelling, concise, and personalized pitch explaining why the recommended anime match the user's specific request.

STRICT GROUNDING CONSTRAINTS:
1. Rely SOLELY on the provided anime metadata (title, synopsis, genres, studios, average score).
2. ONLY discuss anime present in the retrieved candidates list. Strictly forbidden from inventing plot points, characters, or lore not present in the provided synopses. Do NOT extrapolate or introduce external franchise lore.
3. NEVER reveal major plot twists, traitor identities, endings, or character deaths (SPOILER PROHIBITION).
4. TASTE CONCIERGE PERSONA: Cinematic, engaging, and discerning. Explain specifically WHY each anime connects to the narrative hooks, themes, or emotional atmosphere the user is looking for.
5. FORMAT: Provide an engaging introductory hook, followed by a crisp bulleted rationale for each recommended title. Keep it punchy, evocative, and readable.
"""

HTML_TAG_RE = re.compile(r"<[^>]+>")

# Default spoiler patterns for inline scrubbing during streaming
SPOILER_PATTERNS = re.compile(
    r"(?:"
    r"\b(?:dies?|died|is\s+killed|was\s+killed|will\s+die|ends\s+up\s+dying|sacrifices\s+(?:themselves|himself|herself))\s+(?:at|in|near)\s+the\s+(?:end|finale|climax|last\s+episode)\b"
    r"|\b(?:is|was|turns\s+out\s+to\s+be|revealed\s+to\s+be|revealed\s+as)\s+(?:actually\s+|secretly\s+)?(?:the\s+)?(?:real\s+|actual\s+|true\s+)?(?:killer|murderer|villain|culprit|mastermind|traitor)\b"
    r"|\b(?:true|real|secret|hidden)\s+identity\s+(?:is|was|revealed\s+to\s+be)\s+[A-Za-z0-9_\'\s]{1,30}?\b"
    r"|\|\|[\s\S]*?\|\|"
    r"|\[spoiler\][\s\S]*?\[/spoiler\]"
    r")",
    re.IGNORECASE
)


def sanitize_html(text: Optional[str]) -> str:
    """Removes HTML tags and unescapes HTML entities common in raw database synopses."""
    if not text:
        return ""
    clean = HTML_TAG_RE.sub(" ", text)
    clean = html.unescape(clean)
    return re.sub(r"\s+", " ", clean).strip()


def format_sse(event: str, data: Union[Dict[str, Any], List[Any], str]) -> str:
    """
    Formats a payload as a standard Server-Sent Events (SSE) data frame.
    Format:
        event: <event_name>\n
        data: <json_string>\n\n
    """
    serialized_data = json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data)
    return f"event: {event}\ndata: {serialized_data}\n\n"


format_sse_event = format_sse


class RecommendationSynthesizer:
    """
    Async streaming recommendation taste concierge backed by bounded HTTP connections
    and resilient circuit breakers.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 8.0,
        http_client: Optional[httpx.AsyncClient] = None,
        max_retries: int = 2,
        async_client: Optional[Any] = None,
    ):
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.max_retries = max_retries

        self._owned_http_client = False
        if http_client is not None:
            self._async_http_client = http_client
        else:
            self._async_http_client = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
                timeout=httpx.Timeout(15.0, connect=3.0),
            )
            self._owned_http_client = True

        # Initialize AsyncOpenAI client
        if async_client is not None:
            self.async_client = async_client
        elif self.api_key:
            self.async_client = AsyncOpenAI(
                api_key=self.api_key,
                http_client=self._async_http_client,
            )
        else:
            # When API key is explicitly empty and no client provided, disable OpenAI calls
            self.async_client = None

    @staticmethod
    def _extract_title(candidate: Dict[str, Any]) -> str:
        """Extracts the best human-readable title from candidate fields."""
        return (
            candidate.get("title_userPreferred")
            or candidate.get("title_english")
            or candidate.get("title_romaji")
            or f"Anime #{candidate.get('id', 'Unknown')}"
        )

    @classmethod
    def scrub_spoilers(cls, text: str, placeholder: str = "[spoiler redacted]") -> str:
        """Inline spoiler scrubber delegating to DomainGuardrails if available, else local regex."""
        try:
            from .guardrails import DomainGuardrails
            return DomainGuardrails.scrub_spoilers(text, placeholder=placeholder)
        except Exception:
            return SPOILER_PATTERNS.sub(placeholder, text)

    def format_grounding_context(self, candidates: List[Dict[str, Any]]) -> str:
        """
        Formats candidate metadata into a clean, strictly grounded context block
        for LLM synthesis.
        """
        if not candidates:
            return "No candidates retrieved from database."

        blocks = []
        for i, c in enumerate(candidates, 1):
            title = self._extract_title(c)
            romaji = c.get("title_romaji")
            title_line = f"{i}. Title: {title}"
            if romaji and romaji != title:
                title_line += f" ({romaji})"

            score = c.get("averageScore")
            score_str = f"Score: {score}/100" if score is not None else "Score: N/A"

            year = c.get("seasonYear")
            year_str = f"Year: {year}" if year else "Year: N/A"

            genres = c.get("genres")
            if isinstance(genres, list):
                genres_str = ", ".join(str(g) for g in genres)
            else:
                genres_str = str(genres) if genres else "N/A"

            studios = c.get("studios")
            if isinstance(studios, list):
                studios_str = ", ".join(str(s) for s in studios)
            else:
                studios_str = str(studios) if studios else "N/A"

            episodes = c.get("episodes")
            ep_str = f"Episodes: {episodes}" if episodes else "Episodes: N/A"

            desc = sanitize_html(c.get("description"))
            # Truncate overly long synopses to preserve token budget
            if len(desc) > 350:
                desc = desc[:347] + "..."

            block = (
                f"{title_line}\n"
                f"   Metadata: {score_str} | {year_str} | {ep_str} | Studio: {studios_str} | Genres: {genres_str}\n"
                f"   Synopsis: {desc if desc else 'No synopsis available.'}"
            )
            blocks.append(block)

        return "\n\n".join(blocks)

    def build_prompt(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """
        Builds the complete message list for Chat Completions, incorporating
        system instructions, optional conversation history, and strictly grounded context.
        """
        grounding_context = self.format_grounding_context(candidates)

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        # Inject conversation history if multi-turn dialogue is present
        if conversation_history:
            for turn in conversation_history[-6:]:  # Retain rolling 3 turns
                role = turn.get("role")
                content = turn.get("content")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        user_content = (
            f"User Request: \"{query}\"\n\n"
            f"Retrieved Anime Candidate Context (Strict Grounding):\n"
            f"{grounding_context}\n\n"
            "Curate a personalized recommendation pitch for the user based strictly on the above candidates. "
            "Explain why these choices fit the user's taste."
        )
        messages.append({"role": "user", "content": user_content})
        return messages

    def generate_fallback_pitch(
        self,
        query: str,
        candidates: List[Dict[str, Any]]
    ) -> str:
        """
        Deterministic, high-quality grounded fallback recommendation pitch (AC 3.3).
        Activated when OpenAI experiences rate limits (429), server errors (500),
        or network timeouts. Ensures the user receives a 100% usable response
        without HTTP 500 crashes.
        """
        if not candidates:
            return (
                "We were unable to locate strong matches in our database for your request. "
                "Please try refining your search terms or exploring related genres!"
            )

        lines = [
            "Here are the top-rated anime recommendations matching your request from our database:\n"
        ]

        for i, c in enumerate(candidates[:5], 1):
            title = self._extract_title(c)
            score = c.get("averageScore")
            score_str = f" • Rating: {score}%" if score is not None else ""

            studios = c.get("studios")
            studio_str = ""
            if isinstance(studios, list) and studios:
                studio_str = f" • Studio: {', '.join(str(s) for s in studios)}"
            elif isinstance(studios, str) and studios:
                studio_str = f" • Studio: {studios}"

            genres = c.get("genres")
            genres_str = ""
            if isinstance(genres, list) and genres:
                genres_str = f" • Genres: {', '.join(str(g) for g in genres)}"
            elif isinstance(genres, str) and genres:
                genres_str = f" • Genres: {genres}"

            desc = sanitize_html(c.get("description"))
            snippet = (desc[:180] + "...") if len(desc) > 180 else desc

            lines.append(f"{i}. **{title}**{score_str}{studio_str}{genres_str}")
            if snippet:
                lines.append(f"   _{snippet}_\n")
            else:
                lines.append("")

        lines.append(
            "Explore the candidate cards above for full episode counts, visual art, and detailed metrics."
        )
        return "\n".join(lines)

    async def _check_disconnected(
        self,
        is_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
        request: Optional[Any] = None,
    ) -> bool:
        """Helper to evaluate client connection status non-blockingly."""
        if is_disconnected is not None:
            try:
                return await is_disconnected()
            except Exception:
                return False
        if request is not None and hasattr(request, "is_disconnected"):
            try:
                return await request.is_disconnected()
            except Exception:
                return False
        return False

    async def stream_pitch(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        conversation_history: Optional[List[Dict[str, str]]] = None,
        is_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
        request: Optional[Any] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Asynchronously streams the recommendation pitch rationale token-by-token.

        Wraps OpenAI calls with tenacity retry and aggregate timeout circuit breaker.
        Smoothly falls back to `generate_fallback_pitch` on failure without crashing.
        Actively scrubs spoilers across streamed tokens and detects client disconnects.
        """
        if not candidates:
            yield "No matching anime were found in our database for this query."
            return

        # Immediate fallback if OpenAI client is unconfigured
        if self.async_client is None:
            logger.warning("[RecommendationSynthesizer] No OpenAI client configured. Yielding fallback pitch.")
            fallback_text = self.generate_fallback_pitch(query, candidates)
            words = fallback_text.split(" ")
            for i, word in enumerate(words):
                if await self._check_disconnected(is_disconnected, request):
                    return
                token = word + (" " if i < len(words) - 1 else "")
                yield self.scrub_spoilers(token)
            return

        fallback_needed = False
        messages = self.build_prompt(
            query=query,
            candidates=candidates,
            conversation_history=conversation_history,
        )

        # ---------------------------------------------------------------------
        # 1. ATTEMPT OPENAI STREAMING WITH CIRCUIT BREAKER & TIMEOUT
        # ---------------------------------------------------------------------
        try:
            retry_condition = retry_if_exception_type((
                RateLimitError,
                APIConnectionError,
                InternalServerError,
                APITimeoutError,
                APIStatusError,
                asyncio.TimeoutError,
                httpx.TimeoutException,
                httpx.NetworkError,
            ))

            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=2.0),
                retry=retry_condition,
                reraise=True,
            ):
                with attempt:
                    stream_response = await asyncio.wait_for(
                        self.async_client.chat.completions.create(
                            model=self.model,
                            messages=messages,
                            temperature=0.3,
                            stream=True,
                        ),
                        timeout=self.timeout,
                    )

                    # Iterate over streamed chunks
                    async for chunk in stream_response:
                        if await self._check_disconnected(is_disconnected, request):
                            logger.info("Client disconnected during stream; aborting LLM synthesis.")
                            return

                        content = None
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content

                        if content:
                            scrubbed_content = self.scrub_spoilers(content)
                            yield scrubbed_content

                    return

        except Exception as exc:
            logger.warning(
                f"[RecommendationSynthesizer] Circuit breaker tripped during OpenAI streaming "
                f"({type(exc).__name__}: {exc}). Activating graceful fallback pitch."
            )
            fallback_needed = True

        # ---------------------------------------------------------------------
        # 2. DETERMINISTIC CIRCUIT BREAKER FALLBACK (AC 3.3)
        # ---------------------------------------------------------------------
        if fallback_needed:
            fallback_text = self.generate_fallback_pitch(query, candidates)
            words = fallback_text.split(" ")
            for i, word in enumerate(words):
                if await self._check_disconnected(is_disconnected, request):
                    logger.info("Client disconnected during fallback stream; aborting.")
                    return
                token = word + (" " if i < len(words) - 1 else "")
                yield self.scrub_spoilers(token)
                await asyncio.sleep(0.01)

    async def stream_dual_sse(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        timings: Optional[Dict[str, float]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        is_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
        request: Optional[Any] = None,
        post_process_token: Optional[Callable[[str], str]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Complete Dual-Stream SSE Protocol Generator:
        1. `event: metadata` (Immediate emission of enriched candidate cards, ~1.2s TTFT)
        2. `event: token` (Token-by-token taste concierge rationale chunks)
        3. `event: done` (Execution timings, token stats, and circuit breaker status)
        """
        t0 = time.perf_counter()

        # Step 1: Immediate emission of metadata cards (Phase 1)
        metadata_payload = {
            "candidates": candidates,
            "count": len(candidates),
        }
        yield format_sse("metadata", metadata_payload)
        metadata_elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        # Step 2: Stream conversational rationale tokens (Phase 2)
        token_count = 0

        async for token_chunk in self.stream_pitch(
            query=query,
            candidates=candidates,
            conversation_history=conversation_history,
            is_disconnected=is_disconnected,
            request=request,
        ):
            if await self._check_disconnected(is_disconnected, request):
                logger.info("Client disconnected; halting SSE event generator.")
                return

            token_count += 1
            processed_chunk = post_process_token(token_chunk) if post_process_token else token_chunk
            yield format_sse("token", {"text": processed_chunk})

        # Step 3: Emit final telemetry event (Phase 3)
        total_synthesis_ms = round((time.perf_counter() - t0) * 1000, 2)
        execution_timings = dict(timings or {})
        execution_timings["metadata_emission_ms"] = metadata_elapsed_ms
        execution_timings["synthesis_total_ms"] = total_synthesis_ms

        done_payload = {
            "timings": execution_timings,
            "tokens": {
                "chunks": token_count,
            },
            "status": "completed",
        }
        yield format_sse("done", done_payload)

    async def aclose(self):
        """Cleanly releases underlying HTTP client connection pool."""
        if self._owned_http_client and not self._async_http_client.is_closed:
            await self._async_http_client.aclose()

    def close(self):
        """Synchronous cleanup alias."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.aclose())
            else:
                loop.run_until_complete(self.aclose())
        except Exception:
            pass


# Backward-compatible and specification alias
HardenedRecommendationSynthesizer = RecommendationSynthesizer
