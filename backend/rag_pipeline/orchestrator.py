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
import asyncio
import logging
from typing import Optional, List, Dict, Any, Set, Tuple, AsyncGenerator, Callable, Awaitable
from dataclasses import dataclass

from .helper.guardrails import DomainGuardrails, GuardrailResult
from .helper.synthesizer import (
    RecommendationSynthesizer,
    StreamingCitationBuffer,
)
from .helper.state_manager import StateManager, state_manager as default_state_manager
from .helper.nli_parser import NLIParser, should_bypass_nli, default_nli_parser
from .helper.ranking import filter_candidates_by_negative_constraints
from .helper.budget_guard import budget_guard
from .rag_pipeline import async_rag_pipeline
import backend.telemetry.logger as telemetry_logger
from backend.telemetry.logger import strip_scores, sanitize_for_json

logger = logging.getLogger("anime_recommender.orchestrator")


# ----------------------
# SSE FORMATTING HELPER
# ----------------------

def format_sse(event: str, data: Any) -> str:
    """Formats an event name and JSON-serializable data dictionary into standard SSE payload."""
    payload = json.dumps(sanitize_for_json(data), ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


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
        nli_parser: Optional[NLIParser] = None,
    ):
        self.guardrails = guardrails or DomainGuardrails()
        self.synthesizer = synthesizer or RecommendationSynthesizer()
        self.state_manager = state_manager if state_manager is not None else default_state_manager
        self._retrieval_func = retrieval_func or async_rag_pipeline
        self.nli_parser = nli_parser or default_nli_parser

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
        request_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
        """
        Executes non-blocking retrieval and cross-encoder reranking.
        Filters seen_ids via O(1) set subtraction in Ranker.merge_deduplicate.
        Returns candidate anime list and latency timings dictionary.
        """
        try:
            candidates, timings = await self._retrieval_func(
                query=query,
                top_k=top_k,
                allow_adult=allow_adult,
                seen_ids=seen_ids,
                include_metadata=True,
                request_id=request_id,
            )
        except TypeError:
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
        api_key_id: Optional[str] = None,
        request_id: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        client_metadata: Optional[Dict[str, Any]] = None,
        avoid_genres: Optional[List[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Dual-Stream SSE generator powering POST /chat (Sprint 3 & Sprint 4).

        Emits:
        1. event: error    (if pre-retrieval validation fails, <15ms)
        2. event: warning  (if retrieval confidence is low, score < -6.5; top_score stripped at SSE serialization)
        3. event: metadata (immediate candidate anime cards with scores stripped at SSE serialization, TTFT < 1.5s)
        4. event: token    (streamed tokens of personalized pitch, spoiler-scrubbed)
        5. event: done     (final end-to-end timings, token counts, and session metrics)

        Logs telemetry once per turn after the stream ends via asyncio.to_thread.
        """
        stream_start = time.perf_counter()
        stream_start_epoch = time.time()
        pipeline_timings: Dict[str, float] = {}

        # ---------------------------------------------------------
        # STEP 0: SESSION & IDENTITY RESOLUTION
        # ---------------------------------------------------------
        active_session_id = session_id or str(uuid.uuid4())
        active_user_id = user_id or f"anon:{active_session_id}"
        active_request_id = request_id or str(uuid.uuid4())

        candidates: List[Dict[str, Any]] = []
        log_status = "ok"
        log_status_code = 200
        log_error: Optional[str] = None

        try:
            # ---------------------------------------------------------
            # STEP 1: PRE-RETRIEVAL GUARDRAIL VALIDATION (<15ms, AC 3.2)
            # ---------------------------------------------------------
            t0 = time.perf_counter()
            validation = self.validate_query(query)
            validation_ms = round((time.perf_counter() - t0) * 1000, 2)
            pipeline_timings["guardrail_validation_ms"] = validation_ms

            if not validation.is_valid:
                log_status = "error"
                log_status_code = 400
                log_error = f"[{validation.category}] {validation.detail}"
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
            # STEP 2.5: NLI QUERY UNDERSTANDING (Sprint 8 & Sprint 11)
            # ---------------------------------------------------------
            effective_query = query
            nli_avoid_genres: List[str] = []
            avoid_tropes: List[str] = []
            nli_intent = "new_search"

            if should_bypass_nli(query, active_history):
                pipeline_timings["nli_ms"] = 0.0
                logger.info(f"[PipelineOrchestrator] NLI bypassed ($0 spent) for query: '{query}'")
            elif await budget_guard.is_budget_exceeded("nli"):
                pipeline_timings["nli_ms"] = 0.0
                logger.warning(
                    f"[PipelineOrchestrator] NLI daily token budget exceeded! "
                    f"Bypassing NLI query rewrite; passing raw user query directly ($0 spent)."
                )
            else:
                t_nli = time.perf_counter()
                nli_result = await self.nli_parser.parse_async(
                    query=query,
                    history=active_history,
                    request_id=active_request_id,
                    session_id=active_session_id,
                )
                effective_query = nli_result.standalone_query or query
                nli_avoid_genres = nli_result.avoid_genres or []
                avoid_tropes = nli_result.avoid_tropes or []
                nli_intent = nli_result.intent
                pipeline_timings["nli_ms"] = round((time.perf_counter() - t_nli) * 1000, 2)
                logger.info(
                    f"[PipelineOrchestrator] NLI parsed: standalone='{effective_query}', "
                    f"avoid_genres={nli_avoid_genres}, intent={nli_intent} in {pipeline_timings['nli_ms']}ms"
                )

            # Deduplicated case-insensitive merge of avoid_genres from request and NLI (Sprint 9 Task 9.2)
            combined_avoid_genres: List[str] = []
            seen_genres_lower = set()

            for g in (avoid_genres or []):
                if g and str(g).strip():
                    clean_g = str(g).strip()
                    g_lower = clean_g.lower()
                    if g_lower not in seen_genres_lower:
                        seen_genres_lower.add(g_lower)
                        combined_avoid_genres.append(clean_g)

            for g in nli_avoid_genres:
                if g and str(g).strip():
                    clean_g = str(g).strip()
                    g_lower = clean_g.lower()
                    if g_lower not in seen_genres_lower:
                        seen_genres_lower.add(g_lower)
                        combined_avoid_genres.append(clean_g)

            # ---------------------------------------------------------
            # STEP 3: ASYNC RETRIEVAL & CROSS-ENCODER RERANKING
            # ---------------------------------------------------------
            t_retrieval_start = time.perf_counter()
            try:
                candidates, retrieval_timings = await self.execute_retrieval(
                    query=effective_query,
                    top_k=top_k,
                    allow_adult=allow_adult,
                    seen_ids=cumulative_seen_ids,
                    request_id=active_request_id,
                )
                pipeline_timings.update(retrieval_timings)
            except Exception as e:
                log_status = "error"
                log_status_code = 500
                log_error = str(e)
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
            # STEP 3.5: NEGATIVE CONSTRAINT FILTERING (Sprint 8 & Sprint 9)
            # ---------------------------------------------------------
            if combined_avoid_genres or avoid_tropes:
                candidates = filter_candidates_by_negative_constraints(
                    candidates,
                    avoid_genres=combined_avoid_genres,
                    avoid_tropes=avoid_tropes,
                )

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
            # Guardrail check uses unstripped cross_encoder_score internally;
            # top_score is stripped at SSE serialization per Sprint 3 spec.
            is_confident, confidence_msg = self.guardrails.check_retrieval_confidence(candidates)
            if not is_confident:
                logger.warning(f"[PipelineOrchestrator] Low retrieval confidence: {confidence_msg}")
                yield format_sse("warning", {
                    "warning": "Low retrieval confidence",
                    "detail": confidence_msg,
                    "session_id": active_session_id,
                })

            # ---------------------------------------------------------
            # STEP 6: IMMEDIATE METADATA EVENT (TTFT < 1.5s, AC 3.1)
            # ---------------------------------------------------------
            ttft_ms = round((time.perf_counter() - stream_start) * 1000, 2)
            pipeline_timings["ttft_metadata_ms"] = ttft_ms

            public_candidates = strip_scores(candidates)
            yield format_sse("metadata", {
                "query": query,
                "effective_query": effective_query,
                "session_id": active_session_id,
                "user_id": active_user_id,
                "count": len(public_candidates),
                "candidates": public_candidates,
                "avoid_genres": combined_avoid_genres,
                "timings": pipeline_timings,
            })

            # ---------------------------------------------------------
            # STEP 7: STREAMING TASTE CONCIERGE SYNTHESIS (AC 3.3)
            # ---------------------------------------------------------
            t_synth_start = time.perf_counter()
            tokens_emitted = 0
            accumulated_pitch_chunks: List[str] = []

            # Collect valid candidate IDs for structured citation validation (Sprint 10 Task 10.1)
            valid_candidate_ids: Set[int] = {
                c["id"] for c in candidates if isinstance(c, dict) and "id" in c
            }
            citation_buffer = StreamingCitationBuffer(valid_candidate_ids)

            try:
                if await budget_guard.is_budget_exceeded("presentation"):
                    logger.warning(
                        "[PipelineOrchestrator] Presentation daily token budget exceeded! "
                        "Skipping OpenAI streaming; serving deterministic fallback pitch ($0 spent)."
                    )
                    fallback_text = self.synthesizer.generate_fallback_pitch(effective_query, candidates)
                    words = fallback_text.split(" ")
                    for i, word in enumerate(words):
                        if is_disconnected and await is_disconnected():
                            logger.info("[PipelineOrchestrator] Client disconnected during budget fallback stream; aborting.")
                            return
                        token = word + (" " if i < len(words) - 1 else "")
                        scrubbed_token = self.guardrails.scrub_spoilers(token)
                        sanitized_token = citation_buffer.feed(scrubbed_token)
                        if sanitized_token:
                            tokens_emitted += 1
                            accumulated_pitch_chunks.append(sanitized_token)
                            yield format_sse("token", {"text": sanitized_token})
                    flushed_chunk = citation_buffer.flush()
                    if flushed_chunk:
                        tokens_emitted += 1
                        accumulated_pitch_chunks.append(flushed_chunk)
                        yield format_sse("token", {"text": flushed_chunk})
                else:
                    def _invoke_stream_pitch():
                        try:
                            return self.synthesizer.stream_pitch(
                                query=effective_query,
                                candidates=candidates,
                                conversation_history=active_history,
                                is_disconnected=is_disconnected,
                                request_id=active_request_id,
                                session_id=active_session_id,
                            )
                        except TypeError:
                            try:
                                return self.synthesizer.stream_pitch(
                                    query=effective_query,
                                    candidates=candidates,
                                    history=active_history,
                                )
                            except TypeError:
                                return self.synthesizer.stream_pitch(
                                    effective_query,
                                    candidates,
                                )

                    async for token_chunk in _invoke_stream_pitch():
                        if is_disconnected and await is_disconnected():
                            logger.info("[PipelineOrchestrator] Client disconnected during token stream; stopping.")
                            return

                        if token_chunk:
                            scrubbed_chunk = self.guardrails.scrub_spoilers(token_chunk)
                            sanitized_chunk = citation_buffer.feed(scrubbed_chunk)
                            if sanitized_chunk:
                                tokens_emitted += 1
                                accumulated_pitch_chunks.append(sanitized_chunk)
                                yield format_sse("token", {"text": sanitized_chunk})

                    # Flush any remaining buffer at stream completion
                    flushed_chunk = citation_buffer.flush()
                    if flushed_chunk:
                        tokens_emitted += 1
                        accumulated_pitch_chunks.append(flushed_chunk)
                        yield format_sse("token", {"text": flushed_chunk})

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
            log_status = "error"
            log_status_code = 500
            log_error = str(e)
            logger.exception(f"[PipelineOrchestrator] Unexpected stream failure: {e}")
            yield format_sse("error", {
                "detail": "An unexpected error occurred during chat streaming.",
                "error": str(e),
                "session_id": active_session_id,
            })
        finally:
            total_ms = pipeline_timings.get("total_duration_ms") or round(
                (time.perf_counter() - stream_start) * 1000, 2
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    asyncio.to_thread(
                        telemetry_logger.log_recommendation_event,
                        request_id=active_request_id,
                        endpoint="chat",
                        source="user",
                        api_key_id=api_key_id,
                        session_id=active_session_id,
                        query=query,
                        top_k=top_k,
                        allow_adult=allow_adult,
                        results=candidates,
                        results_count=len(candidates),
                        status=log_status,
                        status_code=log_status_code,
                        error=log_error,
                        total_ms=total_ms,
                        timings=pipeline_timings,
                        client_ip=client_ip,
                        user_agent=user_agent,
                        client_metadata=client_metadata,
                    )
                )
            except Exception as log_exc:
                logger.debug(f"[PipelineOrchestrator] Could not schedule chat telemetry: {log_exc}")


# Module singleton for production FastAPI dispatch
orchestrator = PipelineOrchestrator()
