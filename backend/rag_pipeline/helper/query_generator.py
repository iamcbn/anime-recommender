import os
import logging
import json
from openai import OpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential
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

    Returns the original query plus two generated queries for a total of 3
    queries that feed into the multi-query retrieval step.
    """

    SYSTEM_PROMPT = (
        "You are an expert anime recommender. Given a user search query, "
        "generate exactly 2 different hypothetical anime descriptions that "
        "would perfectly match what the user is looking for. "
        "Each description should be 2-3 sentences, written as if it were "
        "an actual anime synopsis. Focus on plot, themes, and setting. "
        "Do NOT mention titles. Do NOT repeat the same ideas."
    )

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY not found. Please add it to your .env file."
            )
        self.client = OpenAI(api_key=api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _generate_impl(self, user_query: str) -> list[str]:
        cache_key = f"hyde_v1_{user_query}"
        cached = llm_cache.get(cache_key)
        if cached:
            logger.info(f"Loaded HyDE queries from local cache for: '{user_query}'")
            return cached

        completion = self.client.beta.chat.completions.parse(
            model= MODEL,
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
        Generates two hypothetical anime descriptions for the given query.

        Returns:
            A list of 3 strings: [original_query, query_b, query_c]
            If generation fails, returns only [original_query] so the
            pipeline degrades gracefully to single-query retrieval.
        """
        try:
            return self._generate_impl(user_query)
        except Exception:
            logger.exception("Query generation failed. Falling back to original query only.")
            return [user_query]
