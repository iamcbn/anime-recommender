# backend/auth/keys.py
"""
High-entropy API key lifecycle management, HMAC-SHA256 derivation,
constant-time verification, in-process caching, and audit logging.

Sprint 2 implementation conforming strictly to telemetry_and_archival_implementation_plan.md.
"""

import os
import re
import hmac
import time
import secrets
import hashlib
import logging
import asyncio
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import psycopg2
from psycopg2 import pool, extras
from cachetools import TTLCache

def _get_base_db_config() -> dict:
    from backend.rag_pipeline.config import config as get_db_config
    return get_db_config()

logger = logging.getLogger("anime_recommender.auth.keys")

# Key format: ar_live_<8 hex chars>_<43 urlsafe chars> (total 60 chars)
KEY_REGEX = re.compile(r"^ar_live_([a-f0-9]{8})_([A-Za-z0-9_-]{43})$")

# Secret pepper loading
KEY_PEPPER = os.getenv("KEY_PEPPER", "anime_recommender_dev_key_pepper_must_be_over_32_bytes_long!!")
KEY_PEPPER_FALLBACK = os.getenv("KEY_PEPPER_FALLBACK")

# Static dummy hash precomputed at boot for constant-time balance on non-existent keys
DUMMY_KEY = "ar_live_00000000_dummy_secret_key_used_for_timing_balance_padding!!"
DUMMY_HASH = hmac.new(KEY_PEPPER.encode("utf-8"), DUMMY_KEY.encode("utf-8"), hashlib.sha256).digest()

# In-process cache: 60s for valid keys, 5s for non-existent/invalid keys
VALID_KEY_CACHE: TTLCache = TTLCache(maxsize=10000, ttl=60)
NEGATIVE_KEY_CACHE: TTLCache = TTLCache(maxsize=5000, ttl=5)

# Throttle cache for last_used_at database updates: 5 minutes (300 seconds)
LAST_USED_THROTTLE_CACHE: TTLCache = TTLCache(maxsize=10000, ttl=300)

# Dedicated thread-safe connection pool for authentication
_AUTH_DB_POOL: Optional[pool.ThreadedConnectionPool] = None


def get_auth_db_pool() -> pool.ThreadedConnectionPool:
    """Returns or initializes the isolated connection pool for authentication queries."""
    global _AUTH_DB_POOL
    if _AUTH_DB_POOL is None or _AUTH_DB_POOL.closed:
        cfg = _get_base_db_config()
        # Set short connection & statement timeouts to prevent worker starvation
        pool_kwargs = dict(cfg)
        pool_kwargs["connect_timeout"] = int(os.getenv("DB_AUTH_CONNECT_TIMEOUT", "3"))
        pool_kwargs["options"] = os.getenv("DB_AUTH_OPTIONS", "-c statement_timeout=3000")
        _AUTH_DB_POOL = pool.ThreadedConnectionPool(minconn=1, maxconn=5, **pool_kwargs)
        logger.info("[AuthDBPool] Initialized auth connection pool (min=1, max=5).")
    return _AUTH_DB_POOL


@dataclass(frozen=True, slots=True)
class ApiKeyContext:
    """Immutable context representing an authenticated API key."""
    key_id: Optional[str]
    name: str
    owner_id: Optional[str]
    role: str
    scopes: List[str]
    rate_limit_per_min: int
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    key_prefix: Optional[str] = None

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None:
            now = datetime.now(timezone.utc)
            exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
            if exp <= now:
                return False
        return True


def hash_api_key(raw_key: str, pepper: Optional[str] = None) -> bytes:
    """Computes HMAC-SHA256 digest of the raw key using KEY_PEPPER."""
    used_pepper = pepper or KEY_PEPPER
    return hmac.new(used_pepper.encode("utf-8"), raw_key.encode("utf-8"), hashlib.sha256).digest()


