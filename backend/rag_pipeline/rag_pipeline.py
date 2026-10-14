from .helper.service_embedding import Embedder
from .helper.retrieval import DatabaseManager
from .helper.ranking import Ranker
from .helper.query_generator import QueryGenerator
from .config import config
from typing import Text
import time
import logging

logger = logging.getLogger(__name__)

PARAMS = config()

# ----------------------
# MODULE-LEVEL SINGLETONS
# Models and DB connections are loaded once at server startup, not per request.
# ----------------------

embedding = Embedder()
retriever = DatabaseManager(PARAMS=PARAMS)
reranker = Ranker()
query_generator = QueryGenerator()

# Run the one-time BM25 migration on startup.
# IF NOT EXISTS guards make this a safe no-op on subsequent calls.
retriever.ensure_bm25_index()


# ----------------------
# LOGGING & TIMING
# ----------------------

class Timer:
    def __init__(self):
        self.start = time.perf_counter()

    def elapsed(self) -> float:
        return round((time.perf_counter() - self.start) * 1000, 2)  # milliseconds


# ----------------------
# RAG PIPELINE
# ----------------------

def rag_pipeline(query: Text, top_k: int, allow_adult: bool = False):
    """
    Full Iteration 2 RAG-Fusion pipeline.

    Flow:
        1. Generation  — generate 2 hypothetical queries via gpt-5.4-mini (HyDE)
        2. Embedding   — embed all 3 queries with MiniLM + FastText
        3. Retrieval   — 9 concurrent searches (MiniLM×3, FastText×3, BM25×3)
        4. Reranking   — pool, dedup, cross-encoder score against original query
        5. Response    — franchise collapse + JSON serialisation
    """
    timings = {}

    # ----------------------
    # STEP 1: HYDE QUERY GENERATION
    # ----------------------
    t = Timer()
    
    # Self-query (LLM metadata filtering) was removed: it filtered too aggressively
    # and added API cost/latency. No extra WHERE clauses are applied to retrieval.
    extra_clauses, extra_params = [], []
    queries = query_generator.generate(user_query=query)
    
    # Kept at 0.0 so the /recommend response 'timings' shape stays backward compatible.
    timings['self_query_ms'] = 0.0
    timings['query_generation_ms'] = t.elapsed()
    
    logger.info(f"Queries for retrieval: {queries}")

    # ----------------------
    # STEP 3: EMBEDDING
    # Embed all queries — returns [(sbert, fasttext), ...] one pair per query.
    # ----------------------

    t = Timer()
    embeddings = embedding.execute(queries=queries)
    timings['embedding_ms'] = t.elapsed()

    # ----------------------
    # STEP 4: RETRIEVAL
    # 9 concurrent searches: MiniLM×3, FastText×3, BM25×3 (original + HyDE).
    # No extra metadata WHERE clauses are applied (self-query was removed).
    # Each query returns top_k=20 candidates, for a total pool of 180.
    # Returns a flat list of all candidates.
    # ----------------------

    t = Timer()
    all_results = retriever.execute(
        queries=queries,
        embeddings=embeddings,
        top_k=20,
        allow_adult=allow_adult,
        extra_clauses=extra_clauses,
        extra_params=extra_params,
    )
    timings['retrieval_ms'] = t.elapsed()

    # ----------------------
    # STEP 5 & 6: RERANKING + RESPONSE
    # Dedup, cross-encoder score against original query, franchise collapse.
    # ----------------------

    t = Timer()
    output = reranker.execute(
        user_query=query,
        all_results=all_results,
        top_k=top_k,
    )
    timings['reranking_ms'] = t.elapsed()

    return output, timings






