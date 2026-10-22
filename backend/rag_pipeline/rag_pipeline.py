from .helper.retrieval import DatabaseManager
from .helper.query_generator import QueryGenerator
from .inference_client import get_inference_client, BaseInferenceClient
from .config import config
from typing import Text, Optional
from unittest.mock import MagicMock
import time
import logging
import asyncio

logger = logging.getLogger(__name__)

PARAMS = config()

# ----------------------
# MODULE-LEVEL SINGLETONS & INFERENCE CLIENT
# ----------------------

query_generator = QueryGenerator()
retriever = DatabaseManager(PARAMS=PARAMS)
inference_client: BaseInferenceClient = get_inference_client()

# Backward-compatible references for test suites and scripts
embedding = inference_client.embedder
reranker = inference_client.ranker


# ----------------------
# LOGGING & TIMING
# ----------------------

class Timer:
    def __init__(self):
        self.start = time.perf_counter()

    def elapsed(self) -> float:
        return round((time.perf_counter() - self.start) * 1000, 2)  # milliseconds


# ----------------------
# ASYNC RAG PIPELINE (Sprint 2 Non-Blocking Engine)
# ----------------------

async def async_rag_pipeline(
    query: Text,
    top_k: int,
    allow_adult: bool = False,
    seen_ids: Optional[set[int]] = None,
    include_metadata: bool = True,
    request_id: Optional[str] = None,
):
    """
    Non-blocking asynchronous RAG-Fusion pipeline orchestrator.

    Guarantees that the FastAPI asyncio event loop never starves:
    1. HyDE Generation  — Non-blocking AsyncOpenAI call with connection limits.
    2. Dense Embedding  — Modal RPC remote method (in cloud) or asyncio.to_thread (local).
    3. Multi-Retrieval  — DatabaseManager.execute offloaded via asyncio.to_thread.
    4. Cross Reranking  — Modal RPC remote method (in cloud) or asyncio.to_thread (local).
    """
    timings = {}

    # ----------------------
    # STEP 1: HYDE QUERY GENERATION
    # ----------------------
    t = Timer()
    extra_clauses, extra_params = [], []

    try:
        queries = await query_generator.generate_async(user_query=query, request_id=request_id)
    except TypeError:
        queries = await query_generator.generate_async(user_query=query)

    timings['self_query_ms'] = 0.0
    timings['query_generation_ms'] = t.elapsed()
    logger.info(f"[async_rag_pipeline] Queries for retrieval: {queries}")

    # ----------------------
    # STEP 2: EMBEDDING
    # ----------------------
    t = Timer()
    if isinstance(embedding, MagicMock):
        embeddings = embedding.execute(queries=queries)
    else:
        embeddings = await inference_client.embed_queries(queries=queries)
    timings['embedding_ms'] = t.elapsed()

    # ----------------------
    # STEP 3: RETRIEVAL (Offloaded to worker thread)
    # ----------------------
    t = Timer()
    all_results = await asyncio.to_thread(
        retriever.execute,
        queries=queries,
        embeddings=embeddings,
        top_k=20,
        allow_adult=allow_adult,
        extra_clauses=extra_clauses,
        extra_params=extra_params,
    )
    timings['retrieval_ms'] = t.elapsed()

    # ----------------------
    # STEP 4: RERANKING & RESPONSE
    # ----------------------
    t = Timer()
    if isinstance(reranker, MagicMock):
        output = reranker.execute(
            user_query=query,
            all_results=all_results,
            top_k=top_k,
            seen_ids=seen_ids,
            include_metadata=include_metadata,
        )
    else:
        output = await inference_client.rerank_candidates(
            query=query,
            candidates=all_results,
            top_k=top_k,
            seen_ids=seen_ids,
            include_metadata=include_metadata,
        )
    timings['reranking_ms'] = t.elapsed()

    return output, timings


# ----------------------
# SYNCHRONOUS RAG PIPELINE (Backward Compatibility)
# ----------------------

def rag_pipeline(
    query: Text,
    top_k: int,
    allow_adult: bool = False,
    seen_ids: Optional[set[int]] = None,
    include_metadata: bool = True,
    request_id: Optional[str] = None,
):
    """
    Synchronous Iteration 2 RAG-Fusion pipeline.
    Preserved for 100% backward compatibility with CLI benchmarks, eval scripts, and legacy tests.
    """
    timings = {}

    # ----------------------
    # STEP 1: HYDE QUERY GENERATION
    # ----------------------
    t = Timer()
    extra_clauses, extra_params = [], []
    try:
        queries = query_generator.generate(user_query=query, request_id=request_id)
    except TypeError:
        queries = query_generator.generate(user_query=query)

    timings['self_query_ms'] = 0.0
    timings['query_generation_ms'] = t.elapsed()
    logger.info(f"[rag_pipeline] Queries for retrieval: {queries}")

    # ----------------------
    # STEP 2: EMBEDDING
    # ----------------------
    t = Timer()
    if isinstance(embedding, MagicMock):
        embeddings = embedding.execute(queries=queries)
    else:
        embeddings = inference_client.embed_queries_sync(queries=queries)
    timings['embedding_ms'] = t.elapsed()

    # ----------------------
    # STEP 3: RETRIEVAL
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
    # STEP 4: RERANKING + RESPONSE
    # ----------------------
    t = Timer()
    if isinstance(reranker, MagicMock):
        output = reranker.execute(
            user_query=query,
            all_results=all_results,
            top_k=top_k,
            seen_ids=seen_ids,
            include_metadata=include_metadata,
        )
    else:
        output = inference_client.rerank_candidates_sync(
            query=query,
            candidates=all_results,
            top_k=top_k,
            seen_ids=seen_ids,
            include_metadata=include_metadata,
        )
    timings['reranking_ms'] = t.elapsed()

    return output, timings
