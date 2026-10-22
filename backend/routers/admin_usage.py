# backend/routers/admin_usage.py
"""
Admin LLM Usage Telemetry & Budget Explorer Router (/admin/llm-usage).
Sprint 11 Task 11.2 Implementation.

Features:
- Admin authentication accepting:
  1. Supabase JWT with app_metadata.role == 'admin'.
  2. Admin API key with role == 'admin'.
  3. Returns 401 unauthenticated, 403 non-admin.
- Endpoint 1: GET /admin/llm-usage/daily
  - Aggregates telemetry.llm_usage by DATE(created_at) and layer.
  - Standard gpt-5.4-mini pricing ($0.15/1M prompt, $0.60/1M completion tokens).
  - Graceful degradation on database errors.
- Endpoint 2: GET /admin/llm-usage/current-budget
  - Real-time status of daily token ceilings from budget_guard.
"""

import os
import hmac
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.rag_pipeline.helper.budget_guard import budget_guard, LayerBudgetStatus
from backend.rag_pipeline.helper.rate_limiter import rate_limiter
from backend.auth.supabase_jwt import get_jwks_service
from backend.auth.keys import authenticate_api_key

logger = logging.getLogger("anime_recommender.routers.admin_usage")

router = APIRouter(prefix="/admin/llm-usage", tags=["Admin LLM Usage"])

# Standard pricing for gpt-5.4-mini
PROMPT_COST_PER_MILLION: float = 0.15
COMPLETION_COST_PER_MILLION: float = 0.60


def calculate_llm_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """
    Calculates estimated USD cost based on standard gpt-5.4-mini pricing:
    $0.15 / 1M prompt tokens, $0.60 / 1M completion tokens.
    """
    cost = (
        max(0, prompt_tokens) * PROMPT_COST_PER_MILLION
        + max(0, completion_tokens) * COMPLETION_COST_PER_MILLION
    ) / 1_000_000.0
    return round(cost, 6)


# ----------------------
# PYDANTIC SCHEMAS
# ----------------------

class DailyUsageItem(BaseModel):
    """Aggregated daily token consumption and cost for a single pipeline layer."""
    date: str = Field(..., description="Date formatted as YYYY-MM-DD")
    layer: str = Field(..., description="Pipeline layer: nli, retrieval, or presentation")
    request_count: int = Field(..., ge=0, description="Total LLM requests recorded")
    prompt_tokens: int = Field(..., ge=0, description="Sum of prompt tokens consumed")
    completion_tokens: int = Field(..., ge=0, description="Sum of completion tokens generated")
    total_tokens: int = Field(..., ge=0, description="Sum of total tokens consumed")
    estimated_cost_usd: float = Field(..., ge=0.0, description="Estimated USD cost")
    cache_hit_count: int = Field(..., ge=0, description="Count of cache hit requests")
    fallback_count: int = Field(..., ge=0, description="Count of fallback requests")


# ----------------------
# ADMIN AUTHENTICATION DEPENDENCY
# ----------------------

async def verify_admin_access(request: Request) -> Dict[str, Any]:
    """
    Admin authentication dependency.
    Accepts either:
    1. Supabase JWT (admin role: app_metadata.role == 'admin').
    2. Admin API Key (role == 'admin').

    Returns admin credentials dict or raises 401 unauthenticated / 403 non-admin.
    """
    client_ip = rate_limiter.extract_client_ip(request)

    auth_header = request.headers.get("Authorization")
    legacy_token = request.headers.get("access_token")
    x_api_key = request.headers.get("x-api-key")

    raw_token: Optional[str] = None
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1].strip()
        elif len(parts) == 1:
            raw_token = parts[0].strip()
    elif legacy_token:
        raw_token = legacy_token.strip()
    elif x_api_key:
        raw_token = x_api_key.strip()

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Missing authentication credentials."}},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Check ADMIN_API_KEY environment variable shortcut
    admin_env_key = os.getenv("ADMIN_API_KEY")
    if admin_env_key and hmac.compare_digest(raw_token, admin_env_key.strip()):
        return {"type": "api_key", "role": "admin", "name": "admin_env_key"}

    # 2. Check Developer / Admin API Key format (ar_live_...)
    if raw_token.startswith("ar_live_"):
        try:
            key_ctx = await authenticate_api_key(
                raw_key=raw_token,
                client_ip=client_ip,
                endpoint=request.url.path,
                redis_client=rate_limiter.redis,
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "unauthorized", "message": "Invalid API key."}},
                headers={"WWW-Authenticate": "Bearer"},
            )

        if key_ctx.role != "admin" and "admin" not in (key_ctx.scopes or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "forbidden", "message": "Administrator privileges required."}},
            )
        return {"type": "api_key", "id": key_ctx.key_id, "role": key_ctx.role, "name": key_ctx.name}

    # 3. Check Supabase Auth JWT
    jwks = get_jwks_service()
    try:
        dev_user = jwks.verify_token(raw_token, require_fresh=False)
        user_role = (dev_user.app_metadata or {}).get("role") or dev_user.role
        if user_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "forbidden", "message": "Administrator privileges required."}},
            )
        return {
            "type": "jwt",
            "user_id": dev_user.user_id,
            "email": dev_user.email,
            "role": user_role,
        }
    except HTTPException:
        raise
    except ValueError as val_err:
        # Check if legacy non-admin key was passed
        legacy_env_key = os.getenv("MY_API_KEY")
        if legacy_env_key and hmac.compare_digest(raw_token, legacy_env_key.strip()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "forbidden", "message": "Administrator privileges required."}},
            )

        # Fallback check against API key table in case a non-standard admin key was provided
        try:
            key_ctx = await authenticate_api_key(
                raw_key=raw_token,
                client_ip=client_ip,
                endpoint=request.url.path,
                redis_client=rate_limiter.redis,
            )
            if key_ctx.role != "admin" and "admin" not in (key_ctx.scopes or []):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": {"code": "forbidden", "message": "Administrator privileges required."}},
                )
            return {"type": "api_key", "id": key_ctx.key_id, "role": key_ctx.role, "name": key_ctx.name}
        except HTTPException:
            raise
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": str(val_err)}},
            headers={"WWW-Authenticate": "Bearer"},
        )


