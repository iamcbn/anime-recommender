# backend/telemetry/archiver.py
"""
Sprint 4 Crash-Safe Telemetry Parquet Archiver.

Moves rows in telemetry.recommendation_logs older than N days (default 30) to cold
Parquet storage in the private 'telemetry-archives' bucket, then prunes the exact
verified row IDs from PostgreSQL.

Architectural & Security Invariants:
1. Strictly hard-coded to telemetry.recommendation_logs (and telemetry.api_key_usage_daily
   for pre-delete usage rollup reconciliation). No table/schema parameters or dynamic SQL.
2. Connects via PostgreSQL Session Pooler (port 5432, application_name=archiver,
   statement_timeout=60000ms) and acquires session-level pg_try_advisory_lock.
3. Computes and freezes cutoff = date_trunc('day', now() AT TIME ZONE 'UTC') - interval '<days> days'
   once on the database server and uses that identical cutoff for all fetches and deletes.
4. Streams candidate rows via keyset pagination (WHERE id > %s AND created_at < %s ORDER BY id ASC LIMIT 50000),
   groups by (source, utc_day), and constructs pyarrow.Table directly with an explicit 18-column schema.
5. Writes ZSTD/Snappy Parquet to a temporary file, computing SHA-256, byte size, and row count.
6. Uploads to deterministic keys:
   - source='user'       -> logs/year=YYYY/month=MM/day=DD/part-<min_id>-<max_id>.parquet
   - source='admin_eval' -> admin_eval/year=YYYY/month=MM/day=DD/part-<min_id>-<max_id>.parquet
   If the key already exists in storage, downloads and verifies it first; if valid, skips upload.
7. Verifies remote Parquet byte size, ParquetFile.metadata.num_rows, schema, and exact row IDs.
8. Only after verification succeeds, reconciles telemetry.api_key_usage_daily and executes
   DELETE FROM telemetry.recommendation_logs WHERE id = ANY(%s) AND created_at < %s
   in sub-batches of 5,000-10,000 IDs within one transaction, asserting rowcount == len(ids).
9. Retries only storage upload/download operations with tenacity (5 attempts, exponential backoff,
   network/5xx errors only). Database deletes are never blindly retried.
10. Supports --dry-run (zero uploads, zero deletes) and --days CLI flags.

Privacy & Retention Policy:
- Bucket 'telemetry-archives' is strictly private.
- Cold Parquet archives are retained for 12-24 months before lifecycle expiration.
- 'admin_eval' rows are isolated under the 'admin_eval/' prefix away from user 'logs/'.
- User-requested erasure is supported via erase_subject_from_telemetry(), which purges
  matching rows from hot storage and rewrites any affected cold Parquet partitions.
"""

import io
import os
import sys
import json
import math
import time
import uuid
import hashlib
import logging
import tempfile
import argparse
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timezone
from typing import (
    Any,
    Callable,
    Dict,
    Final,
    List,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Union,
)

from dotenv import load_dotenv
import psycopg2
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import tenacity

load_dotenv()

logger = logging.getLogger("anime_recommender.telemetry.archiver")

# ---------------------------------------------------------------------------
# Constants & Hard-Coded SQL Statements (Zero Dynamic Table Interpolation)
# ---------------------------------------------------------------------------

ARCHIVE_BUCKET_NAME: Final[str] = "telemetry-archives"
DEFAULT_RETENTION_DAYS: Final[int] = 30
DEFAULT_FETCH_BATCH_SIZE: Final[int] = 50000
DEFAULT_DELETE_BATCH_SIZE: Final[int] = 5000
MAX_PART_ROWS: Final[int] = 50000
MAX_PART_RAW_BYTES: Final[int] = 35 * 1024 * 1024  # ~35 MB cap (well under 50 MB bucket limit)

# Deterministic 64-bit signed advisory lock key ('telearch' in ASCII = 0x74656C6561726368)
ARCHIVER_ADVISORY_LOCK_ID: Final[int] = 8387230058559562856

ACQUIRE_ADVISORY_LOCK_SQL: Final[str] = "SELECT pg_try_advisory_lock(%s);"
RELEASE_ADVISORY_LOCK_SQL: Final[str] = "SELECT pg_advisory_unlock(%s);"

COMPUTE_CUTOFF_SQL: Final[str] = (
    "SELECT (date_trunc('day', now() AT TIME ZONE 'UTC') - (%s * INTERVAL '1 day')) "
    "AT TIME ZONE 'UTC' AS cutoff;"
)

FETCH_BATCH_KEYSET_SQL: Final[str] = """
SELECT
    id,
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
FROM telemetry.recommendation_logs
WHERE id > %s AND created_at < %s
ORDER BY id ASC
LIMIT %s;
"""

UPSERT_USAGE_DAILY_FLOOR_SQL: Final[str] = """
INSERT INTO telemetry.api_key_usage_daily (api_key_id, day, request_count)
VALUES (%s, %s, %s)
ON CONFLICT (api_key_id, day)
DO UPDATE SET request_count = GREATEST(
    telemetry.api_key_usage_daily.request_count,
    EXCLUDED.request_count
);
"""

DELETE_LOGS_BY_IDS_SQL: Final[str] = """
DELETE FROM telemetry.recommendation_logs
WHERE id = ANY(%s) AND created_at < %s;
"""

ERASE_HOT_LOGS_BY_KEY_SQL: Final[str] = """
DELETE FROM telemetry.recommendation_logs
WHERE api_key_id = %s;
"""

ERASE_HOT_USAGE_BY_KEY_SQL: Final[str] = """
DELETE FROM telemetry.api_key_usage_daily
WHERE api_key_id = %s;
"""

ERASE_HOT_LOGS_BY_SESSION_SQL: Final[str] = """
DELETE FROM telemetry.recommendation_logs
WHERE session_id = %s;
"""

# ---------------------------------------------------------------------------
# Explicit 18-Column PyArrow Schema (Zero Pandas Dependency)
# ---------------------------------------------------------------------------

