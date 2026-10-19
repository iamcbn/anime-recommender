# backend/telemetry/logger.py
"""
Sprint 3 Telemetry Logger & Public Response Sanitizer.

Implements:
1. strip_scores(results): Non-mutating removal of cross_encoder_score,
   final_rrf_score, and retrieval_rrf_score (plus defensive cosine_similarity).
2. log_recommendation_event(...): Synchronous telemetry writer backed by the
   isolated telemetry pool in backend/telemetry/db.py.
   - Converts numpy scalars/arrays and NaN/Inf floats before psycopg2.extras.Json.
   - Truncates query (<= 2000 chars) and error (<= 500 chars).
   - Hashes client IPs with HMAC-SHA256(KEY_PEPPER); never persists raw IPs.
   - Never raises: catches all exceptions and logs a warning.
   - Drops immediately on FK/CHECK/DataError or PoolError; retries transient
     DB errors at most once from a bounded in-memory queue (maxlen=100).
   - Atomically upserts telemetry.api_key_usage_daily alongside the log insert.
"""

import os
import re
import json
import math
import uuid
import hmac
import hashlib
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple, FrozenSet, Deque, Union

import numpy as np
import psycopg2
from psycopg2 import pool, extras

from backend.auth.keys import KEY_PEPPER
from backend.telemetry.db import get_telemetry_connection

logger = logging.getLogger("anime_recommender.telemetry.logger")

# Real score fields emitted by Ranker.json_conversion()
SCORE_FIELDS: Tuple[str, ...] = (
    "cross_encoder_score",
    "final_rrf_score",
    "retrieval_rrf_score",
)
# Include cosine_similarity defensively in case a mock or legacy caller injects it
STRIP_SCORE_FIELDS: FrozenSet[str] = frozenset(SCORE_FIELDS + ("cosine_similarity",))

MAX_QUERY_CHARS = 2000
MAX_ERROR_CHARS = 500
MAX_USER_AGENT_CHARS = 256
RETRY_QUEUE_MAXLEN = 100

# Redaction patterns for error strings
_BEARER_REDACT_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]+", re.IGNORECASE)
_KEY_REDACT_RE = re.compile(r"ar_live_[a-f0-9]{8}_[A-Za-z0-9_\-]+", re.IGNORECASE)

# Raw IP keys that must never be persisted in client_metadata
_RAW_IP_KEYS: FrozenSet[str] = frozenset({
    "ip",
    "client_ip",
    "remote_addr",
    "x_forwarded_for",
    "x-forwarded-for",
    "cf_connecting_ip",
    "cf-connecting-ip",
    "x_real_ip",
    "x-real-ip",
})

# Bounded in-memory queue for at most 1 retry of transient DB failures
_RETRY_QUEUE: Deque[Dict[str, Any]] = deque(maxlen=RETRY_QUEUE_MAXLEN)
_QUEUE_LOCK = threading.Lock()

INSERT_RECOMMENDATION_LOG_SQL = """
INSERT INTO telemetry.recommendation_logs (
    request_id,
    created_at,
    endpoint,
    source,
    api_key_id,
    session_id,
    query,
    top_k,
    allow_adult,
    results_count,
    status,
    status_code,
    error,
    total_ms,
    timings,
    candidate_scores,
    client_metadata
)
VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
);
"""

UPSERT_API_KEY_USAGE_DAILY_SQL = """
INSERT INTO telemetry.api_key_usage_daily (api_key_id, day, request_count)
VALUES (%s, (%s AT TIME ZONE 'UTC')::date, 1)
ON CONFLICT (api_key_id, day)
DO UPDATE SET request_count = telemetry.api_key_usage_daily.request_count + 1;
"""


def sanitize_float(val: Any) -> Optional[float]:
    """
    Converts Python or numpy numeric scalars to a clean Python float.
    Returns None if val is None, NaN, Inf, -Inf, or non-numeric.
    """
    if val is None or isinstance(val, bool) or isinstance(val, np.bool_):
        return None
    try:
        f_val = float(val)
        if math.isnan(f_val) or math.isinf(f_val):
            return None
        return f_val
    except (TypeError, ValueError):
        return None


def sanitize_for_json(obj: Any) -> Any:
    """
    Recursively converts numpy scalars/arrays and NaN/Inf floats into
    RFC 8259-compliant Python primitives safe for PostgreSQL JSONB.
    """
    if obj is None:
        return None
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f_val = float(obj)
        if math.isnan(f_val) or math.isinf(f_val):
            return None
        return f_val
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [sanitize_for_json(v) for v in obj.tolist()]
    if hasattr(obj, "item") and callable(obj.item):
        try:
            return sanitize_for_json(obj.item())
        except Exception:
            pass
    return str(obj)


