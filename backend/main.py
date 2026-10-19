import os
import re
import time
import uuid
import hmac
import asyncio
import logging
from typing import Annotated, Optional, Union, List, Dict, Any, Tuple
from collections import defaultdict
from datetime import timedelta, datetime

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
    Security,
    Query,
    Request,
    Response,
    BackgroundTasks,
)
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
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
from backend.auth.keys import (
    ApiKeyContext,
    authenticate_api_key,
)
from backend.routers.dev_keys import router as dev_keys_router
from backend.telemetry.logger import strip_scores, sanitize_for_json, log_recommendation_event

logger = logging.getLogger("anime_recommender.main")

app = FastAPI(title="Anime Recommendation API")

# ----------------------
# CORS MIDDLEWARE
# ----------------------

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"


def _parse_cors_origins(raw_origins: Optional[str] = None) -> List[str]:
    env_val = raw_origins if raw_origins is not None else os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    parsed = [o.strip() for o in env_val.split(",") if o.strip()]
    return parsed if parsed else [o.strip() for o in DEFAULT_CORS_ORIGINS.split(",")]


class DynamicCORSMiddleware(CORSMiddleware):
    """
    CORSMiddleware that evaluates explicit CORS_ORIGINS (defaulting to local dev origins
    and supporting dynamic runtime updates via CORS_ORIGINS environment variable).
    """

    def is_allowed_origin(self, origin: str) -> bool:
        current_origins = _parse_cors_origins()
        if "*" in current_origins:
            return True
        return origin in current_origins


allowed_origins = _parse_cors_origins()

app.add_middleware(
    DynamicCORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "access_token", "x-api-key"],
    expose_headers=["X-Session-ID", "Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

# Mount Developer Self-Service Router
app.include_router(dev_keys_router)


# ----------------------
# LOGGING HYGIENE & ERROR HANDLING
# ----------------------

BEARER_REDACT_REGEX = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]+", re.IGNORECASE)
KEY_REDACT_REGEX = re.compile(r"ar_live_[a-f0-9]{8}_[A-Za-z0-9_\-]+", re.IGNORECASE)


@app.middleware("http")
async def secret_redaction_middleware(request: Request, call_next):
    """Ensures raw API keys and Bearer tokens are never exposed in access or debug logs."""
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        raw_msg = str(exc)
        sanitized_msg = BEARER_REDACT_REGEX.sub(r"\1[REDACTED]", raw_msg)
        sanitized_msg = KEY_REDACT_REGEX.sub("[REDACTED_API_KEY]", sanitized_msg)
        logger.error(f"[GatewayException] Error processing {request.method} {request.url.path}: {sanitized_msg}")
        raise exc


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Formats all HTTPExceptions to uniform schema: {"error": {"code": str, "message": str}, "detail": str}.
    Preserves any BackgroundTasks scheduled on request.state.background_tasks so error-path telemetry executes.
    """
    bg_tasks = getattr(request.state, "background_tasks", None)

    if isinstance(exc.detail, dict) and "error" in exc.detail:
        payload = dict(exc.detail)
        if "detail" not in payload:
            payload["detail"] = payload["error"].get("message", "")
        return JSONResponse(
            status_code=exc.status_code,
            content=payload,
            headers=exc.headers,
            background=bg_tasks,
        )

    code_map = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "unprocessable_entity",
        429: "rate_limit_exceeded",
        500: "internal_server_error",
        503: "service_unavailable",
    }
    err_code = code_map.get(exc.status_code, "error")
    msg = str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": err_code, "message": msg}, "detail": msg},
        headers=exc.headers,
        background=bg_tasks,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Formats validation errors to uniform error envelope."""
    msg = str(exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": {"code": "validation_error", "message": msg}, "detail": exc.errors()}
    )


# ----------------------
# API KEY SECURITY & RATE LIMITING
# ----------------------

def extract_raw_api_key(request: Request) -> Optional[str]:
    """Extracts raw API key from Authorization: Bearer, access_token, or x-api-key."""
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        if len(parts) == 1:
            return parts[0].strip()

    legacy_token = request.headers.get("access_token")
    if legacy_token:
        return legacy_token.strip()

    x_api_key = request.headers.get("x-api-key")
    if x_api_key:
        return x_api_key.strip()

    return None