def validate_key_format(raw_key: str) -> Optional[Tuple[str, str]]:
    """
    Validates key syntax.
    Returns (prefix, secret) tuple or None if invalid.
    """
    if not raw_key or not isinstance(raw_key, str):
        return None
    match = KEY_REGEX.match(raw_key.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def record_audit_log(
    conn,
    actor: str,
    action: str,
    api_key_id: Optional[str],
    detail: Dict[str, Any]
) -> None:
    """Inserts a structured entry into app_auth.key_audit_log."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO app_auth.key_audit_log (actor, action, api_key_id, detail)
                VALUES (%s, %s, %s, %s);
            """, (actor, action, api_key_id, extras.Json(detail)))
    except Exception as e:
        logger.error(f"[AuditLog] Failed to write audit event ({action}): {e}")


def generate_api_key(
    name: str,
    owner_id: Optional[str],
    role: str = "user",
    scopes: Optional[List[str]] = None,
    rate_limit_per_min: int = 20,
    expires_in_days: int = 90,
    actor: Optional[str] = None,
    client_ip: str = "127.0.0.1",
    conn = None
) -> Tuple[str, Dict[str, Any]]:
    """
    Generates a high-entropy CSPRNG API key, computes HMAC-SHA256 digest,
    stores the hashed record in app_auth.api_keys, logs to app_auth.key_audit_log,
    and returns (raw_key, record_dict).
    The raw key is returned ONLY once.
    """
    if not name or len(name) > 64:
        raise ValueError("Key name must be between 1 and 64 characters.")

    prefix_hex = secrets.token_hex(4)  # 8 hex characters
    secret_urlsafe = secrets.token_urlsafe(32)  # 43 chars urlsafe
    raw_key = f"ar_live_{prefix_hex}_{secret_urlsafe}"
    key_prefix = f"ar_live_{prefix_hex}"

    key_hash = hash_api_key(raw_key)

    expires_at = None
    if expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    resolved_scopes = scopes or (["admin", "recommend", "chat"] if role == "admin" else ["recommend"])
    resolved_actor = actor or (f"user:{owner_id}" if owner_id else "system")

    should_close_conn = False
    if conn is None:
        db_pool = get_auth_db_pool()
        conn = db_pool.getconn()
        should_close_conn = True

    try:
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            cur.execute("""
                INSERT INTO app_auth.api_keys (
                    owner_id, name, key_prefix, key_hash, role, scopes,
                    rate_limit_per_min, expires_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at, expires_at;
            """, (
                owner_id,
                name,
                key_prefix,
                key_hash,
                role,
                resolved_scopes,
                rate_limit_per_min,
                expires_at
            ))
            row = cur.fetchone()
            key_id = str(row["id"])
            created_at = row["created_at"]

            # Transactional audit log insertion
            record_audit_log(
                conn,
                actor=resolved_actor,
                action="key.create",
                api_key_id=key_id,
                detail={
                    "name": name,
                    "key_prefix": key_prefix,
                    "role": role,
                    "scopes": resolved_scopes,
                    "rate_limit_per_min": rate_limit_per_min,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                    "client_ip": client_ip,
                }
            )

        conn.commit()

        result_dict = {
            "id": key_id,
            "name": name,
            "prefix": key_prefix,
            "created_at": created_at,
            "expires_at": expires_at,
            "role": role,
            "scopes": resolved_scopes,
            "rate_limit_per_min": rate_limit_per_min,
        }
        return raw_key, result_dict

    finally:
        if should_close_conn and conn:
            db_pool.putconn(conn)


