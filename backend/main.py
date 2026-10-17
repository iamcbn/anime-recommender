import os
import uuid
from typing import Annotated, Optional
from collections import defaultdict
from datetime import timedelta, datetime

from fastapi import FastAPI, Depends, HTTPException, status, Security, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

from backend.rag_pipeline.rag_pipeline import rag_pipeline, async_rag_pipeline
from backend.rag_pipeline.orchestrator import orchestrator
from backend.rag_pipeline.helper.guardrails import DomainGuardrails
from backend.rag_pipeline.helper.rate_limiter import (
    DistributedRateLimiter,
    RateLimiter,
    rate_limiter,
)
from backend.rag_pipeline.helper.state_manager import state_manager


app = FastAPI(title="Anime Recommendation API")

API_KEY = os.getenv("MY_API_KEY")
api_key_header = APIKeyHeader(name="access_token", auto_error=False)


# ----------------------
# API KEY SECURITY & RATE LIMITING
# ----------------------

async def get_api_key(
    request: Request,
    api_key: str = Security(api_key_header)
):
    expected_key = os.getenv("MY_API_KEY", API_KEY)
    if not expected_key or api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key"
        )

    # Rate check supporting distributed Redis, in-memory fallback, and test mock patching
    rate_res = rate_limiter.is_rate_limited(api_key)
    if hasattr(rate_res, "__await__"):
        rate_res = await rate_res

    is_limited = bool(rate_res[0])
    retry_after = rate_res[2] if len(rate_res) > 2 else 0

    if is_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(rate_limiter.requests_per_min),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(retry_after),
            }
        )

    return api_key


# ----------------------
# REQUEST / RESPONSE MODELS
# ----------------------

class RecommendRequest(BaseModel):
    query: Annotated[str, Query(description="The query to recommend anime for", min_length=2)]
    top_k: int = 20
    allow_adult: bool = False

class RecommendResponse(BaseModel):
    query: str
    count: int
    allowed_adult: bool
    results: list
    extra: dict


class ChatRequest(BaseModel):
    query: Annotated[str, Query(description="The conversational prompt or mood query", min_length=2, max_length=500)]
    top_k: int = Field(default=5, ge=1, le=20, description="Number of candidate cards to retrieve")
    allow_adult: bool = Field(default=False, description="Whether to include 18+ adult titles")
    session_id: Optional[str] = Field(default=None, description="Optional multi-turn session ID")
    user_id: Optional[str] = Field(default=None, description="Optional user ID for cross-session watched/dropped history persistence")
    seen_ids: Optional[list[int]] = Field(default=None, description="Optional list of anime IDs to exclude")


# ----------------------
# ENDPOINTS
# ----------------------

@app.get("/")
async def root():
    return {"message": "Welcome to the Anime Recommendation API. Use the /recommend endpoint to get recommendations."}


@app.post("/recommend", response_model=RecommendResponse)
async def recommend(
    request: RecommendRequest,
    api_key: str = Depends(get_api_key)
):
    valid, err_msg = DomainGuardrails.validate_intent(request.query)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg
        )

    results, timings = await async_rag_pipeline(
        query=request.query,
        top_k=request.top_k,
        allow_adult=request.allow_adult
    )

    return RecommendResponse(
        query=request.query,
        count=len(results),
        allowed_adult=request.allow_adult,
        results=results,
        extra={
            "timings": timings,
            "total_ms": sum(timings.values())
        }
    )


@app.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    raw_request: Request,
    api_key: str = Depends(get_api_key),
):
    """
    Conversational SSE streaming endpoint (Sprint 3 & Sprint 4).
    Dual-stream protocol with multi-turn Upstash Redis state tracking:
    1. Immediate Metadata Cards with session_id (TTFT < 1.5s)
    2. Streaming Taste Concierge Personal Rationale with multi-turn history
    3. Automatic candidate ID exclusion recording to prevent title recurrence
    """
    seen_ids_set = set(request.seen_ids) if request.seen_ids else None
    assigned_session_id = request.session_id or str(uuid.uuid4())

    response_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "X-Session-ID": assigned_session_id,
    }

    return StreamingResponse(
        orchestrator.stream_chat(
            query=request.query,
            top_k=request.top_k,
            allow_adult=request.allow_adult,
            seen_ids=seen_ids_set,
            session_id=assigned_session_id,
            user_id=request.user_id,
            is_disconnected=raw_request.is_disconnected,
        ),
        media_type="text/event-stream",
        headers=response_headers,
    )