# ----------------------
# ENDPOINTS
# ----------------------

@router.get(
    "/daily",
    response_model=List[DailyUsageItem],
    summary="Daily LLM Usage Aggregation",
    description="Queries telemetry.llm_usage aggregated by DATE(created_at) and layer."
)
async def get_daily_llm_usage(
    days: int = Query(default=7, ge=1, le=90, description="Number of historical days to aggregate"),
    layer: Optional[str] = Query(default=None, description="Optional layer filter: nli, retrieval, presentation"),
    admin: Dict[str, Any] = Depends(verify_admin_access),
) -> List[DailyUsageItem]:
    """
    Returns daily aggregated token usage, request counts, and estimated costs per layer.
    Gracefully returns empty list if database is unreachable or table is missing.
    """
    try:
        from backend.telemetry.db import get_telemetry_connection
        with get_telemetry_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT
                        TO_CHAR(DATE(created_at), 'YYYY-MM-DD') AS usage_date,
                        layer,
                        COUNT(*) AS request_count,
                        COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                        COALESCE(SUM(total_tokens), 0) AS total_tokens,
                        COUNT(CASE WHEN cached = TRUE OR status = 'cached' THEN 1 END) AS cache_hit_count,
                        COUNT(CASE WHEN status = 'fallback' THEN 1 END) AS fallback_count
                    FROM telemetry.llm_usage
                    WHERE created_at >= (NOW() - (%s * INTERVAL '1 day'))
                """
                params: List[Any] = [max(1, int(days))]
                if layer and layer.strip().lower() != "all":
                    sql += " AND LOWER(layer) = %s"
                    params.append(layer.strip().lower())

                sql += " GROUP BY DATE(created_at), layer ORDER BY usage_date DESC, layer ASC;"
                cur.execute(sql, params)
                rows = cur.fetchall()

                results: List[DailyUsageItem] = []
                for row in rows:
                    p_tokens = int(row[3])
                    c_tokens = int(row[4])
                    t_tokens = int(row[5])
                    cost = calculate_llm_cost(p_tokens, c_tokens)
                    results.append(
                        DailyUsageItem(
                            date=str(row[0]),
                            layer=str(row[1]),
                            request_count=int(row[2]),
                            prompt_tokens=p_tokens,
                            completion_tokens=c_tokens,
                            total_tokens=t_tokens,
                            estimated_cost_usd=cost,
                            cache_hit_count=int(row[6]),
                            fallback_count=int(row[7]),
                        )
                    )
                return results
    except Exception as exc:
        logger.warning(f"[AdminUsage] Database query error or table missing: {exc}")
        return []


@router.get(
    "/current-budget",
    response_model=Dict[str, LayerBudgetStatus],
    summary="Live Layer Budget Ceilings",
    description="Returns live status of daily token ceilings from budget_guard across all layers."
)
async def get_current_budget(
    admin: Dict[str, Any] = Depends(verify_admin_access),
) -> Dict[str, LayerBudgetStatus]:
    """
    Returns live status of daily token ceilings from budget_guard for nli, retrieval, and presentation
    (current usage, limit, remaining, soft_limit_hit, hard_limit_hit, usage_ratio).
    """
    try:
        return await budget_guard.get_all_budgets()
    except Exception as exc:
        logger.warning(f"[AdminUsage] Error retrieving live budgets: {exc}")
        return {
            layer: LayerBudgetStatus(
                layer=layer,
                current_usage=0,
                limit=budget_guard.limits.get(layer, 100000),
                remaining=budget_guard.limits.get(layer, 100000),
                soft_limit_hit=False,
                hard_limit_hit=False,
                usage_ratio=0.0,
            )
            for layer in ["nli", "retrieval", "presentation"]
        }
