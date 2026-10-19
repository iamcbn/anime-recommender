# backend/routers/dev_keys.py
"""
Developer Self-Service API Key Management Router (/dev/keys).

Protected by Supabase Auth JWT.
Implements:
- POST /dev/keys (201, Cache-Control: no-store, 15m fresh JWT required, 90-day default expiry, max 5 limit -> 409)
- GET /dev/keys (keys list without secret or hash)
- DELETE /dev/keys/{id} (204, owner-scoped, foreign keys 404)
- Uniform error envelopes: {"error": {"code": str, "message": str}}
"""

import logging
from typing import List, Optional
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from pydantic import BaseModel, Field, ConfigDict
import psycopg2
from psycopg2 import extras

from backend.auth.supabase_jwt import (
    DevUserContext,
    get_current_dev,
    get_fresh_current_dev,
)
from backend.auth.keys import (
    generate_api_key,
    revoke_api_key,
    get_auth_db_pool,
)
from backend.rag_pipeline.helper.rate_limiter import (
    rate_limiter,
    RateLimiterUnavailableError,
)

logger = logging.getLogger("anime_recommender.routers.dev_keys")

router = APIRouter(prefix="/dev/keys", tags=["Developer Keys"])


# ----------------------
# PYDANTIC SCHEMAS
# ----------------------

class CreateKeyRequest(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Friendly identifier for the API key",
        pattern=r"^[a-zA-Z0-9_\-\s]+$"
    )
    # Strictly forbid extra attributes to prevent mass assignment (e.g. role, rate_limit, scopes, expires_at)
    model_config = ConfigDict(extra="forbid")


class KeyItem(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]


class KeyListResponse(BaseModel):
    keys: List[KeyItem]


class CreateKeyResponse(BaseModel):
    id: str
    name: str
    key: str  # Shown ONCE upon creation
    prefix: str
    created_at: datetime


# ----------------------
# ENDPOINTS
# ----------------------

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateKeyResponse,
    summary="Create a new developer API key"
)
async def create_key(
    request: Request,
    body: CreateKeyRequest,
    response: Response,
    current_dev: DevUserContext = Depends(get_fresh_current_dev)
):
    """
    Provisions a new API key for the authenticated developer.
    - Requires session fresh within 15 minutes.
    - Disallows mass-assignment.
    - Limits to max 5 active keys per developer (409 on overflow).
    - Sets Cache-Control: no-store header.
    """
    client_ip = rate_limiter.extract_client_ip(request)

    # Rate limit key creation (fail-closed if Redis unavailable)
    try:
        is_limited, _, retry_after = await rate_limiter.check_rate_limit(
            identifier=current_dev.user_id,
            limit=10,  # 10 key creations per minute
            is_api_key=False,
            fail_closed=True,
            key_prefix="ratelimit:dev_keys_create"
        )
        if is_limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": {"code": "rate_limit_exceeded", "message": "Key creation rate limit exceeded. Try again later."}},
                headers={"Retry-After": str(retry_after)}
            )
    except RateLimiterUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "service_unavailable", "message": "Rate limiting service unavailable. Operation aborted."}}
        )

    # Prevent caching of the response containing the raw secret
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    db_pool = get_auth_db_pool()
    conn = None
    try:
        conn = db_pool.getconn()
        raw_key, record = generate_api_key(
            name=body.name.strip(),
            owner_id=current_dev.user_id,
            role="user",
            scopes=["recommend", "chat"],
            rate_limit_per_min=20,
            expires_in_days=90,
            actor=f"user:{current_dev.user_id}",
            client_ip=client_ip,
            conn=conn
        )
        return CreateKeyResponse(
            id=record["id"],
            name=record["name"],
            key=raw_key,
            prefix=record["prefix"],
            created_at=record["created_at"]
        )
    except psycopg2.Error as pg_err:
        if conn:
            conn.rollback()
        err_msg = str(pg_err)
        logger.warning(f"[DevKeys] Database error during key creation: {err_msg}")
        if "max_active_keys" in err_msg or "Maximum 5 active API keys" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": {"code": "key_limit_reached", "message": "Maximum active API keys limit (5) reached."}}
            )
        if "uq_api_keys_owner_name" in err_msg or "unique constraint" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": {"code": "duplicate_key_name", "message": "An active key with this name already exists."}}
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": {"code": "database_error", "message": "Failed to create API key."}}
        )
    finally:
        if conn:
            db_pool.putconn(conn)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=KeyListResponse,
    summary="List developer API keys"
)
async def list_keys(
    current_dev: DevUserContext = Depends(get_current_dev)
):
    """
    Returns metadata for all API keys owned by the developer.
    Never exposes raw secrets or key hashes.
    """
    db_pool = get_auth_db_pool()
    conn = None
    try:
        conn = db_pool.getconn()
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            cur.execute("""
                SELECT id, name, key_prefix, created_at, last_used_at, expires_at, revoked_at
                FROM app_auth.api_keys
                WHERE owner_id = %s
                ORDER BY created_at DESC;
            """, (current_dev.user_id,))
            rows = cur.fetchall()

            items = [
                KeyItem(
                    id=str(row["id"]),
                    name=row["name"],
                    prefix=row["key_prefix"],
                    created_at=row["created_at"],
                    last_used_at=row["last_used_at"],
                    expires_at=row["expires_at"],
                    revoked_at=row["revoked_at"]
                )
                for row in rows
            ]
            return KeyListResponse(keys=items)
    except psycopg2.Error as pg_err:
        logger.error(f"[DevKeys] Error fetching keys for user {current_dev.user_id}: {pg_err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": {"code": "database_error", "message": "Failed to retrieve API keys."}}
        )
    finally:
        if conn:
            db_pool.putconn(conn)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-revoke an API key"
)
async def delete_key(
    key_id: UUID,
    request: Request,
    current_dev: DevUserContext = Depends(get_current_dev)
):
    """
    Soft-revokes an active API key owned by the developer.
    - Returns 204 No Content on success.
    - Returns 404 Not Found if key does not exist or belongs to another user.
    - Idempotent: revoking an already revoked key returns 204.
    """
    client_ip = rate_limiter.extract_client_ip(request)
    success = revoke_api_key(
        key_id=str(key_id),
        owner_id=current_dev.user_id,
        actor=f"user:{current_dev.user_id}",
        client_ip=client_ip,
        redis_client=rate_limiter.redis
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "key_not_found", "message": "API key not found."}}
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