def _async_update_last_used_at(key_id: str) -> None:
    """Off-hot-path background update for last_used_at."""
    try:
        db_pool = get_auth_db_pool()
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE app_auth.api_keys
                    SET last_used_at = now()
                    WHERE id = %s
                      AND (last_used_at IS NULL OR last_used_at < now() - INTERVAL '5 minutes');
                """, (key_id,))
            conn.commit()
        finally:
            db_pool.putconn(conn)
    except Exception as e:
        logger.warning(f"[AuthKeys] Failed to update last_used_at for key {key_id}: {e}")


async def authenticate_api_key(
    raw_key: str,
    client_ip: str = "127.0.0.1",
    endpoint: str = "recommend",
    redis_client = None
) -> ApiKeyContext:
    """
    Authenticates an API key with timing-safe checks, multi-tier caching,
    tombstone verification, and fail-closed behavior during database outages.
    Raises ValueError / PermissionError or returns ApiKeyContext.
    """
    if not raw_key:
        raise ValueError("Missing API key.")

    # 1. Break-glass environment admin key check (out-of-band)
    env_admin_key = os.getenv("ADMIN_API_KEY")
    if env_admin_key and hmac.compare_digest(raw_key.strip(), env_admin_key.strip()):
        return ApiKeyContext(
            key_id=None,
            name="breakglass_env_admin",
            owner_id=None,
            role="admin",
            scopes=["admin", "recommend", "chat"],
            rate_limit_per_min=1000,
            expires_at=None,
            revoked_at=None,
            key_prefix="admin_breakglass"
        )

    # 2. Key format pre-validation (cheap rejection before hashing or DB query)
    fmt = validate_key_format(raw_key)
    if not fmt:
        # Constant-time dummy computation to mitigate timing attack
        hmac.compare_digest(DUMMY_HASH, DUMMY_HASH)
        raise ValueError("Invalid API key format.")

    candidate_hash = hash_api_key(raw_key)

    # 3. Check Negative Cache (TTL 5s)
    if candidate_hash in NEGATIVE_KEY_CACHE:
        hmac.compare_digest(candidate_hash, DUMMY_HASH)
        raise ValueError("Invalid API key.")

    # 4. Check Positive In-Process Cache (TTL 60s)
    if candidate_hash in VALID_KEY_CACHE:
        cached_ctx: ApiKeyContext = VALID_KEY_CACHE[candidate_hash]
        # Invariant recheck: verify expiry & revocation on every request
        if not cached_ctx.is_active:
            VALID_KEY_CACHE.pop(candidate_hash, None)
            raise ValueError("API key expired or revoked.")

        # Redis tombstone check if Redis is active
        if redis_client and cached_ctx.key_id:
            try:
                is_revoked = await redis_client.get(f"revoked:key:{cached_ctx.key_id}")
                if is_revoked:
                    VALID_KEY_CACHE.pop(candidate_hash, None)
                    raise ValueError("API key revoked.")
            except Exception as e:
                logger.warning(f"[AuthKeys] Redis tombstone check warning: {e}")

        # Throttled update of last_used_at
        if cached_ctx.key_id and cached_ctx.key_id not in LAST_USED_THROTTLE_CACHE:
            LAST_USED_THROTTLE_CACHE[cached_ctx.key_id] = True
            asyncio.create_task(asyncio.to_thread(_async_update_last_used_at, cached_ctx.key_id))

        return cached_ctx

    # 5. Database lookup via Auth Pool
    db_pool = get_auth_db_pool()
    conn = None
    row = None
    try:
        conn = db_pool.getconn()
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            cur.execute("""
                SELECT id, name, owner_id, role, scopes, rate_limit_per_min,
                       expires_at, revoked_at, key_hash, key_prefix
                FROM app_auth.api_keys
                WHERE key_hash = %s;
            """, (psycopg2.Binary(candidate_hash),))
            row = cur.fetchone()
    except Exception as db_exc:
        logger.error(f"[AuthKeys] Database outage during key lookup: {db_exc}")
        # Fail closed: uncached keys fail with 503
        raise RuntimeError("Database unavailable for authentication.") from db_exc
    finally:
        if conn:
            db_pool.putconn(conn)

    # 6. Evaluation and timing-safe comparison
    if row is None:
        # Check dual-pepper rotation if fallback configured
        if KEY_PEPPER_FALLBACK:
            fallback_hash = hash_api_key(raw_key, pepper=KEY_PEPPER_FALLBACK)
            try:
                conn = db_pool.getconn()
                with conn.cursor(cursor_factory=extras.DictCursor) as cur:
                    cur.execute("""
                        SELECT id, name, owner_id, role, scopes, rate_limit_per_min,
                               expires_at, revoked_at, key_hash, key_prefix
                        FROM app_auth.api_keys
                        WHERE key_hash = %s;
                    """, (psycopg2.Binary(fallback_hash),))
                    row = cur.fetchone()
            finally:
                if conn:
                    db_pool.putconn(conn)

    if row is None:
        # Execute constant-time comparison against static dummy hash
        hmac.compare_digest(candidate_hash, DUMMY_HASH)
        NEGATIVE_KEY_CACHE[candidate_hash] = True
        raise ValueError("Invalid API key.")

    stored_hash = bytes(row["key_hash"])
    if not hmac.compare_digest(candidate_hash, stored_hash):
        NEGATIVE_KEY_CACHE[candidate_hash] = True
        raise ValueError("Invalid API key.")

    key_ctx = ApiKeyContext(
        key_id=str(row["id"]),
        name=row["name"],
        owner_id=str(row["owner_id"]) if row["owner_id"] else None,
        role=row["role"],
        scopes=row["scopes"] or [],
        rate_limit_per_min=row["rate_limit_per_min"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        key_prefix=row["key_prefix"]
    )

    if not key_ctx.is_active:
        NEGATIVE_KEY_CACHE[candidate_hash] = True
        raise ValueError("API key expired or revoked.")

    # Cache positive result
    VALID_KEY_CACHE[candidate_hash] = key_ctx

    # Throttled update of last_used_at
    if key_ctx.key_id and key_ctx.key_id not in LAST_USED_THROTTLE_CACHE:
        LAST_USED_THROTTLE_CACHE[key_ctx.key_id] = True
        asyncio.create_task(asyncio.to_thread(_async_update_last_used_at, key_ctx.key_id))

    return key_ctx


def revoke_api_key(
    key_id: str,
    owner_id: Optional[str] = None,
    actor: Optional[str] = None,
    client_ip: str = "127.0.0.1",
    redis_client = None,
    conn = None
) -> bool:
    """
    Soft-revokes an active API key scoped to owner_id (if provided).
    Evicts in-process caches and writes a Redis tombstone `revoked:key:{key_id}`.
    Returns True if successfully revoked, False if not found or unauthorized.
    """
    should_close_conn = False
    if conn is None:
        db_pool = get_auth_db_pool()
        conn = db_pool.getconn()
        should_close_conn = True

    try:
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            query = """
                SELECT id, owner_id, key_hash, expires_at, revoked_at
                FROM app_auth.api_keys
                WHERE id = %s
            """
            params = [key_id]
            if owner_id:
                query += " AND owner_id = %s"
                params.append(owner_id)

            cur.execute(query, tuple(params))
            row = cur.fetchone()

            if not row:
                return False

            key_hash = bytes(row["key_hash"])
            expires_at = row["expires_at"]

            # If not yet revoked, mark revoked
            if row["revoked_at"] is None:
                cur.execute("""
                    UPDATE app_auth.api_keys
                    SET revoked_at = now()
                    WHERE id = %s;
                """, (key_id,))

                record_audit_log(
                    conn,
                    actor=actor or (f"user:{owner_id}" if owner_id else "admin"),
                    action="key.revoke",
                    api_key_id=key_id,
                    detail={"client_ip": client_ip}
                )
                conn.commit()

        # Evict in-memory positive cache
        VALID_KEY_CACHE.pop(key_hash, None)

        # Write Redis marker if Redis available
        if redis_client:
            now = datetime.now(timezone.utc)
            ttl = 86400 * 30  # Default 30 days
            if expires_at:
                exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
                remaining = int((exp - now).total_seconds())
                ttl = max(60, min(remaining, 86400 * 30))
            try:
                res = redis_client.set(f"revoked:key:{key_id}", "1", ex=ttl)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        asyncio.run(res)
            except Exception as e:
                logger.warning(f"[AuthKeys] Failed to write Redis revocation tombstone: {e}")

        return True
    finally:
        if should_close_conn and conn:
            db_pool.putconn(conn)