RECOMMENDATION_LOGS_ARROW_SCHEMA: Final[pa.Schema] = pa.schema([
    pa.field("id", pa.int64(), nullable=False),
    pa.field("request_id", pa.string(), nullable=False),
    pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("endpoint", pa.string(), nullable=False),
    pa.field("source", pa.string(), nullable=False),
    pa.field("api_key_id", pa.string(), nullable=True),
    pa.field("session_id", pa.string(), nullable=True),
    pa.field("query", pa.string(), nullable=False),
    pa.field("top_k", pa.int32(), nullable=False),
    pa.field("allow_adult", pa.bool_(), nullable=False),
    pa.field("results_count", pa.int32(), nullable=False),
    pa.field("status", pa.string(), nullable=False),
    pa.field("status_code", pa.int32(), nullable=True),
    pa.field("error", pa.string(), nullable=True),
    pa.field("total_ms", pa.float64(), nullable=True),
    pa.field("timings", pa.string(), nullable=True),
    pa.field("candidate_scores", pa.string(), nullable=True),
    pa.field("client_metadata", pa.string(), nullable=True),
])

COLUMN_NAMES: Final[Tuple[str, ...]] = tuple(RECOMMENDATION_LOGS_ARROW_SCHEMA.names)


# ---------------------------------------------------------------------------
# Exceptions & Data Structures
# ---------------------------------------------------------------------------

class ArchiverError(RuntimeError):
    """Base exception for fatal telemetry archival errors."""


class ArchiveVerificationError(ArchiverError):
    """Raised when a local or remote Parquet file fails size, row-count, or ID verification."""


class ArchiveDeleteError(ArchiverError):
    """Raised when an exact-ID delete batch fails or its rowcount mismatches len(ids)."""


class ArchiveStorageClientError(ArchiverError):
    """Non-retryable storage configuration or 4xx client error."""


class RetryableStorageError(ArchiverError):
    """Transient network, timeout, rate-limit (429), or 5xx storage error eligible for tenacity retry."""


@dataclass(frozen=True)
class LocalParquetArtifact:
    object_key: str
    source: str
    utc_day: str
    min_id: int
    max_id: int
    num_rows: int
    file_size: int
    raw_json_bytes: int
    sha256: str
    parquet_bytes: bytes
    row_ids: List[int]
    usage_by_key: Dict[str, int]


@dataclass
class PartArchiveResult:
    object_key: str
    source: str
    utc_day: str
    min_id: int
    max_id: int
    num_rows: int
    file_size: int
    raw_json_bytes: int
    sha256: str
    skipped_existing: bool = False
    deleted_rows: int = 0


@dataclass
class ArchiveRunSummary:
    status: str
    dry_run: bool
    days: int
    cutoff_utc: Optional[str]
    advisory_lock_acquired: bool
    batches_fetched: int = 0
    rows_scanned: int = 0
    rows_archived: int = 0
    rows_deleted: int = 0
    parts_uploaded: int = 0
    parts_skipped_existing: int = 0
    usage_keys_updated: int = 0
    total_parquet_bytes: int = 0
    total_raw_json_bytes: int = 0
    compression_ratio: float = 0.0
    duration_ms: float = 0.0
    parts: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Database Connection & Session Pooler Configuration
# ---------------------------------------------------------------------------

def get_archiver_db_config() -> Dict[str, Any]:
    """
    Resolves PostgreSQL connection parameters for the archiver.
    Prioritizes ARCHIVER_DB_* environment variables, falls back to DB_*,
    and strictly defaults to port 5432 (Session Pooler) rather than 6543 (Transaction Pooler)
    because session-level advisory locks require session pooling.
    """
    host = (
        os.getenv("ARCHIVER_DB_HOST")
        or os.getenv("DB_HOST")
        or "localhost"
    )

    raw_archiver_port = os.getenv("ARCHIVER_DB_PORT")
    raw_db_port = os.getenv("DB_PORT")
    if raw_archiver_port and raw_archiver_port.strip().isdigit():
        port = int(raw_archiver_port.strip())
    elif raw_db_port and raw_db_port.strip().isdigit() and int(raw_db_port.strip()) != 6543:
        port = int(raw_db_port.strip())
    else:
        port = 5432

    database = (
        os.getenv("ARCHIVER_DB_NAME")
        or os.getenv("DB_NAME")
        or "postgres"
    )
    user = (
        os.getenv("ARCHIVER_DB_USER")
        or os.getenv("DB_USER")
        or "postgres"
    )
    password = (
        os.getenv("ARCHIVER_DB_PASSWORD")
        if "ARCHIVER_DB_PASSWORD" in os.environ
        else os.getenv("DB_PASSWORD", "")
    )

    default_ssl = "require" if ("pooler" in host or "supabase.co" in host) else "prefer"
    sslmode = os.getenv("ARCHIVER_DB_SSLMODE") or os.getenv("DB_SSLMODE") or default_ssl

    connect_timeout = int(os.getenv("ARCHIVER_DB_CONNECT_TIMEOUT", "10"))
    statement_timeout_ms = int(os.getenv("ARCHIVER_DB_STATEMENT_TIMEOUT_MS", "60000"))
    options = os.getenv(
        "ARCHIVER_DB_OPTIONS",
        f"-c statement_timeout={statement_timeout_ms} -c timezone=UTC",
    )

    params: Dict[str, Any] = {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "connect_timeout": connect_timeout,
        "application_name": os.getenv("ARCHIVER_DB_APP_NAME", "archiver"),
        "options": options,
    }
    if sslmode:
        params["sslmode"] = sslmode
    return params


def connect_archiver_db(db_params: Optional[Dict[str, Any]] = None) -> Any:
    """
    Opens a dedicated PostgreSQL session connection with autocommit=False
    so multi-batch deletes and usage rollup upserts execute in a single transaction.
    """
    params = db_params or get_archiver_db_config()
    conn = psycopg2.connect(**params)
    conn.autocommit = False
    return conn


