# backend/rag_pipeline/orchestrator.py
"""
Pipeline Orchestrator Layer (Sprint 3).

Coordinates the end-to-end conversational RAG pipeline:
1. Pre-retrieval Intent & Injection Guardrail Validation (<15ms).
2. Non-blocking Asynchronous Retrieval & Cross-Encoder Reranking.
3. Confidence Evaluation & Low-Confidence Warning Dispatch.
4. Dual-Stream Server-Sent Events (SSE) Protocol:
   - Immediate Metadata Event (Cards to UI in <1.5s TTFT).
   - Live Token-by-Token Grounded Taste Concierge Pitch Streaming.
   - Circuit Breaker Resilience: OpenAI 500 / timeout fallback keeps cards intact.
   - Starlette client disconnection monitoring (request.is_disconnected()).
"""

import json
import time
import logging
from typing import Optional, List, Dict, Any, Set, Tuple, AsyncGenerator, Callable, Awaitable
from dataclasses import dataclass, asdict

from .helper.guardrails import DomainGuardrails, GuardrailResult
from .helper.synthesizer import RecommendationSynthesizer
from .rag_pipeline import async_rag_pipeline

logger = logging.getLogger(__name__)


# ----------------------
# SSE FORMATTING HELPER
# ----------------------

def format_sse(event: str, data: Any) -> str:
    """Formats an event name and JSON-serializable data dictionary into standard SSE payload."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ----------------------
# TYPED ORCHESTRATION MODELS
# ----------------------

@dataclass
class RetrievalResult:
    candidates: List[Dict[str, Any]]
    timings: Dict[str, float]
    is_confident: bool = True
    confidence_detail: str = ""


# ----------------------
# PIPELINE ORCHESTRATOR
# ----------------------

class PipelineOrchestrator:
    """
    Coordinates Intent Validation -> Non-Blocking Retrieval -> Grounded Streaming Synthesis.
    """

    def __init__(
        self,
        guardrails: Optional[DomainGuardrails] = None,
        synthesizer: Optional[RecommendationSynthesizer] = None,
        retrieval_func: Optional[Callable[..., Awaitable[Tuple[List[Dict[str, Any]], Dict[str, float]]]]] = None,
    ):
        self.guardrails = guardrails or DomainGuardrails()
        self.synthesizer = synthesizer or RecommendationSynthesizer()
        self._retrieval_func = retrieval_func or async_rag_pipeline

    def validate_query(self, query: str) -> GuardrailResult:
        """
        Executes pre-retrieval intent and injection validation (AC 3.2).
        Guaranteed to complete in <15ms.
        """
        return self.guardrails.validate_intent(query)

    async def execute_retrieval(
        self,
        query: str,
        top_k: int = 5,
        allow_adult: bool = False,
        seen_ids: Optional[Set[int]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
        """
        Executes non-blocking retrieval and cross-encoder reranking.
        Returns candidate anime list and latency timings dictionary.
        """
        candidates, timings = await self._retrieval_func(
            query=query,
            top_k=top_k,
            allow_adult=allow_adult,
            seen_ids=seen_ids,
            include_metadata=True,
        )
        return candidates, timings

    async def stream_chat(
        self,
        query: str,
        top_k: int = 5,
        allow_adult: bool = False,
        seen_ids: Optional[Set[int]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        is_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Dual-Stream SSE generator powering POST /chat.

        Emits:
        1. event: error    (if pre-retrieval validation fails, <15ms)
        2. event: warning  (if retrieval confidence is low, score < -6.5)
        3. event: metadata (immediate candidate anime cards, TTFT < 1.5s)
        4. event: token    (streamed tokens of personalized pitch, spoiler-scrubbed)
        5. event: done     (final end-to-end timings and metrics)
        """
        stream_start = time.perf_counter()
        pipeline_timings: Dict[str, float] = {}

        # ---------------------------------------------------------
        # STEP 1: PRE-RETRIEVAL GUARDRAIL VALIDATION (<15ms, AC 3.2)
        # ---------------------------------------------------------
        t0 = time.perf_counter()
        validation = self.validate_query(query)
        validation_ms = round((time.perf_counter() - t0) * 1000, 2)
        pipeline_timings["guardrail_validation_ms"] = validation_ms

        if not validation.is_valid:
            logger.info(
                f"[PipelineOrchestrator] Query rejected by guardrail: '{query}' "
                f"[{validation.category}]: {validation.detail} in {validation_ms:.2f}ms"
            )
            yield format_sse("error", {
                "detail": validation.detail,
                "category": validation.category,
                "validation_ms": validation_ms,
            })
            return

        # Check client disconnection before starting expensive retrieval
        if is_disconnected and await is_disconnected():
            logger.info("[PipelineOrchestrator] Client disconnected before retrieval; aborting.")
            return

        # ---------------------------------------------------------
        # STEP 2: ASYNC RETRIEVAL & CROSS-ENCODER RERANKING
        # ---------------------------------------------------------
        t_retrieval_start = time.perf_counter()
        try:
            candidates, retrieval_timings = await self.execute_retrieval(
                query=query,
                top_k=top_k,
                allow_adult=allow_adult,
                seen_ids=seen_ids,
            )
            pipeline_timings.update(retrieval_timings)
        except Exception as e:
            logger.exception("[PipelineOrchestrator] Retrieval pipeline failure")
            yield format_sse("error", {
                "detail": "Failed to retrieve anime recommendations. Please try again shortly.",
                "error": str(e),
            })
            return

        total_retrieval_ms = round((time.perf_counter() - t_retrieval_start) * 1000, 2)
        pipeline_timings["total_retrieval_ms"] = total_retrieval_ms

        # Check client disconnection before streaming
        if is_disconnected and await is_disconnected():
            logger.info("[PipelineOrchestrator] Client disconnected after retrieval; aborting.")
            return

        # ---------------------------------------------------------
        # STEP 3: CONFIDENCE THRESHOLDING (< -6.5 CHECK)
        # ---------------------------------------------------------
        is_confident, confidence_msg = self.guardrails.check_retrieval_confidence(candidates)
        if not is_confident:
            logger.warning(f"[PipelineOrchestrator] Low retrieval confidence: {confidence_msg}")
            yield format_sse("warning", {
                "warning": "Low retrieval confidence",
                "detail": confidence_msg,
                "top_score": candidates[0].get("cross_encoder_score") if candidates else None,
            })

        # ---------------------------------------------------------
        # STEP 4: IMMEDIATE METADATA EVENT (TTFT < 1.5s, AC 3.1)
        # ---------------------------------------------------------
        ttft_ms = round((time.perf_counter() - stream_start) * 1000, 2)
        pipeline_timings["ttft_metadata_ms"] = ttft_ms

        yield format_sse("metadata", {
            "query": query,
            "count": len(candidates),
            "candidates": candidates,
            "timings": pipeline_timings,
        })

        # ---------------------------------------------------------
        # STEP 5: STREAMING TASTE CONCIERGE SYNTHESIS (AC 3.3)
        # ---------------------------------------------------------
        t_synth_start = time.perf_counter()
        tokens_emitted = 0

        try:
            async for token_chunk in self.synthesizer.stream_pitch(
                query=query,
                candidates=candidates,
                conversation_history=conversation_history,
                is_disconnected=is_disconnected,
            ):
                if is_disconnected and await is_disconnected():
                    logger.info("[PipelineOrchestrator] Client disconnected during token stream; stopping.")
                    return

                if token_chunk:
                    tokens_emitted += 1
                    scrubbed_chunk = self.guardrails.scrub_spoilers(token_chunk)
                    yield format_sse("token", {"text": scrubbed_chunk})


        except Exception as e:
            logger.exception(f"[PipelineOrchestrator] Uncaught exception in synthesis stream: {e}")
            yield format_sse("token", {"text": "\n(Recommendations loaded from catalog.)"})

        synth_ms = round((time.perf_counter() - t_synth_start) * 1000, 2)
        pipeline_timings["synthesis_ms"] = synth_ms
        pipeline_timings["total_duration_ms"] = round((time.perf_counter() - stream_start) * 1000, 2)

        # ---------------------------------------------------------
        # STEP 6: DONE EVENT
        # ---------------------------------------------------------
        yield format_sse("done", {
            "status": "completed",
            "tokens_emitted": tokens_emitted,
            "timings": pipeline_timings,
        })


# Module singleton for production FastAPI dispatch
orchestrator = PipelineOrchestrator()
