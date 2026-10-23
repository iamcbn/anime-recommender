import time
import logging
import asyncio
from typing import Optional, Any
import httpx
from openai import OpenAI, AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, AsyncRetrying
from .llm_cache import llm_cache
from .llm_clients import resolve_layer_api_key
from .budget_guard import budget_guard
from backend.telemetry.logger import log_llm_usage_event

logger = logging.getLogger(__name__)

MODEL = "gpt-5.4-mini"


def _safe_token_count(val: Any, default: int = 0) -> int:
    """Safely extracts integer token counts, shielding against MagicMock or non-numeric types."""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return int(val)
    return default


# ----------------------
# PYDANTIC RESPONSE SCHEMA
# ----------------------

class HypotheticalQueries(BaseModel):
    query_b: str
    query_c: str


# ----------------------
# GENERATOR
# ----------------------

class QueryGenerator:
    """
    Uses gpt-5.4-mini to generate two hypothetical anime descriptions (HyDE)
    based on the user original query.

    Provides both non-blocking async (`generate_async`) and synchronous (`generate`) interfaces.
    Uses dedicated httpx connection pooling with limits to prevent socket leaks under concurrent load.
    """

    SYSTEM_PROMPT = (
        "You are an expert anime recommender. Given a user search query, "
        "generate exactly 2 different hypothetical anime descriptions that "
        "would perfectly match what the user is looking for. "
        "Each description should be 2-3 sentences, written as if it were "
        "an actual anime synopsis. Focus on plot, themes, and setting. "
        "Do NOT mention titles. Do NOT repeat the same ideas."
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional[OpenAI] = None,
        async_client: Optional[AsyncOpenAI] = None,
    ):
        resolved_key = resolve_layer_api_key("retrieval", api_key)
        if not resolved_key and client is None and async_client is None:
            raise EnvironmentError(
                "OPENAI_API_KEY_RETRIEVAL (or OPENAI_API_KEY) not found. Please add it to your .env file."
            )
        self.api_key = resolved_key

        # Bounded HTTP connection pools to prevent socket exhaustion under high concurrency
        self._http_client = httpx.Client(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=httpx.Timeout(10.0, connect=3.0),
        )
        self._async_http_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            timeout=httpx.Timeout(10.0, connect=3.0),
        )

        self.client = client or (OpenAI(api_key=self.api_key, http_client=self._http_client) if self.api_key else None)
        self.async_client = async_client or (AsyncOpenAI(api_key=self.api_key, http_client=self._async_http_client) if self.api_key else None)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _generate_impl(self, user_query: str, request_id: Optional[str] = None) -> list[str]:
        t0 = time.perf_counter()
        cache_key = f"hyde_v1_{user_query}"
        cached = llm_cache.get(cache_key)
        if cached:
            logger.info(f"Loaded HyDE queries from local cache for: '{user_query}'")
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            try:
                log_llm_usage_event(
                    layer="retrieval",
                    model=MODEL,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cached=True,
                    latency_ms=latency_ms,
                    status="cached",
                    request_id=request_id,
                )
            except Exception:
                pass
            return cached

        completion = self.client.beta.chat.completions.parse(
            model=MODEL,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_query},
            ],
            response_format=HypotheticalQueries,
        )
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        result = completion.choices[0].message.parsed
        queries = [user_query, result.query_b, result.query_c]
        logger.info(f"Generated {len(queries)} queries via OpenAI for: '{user_query}'")

        llm_cache.set(cache_key, queries)

        usage_obj = getattr(completion, "usage", None)
        prompt_tokens = _safe_token_count(getattr(usage_obj, "prompt_tokens", 0) if usage_obj else 0)
        completion_tokens = _safe_token_count(getattr(usage_obj, "completion_tokens", 0) if usage_obj else 0)
        total_tokens = _safe_token_count(
            getattr(usage_obj, "total_tokens", None) if usage_obj else None,
            default=prompt_tokens + completion_tokens,
        )
        try:
            log_llm_usage_event(
                layer="retrieval",
                model=MODEL,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cached=False,
                latency_ms=latency_ms,
                status="ok",
                request_id=request_id,
            )
        except Exception:
            pass

        if total_tokens > 0:
            try:
                budget_guard.record_usage_sync("retrieval", total_tokens)
            except Exception as b_err:
                logger.warning(f"[QueryGenerator] Failed to record budget usage: {b_err}")

        return queries

    def generate(self, user_query: str, request_id: Optional[str] = None) -> list[str]:
        """
        Synchronous query generation.
        Returns:
            [original_query, query_b, query_c] on success, or [original_query] on fallback.
        """
        try:
            if budget_guard.is_budget_exceeded_sync("retrieval"):
                logger.warning(
                    f"[QueryGenerator] Retrieval daily token budget exceeded! "
                    f"Skipping HyDE expansion; returning raw query directly ($0 HyDE tokens)."
                )
                return [user_query]
            return self._generate_impl(user_query, request_id=request_id)
        except Exception as exc:
            logger.exception("Query generation failed. Falling back to original query only.")
            try:
                log_llm_usage_event(
                    layer="retrieval",
                    model=MODEL,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cached=False,
                    status="fallback",
                    error=str(exc),
                    request_id=request_id,
                )
            except Exception:
                pass
            return [user_query]

    async def _generate_async_impl(self, user_query: str, request_id: Optional[str] = None) -> list[str]:
        t0 = time.perf_counter()
        cache_key = f"hyde_v1_{user_query}"
        cached = llm_cache.get(cache_key)
        if cached:
            logger.info(f"Loaded HyDE queries from local cache for: '{user_query}'")
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            try:
                log_llm_usage_event(
                    layer="retrieval",
                    model=MODEL,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cached=True,
                    latency_ms=latency_ms,
                    status="cached",
                    request_id=request_id,
                )
            except Exception:
                pass
            return cached

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=5),
            reraise=True,
        ):
            with attempt:
                completion = await asyncio.wait_for(
                    self.async_client.beta.chat.completions.parse(
                        model=MODEL,
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": user_query},
                        ],
                        response_format=HypotheticalQueries,
                    ),
                    timeout=5.0,
                )
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                result = completion.choices[0].message.parsed
                queries = [user_query, result.query_b, result.query_c]
                logger.info(f"Generated {len(queries)} queries via AsyncOpenAI for: '{user_query}'")
                llm_cache.set(cache_key, queries)

                usage_obj = getattr(completion, "usage", None)
                prompt_tokens = _safe_token_count(getattr(usage_obj, "prompt_tokens", 0) if usage_obj else 0)
                completion_tokens = _safe_token_count(getattr(usage_obj, "completion_tokens", 0) if usage_obj else 0)
                total_tokens = _safe_token_count(
                    getattr(usage_obj, "total_tokens", None) if usage_obj else None,
                    default=prompt_tokens + completion_tokens,
                )
                try:
                    log_llm_usage_event(
                        layer="retrieval",
                        model=MODEL,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        cached=False,
                        latency_ms=latency_ms,
                        status="ok",
                        request_id=request_id,
                    )
                except Exception:
                    pass

                if total_tokens > 0:
                    try:
                        await budget_guard.record_usage("retrieval", total_tokens)
                    except Exception as b_err:
                        logger.warning(f"[QueryGenerator] Failed to record budget usage: {b_err}")

                return queries

        return [user_query]

    async def generate_async(self, user_query: str, request_id: Optional[str] = None) -> list[str]:
        """
        Non-blocking asynchronous HyDE query generation using AsyncOpenAI.
        Guarantees that the event loop yields during network wait.
        Returns:
            [original_query, query_b, query_c] on success, or [original_query] on failure/timeout.
        """
        try:
            if await budget_guard.is_budget_exceeded("retrieval"):
                logger.warning(
                    f"[QueryGenerator] Retrieval daily token budget exceeded! "
                    f"Skipping HyDE expansion; returning raw query directly ($0 HyDE tokens)."
                )
                return [user_query]
            return await self._generate_async_impl(user_query, request_id=request_id)
        except Exception as exc:
            logger.exception("Async query generation failed. Falling back to original query only.")
            try:
                log_llm_usage_event(
                    layer="retrieval",
                    model=MODEL,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cached=False,
                    status="fallback",
                    error=str(exc),
                    request_id=request_id,
                )
            except Exception:
                pass
            return [user_query]

    def close(self):
        """Close synchronous HTTP connection pool."""
        try:
            self._http_client.close()
        except Exception:
            pass

    async def aclose(self):
        """Close asynchronous HTTP connection pool."""
        try:
            await self._async_http_client.aclose()
        except Exception:
            pass
        self.close()
