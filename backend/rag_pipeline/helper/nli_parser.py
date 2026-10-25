# backend/rag_pipeline/helper/nli_parser.py
"""
Natural Language Interface (NLI) Query Parser (Sprint 8).

Implements conversational query understanding, multi-turn reference resolution,
negative constraint extraction, and heuristic cost bypass safeguards:
1. Pydantic structured output schema (NLIOutput).
2. Cost safeguard: should_bypass_nli(query, history) skips NLI for turn-1 and
   standalone queries ($0 spent).
3. NLIParser with per-layer key isolation (OPENAI_API_KEY_NLI), strict 3.0s timeout,
   telemetry logging to telemetry.llm_usage, and robust fallback on error/timeout.
"""

import re
import time
import logging
import asyncio
from typing import List, Literal, Optional, Any
from openai import OpenAI, AsyncOpenAI
from pydantic import BaseModel, Field

from .llm_clients import (
    resolve_layer_api_key,
    get_layer_client,
    get_sync_layer_client,
)
from .budget_guard import budget_guard
from backend.telemetry.logger import log_llm_usage_event

logger = logging.getLogger("anime_recommender.nli_parser")


def _safe_token_count(val: Any, default: int = 0) -> int:
    """Safely extracts integer token counts, shielding against MagicMock or non-numeric types."""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return int(val)
    return default


DEFAULT_NLI_MODEL = "gpt-5.4-mini"

# Regex cues for conversational references and negative constraints
CONVERSATIONAL_CUES_REGEX = re.compile(
    r"\b(more|less|similar|another|instead|not|without|exclude|too|also|earlier|previous|like that|that one|first one|second one|show me|give me|next)\b",
    re.IGNORECASE,
)


# ----------------------
# PYDANTIC OUTPUT SCHEMA
# ----------------------

class NLIOutput(BaseModel):
    standalone_query: str = Field(description="Self-contained anime search query resolving pronouns and references")
    avoid_genres: List[str] = Field(default_factory=list, description="List of genres to explicitly exclude")
    avoid_tropes: List[str] = Field(default_factory=list, description="List of plot tropes, themes, or elements to avoid")
    intent: Literal["new_search", "refine", "exclude_title", "more_like", "queue_more", "paginate"] = Field(
        default="refine",
        description="Conversational intent classification"
    )


# ----------------------
# COST SAFEGUARD BYPASS RULE
# ----------------------

def should_bypass_nli(query: str, history: Optional[List[dict]]) -> bool:
    """
    Cost safeguard: Skip NLI parsing if conversational resolution is unnecessary ($0 spent).
    - If history is empty or None: return True (turn 1 bypass: $0 spent).
    - If query does not contain conversational reference indicators (e.g. regex for cues like
      \b(more|less|similar|another|instead|not|without|exclude|too|also|earlier|previous|like that|that one|first one|second one|show me|give me|next)\b),
      and is a long standalone prompt: return True (bypass: $0 spent).
    - Otherwise return False (run NLI parsing).
    """
    if not history:
        return True

    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return True

    has_cues = bool(CONVERSATIONAL_CUES_REGEX.search(cleaned_query))
    if has_cues:
        return False

    # Standalone prompts without conversational indicators (>= 4 words or >= 20 characters)
    is_long_standalone = len(cleaned_query.split()) >= 4 or len(cleaned_query) >= 20
    if is_long_standalone:
        return True

    return False


# ----------------------
# NLI PARSER ENGINE
# ----------------------