async def get_api_key(request: Request) -> ApiKeyContext:
    """
    Primary API key dependency (Sprint 2 & Sprint 3).
    - Extracts token from Authorization: Bearer <key> or legacy access_token.
    - Evaluates pre-auth IP brute-force throttle (10 failures/min/IP).
    - Authenticates key against database with HMAC-SHA256 and constant-time check.
    - Verifies endpoint scope ('recommend' / 'chat') for non-admin keys.
    - Evaluates dynamic per-key rate limit based on DB row.
    - Returns ApiKeyContext(key_id, role, scopes, rate_limit_per_min, ...).
    """
    client_ip = rate_limiter.extract_client_ip(request)

    # 1. Pre-auth brute-force lockout check
    is_locked, _, retry_after = await rate_limiter.check_auth_failure_rate(client_ip)
    if is_locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "auth_throttled", "message": "Too many failed authentication attempts. Try again later."}},
            headers={"Retry-After": str(retry_after)}
        )

    raw_key = extract_raw_api_key(request)
    if not raw_key:
        await rate_limiter.record_auth_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Invalid or missing API key."}},
            headers={"WWW-Authenticate": "Bearer"}
        )

    # 2. Support legacy test environment MY_API_KEY if configured
    legacy_env_key = os.getenv("MY_API_KEY")
    is_legacy_key = False
    if legacy_env_key and hmac.compare_digest(raw_key.strip(), legacy_env_key.strip()):
        is_legacy_key = True
        key_ctx = ApiKeyContext(
            key_id=None,
            name="legacy_env_key",
            owner_id=None,
            role="user",
            scopes=["recommend", "chat"],
            rate_limit_per_min=rate_limiter.requests_per_min,
            expires_at=None,
            revoked_at=None,
            key_prefix="legacy_env"
        )
    else:
        try:
            key_ctx = await authenticate_api_key(
                raw_key=raw_key,
                client_ip=client_ip,
                endpoint=request.url.path,
                redis_client=rate_limiter.redis
            )
        except RuntimeError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": {"code": "database_unavailable", "message": "Authentication service unavailable."}}
            )
        except Exception:
            await rate_limiter.record_auth_failure(client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "unauthorized", "message": "Invalid or missing API key."}},
                headers={"WWW-Authenticate": "Bearer"}
            )

    # 3. Scope check for non-admin keys
    if key_ctx.role != "admin" and "admin" not in (key_ctx.scopes or []):
        path = request.url.path.rstrip("/")
        if path == "/recommend" and "recommend" not in (key_ctx.scopes or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "forbidden", "message": "API key lacks required 'recommend' scope."}}
            )
        if path == "/chat" and "chat" not in (key_ctx.scopes or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "forbidden", "message": "API key lacks required 'chat' scope."}}
            )

    # 4. Dynamic per-key rate limit (supporting distributed Redis, in-memory fallback, and test mock patching)
    key_identifier = raw_key if is_legacy_key else (key_ctx.key_id or key_ctx.name)
    effective_limit = None if is_legacy_key else key_ctx.rate_limit_per_min
    try:
        if effective_limit is None:
            rate_res = rate_limiter.is_rate_limited(key_identifier)
        else:
            rate_res = rate_limiter.is_rate_limited(key_identifier, limit=effective_limit)
    except TypeError:
        rate_res = rate_limiter.is_rate_limited(key_identifier)

    if hasattr(rate_res, "__await__"):
        rate_res = await rate_res

    is_limited = bool(rate_res[0])
    retry_after = rate_res[2] if len(rate_res) > 2 else 0

    if is_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "rate_limit_exceeded", "message": "Rate limit exceeded. Try again later."}},
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(key_ctx.rate_limit_per_min),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(retry_after),
            }
        )

    return key_ctx


