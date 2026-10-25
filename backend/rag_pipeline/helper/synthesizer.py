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
from typing import List, Dict, Any, Optional, AsyncGenerator, Callable, Awaitable, Union, Set

import httpx
from openai import AsyncOpenAI
from openai import (
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
from .llm_clients import resolve_layer_api_key
from .budget_guard import budget_guard
from backend.telemetry.logger import log_llm_usage_event

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
6. STRUCTURED CITATIONS & ANIME TAGS: Whenever you mention, explain, or pitch an anime from the candidate list, cite it using structured notation: [[anime:<id>]]. For example: "If you want psychological tension, [[anime:19]] (Monster) is a masterpiece of suspense...". The <id> MUST strictly match the numerical candidate ID from the provided candidate list (e.g. [ID: <id>]). Never invent or hallucinate candidate IDs.
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

# Structured anime citation regex pattern [[anime:<id>]]
ANIME_CITATION_PATTERN = re.compile(r"\[\[anime:(\d+)\]\]")

# Matches any suffix that could be an incomplete [[anime:<id>]] tag at stream chunk boundaries
PARTIAL_TAG_PATTERN = re.compile(
    r"\[(?:\[(?:a(?:n(?:i(?:m(?:e(?::(?:\d+(?:\])?)?)?)?)?)?)?)?)?$"
)


def _safe_token_count(val: Any, default: int = 0) -> int:
    """Safely extracts integer token counts, shielding against MagicMock or non-numeric types."""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return int(val)
    return default



def validate_and_sanitize_citations(
    text: str,
    valid_candidate_ids: Optional[Union[Set[Any], List[Any], Dict[Any, Any]]] = None,
) -> str:
    """
    Validates and sanitizes structured anime citation tags [[anime:<id>]].
    Preserves valid candidate tags; strips hallucinated or unverified tags.
    """
    if not text:
        return ""

    if not valid_candidate_ids:
        valid_int_ids = set()
    else:
        valid_int_ids = set()
        for x in valid_candidate_ids:
            try:
                valid_int_ids.add(int(x))
            except (ValueError, TypeError):
                continue

    def _replace_tag(match: re.Match) -> str:
        tag_id_str = match.group(1)
        try:
            tag_id = int(tag_id_str)
            if tag_id in valid_int_ids:
                return match.group(0)
            return ""
        except ValueError:
            return ""

    return ANIME_CITATION_PATTERN.sub(_replace_tag, text)


class StreamingCitationBuffer:
    """
    Stateful streaming citation buffer and sanitization filter.

    Handles token chunk boundary fragmentation where `[[anime:<id>]]` tags may be
    split across arbitrary chunk boundaries (e.g. `[[ani` + `me:19]]`).
    Buffers partial `[[` tag sequences until completed or until confirming it is not a tag,
    validates the resolved ID against `valid_candidate_ids`, and emits sanitized text.
    """

    def __init__(
        self,
        valid_candidate_ids: Optional[Union[Set[Any], List[Any], Dict[Any, Any]]] = None,
        max_buffer_len: int = 64,
    ):
        self.valid_candidate_ids = valid_candidate_ids or set()
        self.max_buffer_len = max_buffer_len
        self._buffer: str = ""

    def feed(self, chunk: Optional[str]) -> str:
        """
        Feeds a newly arrived token chunk into the buffer and returns safe, sanitized text.
        Any incomplete tag suffix remains buffered until the next chunk or flush.
        """
        if not chunk:
            return ""

        self._buffer += chunk

        if len(self._buffer) > self.max_buffer_len:
            safe = self._buffer
            self._buffer = ""
        else:
            match = PARTIAL_TAG_PATTERN.search(self._buffer)
            if match:
                safe = self._buffer[:match.start()]
                self._buffer = self._buffer[match.start():]
            else:
                safe = self._buffer
                self._buffer = ""

        return validate_and_sanitize_citations(safe, self.valid_candidate_ids)

    process_chunk = feed

    def flush(self) -> str:
        """
        Flushes and sanitizes any remaining buffered text at the end of the stream.
        """
        remaining = self._buffer
        self._buffer = ""
        return validate_and_sanitize_citations(remaining, self.valid_candidate_ids)

    finalize = flush


StreamingCitationFilter = StreamingCitationBuffer


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
        resolved_key = resolve_layer_api_key("presentation", api_key)
        self.api_key = resolved_key
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
            or candidate.get("title_userpreferred")
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
            cid = c.get("id")
            id_prefix = f"[ID: {cid}] " if cid is not None else ""
            title_line = f"{i}. {id_prefix}Title: {title}"
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
            cid = c.get("id")
            tag_str = f"[[anime:{cid}]] " if cid is not None else ""
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

            lines.append(f"{i}. {tag_str}**{title}**{score_str}{studio_str}{genres_str}")
            if snippet:
                lines.append(f"   _{snippet}_\n")
            else:
                lines.append("")

        lines.append(
            "Explore the candidate cards above for full episode counts, visual art, and detailed metrics."
        )
        return "\n".join(lines)

    def generate_single_fallback_pitch(
        self,
        query: str,
        candidate: dict,
    ) -> str:
        """Deterministic, grounded single-title fallback rationale."""
        if not candidate:
            return "Recommended title based on catalog relevance."
        title = self._extract_title(candidate)
        cid = candidate.get("id")
        tag_str = f"[[anime:{cid}]] " if cid is not None else ""
        score = candidate.get("averageScore")
        score_str = f"with a {score}% score" if score is not None else ""
        genres = candidate.get("genres")
        genres_str = ""
        if isinstance(genres, list) and genres:
            genres_str = f"featuring {', '.join(str(g) for g in genres[:3])}"
        elif isinstance(genres, str) and genres:
            genres_str = f"featuring {genres}"
        desc = sanitize_html(candidate.get("description") or candidate.get("synopsis") or "")
        snippet = (desc[:160] + "...") if len(desc) > 160 else desc
        meta_parts = [p for p in [score_str, genres_str] if p]
        meta_summary = f" ({', '.join(meta_parts)})" if meta_parts else ""
        if snippet:
            return f"{tag_str}**{title}**{meta_summary} matches your preference: {snippet}"
        return f"{tag_str}**{title}**{meta_summary} is recommended for your request."

    async def synthesize_single_pitch(
        self,
        query: str,
        candidate: dict,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Generates a targeted, concise single-title micro-pitch (<80 completion tokens)."""
        if not candidate:
            return "No anime candidate was provided to generate a rationale."
        if await budget_guard.is_budget_exceeded("presentation") or self.async_client is None:
            return self.generate_single_fallback_pitch(query, candidate)
        title = self._extract_title(candidate)
        cid = candidate.get("id")
        score = candidate.get("averageScore")
        score_str = f"{score}/100" if score is not None else "N/A"
        genres = candidate.get("genres")
        genres_str = ", ".join(str(g) for g in genres) if isinstance(genres, list) else (str(genres) if genres else "N/A")
        studios = candidate.get("studios")
        studios_str = ", ".join(str(s) for s in studios) if isinstance(studios, list) else (str(studios) if studios else "N/A")
        desc = sanitize_html(candidate.get("description") or candidate.get("synopsis") or "")
        if len(desc) > 300:
            desc = desc[:297] + "..."
        system_prompt = (
            "You are an elite anime taste concierge.\n"
            "Your mission is to craft a targeted, concise single-title pitch explaining specifically "
            "why this anime matches the user's request.\n\n"
            "STRICT GROUNDING & BREVITY CONSTRAINTS:\n"
            "1. Rely SOLELY on the provided anime metadata (title, synopsis, genres, studios, average score).\n"
            "2. Do NOT invent plot points, characters, or lore not present in the synopsis.\n"
            "3. NEVER reveal major spoilers, endings, or character deaths.\n"
            "4. FORMAT: Keep it to 1 to 2 punchy, cinematic sentences (<80 tokens).\n"
            "5. Cite the title as [[anime:<id>]] tag."
        )
        user_content = (
            f"User Query: \"{query}\"\n"
            f"Candidate Anime Metadata:\n"
            f"• Title: {title} [ID: {cid}]\n"
            f"• Average Score: {score_str}\n"
            f"• Studios: {studios_str}\n"
            f"• Genres: {genres_str}\n"
            f"Synopsis: {desc if desc else 'No synopsis available.'}\n\n"
            "Provide a concise personalized pitch explaining why this specific anime fits the user query."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        t0 = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self.async_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=80,
                ),
                timeout=self.timeout,
            )
            pitch_text = response.choices[0].message.content.strip() if response.choices and response.choices[0].message.content else ""
            usage_obj = getattr(response, "usage", None)
            prompt_tokens = _safe_token_count(getattr(usage_obj, "prompt_tokens", 0) or 0)
            completion_tokens = _safe_token_count(getattr(usage_obj, "completion_tokens", 0) or 0)
            total_tokens = _safe_token_count(getattr(usage_obj, "total_tokens", None), default=prompt_tokens + completion_tokens)
            try:
                log_llm_usage_event(
                    layer="presentation",
                    model=self.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cached=False,
                    latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                    status="ok",
                    request_id=request_id,
                    session_id=session_id,
                )
            except Exception:
                pass
            if total_tokens > 0:
                try:
                    await budget_guard.record_usage("presentation", total_tokens)
                except Exception:
                    pass
            if not pitch_text:
                return self.generate_single_fallback_pitch(query, candidate)
            scrubbed = self.scrub_spoilers(pitch_text)
            valid_ids = {cid} if cid is not None else set()
            sanitised = validate_and_sanitize_citations(scrubbed, valid_ids)
            return sanitised or scrubbed
        except Exception as exc:
            logger.warning(f"[RecommendationSynthesizer] Single pitch failed: {exc}. Serving fallback.")
            return self.generate_single_fallback_pitch(query, candidate)

    async def stream_single_pitch(
        self,
        query: str,
        candidate: dict,
        is_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """Asynchronously streams targeted single-title pitch rationale token-by-token."""
        if not candidate:
            yield "No candidate provided."
            return
        if await budget_guard.is_budget_exceeded("presentation") or self.async_client is None:
            fallback = self.generate_single_fallback_pitch(query, candidate)
            words = fallback.split(" ")
            for i, word in enumerate(words):
                if is_disconnected and await is_disconnected():
                    return
                yield word + (" " if i < len(words) - 1 else "")
                await asyncio.sleep(0.01)
            return
        title = self._extract_title(candidate)
        cid = candidate.get("id")
        score = candidate.get("averageScore")
        score_str = f"{score}/100" if score is not None else "N/A"
        genres = candidate.get("genres")
        genres_str = ", ".join(str(g) for g in genres) if isinstance(genres, list) else (str(genres) if genres else "N/A")
        studios = candidate.get("studios")
        studios_str = ", ".join(str(s) for s in studios) if isinstance(studios, list) else (str(studios) if studios else "N/A")
        desc = sanitize_html(candidate.get("description") or candidate.get("synopsis") or "")
        if len(desc) > 300:
            desc = desc[:297] + "..."
        system_prompt = (
            "You are an elite anime taste concierge.\n"
            "Your mission is to craft a targeted, concise single-title pitch explaining specifically "
            "why this anime matches the user's request.\n\n"
            "STRICT GROUNDING & BREVITY CONSTRAINTS:\n"
            "1. Rely SOLELY on the provided anime metadata (title, synopsis, genres, studios, average score).\n"
            "2. Do NOT invent plot points, characters, or lore not present in the synopsis.\n"
            "3. NEVER reveal major spoilers, endings, or character deaths.\n"
            "4. FORMAT: Keep it to 1 to 2 punchy, cinematic sentences (<80 tokens).\n"
            "5. Cite the title as [[anime:<id>]] tag."
        )
        user_content = (
            f"User Query: \"{query}\"\n"
            f"Candidate Anime Metadata:\n"
            f"• Title: {title} [ID: {cid}]\n"
            f"• Average Score: {score_str}\n"
            f"• Studios: {studios_str}\n"
            f"• Genres: {genres_str}\n"
            f"Synopsis: {desc if desc else 'No synopsis available.'}\n\n"
            "Provide a concise personalized pitch explaining why this specific anime fits the user query."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        t0 = time.perf_counter()
        accumulated_tokens = []
        try:
            stream_resp = await asyncio.wait_for(
                self.async_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=80,
                    stream=True,
                ),
                timeout=self.timeout,
            )
            async for chunk in stream_resp:
                if is_disconnected and await is_disconnected():
                    return
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    tok = chunk.choices[0].delta.content
                    scrubbed = self.scrub_spoilers(tok)
                    accumulated_tokens.append(scrubbed)
                    yield scrubbed
            total_tokens = len("".join(accumulated_tokens).split()) * 2
            try:
                log_llm_usage_event(
                    layer="presentation",
                    model=self.model,
                    prompt_tokens=40,
                    completion_tokens=len(accumulated_tokens),
                    total_tokens=total_tokens,
                    cached=False,
                    latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                    status="ok",
                    request_id=request_id,
                    session_id=session_id,
                )
            except Exception:
                pass
        except Exception as exc:
            logger.warning(f"[RecommendationSynthesizer] Single pitch streaming failed: {exc}. Yielding fallback.")
            fallback = self.generate_single_fallback_pitch(query, candidate)
            words = fallback.split(" ")
            for i, word in enumerate(words):
                if is_disconnected and await is_disconnected():
                    return
                yield word + (" " if i < len(words) - 1 else "")
                await asyncio.sleep(0.01)

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
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Asynchronously streams the recommendation pitch rationale token-by-token.

        Wraps OpenAI calls with tenacity retry and aggregate timeout circuit breaker.
        Smoothly falls back to `generate_fallback_pitch` on failure without crashing.
        Actively scrubs spoilers across streamed tokens and detects client disconnects.
        Records token usage to telemetry.llm_usage (Sprint 7).
        """
        if not candidates:
            yield "No matching anime were found in our database for this query."
            return

        # Check daily presentation budget ceiling (Sprint 11)
        if await budget_guard.is_budget_exceeded("presentation"):
            logger.warning(
                "[RecommendationSynthesizer] Presentation daily token budget exceeded! "
                "Skipping OpenAI streaming; yielding deterministic fallback pitch ($0 presentation tokens)."
            )
            fallback_text = self.generate_fallback_pitch(query, candidates)
            words = fallback_text.split(" ")
            for i, word in enumerate(words):
                if await self._check_disconnected(is_disconnected, request):
                    return
                token = word + (" " if i < len(words) - 1 else "")
                yield self.scrub_spoilers(token)
                await asyncio.sleep(0.01)
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
        t_stream_start = time.perf_counter()
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

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
                    create_kwargs = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.3,
                        "stream": True,
                        "stream_options": {"include_usage": True},
                    }
                    try:
                        stream_response = await asyncio.wait_for(
                            self.async_client.chat.completions.create(**create_kwargs),
                            timeout=self.timeout,
                        )
                    except TypeError:
                        create_kwargs.pop("stream_options", None)
                        stream_response = await asyncio.wait_for(
                            self.async_client.chat.completions.create(**create_kwargs),
                            timeout=self.timeout,
                        )

                    # Iterate over streamed chunks
                    async for chunk in stream_response:
                        usage_obj = getattr(chunk, "usage", None)
                        if usage_obj is not None:
                            prompt_tokens = _safe_token_count(getattr(usage_obj, "prompt_tokens", 0) or 0)
                            completion_tokens = _safe_token_count(getattr(usage_obj, "completion_tokens", 0) or 0)
                            total_tokens = _safe_token_count(
                                getattr(usage_obj, "total_tokens", None),
                                default=prompt_tokens + completion_tokens,
                            )

                        if await self._check_disconnected(is_disconnected, request):
                            logger.info("Client disconnected during stream; aborting LLM synthesis.")
                            return

                        content = None
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content

                        if content:
                            scrubbed_content = self.scrub_spoilers(content)
                            yield scrubbed_content

                    latency_ms = round((time.perf_counter() - t_stream_start) * 1000, 2)
                    try:
                        log_llm_usage_event(
                            layer="presentation",
                            model=self.model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=total_tokens,
                            cached=False,
                            latency_ms=latency_ms,
                            status="ok",
                            request_id=request_id,
                            session_id=session_id,
                        )
                    except Exception:
                        pass

                    if total_tokens > 0:
                        try:
                            await budget_guard.record_usage("presentation", total_tokens)
                        except Exception as b_err:
                            logger.warning(f"[RecommendationSynthesizer] Failed to record budget usage: {b_err}")

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
            try:
                log_llm_usage_event(
                    layer="presentation",
                    model=self.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cached=False,
                    latency_ms=round((time.perf_counter() - t_stream_start) * 1000, 2),
                    status="fallback",
                    request_id=request_id,
                    session_id=session_id,
                )
            except Exception:
                pass

            fallback_text = self.generate_fallback_pitch(query, candidates)
            words = fallback_text.split(" ")
            for i, word in enumerate(words):
                if await self._check_disconnected(is_disconnected, request):
                    logger.info("Client disconnected during fallback stream; aborting.")
                    return
                token = word + (" " if i < len(words) - 1 else "")
                yield self.scrub_spoilers(token)
                await asyncio.sleep(0.01)

    generate_pitch_stream = stream_pitch

    async def stream_dual_sse(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        timings: Optional[Dict[str, float]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        is_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
        request: Optional[Any] = None,
        post_process_token: Optional[Callable[[str], str]] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
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
        valid_candidate_ids = {c["id"] for c in candidates if isinstance(c, dict) and "id" in c}
        citation_buffer = StreamingCitationBuffer(valid_candidate_ids)

        async for token_chunk in self.stream_pitch(
            query=query,
            candidates=candidates,
            conversation_history=conversation_history,
            is_disconnected=is_disconnected,
            request=request,
            request_id=request_id,
            session_id=session_id,
        ):
            if await self._check_disconnected(is_disconnected, request):
                logger.info("Client disconnected; halting SSE event generator.")
                return

            filtered_chunk = citation_buffer.feed(token_chunk)
            if filtered_chunk:
                token_count += 1
                processed_chunk = post_process_token(filtered_chunk) if post_process_token else filtered_chunk
                yield format_sse("token", {"text": processed_chunk})

        flushed_chunk = citation_buffer.flush()
        if flushed_chunk:
            token_count += 1
            processed_chunk = post_process_token(flushed_chunk) if post_process_token else flushed_chunk
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
