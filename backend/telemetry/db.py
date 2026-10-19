# backend/telemetry/db.py
"""
Isolated PostgreSQL connection pool for Sprint 3 background telemetry logging.

Design decisions (telemetry_and_archival_implementation_plan.md Section 2):
- Uses a dedicated small psycopg2.pool.ThreadedConnectionPool (min=1, max=3).
- Enforces connect_timeout=3 and statement_timeout=3000ms so telemetry writes
  never starve the retrieval pool or block worker threads during DB degradation.
- Compatible with both direct PostgreSQL (5432) and Supabase PgBouncer
  transaction pooler (6543).
"""

import os
import logging
import threading
from contextlib import contextmanager
from typing import Optional, Generator

import psycopg2
from psycopg2 import pool, extensions

from backend.rag_pipeline.config import config as get_db_config

logger = logging.getLogger("anime_recommender.telemetry.db")

_TELEMETRY_DB_POOL: Optional[pool.ThreadedConnectionPool] = None
_POOL_LOCK = threading.Lock()


def get_telemetry_db_pool() -> pool.ThreadedConnectionPool:
    """
    Thread-safely initializes and returns the isolated ThreadedConnectionPool
    for telemetry writes (min=1, max=3, connect_timeout=3, statement_timeout=3000ms).
    """
    global _TELEMETRY_DB_POOL
    if _TELEMETRY_DB_POOL is None or _TELEMETRY_DB_POOL.closed:
        with _POOL_LOCK:
            if _TELEMETRY_DB_POOL is None or _TELEMETRY_DB_POOL.closed:
                cfg = get_db_config()
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
                    f"[TelemetryDBPool] Initialized telemetry connection pool (min={minconn}, max={maxconn})."
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
