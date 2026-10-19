# backend/telemetry/__init__.py
"""
Telemetry & Observability package (Sprint 3).
Provides isolated database pooling, score stripping, and asynchronous/background
recommendation event logging with bounded retry and daily usage rollups.
"""

from .db import (
    get_telemetry_db_pool,
    get_telemetry_connection,
    close_telemetry_db_pool,
)
from .logger import (
    SCORE_FIELDS,
    STRIP_SCORE_FIELDS,
    strip_scores,
    extract_candidate_scores,
    sanitize_float,
    sanitize_for_json,
    hash_client_ip,
    sanitize_client_metadata,
    log_recommendation_event,
    flush_retry_queue,
)

__all__ = [
    "get_telemetry_db_pool",
    "get_telemetry_connection",
    "close_telemetry_db_pool",
    "SCORE_FIELDS",
    "STRIP_SCORE_FIELDS",
    "strip_scores",
    "extract_candidate_scores",
    "sanitize_float",
    "sanitize_for_json",
    "hash_client_ip",
    "sanitize_client_metadata",
    "log_recommendation_event",
    "flush_retry_queue",
]