async def get_admin_key(key_ctx: ApiKeyContext = Depends(get_api_key)) -> ApiKeyContext:
    """Requires role == 'admin' (401 unauthenticated, 403 non-admin)."""
    if key_ctx.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Administrator privileges required."}}
        )
    return key_ctx


# ----------------------
# REQUEST / RESPONSE MODELS
# ----------------------

class RecommendRequest(BaseModel):
    query: Annotated[str, Query(description="The query to recommend anime for", min_length=2)]
    top_k: int = 20
    allow_adult: bool = False


class PublicRecommendResponse(BaseModel):
    """Public response model for POST /recommend: clean anime cards only (no extra, no timings, no scores)."""
    query: str
    count: int
    allowed_adult: bool
    results: list


class AdminRecommendResponse(BaseModel):
    """Admin response model for POST /admin/recommend: includes full timings, total_ms, and candidate scores."""
    query: str
    count: int
    allowed_adult: bool
    results: list
    extra: dict


# Preserve RecommendResponse alias for backward-compatible symbol imports
RecommendResponse = AdminRecommendResponse


class ChatRequest(BaseModel):
    query: Annotated[str, Query(description="The conversational prompt or mood query", min_length=2, max_length=500)]
    top_k: int = Field(default=5, ge=1, le=20, description="Number of candidate cards to retrieve")
    allow_adult: bool = Field(default=False, description="Whether to include 18+ adult titles")
    session_id: Optional[str] = Field(default=None, description="Optional multi-turn session ID")
    user_id: Optional[str] = Field(default=None, description="Optional user ID for cross-session watched/dropped history persistence")
    seen_ids: Optional[list[int]] = Field(default=None, description="Optional list of anime IDs to exclude")


# ----------------------
# INTERNAL RECOMMENDATION EXECUTION & TELEMETRY HELPER
# ----------------------