def try_acquire_advisory_lock(conn: Any) -> bool:
    """
    Attempts to acquire the non-blocking session-level advisory lock.
    Immediately commits the read transaction so the connection is not left
    'idle in transaction' during Parquet construction and Storage I/O.
    """
    with conn.cursor() as cur:
        cur.execute(ACQUIRE_ADVISORY_LOCK_SQL, (ARCHIVER_ADVISORY_LOCK_ID,))
        row = cur.fetchone()
        acquired = bool(row[0]) if row else False
    conn.commit()
    return acquired


def release_advisory_lock(conn: Any) -> bool:
    """Releases the session-level advisory lock safely."""
    if conn is None or getattr(conn, "closed", 1) != 0:
        return False
    try:
        try:
            conn.rollback()
        except Exception:
            pass
        with conn.cursor() as cur:
            cur.execute(RELEASE_ADVISORY_LOCK_SQL, (ARCHIVER_ADVISORY_LOCK_ID,))
            row = cur.fetchone()
            released = bool(row[0]) if row else False
        conn.commit()
        return released
    except Exception as exc:
        logger.debug(f"[Archiver] Advisory lock release notice: {exc}")
        return False


def compute_fixed_cutoff(conn: Any, days: int = DEFAULT_RETENTION_DAYS) -> datetime:
    """
    Computes and freezes cutoff = date_trunc('day', now() AT TIME ZONE 'UTC') - interval '<days> days'
    once on the database server. Returns a timezone-aware UTC datetime.
    """
    if days < 0:
        raise ValueError(f"days must be >= 0, got {days}")
    with conn.cursor() as cur:
        cur.execute(COMPUTE_CUTOFF_SQL, (int(days),))
        row = cur.fetchone()
        if not row or row[0] is None:
            raise ArchiverError("Database failed to return a valid cutoff timestamp.")
        cutoff_dt = row[0]
    conn.commit()
    return ensure_utc_datetime(cutoff_dt)


def fetch_keyset_batch(
    conn: Any,
    *,
    last_id: int,
    cutoff: datetime,
    batch_size: int = DEFAULT_FETCH_BATCH_SIZE,
) -> List[Dict[str, Any]]:
    """
    Fetches up to batch_size rows from telemetry.recommendation_logs using keyset pagination:
    WHERE id > last_id AND created_at < cutoff ORDER BY id ASC LIMIT batch_size.
    Commits immediately after reading to prevent idle-in-transaction timeouts.
    """
    rows_out: List[Dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute(FETCH_BATCH_KEYSET_SQL, (int(last_id), cutoff, int(batch_size)))
        raw_rows = cur.fetchall()
        col_names = (
            [desc[0] for desc in cur.description]
            if cur.description
            else list(COLUMN_NAMES)
        )
        for raw in raw_rows:
            if isinstance(raw, dict):
                rows_out.append(dict(raw))
            else:
                rows_out.append(dict(zip(col_names, raw)))
    conn.commit()
    return rows_out


# ---------------------------------------------------------------------------
# Normalization, Deterministic JSON Serialization & Direct PyArrow Construction
# ---------------------------------------------------------------------------

def sanitize_float(val: Any) -> Optional[float]:
    """Converts a numeric scalar to a finite Python float, or None if None/NaN/Inf/bool."""
    if val is None or isinstance(val, bool) or type(val).__name__ == "bool_":
        return None
    try:
        f_val = float(val)
        if math.isnan(f_val) or math.isinf(f_val):
            return None
        return f_val
    except (TypeError, ValueError):
        return None


def sanitize_for_json(obj: Any) -> Any:
    """Recursively normalizes primitives, dicts, lists, and scalar/array wrappers into RFC 8259 JSON values."""
    if obj is None:
        return None
    if isinstance(obj, bool) or type(obj).__name__ == "bool_":
        return bool(obj)
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_for_json(v) for v in obj]
    if hasattr(obj, "tolist") and callable(obj.tolist):
        try:
            return sanitize_for_json(obj.tolist())
        except Exception:
            pass
    if hasattr(obj, "item") and callable(obj.item):
        try:
            return sanitize_for_json(obj.item())
        except Exception:
            pass
    return str(obj)