class NLIParser:
    """
    NLI conversational query parser using gpt-5.4-mini structured outputs.
    Resolves conversational pronouns, relative references, and negative constraints.
    """

    SYSTEM_PROMPT = (
        "You are an anime Natural Language Interface (NLI) query parser.\n"
        "Analyze multi-turn conversation history and the latest user request for anime recommendations.\n"
        "Resolve all conversational references (pronouns, relative references, exclusions, comparisons) "
        "and produce a structured query specification.\n\n"
        "Guidelines:\n"
        "1. `standalone_query`: Provide a self-contained anime search query that incorporates core "
        "themes, genres, or premises from context, resolving pronouns like 'it', 'that', 'them', or relative "
        "references like 'similar to the first one' or 'less gory'.\n"
        "   - When user asks for more (e.g. 'show me 5 more', 'next 5', 'give me more'), set intent='queue_more' and preserve the previous search theme as standalone_query.\n"
        "   - When user asks for 'more like the second one', resolve the title/ID from context, set intent='more_like'.\n"
        "2. `avoid_genres`: List explicit genres to exclude (e.g. 'less gory' -> ['Horror', 'Gore'], "
        "'no mecha' -> ['Mecha'], 'without romance' -> ['Romance'], 'less violent' -> ['Action', 'Horror', 'Gore']). Capitalize standard genre names.\n"
        "3. `avoid_tropes`: List plot tropes, narrative elements, or themes to avoid (e.g. ['harem', 'ecchi', 'isekai', 'overpowered MC', 'violence', 'gore']).\n"
        "4. `intent`: Classify user intent as 'new_search', 'refine', 'exclude_title', 'more_like', 'queue_more', or 'paginate'."
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional[OpenAI] = None,
        async_client: Optional[AsyncOpenAI] = None,
        model: str = DEFAULT_NLI_MODEL,
    ):
        self.api_key = resolve_layer_api_key("nli", api_key)
        self.model = model
        self.client = client or (get_sync_layer_client("nli", override_key=self.api_key) if self.api_key else None)
        self.async_client = async_client or (get_layer_client("nli", override_key=self.api_key) if self.api_key else None)

    def _build_messages(self, query: str, history: Optional[List[dict]] = None) -> List[dict]:
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        if history:
            for turn in history[-6:]:
                role = turn.get("role")
                content = turn.get("content")
                if role in ("user", "assistant") and content:
                    content_str = str(content)
                    if role == "assistant" and len(content_str) > 300:
                        content_str = content_str[:300] + "..."
                    messages.append({"role": role, "content": content_str})
        messages.append({"role": "user", "content": query})
        return messages

    async def parse_async(
        self,
        query: str,
        history: Optional[List[dict]] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> NLIOutput:
        """
        Asynchronously parses the conversational query into structured NLIOutput.
        Enforces a strict 3.0s timeout and records token metrics to telemetry.llm_usage.
        Falls back to raw query on error or timeout without crashing.
        """
        t0 = time.perf_counter()
        if await budget_guard.is_budget_exceeded("nli"):
            logger.warning("[NLIParser] NLI daily token budget exceeded. Bypassing NLI query rewrite ($0 spent).")
            return NLIOutput(standalone_query=query, intent="new_search")

        if not self.async_client:
            logger.warning("[NLIParser] No AsyncOpenAI client or API key available. Falling back to raw query.")
            try:
                log_llm_usage_event(
                    layer="nli",
                    model=self.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cached=False,
                    status="fallback",
                    error="No AsyncOpenAI client or API key available",
                    request_id=request_id,
                    session_id=session_id,
                )
            except Exception:
                pass
            return NLIOutput(standalone_query=query, intent="new_search")

        messages = self._build_messages(query, history)
        try:
            completion = await asyncio.wait_for(
                self.async_client.beta.chat.completions.parse(
                    model=self.model,
                    messages=messages,
                    response_format=NLIOutput,
                    max_tokens=120,
                    temperature=0.1,
                ),
                timeout=3.0,
            )
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            parsed: Optional[NLIOutput] = completion.choices[0].message.parsed
            if not parsed:
                raise ValueError("NLI model returned empty parsed completion")

            usage_obj = getattr(completion, "usage", None)
            prompt_tokens = _safe_token_count(getattr(usage_obj, "prompt_tokens", 0) if usage_obj else 0)
            completion_tokens = _safe_token_count(getattr(usage_obj, "completion_tokens", 0) if usage_obj else 0)
            total_tokens = _safe_token_count(
                getattr(usage_obj, "total_tokens", None) if usage_obj else None,
                default=prompt_tokens + completion_tokens,
            )

            try:
                log_llm_usage_event(
                    layer="nli",
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
                    await budget_guard.record_usage("nli", total_tokens)
                except Exception as b_err:
                    logger.warning(f"[NLIParser] Failed to record budget usage: {b_err}")

            return parsed

        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.warning(f"[NLIParser] NLI parsing failed or timed out ({exc}). Falling back to raw query.")
            try:
                log_llm_usage_event(
                    layer="nli",
                    model=self.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cached=False,
                    latency_ms=latency_ms,
                    status="fallback",
                    error=str(exc),
                    request_id=request_id,
                    session_id=session_id,
                )
            except Exception:
                pass
            return NLIOutput(standalone_query=query, intent="new_search")

    def parse(
        self,
        query: str,
        history: Optional[List[dict]] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> NLIOutput:
        """
        Synchronously parses conversational query into structured NLIOutput.
        Enforces a strict 3.0s timeout and records token metrics to telemetry.llm_usage.
        Falls back to raw query on error or timeout without crashing.
        """
        t0 = time.perf_counter()
        if budget_guard.is_budget_exceeded_sync("nli"):
            logger.warning("[NLIParser] NLI daily token budget exceeded. Bypassing NLI query rewrite ($0 spent).")
            return NLIOutput(standalone_query=query, intent="new_search")

        if not self.client:
            logger.warning("[NLIParser] No OpenAI client or API key available. Falling back to raw query.")
            try:
                log_llm_usage_event(
                    layer="nli",
                    model=self.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cached=False,
                    status="fallback",
                    error="No OpenAI client or API key available",
                    request_id=request_id,
                    session_id=session_id,
                )
            except Exception:
                pass
            return NLIOutput(standalone_query=query, intent="new_search")

        messages = self._build_messages(query, history)
        try:
            completion = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=messages,
                response_format=NLIOutput,
                max_tokens=120,
                temperature=0.1,
                timeout=3.0,
            )
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            parsed: Optional[NLIOutput] = completion.choices[0].message.parsed
            if not parsed:
                raise ValueError("NLI model returned empty parsed completion")

            usage_obj = getattr(completion, "usage", None)
            prompt_tokens = _safe_token_count(getattr(usage_obj, "prompt_tokens", 0) if usage_obj else 0)
            completion_tokens = _safe_token_count(getattr(usage_obj, "completion_tokens", 0) if usage_obj else 0)
            total_tokens = _safe_token_count(
                getattr(usage_obj, "total_tokens", None) if usage_obj else None,
                default=prompt_tokens + completion_tokens,
            )

            try:
                log_llm_usage_event(
                    layer="nli",
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
                    budget_guard.record_usage_sync("nli", total_tokens)
                except Exception as b_err:
                    logger.warning(f"[NLIParser] Failed to record budget usage: {b_err}")

            return parsed

        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.warning(f"[NLIParser] Sync NLI parsing failed ({exc}). Falling back to raw query.")
            try:
                log_llm_usage_event(
                    layer="nli",
                    model=self.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cached=False,
                    latency_ms=latency_ms,
                    status="fallback",
                    error=str(exc),
                    request_id=request_id,
                    session_id=session_id,
                )
            except Exception:
                pass
            return NLIOutput(standalone_query=query, intent="new_search")


# Module-level default instance
default_nli_parser = NLIParser()