async def _execute_recommend_flow(
    *,
    request: RecommendRequest,
    raw_request: Request,
    background_tasks: BackgroundTasks,
    api_key: ApiKeyContext,
    endpoint_name: str,
    source_name: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, float], float]:
    """
    Executes guardrail validation, async RAG retrieval, and schedules background telemetry logging
    for both success (200) and error (400 / 500) paths.
    """
    request_id = str(uuid.uuid4())
    t_start = time.perf_counter()
    raw_request.state.background_tasks = background_tasks
    client_ip = rate_limiter.extract_client_ip(raw_request)
    user_agent = raw_request.headers.get("user-agent")

    t_val0 = time.perf_counter()
    valid, err_msg = DomainGuardrails.validate_intent(request.query)
    val_ms = round((time.perf_counter() - t_val0) * 1000, 2)
    if not valid:
        background_tasks.add_task(
            log_recommendation_event,
            request_id=request_id,
            endpoint=endpoint_name,
            source=source_name,
            api_key_id=api_key.key_id,
            query=request.query,
            top_k=request.top_k,
            allow_adult=request.allow_adult,
            results=[],
            results_count=0,
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            error=err_msg,
            total_ms=val_ms,
            timings={"guardrail_validation_ms": val_ms},
            client_ip=client_ip,
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "bad_request", "message": err_msg}},
        )

    try:
        results, timings = await async_rag_pipeline(
            query=request.query,
            top_k=request.top_k,
            allow_adult=request.allow_adult,
        )
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)
        await asyncio.to_thread(
            log_recommendation_event,
            request_id=request_id,
            endpoint=endpoint_name,
            source=source_name,
            api_key_id=api_key.key_id,
            query=request.query,
            top_k=request.top_k,
            allow_adult=request.allow_adult,
            results=[],
            results_count=0,
            status="error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error=str(exc),
            total_ms=elapsed_ms,
            timings=None,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        raise

    total_ms = (
        round(float(sum(timings.values())), 2)
        if timings
        else round((time.perf_counter() - t_start) * 1000, 2)
    )

    # Schedule background telemetry with UNSTRIPPED results
    background_tasks.add_task(
        log_recommendation_event,
        request_id=request_id,
        endpoint=endpoint_name,
        source=source_name,
        api_key_id=api_key.key_id,
        query=request.query,
        top_k=request.top_k,
        allow_adult=request.allow_adult,
        results=results,
        results_count=len(results),
        status="ok",
        status_code=status.HTTP_200_OK,
        error=None,
        total_ms=total_ms,
        timings=timings,
        client_ip=client_ip,
        user_agent=user_agent,
    )

    return results, timings, total_ms


# ----------------------
# ENDPOINTS
# ----------------------

@app.get("/")
async def root():
    return {"message": "Welcome to the Anime Recommendation API. Use the /recommend endpoint to get recommendations."}


@app.post("/recommend", response_model=PublicRecommendResponse)
async def recommend(
    request: RecommendRequest,
    raw_request: Request,
    background_tasks: BackgroundTasks,
    api_key: ApiKeyContext = Depends(get_api_key),
):
    """
    Public recommendation endpoint (Sprint 3).
    Returns clean anime cards only (zero timings, zero model scores, no extra).
    Logs full unstripped scores and timings asynchronously with source='user'.
    """
    results, _, _ = await _execute_recommend_flow(
        request=request,
        raw_request=raw_request,
        background_tasks=background_tasks,
        api_key=api_key,
        endpoint_name="recommend",
        source_name="user",
    )

    clean_results = strip_scores(results)
    return PublicRecommendResponse(
        query=request.query,
        count=len(clean_results),
        allowed_adult=request.allow_adult,
        results=clean_results,
    )


@app.post("/admin/recommend", response_model=RecommendResponse)
async def admin_recommend(
    request: RecommendRequest,
    raw_request: Request,
    background_tasks: BackgroundTasks,
    api_key: ApiKeyContext = Depends(get_admin_key),
):
    """
    Administrative evaluation endpoint requiring admin-role API key (Sprint 3).
    Returns full response including timings, total_ms, and candidate model scores.
    Logs asynchronously with endpoint='admin_recommend' and source='admin_eval'.
    """
    results, timings, total_ms = await _execute_recommend_flow(
        request=request,
        raw_request=raw_request,
        background_tasks=background_tasks,
        api_key=api_key,
        endpoint_name="admin_recommend",
        source_name="admin_eval",
    )

    return RecommendResponse(
        query=request.query,
        count=len(results),
        allowed_adult=request.allow_adult,
        results=sanitize_for_json(results),
        extra={
            "timings": sanitize_for_json(timings),
            "total_ms": total_ms,
        },
    )


@app.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    raw_request: Request,
    api_key: ApiKeyContext = Depends(get_api_key),
):
    """
    Conversational SSE streaming endpoint (Sprint 3 & Sprint 4).
    Dual-stream protocol with multi-turn Upstash Redis state tracking.
    Strips candidate scores and top_score at SSE serialization and logs telemetry
    once per turn after the stream ends via asyncio.to_thread.
    """
    seen_ids_set = set(request.seen_ids) if request.seen_ids else None
    assigned_session_id = request.session_id or str(uuid.uuid4())
    client_ip = rate_limiter.extract_client_ip(raw_request)
    user_agent = raw_request.headers.get("user-agent")

    response_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "X-Session-ID": assigned_session_id,
    }

    try:
        stream_gen = orchestrator.stream_chat(
            query=request.query,
            top_k=request.top_k,
            allow_adult=request.allow_adult,
            seen_ids=seen_ids_set,
            session_id=assigned_session_id,
            user_id=request.user_id,
            is_disconnected=raw_request.is_disconnected,
            api_key_id=api_key.key_id,
            client_ip=client_ip,
            user_agent=user_agent,
        )
    except TypeError:
        # Fallback if a unit test replaces orchestrator.stream_chat with a mock accepting legacy args only
        stream_gen = orchestrator.stream_chat(
            query=request.query,
            top_k=request.top_k,
            allow_adult=request.allow_adult,
            seen_ids=seen_ids_set,
            session_id=assigned_session_id,
            user_id=request.user_id,
            is_disconnected=raw_request.is_disconnected,
        )

    return StreamingResponse(
        stream_gen,
        media_type="text/event-stream",
        headers=response_headers,
    )