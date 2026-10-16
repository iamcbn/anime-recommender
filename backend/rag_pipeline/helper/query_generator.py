import os
import logging
import asyncio
import httpx
from openai import OpenAI, AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, AsyncRetrying
from .llm_cache import llm_cache

logger = logging.getLogger(__name__)

MODEL = "gpt-5.4-mini"

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

    def __init__(self, api_key: str = None):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY not found. Please add it to your .env file."
            )
        self.api_key = api_key

        # Bounded HTTP connection pools to prevent socket exhaustion under high concurrency
        self._http_client = httpx.Client(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=httpx.Timeout(10.0, connect=3.0),
        )
        self._async_http_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            timeout=httpx.Timeout(10.0, connect=3.0),
        )

        self.client = OpenAI(api_key=api_key, http_client=self._http_client)
        self.async_client = AsyncOpenAI(api_key=api_key, http_client=self._async_http_client)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _generate_impl(self, user_query: str) -> list[str]:
        cache_key = f"hyde_v1_{user_query}"
        cached = llm_cache.get(cache_key)
        if cached:
            logger.info(f"Loaded HyDE queries from local cache for: '{user_query}'")
            return cached

        completion = self.client.beta.chat.completions.parse(
            model=MODEL,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_query},
            ],
            response_format=HypotheticalQueries,
        )
        result = completion.choices[0].message.parsed
        queries = [user_query, result.query_b, result.query_c]
        logger.info(f"Generated {len(queries)} queries via OpenAI for: '{user_query}'")

        llm_cache.set(cache_key, queries)
        return queries

    def generate(self, user_query: str) -> list[str]:
        """
        Synchronous query generation.
        Returns:
            [original_query, query_b, query_c] on success, or [original_query] on fallback.
        """
        try:
            return self._generate_impl(user_query)
        except Exception:
            logger.exception("Query generation failed. Falling back to original query only.")
            return [user_query]

    async def _generate_async_impl(self, user_query: str) -> list[str]:
        cache_key = f"hyde_v1_{user_query}"
        cached = llm_cache.get(cache_key)
        if cached:
            logger.info(f"Loaded HyDE queries from local cache for: '{user_query}'")
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
                result = completion.choices[0].message.parsed
                queries = [user_query, result.query_b, result.query_c]
                logger.info(f"Generated {len(queries)} queries via AsyncOpenAI for: '{user_query}'")
                llm_cache.set(cache_key, queries)
                return queries

        return [user_query]

    async def generate_async(self, user_query: str) -> list[str]:
        """
        Non-blocking asynchronous HyDE query generation using AsyncOpenAI.
        Guarantees that the event loop yields during network wait.
        Returns:
            [original_query, query_b, query_c] on success, or [original_query] on failure/timeout.
        """
        try:
            return await self._generate_async_impl(user_query)
        except Exception:
            logger.exception("Async query generation failed. Falling back to original query only.")
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