def _safe_jsonb(obj: Any) -> Optional[extras.Json]:
    """Wraps a sanitized object in psycopg2.extras.Json with allow_nan=False."""
    if obj is None:
        return None
    clean_obj = sanitize_for_json(obj)
    return extras.Json(clean_obj, dumps=lambda x: json.dumps(x, allow_nan=False))


def strip_scores(results: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Removes cross_encoder_score, final_rrf_score, and retrieval_rrf_score
    (plus cosine_similarity if present) from candidate dictionaries and converts
    any numpy scalars in the remaining fields to standard Python primitives.

    CRITICAL: Never mutates the input list or candidate dictionaries in-place,
    ensuring background telemetry logging still accesses unstripped scores.
    """
    if not results:
        return []
    cleaned: List[Dict[str, Any]] = []
    for item in results:
        if isinstance(item, dict):
            cleaned.append(
                {k: sanitize_for_json(v) for k, v in item.items() if k not in STRIP_SCORE_FIELDS}
            )
        else:
            cleaned.append(sanitize_for_json(item))
    return cleaned


def extract_candidate_scores(results: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Extracts [{id, cross_encoder_score, final_rrf_score, retrieval_rrf_score}]
    from unstripped pipeline results with all numpy floats converted to Python float.
    """
    if not results:
        return []
    extracted: List[Dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if isinstance(raw_id, (int, np.integer)) and not isinstance(raw_id, bool):
            clean_id: Any = int(raw_id)
        else:
            clean_id = sanitize_for_json(raw_id)

        score_entry: Dict[str, Any] = {
            "id": clean_id,
            "cross_encoder_score": sanitize_float(item.get("cross_encoder_score")),
            "final_rrf_score": sanitize_float(item.get("final_rrf_score")),
            "retrieval_rrf_score": sanitize_float(item.get("retrieval_rrf_score")),
        }
        extracted.append(score_entry)
    return extracted


def hash_client_ip(client_ip: Optional[str]) -> Optional[str]:
    """
    Computes a privacy-preserving 16-hex-character HMAC-SHA256 digest of client_ip
    using KEY_PEPPER. Returns None if client_ip is empty or 'unknown'.
    """
    if not client_ip or not isinstance(client_ip, str):
        return None
    cleaned = client_ip.strip()
    if not cleaned or cleaned.lower() == "unknown":
        return None
    pepper = (KEY_PEPPER or "anime_recommender_default_pepper").encode("utf-8")
    return hmac.new(pepper, cleaned.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def sanitize_client_metadata(
    client_metadata: Optional[Dict[str, Any]] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Builds a privacy-safe client_metadata dictionary.
    Replaces any raw IP fields with ip_hash and truncates user_agent.
    """
    meta: Dict[str, Any] = {}
    extracted_raw_ip = client_ip

    if isinstance(client_metadata, dict):
        for k, v in client_metadata.items():
            k_str = str(k)
            if k_str.lower() in _RAW_IP_KEYS:
                if not extracted_raw_ip and isinstance(v, str):
                    extracted_raw_ip = v
            else:
                meta[k_str] = sanitize_for_json(v)

    ip_hash = hash_client_ip(extracted_raw_ip)
    if ip_hash:
        meta["ip_hash"] = ip_hash

    ua = user_agent or meta.get("user_agent")
    if isinstance(ua, str) and ua.strip():
        meta["user_agent"] = ua.strip()[:MAX_USER_AGENT_CHARS]
    elif "user_agent" in meta and meta["user_agent"] is None:
        meta.pop("user_agent", None)

    return meta if meta else None


def _normalize_endpoint(endpoint: Optional[str]) -> str:
    """Normalizes endpoint string to satisfy CHECK (endpoint IN ('recommend','chat','admin_recommend'))."""
    if not endpoint:
        return "recommend"
    cleaned = endpoint.strip().strip("/").lower().replace("/", "_")
    if cleaned in ("recommend", "chat", "admin_recommend"):
        return cleaned
    if "admin" in cleaned:
        return "admin_recommend"
    if "chat" in cleaned:
        return "chat"
    return "recommend"


def _normalize_source(source: Optional[str], normalized_endpoint: str) -> str:
    """Normalizes source string to satisfy CHECK (source IN ('user','admin_eval'))."""
    if source:
        cleaned = source.strip().lower()
        if cleaned in ("user", "admin_eval"):
            return cleaned
    if normalized_endpoint == "admin_recommend":
        return "admin_eval"
    return "user"


def _normalize_uuid(val: Optional[Union[str, uuid.UUID]], generate_if_missing: bool = False) -> Optional[str]:
    """Validates UUID format; returns canonical UUID string or None."""
    if val is not None:
        if isinstance(val, uuid.UUID):
            return str(val)
        if isinstance(val, str) and val.strip():
            try:
                return str(uuid.UUID(val.strip()))
            except ValueError:
                pass
    if generate_if_missing:
        return str(uuid.uuid4())
    return None


def _sanitize_error_text(error: Optional[str]) -> Optional[str]:
    """Redacts any accidental secrets from error text and truncates to 500 characters."""
    if error is None:
        return None
    text = str(error)
    text = _BEARER_REDACT_RE.sub(r"\1[REDACTED]", text)
    text = _KEY_REDACT_RE.sub("[REDACTED_API_KEY]", text)
    return text[:MAX_ERROR_CHARS]


def _execute_db_insert(conn: Any, payload: Dict[str, Any]) -> None:
    """Executes the recommendation_logs insert and paired api_key_usage_daily upsert in one transaction."""
    with conn.cursor() as cur:
        cur.execute(
            INSERT_RECOMMENDATION_LOG_SQL,
            (
                payload["request_id"],
                payload["created_at"],
                payload["endpoint"],
                payload["source"],
                payload["api_key_id"],
                payload["session_id"],
                payload["query"],
                payload["top_k"],
                payload["allow_adult"],
                payload["results_count"],
                payload["status"],
                payload["status_code"],
                payload["error"],
                payload["total_ms"],
                _safe_jsonb(payload["timings"]),
                _safe_jsonb(payload["candidate_scores"]),
                _safe_jsonb(payload["client_metadata"]),
            ),
        )
        if payload["api_key_id"] is not None:
            cur.execute(
                UPSERT_API_KEY_USAGE_DAILY_SQL,
                (payload["api_key_id"], payload["created_at"]),
            )
    conn.commit()


def _enqueue_for_single_retry(payload: Dict[str, Any]) -> None:
    """Enqueues a failed payload into the bounded retry queue if it hasn't been retried yet."""
    if payload.get("_retry_attempt", 0) >= 1:
        logger.warning(
            f"[TelemetryLogger] Dropping telemetry event {payload.get('request_id')} after 1 retry attempt."
        )
        return
    retry_copy = dict(payload)
    retry_copy["_retry_attempt"] = 1
    with _QUEUE_LOCK:
        _RETRY_QUEUE.append(retry_copy)


def flush_retry_queue(conn: Optional[Any] = None, max_items: int = 1) -> int:
    """
    Attempts to flush up to max_items queued events from _RETRY_QUEUE.
    Each item is tried at most once; if it fails again, it is permanently dropped.
    Returns the number of successfully flushed items.
    """
    flushed = 0
    for _ in range(max_items):
        with _QUEUE_LOCK:
            if not _RETRY_QUEUE:
                break
            queued_payload = _RETRY_QUEUE.popleft()

        try:
            if conn is not None:
                _execute_db_insert(conn, queued_payload)
            else:
                with get_telemetry_connection() as active_conn:
                    _execute_db_insert(active_conn, queued_payload)
            flushed += 1
        except Exception as exc:
            logger.warning(
                f"[TelemetryLogger] Retry failed for queued event {queued_payload.get('request_id')}; "
                f"dropping permanently: {exc}"
            )
            if conn is not None and getattr(conn, "closed", 1) == 0:
                try:
                    conn.rollback()
                except Exception:
                    pass
    return flushed


def log_recommendation_event(
    *,
    endpoint: str = "recommend",
    query: str = "",
    top_k: int = 20,
    allow_adult: bool = False,
    source: Optional[str] = None,
    api_key_id: Optional[Union[str, uuid.UUID]] = None,
    session_id: Optional[str] = None,
    request_id: Optional[Union[str, uuid.UUID]] = None,
    results: Optional[List[Dict[str, Any]]] = None,
    results_count: Optional[int] = None,
    candidate_scores: Optional[List[Dict[str, Any]]] = None,
    timings: Optional[Dict[str, Any]] = None,
    total_ms: Optional[float] = None,
    status: str = "ok",
    status_code: Optional[int] = 200,
    error: Optional[str] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    client_metadata: Optional[Dict[str, Any]] = None,
    created_at: Optional[datetime] = None,
    conn: Optional[Any] = None,
) -> bool:
    """
    Synchronous telemetry logger for /recommend, /admin/recommend, and /chat.
    - Converts numpy floats with float() before psycopg2.extras.Json.
    - Truncates query (2000) and error (500).
    - Hashes or drops client IPs.
    - Never raises: catches everything and logs a warning.
    - On FK/check/data or pool errors, drops the event immediately.
    - On transient DB errors, queues for at most one retry in _RETRY_QUEUE.
    - Upserts into telemetry.api_key_usage_daily alongside the log insert.
    """
    try:
        norm_endpoint = _normalize_endpoint(endpoint)
        norm_source = _normalize_source(source, norm_endpoint)
        norm_request_id = _normalize_uuid(request_id, generate_if_missing=True)
        norm_api_key_id = _normalize_uuid(api_key_id, generate_if_missing=False)

        safe_query = (str(query) if query is not None else "")[:MAX_QUERY_CHARS]
        safe_error = _sanitize_error_text(error)
        safe_status = (str(status) if status else "ok")[:12]

        try:
            safe_top_k = int(top_k) if top_k is not None else 20
        except (TypeError, ValueError):
            safe_top_k = 20

        safe_allow_adult = bool(allow_adult)

        if candidate_scores is not None:
            resolved_scores = sanitize_for_json(candidate_scores)
        elif results is not None:
            resolved_scores = extract_candidate_scores(results)
        else:
            resolved_scores = []

        if results_count is not None:
            try:
                safe_results_count = int(results_count)
            except (TypeError, ValueError):
                safe_results_count = len(results) if results else 0
        elif results is not None:
            safe_results_count = len(results)
        elif candidate_scores is not None:
            safe_results_count = len(candidate_scores)
        else:
            safe_results_count = 0

        clean_timings = sanitize_for_json(timings) if timings is not None else None
        clean_total_ms = sanitize_float(total_ms)
        if clean_total_ms is None and isinstance(clean_timings, dict) and clean_timings:
            numeric_vals = [
                v for v in (sanitize_float(val) for val in clean_timings.values()) if v is not None
            ]
            if numeric_vals:
                clean_total_ms = round(sum(numeric_vals), 2)

        clean_client_meta = sanitize_client_metadata(
            client_metadata=client_metadata,
            client_ip=client_ip,
            user_agent=user_agent,
        )

        event_time = created_at or datetime.now(timezone.utc)
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        payload: Dict[str, Any] = {
            "request_id": norm_request_id,
            "created_at": event_time,
            "endpoint": norm_endpoint,
            "source": norm_source,
            "api_key_id": norm_api_key_id,
            "session_id": str(session_id) if session_id else None,
            "query": safe_query,
            "top_k": safe_top_k,
            "allow_adult": safe_allow_adult,
            "results_count": safe_results_count,
            "status": safe_status,
            "status_code": int(status_code) if status_code is not None else None,
            "error": safe_error,
            "total_ms": clean_total_ms,
            "timings": clean_timings,
            "candidate_scores": resolved_scores,
            "client_metadata": clean_client_meta,
            "_retry_attempt": 0,
        }

        if conn is not None:
            _execute_db_insert(conn, payload)
            flush_retry_queue(conn=conn, max_items=1)
            return True

        with get_telemetry_connection() as active_conn:
            _execute_db_insert(active_conn, payload)
            flush_retry_queue(conn=active_conn, max_items=1)
        return True

    except (
        pool.PoolError,
        psycopg2.IntegrityError,
        psycopg2.DataError,
        psycopg2.ProgrammingError,
    ) as drop_exc:
        # Per Sprint 3 spec: On FK/constraint or pool errors, drop the event without retry
        logger.warning(f"[TelemetryLogger] Dropping telemetry event due to pool/constraint error: {drop_exc}")
        return False
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as transient_exc:
        logger.warning(f"[TelemetryLogger] Transient DB error logging telemetry; queuing for 1 retry: {transient_exc}")
        if "payload" in locals():
            _enqueue_for_single_retry(payload)
        return False
    except Exception as exc:
        logger.warning(f"[TelemetryLogger] Unexpected error logging telemetry event: {exc}")
        return False