def ensure_utc_datetime(val: Union[datetime, str]) -> datetime:
    """Normalizes a datetime or ISO-8601 string into a timezone-aware UTC datetime."""
    if isinstance(val, str):
        cleaned = val.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
    elif isinstance(val, datetime):
        dt = val
    else:
        raise TypeError(f"Expected datetime or ISO string, got {type(val).__name__}")

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def serialize_jsonb_deterministic(val: Any) -> Optional[str]:
    """
    Serializes a JSONB value (dict, list, or pre-serialized JSON string) into a
    canonical UTF-8 JSON string with sort_keys=True and compact separators.
    Returns None if val is None.
    """
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8")
    if isinstance(val, str):
        stripped = val.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
            clean_parsed = sanitize_for_json(parsed)
            return json.dumps(
                clean_parsed,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except ValueError:
            return json.dumps(
                stripped,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
    clean_val = sanitize_for_json(val)
    return json.dumps(
        clean_val,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def normalize_row_for_arrow(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes a single database row dictionary to match RECOMMENDATION_LOGS_ARROW_SCHEMA.
    """
    raw_id = row["id"]
    norm_id = int(raw_id)

    raw_req_id = row["request_id"]
    norm_req_id = str(uuid.UUID(str(raw_req_id).strip()))

    norm_created_at = ensure_utc_datetime(row["created_at"])

    norm_endpoint = str(row.get("endpoint") or "recommend")
    norm_source = "admin_eval" if str(row.get("source") or "") == "admin_eval" else "user"

    raw_api_key_id = row.get("api_key_id")
    norm_api_key_id: Optional[str] = None
    if raw_api_key_id is not None and str(raw_api_key_id).strip():
        norm_api_key_id = str(uuid.UUID(str(raw_api_key_id).strip()))

    raw_session_id = row.get("session_id")
    norm_session_id = str(raw_session_id) if raw_session_id is not None else None

    norm_query = str(row.get("query") or "")
    norm_top_k = int(row.get("top_k") if row.get("top_k") is not None else 20)
    norm_allow_adult = bool(row.get("allow_adult", False))
    norm_results_count = int(row.get("results_count") if row.get("results_count") is not None else 0)
    norm_status = str(row.get("status") or "ok")

    raw_status_code = row.get("status_code")
    norm_status_code = int(raw_status_code) if raw_status_code is not None else None

    raw_error = row.get("error")
    norm_error = str(raw_error) if raw_error is not None else None

    norm_total_ms = sanitize_float(row.get("total_ms"))

    norm_timings = serialize_jsonb_deterministic(row.get("timings"))
    norm_candidate_scores = serialize_jsonb_deterministic(row.get("candidate_scores"))
    norm_client_metadata = serialize_jsonb_deterministic(row.get("client_metadata"))

    return {
        "id": norm_id,
        "request_id": norm_req_id,
        "created_at": norm_created_at,
        "endpoint": norm_endpoint,
        "source": norm_source,
        "api_key_id": norm_api_key_id,
        "session_id": norm_session_id,
        "query": norm_query,
        "top_k": norm_top_k,
        "allow_adult": norm_allow_adult,
        "results_count": norm_results_count,
        "status": norm_status,
        "status_code": norm_status_code,
        "error": norm_error,
        "total_ms": norm_total_ms,
        "timings": norm_timings,
        "candidate_scores": norm_candidate_scores,
        "client_metadata": norm_client_metadata,
    }


def rows_to_arrow_table(rows: Sequence[Dict[str, Any]]) -> pa.Table:
    """
    Constructs a pyarrow.Table directly from row dictionaries using
    RECOMMENDATION_LOGS_ARROW_SCHEMA (without pandas).
    """
    columns: Dict[str, List[Any]] = {col: [] for col in COLUMN_NAMES}
    for row in rows:
        norm = normalize_row_for_arrow(row)
        for col in COLUMN_NAMES:
            columns[col].append(norm[col])
    return pa.Table.from_pydict(columns, schema=RECOMMENDATION_LOGS_ARROW_SCHEMA)


def estimate_raw_json_bytes(rows: Sequence[Dict[str, Any]]) -> int:
    """Computes the equivalent raw UTF-8 JSON byte size of the given rows."""
    serializable_rows = []
    for row in rows:
        norm = normalize_row_for_arrow(row)
        item = dict(norm)
        item["created_at"] = norm["created_at"].isoformat()
        for json_col in ("timings", "candidate_scores", "client_metadata"):
            if item[json_col] is not None:
                try:
                    item[json_col] = json.loads(item[json_col])
                except ValueError:
                    pass
        serializable_rows.append(item)
    return len(json.dumps(serializable_rows, ensure_ascii=False).encode("utf-8"))


# ---------------------------------------------------------------------------
# Partition Grouping, Deterministic Keys & Local Parquet Writer
# ---------------------------------------------------------------------------

def build_archive_object_key(
    source: str,
    utc_day: Union[date, str],
    min_id: int,
    max_id: int,
) -> str:
    """
    Builds the deterministic object storage path with zero run-timestamp:
    - source == 'user'       -> logs/year=YYYY/month=MM/day=DD/part-<min_id>-<max_id>.parquet
    - source == 'admin_eval' -> admin_eval/year=YYYY/month=MM/day=DD/part-<min_id>-<max_id>.parquet
    """
    if isinstance(utc_day, str):
        day_obj = date.fromisoformat(utc_day)
    else:
        day_obj = utc_day

    if min_id > max_id:
        raise ValueError(f"min_id ({min_id}) cannot exceed max_id ({max_id})")

    prefix = "admin_eval" if source == "admin_eval" else "logs"
    return (
        f"{prefix}/year={day_obj.year:04d}/month={day_obj.month:02d}/day={day_obj.day:02d}/"
        f"part-{int(min_id)}-{int(max_id)}.parquet"
    )


def group_rows_by_partition(
    rows: Sequence[Dict[str, Any]],
    *,
    max_part_rows: int = MAX_PART_ROWS,
    max_part_raw_bytes: int = MAX_PART_RAW_BYTES,
) -> List[Tuple[str, date, List[Dict[str, Any]]]]:
    """
    Groups keyset-ordered rows by (source, utc_day) and caps each partition chunk
    at max_part_rows (default 50,000) and ~max_part_raw_bytes (~35 MB).
    Preserves ascending id order within each group.
    """
    grouped: Dict[Tuple[str, date], List[Dict[str, Any]]] = {}
    for row in rows:
        utc_dt = ensure_utc_datetime(row["created_at"])
        utc_day = utc_dt.date()
        source = "admin_eval" if str(row.get("source") or "") == "admin_eval" else "user"
        key = (source, utc_day)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(row)

    partitions: List[Tuple[str, date, List[Dict[str, Any]]]] = []
    for (source, utc_day) in sorted(grouped.keys(), key=lambda k: (k[1], k[0])):
        day_rows = sorted(grouped[(source, utc_day)], key=lambda r: int(r["id"]))
        current_chunk: List[Dict[str, Any]] = []
        current_bytes = 0

        for r in day_rows:
            row_est_bytes = len(str(r.get("query") or "")) + len(str(r.get("candidate_scores") or "")) + 256
            if current_chunk and (
                len(current_chunk) >= max_part_rows
                or (current_bytes + row_est_bytes > max_part_raw_bytes)
            ):
                partitions.append((source, utc_day, current_chunk))
                current_chunk = []
                current_bytes = 0
            current_chunk.append(r)
            current_bytes += row_est_bytes

        if current_chunk:
            partitions.append((source, utc_day, current_chunk))

    return partitions


def write_parquet_artifact(
    source: str,
    utc_day: date,
    rows: Sequence[Dict[str, Any]],
    *,
    compression: str = "zstd",
) -> LocalParquetArtifact:
    """
    Builds a pyarrow.Table for the partition, writes a compressed Parquet file to a
    Windows-safe temporary file, verifies its footer metadata and row count, computes
    SHA-256, and unlinks the temporary file in `finally`.
    """
    if not rows:
        raise ValueError("Cannot build Parquet artifact from empty row sequence.")

    sorted_rows = sorted(rows, key=lambda r: int(r["id"]))
    row_ids = [int(r["id"]) for r in sorted_rows]
    min_id = row_ids[0]
    max_id = row_ids[-1]
    object_key = build_archive_object_key(source, utc_day, min_id, max_id)

    usage_by_key: Dict[str, int] = {}
    for r in sorted_rows:
        raw_key_id = r.get("api_key_id")
        if raw_key_id is not None and str(raw_key_id).strip():
            norm_key = str(uuid.UUID(str(raw_key_id).strip()))
            usage_by_key[norm_key] = usage_by_key.get(norm_key, 0) + 1

    table = rows_to_arrow_table(sorted_rows)
    raw_json_size = estimate_raw_json_bytes(sorted_rows)

    comp_upper = compression.strip().upper()
    if comp_upper not in ("ZSTD", "SNAPPY"):
        raise ValueError(f"Unsupported Parquet compression: {compression}")

    tmp_file = tempfile.NamedTemporaryFile(
        prefix="telemetry_archive_",
        suffix=".parquet",
        delete=False,
    )
    tmp_path = tmp_file.name
    tmp_file.close()

    try:
        write_kwargs: Dict[str, Any] = {
            "compression": comp_upper,
            "use_dictionary": True,
            "write_statistics": True,
        }
        if comp_upper == "ZSTD":
            write_kwargs["compression_level"] = 9

        pq.write_table(table, tmp_path, **write_kwargs)

        with open(tmp_path, "rb") as f:
            parquet_bytes = f.read()

        file_size = len(parquet_bytes)
        sha256_hex = hashlib.sha256(parquet_bytes).hexdigest()

        pq_file = pq.ParquetFile(io.BytesIO(parquet_bytes))
        if pq_file.metadata.num_rows != len(sorted_rows):
            raise ArchiveVerificationError(
                f"Local Parquet row count mismatch for {object_key}: "
                f"expected {len(sorted_rows)}, got {pq_file.metadata.num_rows}"
            )

        return LocalParquetArtifact(
            object_key=object_key,
            source=source,
            utc_day=utc_day.isoformat(),
            min_id=min_id,
            max_id=max_id,
            num_rows=len(sorted_rows),
            file_size=file_size,
            raw_json_bytes=raw_json_size,
            sha256=sha256_hex,
            parquet_bytes=parquet_bytes,
            row_ids=row_ids,
            usage_by_key=usage_by_key,
        )
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError as exc:
                logger.warning(f"[Archiver] Failed to unlink temporary file {tmp_path}: {exc}")


# ---------------------------------------------------------------------------
# Storage Abstraction, Tenacity Retry Policy & Remote Verification
# ---------------------------------------------------------------------------

class ArchiveStorageProtocol(Protocol):
    """Protocol implemented by SupabaseArchiveStorage and test storage mocks."""

    def object_exists(self, object_key: str) -> bool:
        ...

    def upload_bytes(
        self,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        ...

    def download_bytes(self, object_key: str) -> bytes:
        ...


def is_retryable_storage_exception(exc: BaseException) -> bool:
    """
    Determines whether a storage exception is a transient network/timeout/5xx/429
    error that should be retried by tenacity.
    Never retries 4xx client/auth errors or ArchiveVerificationError.
    """
    if isinstance(exc, (ArchiveVerificationError, ArchiveDeleteError, ArchiveStorageClientError)):
        return False
    if isinstance(exc, (RetryableStorageError, ConnectionError, TimeoutError, OSError)):
        return True

    status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status_code is not None:
        try:
            code_int = int(status_code)
            return code_int >= 500 or code_int == 429
        except (TypeError, ValueError):
            pass

    msg = str(exc).lower()
    non_retryable_tokens = ("400", "401", "403", "404", "unauthorized", "forbidden", "invalid jwt")
    if any(tok in msg for tok in non_retryable_tokens):
        return False

    retryable_tokens = (
        "500",
        "502",
        "503",
        "504",
        "429",
        "timeout",
        "timed out",
        "connection",
        "network",
        "temporarily unavailable",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "reset by peer",
    )
    return any(tok in msg for tok in retryable_tokens)


def make_storage_retry_decorator(
    *,
    max_attempts: int = 5,
    wait_min: float = 1.0,
    wait_max: float = 16.0,
    wait_multiplier: float = 1.0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Builds a tenacity retry decorator for storage upload/download operations:
    exponential backoff, 5 attempts, network/5xx errors only.
    """
    return tenacity.retry(
        reraise=True,
        stop=tenacity.stop_after_attempt(max_attempts),
        wait=tenacity.wait_exponential(multiplier=wait_multiplier, min=wait_min, max=wait_max),
        retry=tenacity.retry_if_exception(is_retryable_storage_exception),
    )


class SupabaseArchiveStorage:
    """
    Adapter around the official Supabase Storage SDK for the private
    'telemetry-archives' bucket.
    """

    def __init__(
        self,
        bucket_name: str = ARCHIVE_BUCKET_NAME,
        supabase_url: Optional[str] = None,
        service_role_key: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        self.bucket_name = bucket_name
        if client is not None:
            self._client = client
        else:
            url = supabase_url or os.getenv("SUPABASE_URL")
            key = service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            if not url or not key:
                raise ArchiveStorageClientError(
                    "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for SupabaseArchiveStorage."
                )
            from supabase import create_client
            self._client = create_client(url, key)

    @property
    def _bucket(self) -> Any:
        return self._client.storage.from_(self.bucket_name)

    def object_exists(self, object_key: str) -> bool:
        folder = os.path.dirname(object_key).replace("\\", "/")
        filename = os.path.basename(object_key)
        res = self._bucket.list(path=folder, options={"search": filename, "limit": 100})
        if isinstance(res, list):
            return any(isinstance(item, dict) and item.get("name") == filename for item in res)
        return False

    def upload_bytes(
        self,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        self._bucket.upload(
            path=object_key,
            file=data,
            file_options={"content-type": content_type, "upsert": "false"},
        )

    def download_bytes(self, object_key: str) -> bytes:
        res = self._bucket.download(object_key)
        if isinstance(res, (bytes, bytearray)):
            return bytes(res)
        raise ArchiveVerificationError(
            f"Unexpected download response type for {object_key}: {type(res).__name__}"
        )


def verify_remote_parquet(
    remote_bytes: bytes,
    *,
    object_key: str,
    expected_rows: int,
    expected_size: Optional[int] = None,
    expected_ids: Optional[Sequence[int]] = None,
    expected_sha256: Optional[str] = None,
) -> None:
    """
    Verifies a downloaded Parquet object from Storage before any DB deletion is allowed:
    1. Confirms remote byte length is non-empty and matches expected_size (when provided).
    2. Confirms pq.ParquetFile(BytesIO(remote_bytes)).metadata.num_rows == expected_rows.
    3. Confirms Arrow schema column names match RECOMMENDATION_LOGS_ARROW_SCHEMA.
    4. Confirms the 'id' column in the remote Parquet matches expected_ids (when provided).
    5. Confirms SHA-256 digest matches expected_sha256 (when provided).
    Raises ArchiveVerificationError on any discrepancy.
    """
    if not isinstance(remote_bytes, (bytes, bytearray)) or len(remote_bytes) == 0:
        raise ArchiveVerificationError(
            f"Remote Parquet verification failed for {object_key}: empty or invalid payload."
        )

    actual_size = len(remote_bytes)
    if expected_size is not None and actual_size != expected_size:
        raise ArchiveVerificationError(
            f"Remote Parquet size mismatch for {object_key}: "
            f"expected {expected_size} bytes, got {actual_size} bytes."
        )

    if expected_sha256 is not None:
        actual_sha256 = hashlib.sha256(remote_bytes).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ArchiveVerificationError(
                f"Remote Parquet SHA-256 mismatch for {object_key}: "
                f"expected {expected_sha256}, got {actual_sha256}."
            )

    try:
        pq_file = pq.ParquetFile(io.BytesIO(remote_bytes))
        actual_rows = pq_file.metadata.num_rows
    except Exception as exc:
        raise ArchiveVerificationError(
            f"Remote Parquet footer unreadable for {object_key}: {exc}"
        ) from exc

    if actual_rows != expected_rows:
        raise ArchiveVerificationError(
            f"Remote Parquet row count mismatch for {object_key}: "
            f"expected {expected_rows} rows, got {actual_rows} rows."
        )

    try:
        remote_table = pq.read_table(io.BytesIO(remote_bytes))
    except Exception as exc:
        raise ArchiveVerificationError(
            f"Remote Parquet table unreadable for {object_key}: {exc}"
        ) from exc

    if tuple(remote_table.schema.names) != COLUMN_NAMES:
        raise ArchiveVerificationError(
            f"Remote Parquet schema mismatch for {object_key}: "
            f"expected {COLUMN_NAMES}, got {tuple(remote_table.schema.names)}"
        )

    if expected_ids is not None:
        remote_ids = [int(x) for x in remote_table.column("id").to_pylist()]
        if remote_ids != list(expected_ids):
            raise ArchiveVerificationError(
                f"Remote Parquet ID sequence mismatch for {object_key}: "
                f"expected {len(expected_ids)} exact IDs [{expected_ids[0]}..{expected_ids[-1]}], "
                f"got {len(remote_ids)} IDs."
            )


# ---------------------------------------------------------------------------
# Transactional Rollup Reconciliation & Batched Exact-ID Deletion
# ---------------------------------------------------------------------------

def commit_verified_part_deletion(
    conn: Any,
    *,
    row_ids: Sequence[int],
    cutoff: datetime,
    usage_rows: Sequence[Tuple[str, date, int]],
    delete_batch_size: int = DEFAULT_DELETE_BATCH_SIZE,
) -> int:
    """
    Executes in a SINGLE database transaction (only after remote Parquet verification succeeds):
    1. Reconciles telemetry.api_key_usage_daily via GREATEST(request_count, EXCLUDED.request_count)
       so daily usage survives pruning without double-counting live increments or re-runs.
    2. Deletes the exact verified row IDs from telemetry.recommendation_logs in sub-batches
       of delete_batch_size (5,000-10,000) with `WHERE id = ANY(%s) AND created_at < %s`.
    3. Asserts cur.rowcount == len(sub_batch) on every sub-batch.
    4. Commits on full success or rolls back completely on any failure.
    Never retried blindly.
    """
    if delete_batch_size <= 0:
        raise ValueError(f"delete_batch_size must be > 0, got {delete_batch_size}")

    ids_list = [int(i) for i in row_ids]
    if not ids_list:
        return 0

    total_deleted = 0
    try:
        with conn.cursor() as cur:
            for api_key_id, day_val, count_val in usage_rows:
                cur.execute(
                    UPSERT_USAGE_DAILY_FLOOR_SQL,
                    (str(api_key_id), day_val, int(count_val)),
                )

            for idx in range(0, len(ids_list), delete_batch_size):
                sub_batch = ids_list[idx : idx + delete_batch_size]
                cur.execute(DELETE_LOGS_BY_IDS_SQL, (sub_batch, cutoff))
                if cur.rowcount != len(sub_batch):
                    raise ArchiveDeleteError(
                        f"Exact-ID delete rowcount mismatch: expected {len(sub_batch)}, "
                        f"got {cur.rowcount}"
                    )
                total_deleted += cur.rowcount

        conn.commit()
        return total_deleted
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        if isinstance(exc, ArchiveDeleteError):
            raise
        raise ArchiveDeleteError(f"Failed transactional delete of verified batch: {exc}") from exc


# ---------------------------------------------------------------------------
# Main Archiver Orchestration
# ---------------------------------------------------------------------------

def run_archiver(
    *,
    conn: Optional[Any] = None,
    storage: Optional[ArchiveStorageProtocol] = None,
    days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
    batch_size: int = DEFAULT_FETCH_BATCH_SIZE,
    delete_batch_size: int = DEFAULT_DELETE_BATCH_SIZE,
    max_part_rows: int = MAX_PART_ROWS,
    compression: str = "zstd",
    retry_max_attempts: int = 5,
    retry_wait_min: float = 1.0,
    retry_wait_max: float = 16.0,
    after_verify_hook: Optional[Callable[[LocalParquetArtifact], None]] = None,
) -> ArchiveRunSummary:
    """
    Executes the end-to-end Sprint 4 Parquet archival flow.
    """
    t0 = time.perf_counter()
    owns_conn = conn is None
    active_conn = conn if conn is not None else connect_archiver_db()
    lock_acquired = False

    summary = ArchiveRunSummary(
        status="started",
        dry_run=bool(dry_run),
        days=int(days),
        cutoff_utc=None,
        advisory_lock_acquired=False,
    )

    retry_wrap = make_storage_retry_decorator(
        max_attempts=retry_max_attempts,
        wait_min=retry_wait_min,
        wait_max=retry_wait_max,
    )

    try:
        lock_acquired = try_acquire_advisory_lock(active_conn)
        summary.advisory_lock_acquired = lock_acquired
        if not lock_acquired:
            logger.info("[Archiver] Advisory lock is already held by another process; exiting cleanly.")
            summary.status = "locked"
            summary.duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return summary

        cutoff = compute_fixed_cutoff(active_conn, days=days)
        summary.cutoff_utc = cutoff.isoformat()
        logger.info(
            f"[Archiver] Starting archival run (dry_run={dry_run}, days={days}, cutoff={summary.cutoff_utc})."
        )

        if not dry_run and storage is None:
            storage = SupabaseArchiveStorage()

        cumulative_usage: Dict[Tuple[str, date], int] = {}
        touched_usage_keys: set[Tuple[str, date]] = set()
        last_id = 0

        while True:
            batch_rows = fetch_keyset_batch(
                active_conn,
                last_id=last_id,
                cutoff=cutoff,
                batch_size=batch_size,
            )
            if not batch_rows:
                break

            summary.batches_fetched += 1
            summary.rows_scanned += len(batch_rows)
            last_id = max(int(r["id"]) for r in batch_rows)

            partitions = group_rows_by_partition(
                batch_rows,
                max_part_rows=min(batch_size, max_part_rows),
            )

            for source, utc_day, part_rows in partitions:
                artifact = write_parquet_artifact(
                    source=source,
                    utc_day=utc_day,
                    rows=part_rows,
                    compression=compression,
                )

                summary.rows_archived += artifact.num_rows
                summary.total_parquet_bytes += artifact.file_size
                summary.total_raw_json_bytes += artifact.raw_json_bytes

                if dry_run:
                    part_res = PartArchiveResult(
                        object_key=artifact.object_key,
                        source=artifact.source,
                        utc_day=artifact.utc_day,
                        min_id=artifact.min_id,
                        max_id=artifact.max_id,
                        num_rows=artifact.num_rows,
                        file_size=artifact.file_size,
                        raw_json_bytes=artifact.raw_json_bytes,
                        sha256=artifact.sha256,
                        skipped_existing=False,
                        deleted_rows=0,
                    )
                    summary.parts.append(asdict(part_res))
                    continue

                assert storage is not None
                exists_fn = retry_wrap(storage.object_exists)
                upload_fn = retry_wrap(storage.upload_bytes)
                download_fn = retry_wrap(storage.download_bytes)

                already_exists = bool(exists_fn(artifact.object_key))
                skipped_existing = False

                if already_exists:
                    logger.info(
                        f"[Archiver] Object '{artifact.object_key}' already exists; verifying before skip."
                    )
                    remote_bytes = download_fn(artifact.object_key)
                    verify_remote_parquet(
                        remote_bytes,
                        object_key=artifact.object_key,
                        expected_rows=artifact.num_rows,
                        expected_size=artifact.file_size,
                        expected_ids=artifact.row_ids,
                    )
                    skipped_existing = True
                    summary.parts_skipped_existing += 1
                else:
                    upload_fn(
                        artifact.object_key,
                        artifact.parquet_bytes,
                        "application/octet-stream",
                    )
                    remote_bytes = download_fn(artifact.object_key)
                    verify_remote_parquet(
                        remote_bytes,
                        object_key=artifact.object_key,
                        expected_rows=artifact.num_rows,
                        expected_size=artifact.file_size,
                        expected_ids=artifact.row_ids,
                        expected_sha256=artifact.sha256,
                    )
                    summary.parts_uploaded += 1

                if after_verify_hook is not None:
                    after_verify_hook(artifact)

                usage_rows_for_part: List[Tuple[str, date, int]] = []
                for key_id_str, count_inc in artifact.usage_by_key.items():
                    u_key = (key_id_str, utc_day)
                    cumulative_usage[u_key] = cumulative_usage.get(u_key, 0) + count_inc
                    touched_usage_keys.add(u_key)
                    usage_rows_for_part.append((key_id_str, utc_day, cumulative_usage[u_key]))

                deleted_count = commit_verified_part_deletion(
                    active_conn,
                    row_ids=artifact.row_ids,
                    cutoff=cutoff,
                    usage_rows=usage_rows_for_part,
                    delete_batch_size=delete_batch_size,
                )
                summary.rows_deleted += deleted_count
                summary.usage_keys_updated = len(touched_usage_keys)

                part_res = PartArchiveResult(
                    object_key=artifact.object_key,
                    source=artifact.source,
                    utc_day=artifact.utc_day,
                    min_id=artifact.min_id,
                    max_id=artifact.max_id,
                    num_rows=artifact.num_rows,
                    file_size=artifact.file_size,
                    raw_json_bytes=artifact.raw_json_bytes,
                    sha256=artifact.sha256,
                    skipped_existing=skipped_existing,
                    deleted_rows=deleted_count,
                )
                summary.parts.append(asdict(part_res))

        if summary.total_raw_json_bytes > 0:
            summary.compression_ratio = round(
                summary.total_parquet_bytes / float(summary.total_raw_json_bytes),
                4,
            )
        summary.status = "dry_run_ok" if dry_run else "ok"
        summary.duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return summary

    except Exception as exc:
        summary.status = "error"
        summary.error = str(exc)
        summary.duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        logger.error(f"[Archiver] Archival run failed: {exc}")
        raise
    finally:
        if lock_acquired:
            release_advisory_lock(active_conn)
        if owns_conn and active_conn is not None and getattr(active_conn, "closed", 1) == 0:
            try:
                active_conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# User-Requested Privacy Erasure Path (Hot DB + Cold Parquet Archives)
# ---------------------------------------------------------------------------

def erase_subject_from_parquet_bytes(
    parquet_bytes: bytes,
    *,
    api_key_id: Optional[str] = None,
    session_id: Optional[str] = None,
    compression: str = "zstd",
) -> Tuple[Optional[bytes], int]:
    """
    Filters a cold Parquet archive file to remove rows matching api_key_id or session_id.
    Returns (new_parquet_bytes_or_None_if_empty, removed_row_count).
    """
    if not api_key_id and not session_id:
        raise ValueError("At least one of api_key_id or session_id must be specified for erasure.")

    table = pq.read_table(io.BytesIO(parquet_bytes))
    initial_rows = table.num_rows
    if initial_rows == 0:
        return None, 0

    keep_mask = None
    if api_key_id:
        norm_key = str(uuid.UUID(str(api_key_id).strip()))
        col = table.column("api_key_id")
        key_match = pc.equal(col, pa.scalar(norm_key, type=pa.string()))
        keep_key = pc.or_kleene(pc.is_null(col), pc.invert(key_match))
        keep_mask = keep_key

    if session_id:
        col_sess = table.column("session_id")
        sess_match = pc.equal(col_sess, pa.scalar(str(session_id), type=pa.string()))
        keep_sess = pc.or_kleene(pc.is_null(col_sess), pc.invert(sess_match))
        keep_mask = keep_sess if keep_mask is None else pc.and_kleene(keep_mask, keep_sess)

    filtered_table = table.filter(keep_mask)
    removed_count = initial_rows - filtered_table.num_rows
    if removed_count == 0:
        return parquet_bytes, 0
    if filtered_table.num_rows == 0:
        return None, removed_count

    buf = io.BytesIO()
    comp_upper = compression.strip().upper()
    pq.write_table(
        filtered_table,
        buf,
        compression=comp_upper,
        compression_level=9 if comp_upper == "ZSTD" else None,
        use_dictionary=True,
        write_statistics=True,
    )
    return buf.getvalue(), removed_count


def erase_subject_from_telemetry(
    conn: Any,
    *,
    api_key_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, int]:
    """
    Executes user-requested privacy erasure on hot telemetry tables
    (telemetry.recommendation_logs and telemetry.api_key_usage_daily).
    """
    if not api_key_id and not session_id:
        raise ValueError("Must provide api_key_id or session_id for telemetry erasure.")

    deleted_logs = 0
    deleted_usage = 0
    try:
        with conn.cursor() as cur:
            if api_key_id is not None:
                norm_key = str(uuid.UUID(str(api_key_id).strip()))
                cur.execute(ERASE_HOT_LOGS_BY_KEY_SQL, (norm_key,))
                deleted_logs += cur.rowcount
                cur.execute(ERASE_HOT_USAGE_BY_KEY_SQL, (norm_key,))
                deleted_usage += cur.rowcount
            if session_id is not None:
                cur.execute(ERASE_HOT_LOGS_BY_SESSION_SQL, (str(session_id),))
                deleted_logs += cur.rowcount
        conn.commit()
        return {"deleted_logs": deleted_logs, "deleted_usage_rows": deleted_usage}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sprint 4 Crash-Safe Telemetry Parquet Archiver"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help="Archive rows older than N days before UTC midnight (default: 30).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan, group, and measure Parquet sizes without uploading or deleting.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_FETCH_BATCH_SIZE,
        help="Keyset fetch limit per query (default: 50000).",
    )
    parser.add_argument(
        "--delete-batch-size",
        type=int,
        default=DEFAULT_DELETE_BATCH_SIZE,
        help="Number of exact IDs per DELETE statement (default: 5000).",
    )
    parser.add_argument(
        "--compression",
        choices=["zstd", "snappy"],
        default="zstd",
        help="Parquet compression codec (default: zstd).",
    )
    parser.add_argument(
        "--summary-file",
        type=str,
        default=None,
        help="Optional path to write the JSON run summary.",
    )
    parser.add_argument(
        "--manifest-file",
        "--manifest-path",
        dest="manifest_file",
        type=str,
        default=None,
        help="Optional path to write the JSON parts manifest.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    return parser


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    conn: Optional[Any] = None,
    storage: Optional[ArchiveStorageProtocol] = None,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        summary = run_archiver(
            conn=conn,
            storage=storage,
            days=args.days,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            delete_batch_size=args.delete_batch_size,
            compression=args.compression,
        )
        summary_dict = summary.to_dict()
        summary_json = json.dumps(summary_dict, indent=2, sort_keys=True)
        print(summary_json)

        if args.summary_file:
            with open(args.summary_file, "w", encoding="utf-8") as f:
                f.write(summary_json + "\n")

        if args.manifest_file:
            manifest_payload = {
                "status": summary.status,
                "dry_run": summary.dry_run,
                "days": summary.days,
                "cutoff_utc": summary.cutoff_utc,
                "total_parts": len(summary.parts),
                "total_rows_archived": summary.rows_archived,
                "total_rows_deleted": summary.rows_deleted,
                "total_parquet_bytes": summary.total_parquet_bytes,
                "compression_ratio": summary.compression_ratio,
                "parts": summary.parts,
            }
            with open(args.manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest_payload, f, indent=2, sort_keys=True)
                f.write("\n")

        return 0
    except Exception as exc:
        error_payload = {
            "status": "error",
            "dry_run": bool(args.dry_run),
            "days": int(args.days),
            "error": str(exc),
        }
        print(json.dumps(error_payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
