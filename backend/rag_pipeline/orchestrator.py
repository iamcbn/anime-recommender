# backend/rag_pipeline/orchestrator.py
"""
Pipeline Orchestrator Layer (Sprint 3 & Sprint 4).

Coordinates the end-to-end conversational RAG pipeline:
1. Pre-retrieval Intent & Injection Guardrail Validation (<15ms).
2. Distributed State Management (Upstash Redis):
   - Multi-turn conversation context retrieval (rolling 5 turns).
   - Long-term watched / already recommended title exclusion sets.
3. Non-blocking Asynchronous Retrieval & Cross-Encoder Reranking with O(1) seen title filtering.
4. Confidence Evaluation & Low-Confidence Warning Dispatch.
5. Dual-Stream Server-Sent Events (SSE) Protocol:
   - Immediate Metadata Event (Cards to UI in <1.5s TTFT, including session_id).
   - Live Token-by-Token Grounded Taste Concierge Pitch Streaming with conversation context.
   - Immediate candidate ID exclusion recording in Redis.
   - Turn persistence to session history upon stream completion.
   - Circuit Breaker Resilience: OpenAI 500 / timeout fallback keeps cards intact.
   - Starlette client disconnection monitoring (request.is_disconnected()).
"""

import json
import time
import uuid
import logging
from typing import Optional, List, Dict, Any, Set, Tuple, AsyncGenerator, Callable, Awaitable
from dataclasses import dataclass

from .helper.guardrails import DomainGuardrails, GuardrailResult
from .helper.synthesizer import RecommendationSynthesizer
from .helper.state_manager import StateManager, state_manager as default_state_manager
from .rag_pipeline import async_rag_pipeline

