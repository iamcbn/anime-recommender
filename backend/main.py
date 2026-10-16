import os
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


app = FastAPI(title="Anime Recommendation API")

API_KEY = os.getenv("MY_API_KEY")
api_key_header = APIKeyHeader(name="access_token", auto_error=False)


# ----------------------
# RATE LIMITING
# ----------------------

class RateLimiter:
    def __init__(self, requests_num: int = 20, period: timedelta = timedelta(minutes=1)):
        self.requests_per_min = requests_num
        self.period = period
        self.requests = defaultdict(list)

    def is_rate_limited(self, api_key: str) -> tuple[bool, int]:
        now = datetime.now()
        start_time = now - self.period
        start_ts = start_time.timestamp()

        valid_requests = []
        for req in self.requests[api_key]:
            req_ts = req.timestamp() if isinstance(req, datetime) else float(req)
            if req_ts > start_ts:
                valid_requests.append(req)
        self.requests[api_key] = valid_requests

        recent_requests = len(self.requests[api_key])
        if recent_requests >= self.requests_per_min:
            return True, 0
        else:
            self.requests[api_key].append(now)
            return False, self.requests_per_min - recent_requests - 1


# ----------------------
# API KEY SECURITY
# ----------------------
rate_limiter = RateLimiter()


async def get_api_key(api_key: str = Security(api_key_header)):
    expected_key = os.getenv("MY_API_KEY", API_KEY)
    if not expected_key or api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key"
        )

    is_limited, _ = rate_limiter.is_rate_limited(api_key)
    if is_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later."
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
    session_id: Optional[str] = Field(default=None, description="Optional multi-turn session ID (Sprint 4 hook)")
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
    Conversational SSE streaming endpoint (Sprint 3).
    Dual-stream protocol:
    1. Immediate Metadata Cards (TTFT < 1.5s)
    2. Streaming Taste Concierge Personal Rationale
    """
    seen_ids_set = set(request.seen_ids) if request.seen_ids else None

    return StreamingResponse(
        orchestrator.stream_chat(
            query=request.query,
            top_k=request.top_k,
            allow_adult=request.allow_adult,
            seen_ids=seen_ids_set,
            is_disconnected=raw_request.is_disconnected,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )