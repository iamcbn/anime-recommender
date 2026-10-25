# backend/telemetry/db.py
"""
Isolated PostgreSQL connection pool for telemetry and first-party feedback logging.

Design decisions (telemetry_and_archival_implementation_plan.md Section 2):
- Uses a dedicated small psycopg2.pool.ThreadedConnectionPool (min=1, max=3).
- Enforces connect_timeout=3 and statement_timeout=3000ms so telemetry writes
  never starve the retrieval pool or block worker threads during DB degradation.
- Compatible with both direct PostgreSQL (5432) and Supabase PgBouncer
  transaction pooler (6543).
"""

import os
import uuid
import hashlib
import asyncio
import logging
import threading
from contextlib import contextmanager
from typing import Optional, Dict, Any, Generator

import psycopg2
from psycopg2 import pool, extensions, extras

logger = logging.getLogger("anime_recommender.telemetry.db")

_TELEMETRY_DB_POOL: Optional[pool.ThreadedConnectionPool] = None
_POOL_LOCK = threading.Lock()


def _get_base_db_config() -> dict:
    from backend.rag_pipeline.config import config as get_db_config
    return get_db_config()


def get_telemetry_db_pool() -> pool.ThreadedConnectionPool:
    """
    Thread-safely initialises and returns the isolated ThreadedConnectionPool
    for telemetry writes (min=1, max=3, connect_timeout=3, statement_timeout=3000ms).
    """
    global _TELEMETRY_DB_POOL
    if _TELEMETRY_DB_POOL is None or _TELEMETRY_DB_POOL.closed:
        with _POOL_LOCK:
            if _TELEMETRY_DB_POOL is None or _TELEMETRY_DB_POOL.closed:
                cfg = _get_base_db_config()
                pool_kwargs = dict(cfg)
                pool_kwargs["connect_timeout"] = int(os.getenv("DB_TELEMETRY_CONNECT_TIMEOUT", "3"))
                pool_kwargs["options"] = os.getenv(
                    "DB_TELEMETRY_OPTIONS", "-c statement_timeout=3000"
                )
                pool_kwargs["application_name"] = os.getenv(
                    "DB_TELEMETRY_APP_NAME", "anime_recommender_telemetry"
                )
                minconn = int(os.getenv("DB_TELEMETRY_MIN_CONN", "1"))
                maxconn = int(os.getenv("DB_TELEMETRY_MAX_CONN", "3"))
                _TELEMETRY_DB_POOL = pool.ThreadedConnectionPool(
                    minconn=minconn,
                    maxconn=maxconn,
                    **pool_kwargs,
                )
                logger.info(
                    f"[TelemetryDBPool] Initialised telemetry connection pool (min={minconn}, max={maxconn})."
                )
    return _TELEMETRY_DB_POOL


@contextmanager
def get_telemetry_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Acquires a telemetry DB connection from the pool and guarantees safe release.
    Discards broken connections (close=True) on OperationalError/InterfaceError.
    """
    db_pool = get_telemetry_db_pool()
    conn = db_pool.getconn()
    discard = False
    try:
        if conn.closed != 0:
            db_pool.putconn(conn, close=True)
            conn = db_pool.getconn()
        elif conn.info.transaction_status == extensions.TRANSACTION_STATUS_INERROR:
            conn.rollback()

        yield conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        discard = True
        raise
    except Exception:
        if conn and conn.closed == 0:
            try:
                conn.rollback()
            except Exception:
                discard = True
        raise
    finally:
        if conn is not None:
            try:
                db_pool.putconn(conn, close=discard or (conn.closed != 0))
            except Exception as put_exc:
                logger.debug(f"[TelemetryDBPool] Error returning connection to pool: {put_exc}")


def close_telemetry_db_pool() -> None:
    """Closes all connections in the telemetry pool (for clean shutdown and testing)."""
    global _TELEMETRY_DB_POOL
    with _POOL_LOCK:
        if _TELEMETRY_DB_POOL is not None and not _TELEMETRY_DB_POOL.closed:
            _TELEMETRY_DB_POOL.closeall()
        _TELEMETRY_DB_POOL = None


def insert_feedback_event(
    recommendation_id: str,
    event_type: str,
    anime_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> bool:
    """
    Inserts a user feedback event into telemetry.feedback_events.
    Validates event_type against allowed literals:
    ('thumbs_up', 'thumbs_down', 'more_like_this', 'watchlist_add').
    Hashes client IP to ensure zero raw IP storage.
    """
    valid_events = {"thumbs_up", "thumbs_down", "more_like_this", "watchlist_add"}
    if event_type not in valid_events:
        logger.warning(f"[TelemetryDB] Invalid feedback event_type '{event_type}' rejected.")
        return False

    try:
        uuid.UUID(str(recommendation_id))
    except (ValueError, AttributeError):
        logger.warning(f"[TelemetryDB] Invalid recommendation_id UUID '{recommendation_id}' rejected.")
        return False

    # Privacy preservation: hash IP if provided
    hashed_ip: Optional[str] = None
    if client_ip:
        hashed_ip = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:32]

    serialized_meta = psycopg2.extras.Json(metadata) if metadata is not None else None

    stmt = """
    INSERT INTO telemetry.feedback_events (
        recommendation_id,
        event_type,
        anime_id,
        metadata,
        user_id,
        client_ip
    ) VALUES (%s, %s, %s, %s, %s, %s);
    """

    try:
        with get_telemetry_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    stmt,
                    (
                        str(recommendation_id),
                        event_type,
                        anime_id,
                        serialized_meta,
                        user_id,
                        hashed_ip,
                    )
                )
            conn.commit()
        return True
    except psycopg2.IntegrityError as ie:
        # FK or check constraint violation
        logger.warning(f"[TelemetryDB] Integrity constraint on feedback event: {ie}")
        return False
    except Exception as exc:
        logger.error(f"[TelemetryDB] Failed to insert feedback event: {exc}")
        return False


async def insert_feedback_event_async(
    recommendation_id: str,
    event_type: str,
    anime_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> bool:
    """Non-blocking asynchronous wrapper for feedback event insertion."""
    return await asyncio.to_thread(
        insert_feedback_event,
        recommendation_id,
        event_type,
        anime_id,
        metadata,
        user_id,
        client_ip,
    )