logger = logging.getLogger("anime_recommender.orchestrator")


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
    Coordinates Intent Validation -> State Lookup -> Non-Blocking Retrieval -> Grounded Streaming Synthesis -> State Commit.
    """

    def __init__(
        self,
        guardrails: Optional[DomainGuardrails] = None,
        synthesizer: Optional[RecommendationSynthesizer] = None,
        state_manager: Optional[StateManager] = None,
        retrieval_func: Optional[Callable[..., Awaitable[Tuple[List[Dict[str, Any]], Dict[str, float]]]]] = None,
    ):
        self.guardrails = guardrails or DomainGuardrails()
        self.synthesizer = synthesizer or RecommendationSynthesizer()
        self.state_manager = state_manager if state_manager is not None else default_state_manager
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
        Filters seen_ids via O(1) set subtraction in Ranker.merge_deduplicate.
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
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        is_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Dual-Stream SSE generator powering POST /chat (Sprint 3 & Sprint 4).

        Emits:
        1. event: error    (if pre-retrieval validation fails, <15ms)
        2. event: warning  (if retrieval confidence is low, score < -6.5)
        3. event: metadata (immediate candidate anime cards, TTFT < 1.5s, session_id attached)
        4. event: token    (streamed tokens of personalized pitch, spoiler-scrubbed)
        5. event: done     (final end-to-end timings, token counts, and session metrics)
        """
        stream_start = time.perf_counter()
        stream_start_epoch = time.time()
        pipeline_timings: Dict[str, float] = {}

        # ---------------------------------------------------------
        # STEP 0: SESSION & IDENTITY RESOLUTION
        # ---------------------------------------------------------
        active_session_id = session_id or str(uuid.uuid4())
        active_user_id = user_id or f"anon:{active_session_id}"

        try:
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
                    "session_id": active_session_id,
                    "validation_ms": validation_ms,
                })
                return

            # Check client disconnection before starting expensive operations
            if is_disconnected and await is_disconnected():
                logger.info("[PipelineOrchestrator] Client disconnected before state lookup; aborting.")
                return

            # ---------------------------------------------------------
            # STEP 2: STATE MANAGER LOOKUPS (History & Seen IDs)
            # ---------------------------------------------------------
            t_state_start = time.perf_counter()
            active_history = conversation_history

            if active_history is None and self.state_manager is not None:
                try:
                    active_history = await self.state_manager.get_session_history(active_session_id)
                except Exception as exc:
                    logger.warning(f"[PipelineOrchestrator] Session history lookup failed: {exc}; using empty.")
                    active_history = []
            elif active_history is None:
                active_history = []

            # Retrieve cumulative seen IDs: request seen_ids + Redis persistent seen_ids
            cumulative_seen_ids: Set[int] = set(seen_ids) if seen_ids else set()
            if self.state_manager is not None:
                try:
                    persisted_seen = await self.state_manager.get_excluded_ids(active_user_id)
                    cumulative_seen_ids.update(persisted_seen)
                except Exception as exc:
                    logger.warning(f"[PipelineOrchestrator] Excluded IDs lookup failed: {exc}")

            state_lookup_ms = round((time.perf_counter() - t_state_start) * 1000, 2)
            pipeline_timings["state_lookup_ms"] = state_lookup_ms

            # ---------------------------------------------------------
            # STEP 3: ASYNC RETRIEVAL & CROSS-ENCODER RERANKING
            # ---------------------------------------------------------
            t_retrieval_start = time.perf_counter()
            try:
                candidates, retrieval_timings = await self.execute_retrieval(
                    query=query,
                    top_k=top_k,
                    allow_adult=allow_adult,
                    seen_ids=cumulative_seen_ids,
                )
                pipeline_timings.update(retrieval_timings)
            except Exception as e:
                logger.exception("[PipelineOrchestrator] Retrieval pipeline failure")
                yield format_sse("error", {
                    "detail": "Failed to retrieve anime recommendations. Please try again shortly.",
                    "error": str(e),
                    "session_id": active_session_id,
                })
                return

            total_retrieval_ms = round((time.perf_counter() - t_retrieval_start) * 1000, 2)
            pipeline_timings["total_retrieval_ms"] = total_retrieval_ms

            # ---------------------------------------------------------
            # STEP 4: RECORD NEW SEEN IDS TO REDIS (AC 4.2)
            # ---------------------------------------------------------
            newly_recommended_ids = [c["id"] for c in candidates if isinstance(c, dict) and "id" in c]
            if newly_recommended_ids and self.state_manager is not None:
                try:
                    await self.state_manager.record_seen_ids(active_user_id, newly_recommended_ids)
                except Exception as exc:
                    logger.warning(f"[PipelineOrchestrator] Failed to commit seen IDs: {exc}")

            # Check client disconnection before streaming
            if is_disconnected and await is_disconnected():
                logger.info("[PipelineOrchestrator] Client disconnected after retrieval; aborting.")
                return

            # ---------------------------------------------------------
            # STEP 5: CONFIDENCE THRESHOLDING (< -6.5 CHECK)
            # ---------------------------------------------------------
            is_confident, confidence_msg = self.guardrails.check_retrieval_confidence(candidates)
            if not is_confident:
                logger.warning(f"[PipelineOrchestrator] Low retrieval confidence: {confidence_msg}")
                yield format_sse("warning", {
                    "warning": "Low retrieval confidence",
                    "detail": confidence_msg,
                    "top_score": candidates[0].get("cross_encoder_score") if candidates else None,
                    "session_id": active_session_id,
                })

            # ---------------------------------------------------------
            # STEP 6: IMMEDIATE METADATA EVENT (TTFT < 1.5s, AC 3.1)
            # ---------------------------------------------------------
            ttft_ms = round((time.perf_counter() - stream_start) * 1000, 2)
            pipeline_timings["ttft_metadata_ms"] = ttft_ms

            yield format_sse("metadata", {
                "query": query,
                "session_id": active_session_id,
                "user_id": active_user_id,
                "count": len(candidates),
                "candidates": candidates,
                "timings": pipeline_timings,
            })

            # ---------------------------------------------------------
            # STEP 7: STREAMING TASTE CONCIERGE SYNTHESIS (AC 3.3)
            # ---------------------------------------------------------
            t_synth_start = time.perf_counter()
            tokens_emitted = 0
            accumulated_pitch_chunks: List[str] = []

            try:
                async for token_chunk in self.synthesizer.stream_pitch(
                    query=query,
                    candidates=candidates,
                    conversation_history=active_history,
                    is_disconnected=is_disconnected,
                ):
                    if is_disconnected and await is_disconnected():
                        logger.info("[PipelineOrchestrator] Client disconnected during token stream; stopping.")
                        return

                    if token_chunk:
                        tokens_emitted += 1
                        scrubbed_chunk = self.guardrails.scrub_spoilers(token_chunk)
                        accumulated_pitch_chunks.append(scrubbed_chunk)
                        yield format_sse("token", {"text": scrubbed_chunk})

            except Exception as e:
                logger.exception(f"[PipelineOrchestrator] Uncaught exception in synthesis stream: {e}")
                fallback_msg = "\n(Recommendations loaded from catalog.)"
                accumulated_pitch_chunks.append(fallback_msg)
                yield format_sse("token", {"text": fallback_msg})

            synth_ms = round((time.perf_counter() - t_synth_start) * 1000, 2)
            pipeline_timings["synthesis_ms"] = synth_ms
            pipeline_timings["total_duration_ms"] = round((time.perf_counter() - stream_start) * 1000, 2)

            # ---------------------------------------------------------
            # STEP 8: COMMIT CONVERSATION TURN TO STATE MANAGER (AC 4.1)
            # ---------------------------------------------------------
            if self.state_manager is not None:
                try:
                    full_pitch = "".join(accumulated_pitch_chunks).strip()
                    turns_to_commit = [
                        {"role": "user", "content": query, "timestamp": stream_start_epoch},
                        {
                            "role": "assistant",
                            "content": full_pitch or "(Recommendations provided)",
                            "recommended_ids": newly_recommended_ids,
                            "timestamp": time.time(),
                        },
                    ]
                    await self.state_manager.append_session_turn(active_session_id, turns_to_commit)
                except Exception as exc:
                    logger.warning(f"[PipelineOrchestrator] Failed to commit session turns: {exc}")

            # ---------------------------------------------------------
            # STEP 9: DONE EVENT
            # ---------------------------------------------------------
            yield format_sse("done", {
                "status": "completed",
                "session_id": active_session_id,
                "user_id": active_user_id,
                "tokens_emitted": tokens_emitted,
                "timings": pipeline_timings,
            })

        except GeneratorExit:
            logger.info(f"[PipelineOrchestrator] Stream cancelled by client for session {active_session_id}")
        except Exception as e:
            logger.exception(f"[PipelineOrchestrator] Unexpected stream failure: {e}")
            yield format_sse("error", {
                "detail": "An unexpected error occurred during chat streaming.",
                "error": str(e),
                "session_id": active_session_id,
            })


# Module singleton for production FastAPI dispatch
orchestrator = PipelineOrchestrator()
