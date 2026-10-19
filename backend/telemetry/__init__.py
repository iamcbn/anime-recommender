# backend/telemetry/__init__.py
"""
Telemetry & Observability package (Sprints 3 & 4).
Provides isolated database pooling, score stripping, asynchronous/background
recommendation event logging, and crash-safe Parquet cold-storage archival.
"""

from typing import Any
from .db import (
    get_telemetry_db_pool,
    get_telemetry_connection,
    close_telemetry_db_pool,
)

_LOGGER_EXPORTS = {
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
}

_ARCHIVER_EXPORTS = {
    "ARCHIVE_BUCKET_NAME",
    "ARCHIVER_ADVISORY_LOCK_ID",
    "RECOMMENDATION_LOGS_ARROW_SCHEMA",
    "ArchiverError",
    "ArchiveVerificationError",
    "ArchiveDeleteError",
    "RetryableStorageError",
    "ArchiveRunSummary",
    "PartArchiveResult",
    "LocalParquetArtifact",
    "SupabaseArchiveStorage",
    "get_archiver_db_config",
    "rows_to_arrow_table",
    "build_archive_object_key",
    "write_parquet_artifact",
    "verify_remote_parquet",
    "run_archiver",
    "erase_subject_from_parquet_bytes",
    "erase_subject_from_telemetry",
}

__all__ = [
    "get_telemetry_db_pool",
    "get_telemetry_connection",
    "close_telemetry_db_pool",
    *_LOGGER_EXPORTS,
    *_ARCHIVER_EXPORTS,
]


def __getattr__(name: str) -> Any:
    if name in _LOGGER_EXPORTS:
        from . import logger as _logger_mod
        return getattr(_logger_mod, name)
    if name in _ARCHIVER_EXPORTS:
        from . import archiver as _archiver_mod
        return getattr(_archiver_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
