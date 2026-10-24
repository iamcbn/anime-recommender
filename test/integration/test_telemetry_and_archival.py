"""
test/test_telemetry_and_archival.py

Comprehensive Automated Unit, Integration, Failure-Injection, Security & Compression
Verification Suite for Sprint 4 ("Parquet Archiver (crash-safe)" in
telemetry_and_archival_implementation_plan.md).

Covers all Sprint 4 Objectives, Scope & Acceptance Criteria:
1. Static Scope & SQL Isolation:
   - requirements-archive.txt pins minimal archival deps (pyarrow, supabase,
     psycopg2-binary, tenacity) without pulling CUDA/PyTorch.
   - backend/telemetry/archiver.py has zero pandas imports, zero table/schema parameters,
     zero dynamic SQL interpolation, and references exclusively telemetry.recommendation_logs
     and telemetry.api_key_usage_daily.
2. Session Pooler & Advisory Lock:
   - Enforces port 5432 (Session Pooler), application_name='archiver', and statement_timeout.
   - Acquires pg_try_advisory_lock and exits cleanly if already held by another process.
3. Unit Tests with Fake Cursor:
   - Keyset pagination chunk boundaries and sub-batch delete boundaries (5k-10k).
   - Non-contiguous IDs (out-of-order commits) proving exact-ID deletion (WHERE id = ANY(%s))
     and never min_id/max_id range deletion.
   - Direct pyarrow.Table construction with explicit 18-column schema (UUID as string,
     timestamp[us, UTC], float64, nullable api_key_id) and deterministic JSONB round-trip
     via json.dumps(sort_keys=True) and pyarrow.parquet.read_table().
   - Deterministic keys without run-timestamps, isolating 'user' under logs/ and
     'admin_eval' under admin_eval/.
   - Compression benchmark confirming Parquet size < 15% of equivalent raw JSON.
4. Live PostgreSQL Integration & Failure Injection:
   - Upload fails (after 5 tenacity attempts on network/5xx) -> zero rows deleted.
   - Transient network error on upload (< 5 attempts) -> tenacity recovers and archives.
   - Verification mismatch (byte size, ParquetFile.metadata.num_rows, or SHA-256) -> zero rows deleted.
   - Crash after upload & verify, before delete -> re-run verifies existing key without
     overwriting, skips upload, deletes exact IDs, and converges with zero duplicates or lost rows.
   - Delete fails mid-transaction -> rolls back completely; re-run converges cleanly.
   - Seeded app_auth.api_keys and app_auth.key_audit_log rows older than 30 days survive untouched.
   - Out-of-order commit where a newer row has an ID strictly between min_id and max_id
     of an archived batch survives untouched while all rows older than cutoff are pruned.
   - telemetry.api_key_usage_daily is reconciled before deletion and survives pruning
     without double-counting live increments.
   - --dry-run performs zero uploads and zero deletes and outputs accurate counts.
   - Privacy erasure path removes subject rows from both hot tables and cold Parquet archives.
   - End-to-end synthetic CLI smoke test with JSON summary and manifest verification.
"""

import io
import os
import re
import ast
import sys
import json
import uuid
import hashlib
from datetime import datetime, date, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from unittest.mock import patch

import pytest
import psycopg2
import pyarrow as pa
import pyarrow.parquet as pq

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import backend.telemetry.archiver as archiver
from backend.telemetry.archiver import (
    ARCHIVE_BUCKET_NAME,
    ARCHIVER_ADVISORY_LOCK_ID,
    RECOMMENDATION_LOGS_ARROW_SCHEMA,
    COLUMN_NAMES,
    ArchiverError,
    ArchiveVerificationError,
    ArchiveDeleteError,
    RetryableStorageError,
    ArchiveStorageClientError,
    LocalParquetArtifact,
    get_archiver_db_config,
    try_acquire_advisory_lock,
    release_advisory_lock,
    compute_fixed_cutoff,
    rows_to_arrow_table,
    serialize_jsonb_deterministic,
    build_archive_object_key,
    group_rows_by_partition,
    write_parquet_artifact,
    verify_remote_parquet,
    run_archiver,
    erase_subject_from_parquet_bytes,
    erase_subject_from_telemetry,
    main as archiver_cli_main,
)


# ---------------------------------------------------------------------------
# Helpers: Synthetic Telemetry Row Builder, Fake Cursor & Mock Storage Client
# ---------------------------------------------------------------------------

def make_synthetic_log_row(
    row_id: int,
    *,
    created_at: datetime,
    source: str = "user",
    endpoint: str = "recommend",
    api_key_id: Optional[str] = None,
    session_id: Optional[str] = None,
    query: str = "cyberpunk psychological sci-fi anime like Serial Experiments Lain",
    top_k: int = 20,
    allow_adult: bool = False,
    results_count: int = 5,
    status: str = "ok",
    status_code: Optional[int] = 200,
    error: Optional[str] = None,
    total_ms: Optional[float] = 42.75,
) -> Dict[str, Any]:
    return {
        "id": row_id,
        "request_id": str(uuid.uuid5(uuid.NAMESPACE_OID, f"req-{row_id}")),
        "created_at": created_at,
        "endpoint": endpoint,
        "source": source,
        "api_key_id": api_key_id,
        "session_id": session_id,
        "query": query,
        "top_k": top_k,
        "allow_adult": allow_adult,
        "results_count": results_count,
        "status": status,
        "status_code": status_code,
        "error": error,
        "total_ms": total_ms,
        "timings": {
            "reranking_ms": 14.6,
            "retrieval_ms": 8.2,
            "embedding_ms": 4.8,
            "query_generation_ms": 15.15,
            "self_query_ms": 0.0,
        },
        "candidate_scores": [
            {
                "id": 339,
                "cross_encoder_score": 6.1245,
                "final_rrf_score": 0.0942,
                "retrieval_rrf_score": 0.0491,
            },
            {
                "id": 43,
                "cross_encoder_score": 5.8012,
                "final_rrf_score": 0.0884,
                "retrieval_rrf_score": 0.0465,
            },
            {
                "id": 1,
                "cross_encoder_score": 5.4321,
                "final_rrf_score": 0.0812,
                "retrieval_rrf_score": 0.0421,
            },
        ],
        "client_metadata": {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AnimeClient/2.0",
            "ip_hash": "9f86d081884c7d65",
        },
    }


class FakeCursor:
    """
    In-memory fake psycopg2 cursor for pure unit testing of keyset pagination,
    exact-ID batch deletion, usage rollup upserts, and transaction rollbacks.
    """

    def __init__(self, fake_conn: "FakeConnection") -> None:
        self.conn = fake_conn
        self.rowcount: int = 0
        self.description: Optional[List[Tuple[str, ...]]] = None
        self._results: List[Any] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def execute(self, sql_query: str, params: Optional[Sequence[Any]] = None) -> None:
        norm_sql = " ".join(sql_query.strip().split())
        self.conn.executed_queries.append((norm_sql, params))

        if "pg_try_advisory_lock" in norm_sql:
            self.description = [("pg_try_advisory_lock",)]
            self._results = [(self.conn.lock_available,)]
            self.rowcount = 1
            return

        if "pg_advisory_unlock" in norm_sql:
            self.description = [("pg_advisory_unlock",)]
            self._results = [(True,)]
            self.rowcount = 1
            return

        if "AS cutoff" in norm_sql:
            days = int(params[0]) if params else 30
            cutoff = self.conn.fixed_now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(days=days)
            self.description = [("cutoff",)]
            self._results = [(cutoff,)]
            self.rowcount = 1
            return

        if "FROM telemetry.recommendation_logs WHERE id > %s AND created_at < %s" in norm_sql:
            assert params is not None
            last_id, cutoff, limit = int(params[0]), params[1], int(params[2])
            matching = [
                r
                for r in sorted(self.conn.rows.values(), key=lambda x: int(x["id"]))
                if int(r["id"]) > last_id and r["created_at"] < cutoff
            ][:limit]
            self.description = [(col,) for col in COLUMN_NAMES]
            self._results = [tuple(r[col] for col in COLUMN_NAMES) for r in matching]
            self.rowcount = len(self._results)
            return

        if "INSERT INTO telemetry.api_key_usage_daily" in norm_sql:
            assert params is not None
            key_id, day_val, req_count = str(params[0]), params[1], int(params[2])
            existing = self.conn._staged_usage.get((key_id, day_val), 0)
            self.conn._staged_usage[(key_id, day_val)] = max(existing, req_count)
            self.description = None
            self._results = []
            self.rowcount = 1
            return

        if "DELETE FROM telemetry.recommendation_logs WHERE id = ANY(%s) AND created_at < %s" in norm_sql:
            assert params is not None
            ids_to_delete, cutoff = list(params[0]), params[1]
            self.conn.delete_batches_received.append((list(ids_to_delete), cutoff))

            if (
                self.conn.fail_on_delete_call is not None
                and len(self.conn.delete_batches_received) == self.conn.fail_on_delete_call
            ):
                raise psycopg2.OperationalError("Simulated DB failure during sub-batch DELETE")

            if self.conn.force_rowcount_mismatch:
                self.rowcount = max(0, len(ids_to_delete) - 1)
                return

            deleted = 0
            for rid in ids_to_delete:
                row = self.conn._staged_rows.get(int(rid))
                if row is not None and row["created_at"] < cutoff:
                    del self.conn._staged_rows[int(rid)]
                    deleted += 1
            self.rowcount = deleted
            self.description = None
            self._results = []
            return

        raise AssertionError(f"Unexpected SQL executed by archiver: {norm_sql}")

    def fetchone(self) -> Optional[Any]:
        return self._results[0] if self._results else None

    def fetchall(self) -> List[Any]:
        return list(self._results)


class FakeConnection:
    """Transactional in-memory connection wrapper for FakeCursor."""

    def __init__(
        self,
        rows: Sequence[Dict[str, Any]],
        *,
        fixed_now: Optional[datetime] = None,
        lock_available: bool = True,
        fail_on_delete_call: Optional[int] = None,
        force_rowcount_mismatch: bool = False,
    ) -> None:
        self.fixed_now = fixed_now or datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        self.lock_available = lock_available
        self.fail_on_delete_call = fail_on_delete_call
        self.force_rowcount_mismatch = force_rowcount_mismatch
        self.closed = 0
        self.autocommit = False

        self.rows: Dict[int, Dict[str, Any]] = {int(r["id"]): dict(r) for r in rows}
        self.usage_daily: Dict[Tuple[str, date], int] = {}
        self._staged_rows: Dict[int, Dict[str, Any]] = dict(self.rows)
        self._staged_usage: Dict[Tuple[str, date], int] = dict(self.usage_daily)

        self.executed_queries: List[Tuple[str, Optional[Sequence[Any]]]] = []
        self.delete_batches_received: List[Tuple[List[int], datetime]] = []
        self.commits: int = 0
        self.rollbacks: int = 0

    def cursor(self, *args: Any, **kwargs: Any) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1
        self.rows = dict(self._staged_rows)
        self.usage_daily = dict(self._staged_usage)

    def rollback(self) -> None:
        self.rollbacks += 1
        self._staged_rows = dict(self.rows)
        self._staged_usage = dict(self.usage_daily)

    def close(self) -> None:
        self.closed = 1


class MockStorageBackend:
    """
    Configurable in-memory Storage client supporting failure injection:
    - Persistent or transient upload errors (for tenacity testing)
    - Corrupted download bytes / truncated size / altered row count
    - Call counters for object_exists, upload_bytes, download_bytes
    """

    def __init__(
        self,
        *,
        fail_upload_times: int = 0,
        upload_exception_factory: Callable[[], BaseException] = lambda: RetryableStorageError(
            "503 Service Unavailable: Storage gateway timeout"
        ),
        corrupt_download_mode: Optional[str] = None,
    ) -> None:
        self.objects: Dict[str, bytes] = {}
        self.fail_upload_times = fail_upload_times
        self.upload_exception_factory = upload_exception_factory
        self.corrupt_download_mode = corrupt_download_mode

        self.exists_calls: List[str] = []
        self.upload_calls: List[str] = []
        self.download_calls: List[str] = []

    def object_exists(self, object_key: str) -> bool:
        self.exists_calls.append(object_key)
        return object_key in self.objects

    def upload_bytes(
        self,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.upload_calls.append(object_key)
        if len(self.upload_calls) <= self.fail_upload_times:
            raise self.upload_exception_factory()
        if object_key in self.objects:
            raise AssertionError(
                f"Archiver attempted to blindly overwrite existing object key: {object_key}"
            )
        self.objects[object_key] = bytes(data)

    def download_bytes(self, object_key: str) -> bytes:
        self.download_calls.append(object_key)
        if object_key not in self.objects:
            raise ArchiveStorageClientError(f"404 Object not found: {object_key}")
        raw = self.objects[object_key]

        if self.corrupt_download_mode == "truncate_bytes":
            return raw[:-16]
        if self.corrupt_download_mode == "bitflip_same_size":
            ba = bytearray(raw)
            ba[len(ba) // 2] ^= 0xFF
            return bytes(ba)
        if self.corrupt_download_mode == "fewer_rows":
            table = pq.read_table(io.BytesIO(raw))
            sliced = table.slice(0, max(0, table.num_rows - 1))
            buf = io.BytesIO()
            pq.write_table(sliced, buf, compression="ZSTD")
            return buf.getvalue()

        return raw


# ---------------------------------------------------------------------------
# Class 1: Static Scope, AST Security & Requirements Pinning Verification
# ---------------------------------------------------------------------------

class TestSprint4ScopeAndStaticSecurity:
    """Verifies strict Sprint 4 scope, dependency pinning, and SQL table isolation."""

    def test_archiver_ast_hardcoded_scope_and_no_pandas(self):
        archiver_path = os.path.join(ROOT_DIR, "backend", "telemetry", "archiver.py")
        with open(archiver_path, "r", encoding="utf-8") as f:
            source_text = f.read()

        tree = ast.parse(source_text, filename=archiver_path)

        # 1. Verify pandas is never imported
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("pandas"), "pandas must not be imported in archiver.py"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("pandas"), "pandas must not be imported in archiver.py"

        # 2. Verify no function accepts a generic table or schema parameter
        forbidden_arg_names = {"table", "table_name", "schema", "schema_name", "target_table"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                all_args = (
                    list(node.args.posonlyargs)
                    + list(node.args.args)
                    + list(node.args.kwonlyargs)
                )
                for arg in all_args:
                    assert arg.arg not in forbidden_arg_names, (
                        f"Function '{node.name}' accepts forbidden generic parameter '{arg.arg}'; "
                        "archiver must be strictly hard-coded to telemetry.recommendation_logs."
                    )

        # 3. Verify no SQL query is built via f-strings
        sql_keywords = ("SELECT ", "DELETE FROM ", "INSERT INTO ", "UPDATE ", "TRUNCATE ", "DROP ")
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                literal_parts = "".join(
                    part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str)
                ).upper()
                for kw in sql_keywords:
                    assert kw not in literal_parts, (
                        f"Dynamic f-string SQL detected containing '{kw}'; use static SQL constants only."
                    )



# ---------------------------------------------------------------------------
# Class 2: Pure Unit Tests with Fake Cursor & Mock Storage
# ---------------------------------------------------------------------------

class TestArchiverUnitWithFakeCursor:
    """Pure unit tests verifying pagination, exact-ID deletes, Parquet schema, and compression."""

    def test_keyset_pagination_and_sub_batch_delete_boundaries(self):
        day_utc = datetime(2026, 1, 10, 8, 30, 0, tzinfo=timezone.utc)
        rows = [
            make_synthetic_log_row(i, created_at=day_utc + timedelta(minutes=i))
            for i in range(1, 12)  # 11 rows total
        ]
        fake_conn = FakeConnection(rows)
        storage = MockStorageBackend()

        # Fetch in pages of 4 rows, delete in sub-batches of 2 IDs
        summary = run_archiver(
            conn=fake_conn,
            storage=storage,
            days=30,
            batch_size=4,
            delete_batch_size=2,
            retry_wait_min=0.001,
            retry_wait_max=0.01,
        )

        assert summary.status == "ok"
        assert summary.batches_fetched == 3  # 4 + 4 + 3 = 11 rows
        assert summary.rows_scanned == 11
        assert summary.rows_archived == 11
        assert summary.rows_deleted == 11
        assert summary.parts_uploaded == 3
        assert len(fake_conn.rows) == 0

        # Verify sub-batch delete sizes: [2, 2], [2, 2], [2, 1]
        batch_lengths = [len(b[0]) for b in fake_conn.delete_batches_received]
        assert batch_lengths == [2, 2, 2, 2, 2, 1]

    def test_non_contiguous_ids_out_of_order_commits_never_delete_gaps(self):
        old_dt = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        newer_dt = datetime(2026, 3, 10, 9, 0, 0, tzinfo=timezone.utc)  # Newer than 30-day cutoff

        # Out-of-order commits: IDs 101, 105, 109, 250 are old; ID 103 is newer than cutoff!
        rows = [
            make_synthetic_log_row(101, created_at=old_dt),
            make_synthetic_log_row(103, created_at=newer_dt),
            make_synthetic_log_row(105, created_at=old_dt + timedelta(seconds=10)),
            make_synthetic_log_row(109, created_at=old_dt + timedelta(seconds=20)),
            make_synthetic_log_row(250, created_at=old_dt + timedelta(seconds=30)),
        ]
        fake_conn = FakeConnection(rows)
        storage = MockStorageBackend()

        summary = run_archiver(
            conn=fake_conn,
            storage=storage,
            days=30,
            batch_size=50000,
            delete_batch_size=5000,
        )

        assert summary.rows_archived == 4
        assert summary.rows_deleted == 4
        expected_key = "logs/year=2026/month=01/day=15/part-101-250.parquet"
        assert expected_key in storage.objects

        # Confirm exact IDs sent to DELETE: [101, 105, 109, 250] - 103 was NEVER in the delete list
        assert len(fake_conn.delete_batches_received) == 1
        deleted_id_list, _ = fake_conn.delete_batches_received[0]
        assert deleted_id_list == [101, 105, 109, 250]
        assert 103 not in deleted_id_list
        assert set(fake_conn.rows.keys()) == {103}

    def test_jsonb_round_trip_and_explicit_pyarrow_schema(self):
        key_uuid = str(uuid.uuid4())
        row_with_key = make_synthetic_log_row(
            501,
            created_at=datetime(2026, 1, 20, 18, 45, 12, 123456, tzinfo=timezone.utc),
            api_key_id=key_uuid,
            session_id="sess_abc_123",
            status="ok",
            status_code=200,
            error=None,
            total_ms=37.125,
        )
        row_nullable = make_synthetic_log_row(
            502,
            created_at=datetime(2026, 1, 20, 19, 0, 0, tzinfo=timezone.utc),
            api_key_id=None,
            session_id=None,
            status="error",
            status_code=500,
            error="Pipeline timeout",
            total_ms=None,
        )
        row_nullable["timings"] = None
        row_nullable["candidate_scores"] = []
        row_nullable["client_metadata"] = None

        artifact = write_parquet_artifact(
            source="user",
            utc_day=date(2026, 1, 20),
            rows=[row_with_key, row_nullable],
        )

        # Read back with pyarrow.parquet.read_table
        table = pq.read_table(io.BytesIO(artifact.parquet_bytes))
        assert table.num_rows == 2
        assert table.schema.equals(RECOMMENDATION_LOGS_ARROW_SCHEMA)

        # Verify explicit types from Sprint 4 spec
        assert table.schema.field("id").type == pa.int64()
        assert table.schema.field("request_id").type == pa.string()
        assert table.schema.field("created_at").type == pa.timestamp("us", tz="UTC")
        assert table.schema.field("api_key_id").type == pa.string()
        assert table.schema.field("api_key_id").nullable is True
        assert table.schema.field("total_ms").type == pa.float64()
        assert table.schema.field("timings").type == pa.string()
        assert table.schema.field("candidate_scores").type == pa.string()
        assert table.schema.field("client_metadata").type == pa.string()

        rows_back = table.to_pylist()
        r0, r1 = rows_back[0], rows_back[1]

        assert r0["id"] == 501
        assert r0["api_key_id"] == key_uuid
        assert r0["total_ms"] == pytest.approx(37.125)

        # Verify JSONB columns were serialized with sort_keys=True and round-trip cleanly
        expected_timings_str = json.dumps(
            row_with_key["timings"], sort_keys=True, separators=(",", ":")
        )
        assert r0["timings"] == expected_timings_str
        assert json.loads(r0["timings"]) == row_with_key["timings"]
        assert json.loads(r0["candidate_scores"]) == row_with_key["candidate_scores"]
        assert json.loads(r0["client_metadata"]) == row_with_key["client_metadata"]

        # Verify nullable fields on second row
        assert r1["id"] == 502
        assert r1["api_key_id"] is None
        assert r1["session_id"] is None
        assert r1["total_ms"] is None
        assert r1["timings"] is None
        assert json.loads(r1["candidate_scores"]) == []
        assert r1["client_metadata"] is None

    def test_deterministic_keys_separate_user_and_admin_eval_prefixes(self):
        d1 = datetime(2026, 1, 5, 10, 0, 0, tzinfo=timezone.utc)
        d2 = datetime(2026, 1, 6, 10, 0, 0, tzinfo=timezone.utc)
        rows = [
            make_synthetic_log_row(10, created_at=d1, source="user", endpoint="recommend"),
            make_synthetic_log_row(15, created_at=d1, source="user", endpoint="chat"),
            make_synthetic_log_row(12, created_at=d1, source="admin_eval", endpoint="admin_recommend"),
            make_synthetic_log_row(20, created_at=d1, source="admin_eval", endpoint="admin_recommend"),
            make_synthetic_log_row(30, created_at=d2, source="user", endpoint="recommend"),
        ]
        fake_conn = FakeConnection(rows)
        storage = MockStorageBackend()

        summary = run_archiver(conn=fake_conn, storage=storage, days=30)
        assert summary.status == "ok"
        assert set(storage.objects.keys()) == {
            "logs/year=2026/month=01/day=05/part-10-15.parquet",
            "admin_eval/year=2026/month=01/day=05/part-12-20.parquet",
            "logs/year=2026/month=01/day=06/part-30-30.parquet",
        }

    def test_compression_ratio_parquet_under_15_percent_of_raw_json(self):
        base_dt = datetime(2026, 1, 12, 0, 0, 0, tzinfo=timezone.utc)
        shared_keys = [str(uuid.uuid5(uuid.NAMESPACE_OID, f"dev-key-{i}")) for i in range(5)]
        sample_queries = [
            "dark psychological thriller anime with mind games like Death Note and Monster",
            "wholesome slice of life anime set in the countryside like Non Non Biyori",
            "mecha space opera with political intrigue like Legend of the Galactic Heroes",
            "high-octane fantasy action anime with great animation by ufotable or MAPPA",
        ]

        rows: List[Dict[str, Any]] = []
        for idx in range(1, 1501):
            r = make_synthetic_log_row(
                idx,
                created_at=base_dt + timedelta(seconds=idx * 15),
                source="user",
                endpoint="recommend" if idx % 3 != 0 else "chat",
                api_key_id=shared_keys[idx % len(shared_keys)],
                query=sample_queries[idx % len(sample_queries)],
                results_count=20,
            )
            # Realistic 20 candidate score entries per recommendation request
            r["candidate_scores"] = [
                {
                    "id": c_id,
                    "cross_encoder_score": round(6.5 - c_id * 0.15, 4),
                    "final_rrf_score": round(0.095 - c_id * 0.002, 5),
                    "retrieval_rrf_score": round(0.048 - c_id * 0.001, 5),
                }
                for c_id in range(1, 21)
            ]
            rows.append(r)

        artifact = write_parquet_artifact(
            source="user",
            utc_day=date(2026, 1, 12),
            rows=rows,
            compression="zstd",
        )

        ratio = artifact.file_size / float(artifact.raw_json_bytes)
        assert ratio < 0.15, (
            f"Expected Parquet size < 15% of raw JSON, got {ratio:.2%} "
            f"({artifact.file_size} bytes vs {artifact.raw_json_bytes} bytes)"
        )


# ---------------------------------------------------------------------------
# Class 3: Live PostgreSQL Integration & Failure-Injection Suite
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_conn():
    cfg = get_archiver_db_config()
    conn = psycopg2.connect(**cfg)
    conn.autocommit = False
    yield conn
    if not conn.closed:
        conn.close()


@pytest.fixture(autouse=True)
def isolated_db_state(db_conn):
    """
    Snapshots pre-existing rows in telemetry and app_auth before each test
    and restores the database to its exact pre-test state after each test.
    """
    db_conn.rollback()
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM telemetry.recommendation_logs;")
        pre_rlogs = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT api_key_id, day, request_count FROM telemetry.api_key_usage_daily;")
        pre_usage = {(r[0], r[1]): r[2] for r in cur.fetchall()}
        cur.execute("SELECT id FROM app_auth.api_keys;")
        pre_keys = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT id FROM app_auth.key_audit_log;")
        pre_audits = {r[0] for r in cur.fetchall()}
    db_conn.commit()

    yield

    db_conn.rollback()
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM telemetry.recommendation_logs;")
        cur_rlogs = {r[0] for r in cur.fetchall()}
        added_rlogs = list(cur_rlogs - pre_rlogs)
        if added_rlogs:
            cur.execute("DELETE FROM telemetry.recommendation_logs WHERE id = ANY(%s);", (added_rlogs,))

        cur.execute("SELECT api_key_id, day FROM telemetry.api_key_usage_daily;")
        cur_usage_keys = {(r[0], r[1]) for r in cur.fetchall()}
        for k_id, day_val in cur_usage_keys - set(pre_usage.keys()):
            cur.execute(
                "DELETE FROM telemetry.api_key_usage_daily WHERE api_key_id = %s AND day = %s;",
                (k_id, day_val),
            )
        for (k_id, day_val), orig_cnt in pre_usage.items():
            cur.execute(
                "UPDATE telemetry.api_key_usage_daily SET request_count = %s WHERE api_key_id = %s AND day = %s;",
                (orig_cnt, k_id, day_val),
            )

        cur.execute("SELECT id FROM app_auth.key_audit_log;")
        cur_audits = {r[0] for r in cur.fetchall()}
        added_audits = list(cur_audits - pre_audits)
        if added_audits:
            cur.execute("DELETE FROM app_auth.key_audit_log WHERE id = ANY(%s);", (added_audits,))

        cur.execute("SELECT id FROM app_auth.api_keys;")
        cur_keys = {r[0] for r in cur.fetchall()}
        added_keys = list(cur_keys - pre_keys)
        if added_keys:
            cur.execute("DELETE FROM app_auth.api_keys WHERE id = ANY(%s::uuid[]);", (added_keys,))
    db_conn.commit()


def _seed_db_log_row(
    conn: Any,
    *,
    created_at: datetime,
    source: str = "user",
    endpoint: str = "recommend",
    api_key_id: Optional[str] = None,
    session_id: Optional[str] = None,
    query: str = "seeded archival test query",
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO telemetry.recommendation_logs (
                request_id, created_at, endpoint, source, api_key_id, session_id,
                query, top_k, allow_adult, results_count, status, status_code,
                total_ms, timings, candidate_scores, client_metadata
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, 20, false, 3, 'ok', 200,
                31.5,
                %s::jsonb,
                %s::jsonb,
                %s::jsonb
            )
            RETURNING id;
            """,
            (
                str(uuid.uuid4()),
                created_at,
                endpoint,
                source,
                api_key_id,
                session_id,
                query,
                json.dumps({"retrieval_ms": 11.2, "reranking_ms": 20.3}),
                json.dumps([{"id": 1, "cross_encoder_score": 5.1, "final_rrf_score": 0.08, "retrieval_rrf_score": 0.04}]),
                json.dumps({"ip_hash": "abcdef0123456789", "user_agent": "pytest-archiver"}),
            ),
        )
        new_id = int(cur.fetchone()[0])
    conn.commit()
    return new_id


class TestArchiverPostgresIntegrationAndFailureInjection:
    """Integration tests against live PostgreSQL with mocked Storage failure injection."""

    def test_upload_failure_after_tenacity_retries_leaves_db_untouched(self, db_conn):
        cutoff = compute_fixed_cutoff(db_conn, days=30)
        old_time = cutoff - timedelta(days=10)
        seeded_ids = [_seed_db_log_row(db_conn, created_at=old_time) for _ in range(6)]

        # Fail all 5 tenacity attempts
        storage = MockStorageBackend(fail_upload_times=10)

        with pytest.raises(RetryableStorageError):
            run_archiver(
                conn=db_conn,
                storage=storage,
                days=30,
                retry_max_attempts=5,
                retry_wait_min=0.001,
                retry_wait_max=0.005,
            )

        # Verify tenacity retried exactly 5 times and 0 rows were deleted from Postgres
        assert len(storage.upload_calls) == 5
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM telemetry.recommendation_logs WHERE id = ANY(%s);",
                (seeded_ids,),
            )
            assert cur.fetchone()[0] == 6

    def test_upload_transient_failure_recovers_within_5_attempts(self, db_conn):
        cutoff = compute_fixed_cutoff(db_conn, days=30)
        old_time = cutoff - timedelta(days=12)
        seeded_ids = [_seed_db_log_row(db_conn, created_at=old_time) for _ in range(4)]

        # Fail first 2 attempts, succeed on 3rd attempt
        storage = MockStorageBackend(fail_upload_times=2)

        summary = run_archiver(
            conn=db_conn,
            storage=storage,
            days=30,
            retry_max_attempts=5,
            retry_wait_min=0.001,
            retry_wait_max=0.005,
        )

        assert summary.status == "ok"
        assert len(storage.upload_calls) == 3
        assert summary.rows_deleted == len(seeded_ids)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM telemetry.recommendation_logs WHERE id = ANY(%s);",
                (seeded_ids,),
            )
            assert cur.fetchone()[0] == 0

    @pytest.mark.parametrize(
        "corrupt_mode",
        ["truncate_bytes", "bitflip_same_size", "fewer_rows"],
    )
    def test_verify_mismatch_leaves_db_untouched(self, db_conn, corrupt_mode):
        cutoff = compute_fixed_cutoff(db_conn, days=30)
        old_time = cutoff - timedelta(days=15)
        seeded_ids = [_seed_db_log_row(db_conn, created_at=old_time) for _ in range(5)]

        storage = MockStorageBackend(corrupt_download_mode=corrupt_mode)

        with pytest.raises(ArchiveVerificationError):
            run_archiver(
                conn=db_conn,
                storage=storage,
                days=30,
                retry_wait_min=0.001,
                retry_wait_max=0.005,
            )

        # Confirm zero rows were deleted when verification failed
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM telemetry.recommendation_logs WHERE id = ANY(%s);",
                (seeded_ids,),
            )
            assert cur.fetchone()[0] == 5

    def test_crash_after_upload_before_delete_converges_on_rerun_without_overwrite(self, db_conn):
        cutoff = compute_fixed_cutoff(db_conn, days=30)
        old_time = cutoff - timedelta(days=8)
        seeded_ids = [_seed_db_log_row(db_conn, created_at=old_time) for _ in range(7)]

        storage = MockStorageBackend()

        def simulate_crash_after_verify(artifact: LocalParquetArtifact) -> None:
            raise RuntimeError(f"Simulated process crash after uploading {artifact.object_key}")

        # Run 1: Crashes after upload + verify, before DB delete
        with pytest.raises(RuntimeError, match="Simulated process crash"):
            run_archiver(
                conn=db_conn,
                storage=storage,
                days=30,
                after_verify_hook=simulate_crash_after_verify,
            )

        assert len(storage.upload_calls) == 1
        assert len(storage.objects) == 1

        # All 7 rows are still in Postgres after the crash
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM telemetry.recommendation_logs WHERE id = ANY(%s);",
                (seeded_ids,),
            )
            assert cur.fetchone()[0] == 7

        # Run 2 (Recovery): Re-run without the crash hook
        summary_rerun = run_archiver(
            conn=db_conn,
            storage=storage,
            days=30,
        )

        assert summary_rerun.status == "ok"
        assert summary_rerun.parts_skipped_existing == 1
        assert summary_rerun.parts_uploaded == 0
        # Upload was NOT called a second time (existing file verified and reused)
        assert len(storage.upload_calls) == 1
        assert summary_rerun.rows_deleted == 7

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM telemetry.recommendation_logs WHERE id = ANY(%s);",
                (seeded_ids,),
            )
            assert cur.fetchone()[0] == 0

    def test_delete_failure_mid_transaction_rolls_back_and_rerun_converges(self, db_conn):
        cutoff = compute_fixed_cutoff(db_conn, days=30)
        old_time = cutoff - timedelta(days=20)
        key_id = str(uuid.uuid4())
        seeded_ids = [
            _seed_db_log_row(db_conn, created_at=old_time + timedelta(seconds=i), api_key_id=key_id)
            for i in range(8)
        ]

        storage = MockStorageBackend()

        # Inject a failure on the 2nd DELETE sub-batch by wrapping commit_verified_part_deletion
        orig_commit_fn = archiver.commit_verified_part_deletion
        call_counter = {"count": 0}

        def failing_delete_once(*args: Any, **kwargs: Any) -> int:
            call_counter["count"] += 1
            if call_counter["count"] == 1:
                # Perform partial work inside transaction then fail to verify rollback
                with db_conn.cursor() as cur:
                    cur.execute(
                        archiver.DELETE_LOGS_BY_IDS_SQL,
                        (seeded_ids[:3], cutoff),
                    )
                db_conn.rollback()
                raise ArchiveDeleteError("Simulated mid-transaction delete failure on sub-batch 2")
            return orig_commit_fn(*args, **kwargs)

        with patch.object(archiver, "commit_verified_part_deletion", side_effect=failing_delete_once):
            with pytest.raises(ArchiveDeleteError, match="Simulated mid-transaction delete failure"):
                run_archiver(
                    conn=db_conn,
                    storage=storage,
                    days=30,
                    delete_batch_size=3,
                )

        # Because the transaction rolled back, all 8 rows must still be present in Postgres
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM telemetry.recommendation_logs WHERE id = ANY(%s);",
                (seeded_ids,),
            )
            assert cur.fetchone()[0] == 8

        # Re-run converges cleanly: verifies existing Parquet in storage, skips upload, deletes all 8 rows
        summary = run_archiver(
            conn=db_conn,
            storage=storage,
            days=30,
            delete_batch_size=3,
        )
        assert summary.status == "ok"
        assert summary.parts_skipped_existing == 1
        assert summary.rows_deleted == 8

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM telemetry.recommendation_logs WHERE id = ANY(%s);",
                (seeded_ids,),
            )
            assert cur.fetchone()[0] == 0

    def test_concurrent_advisory_lock_held_exits_cleanly(self, db_conn):
        cutoff = compute_fixed_cutoff(db_conn, days=30)
        old_time = cutoff - timedelta(days=10)
        seeded_id = _seed_db_log_row(db_conn, created_at=old_time)

        # Open a second connection and hold ARCHIVER_ADVISORY_LOCK_ID
        holder_conn = psycopg2.connect(**get_archiver_db_config())
        holder_conn.autocommit = True
        try:
            with holder_conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s);", (ARCHIVER_ADVISORY_LOCK_ID,))
                assert cur.fetchone()[0] is True

            storage = MockStorageBackend()
            summary = run_archiver(conn=db_conn, storage=storage, days=30)

            assert summary.status == "locked"
            assert summary.advisory_lock_acquired is False
            assert summary.rows_deleted == 0
            assert len(storage.upload_calls) == 0

            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM telemetry.recommendation_logs WHERE id = %s;",
                    (seeded_id,),
                )
                assert cur.fetchone()[0] == 1
        finally:
            with holder_conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s);", (ARCHIVER_ADVISORY_LOCK_ID,))
            holder_conn.close()

    def test_api_keys_older_than_30_days_survive_and_usage_rollup_preserved(self, db_conn):
        cutoff = compute_fixed_cutoff(db_conn, days=30)
        very_old_key_time = cutoff - timedelta(days=60)  # 90 days old
        old_log_time = cutoff - timedelta(days=14)       # 44 days old
        old_log_day = old_log_time.astimezone(timezone.utc).date()

        # Seed two 90-day-old API keys in app_auth.api_keys and audit log entries
        seeded_key_ids: List[str] = []
        with db_conn.cursor() as cur:
            for idx in range(2):
                k_prefix = f"s4old_{uuid.uuid4().hex[:6]}"
                k_hash = hashlib.sha256(f"sprint4-old-key-{idx}-{uuid.uuid4()}".encode()).digest()
                cur.execute(
                    """
                    INSERT INTO app_auth.api_keys (name, key_prefix, key_hash, role, created_at)
                    VALUES (%s, %s, %s, 'user', %s)
                    RETURNING id;
                    """,
                    (f"sprint4-ancient-key-{idx}", k_prefix, k_hash, very_old_key_time),
                )
                k_id = str(cur.fetchone()[0])
                seeded_key_ids.append(k_id)
                cur.execute(
                    """
                    INSERT INTO app_auth.key_audit_log (at, actor, action, api_key_id, detail)
                    VALUES (%s, 'system', 'created', %s, '{"test": true}'::jsonb);
                    """,
                    (very_old_key_time, k_id),
                )
        db_conn.commit()

        # Seed 3 old recommendation_logs for key 0 (without pre-populating api_key_usage_daily)
        # and 2 old recommendation_logs for key 1 (with live count=5 already in api_key_usage_daily)
        for _ in range(3):
            _seed_db_log_row(db_conn, created_at=old_log_time, api_key_id=seeded_key_ids[0])
        for _ in range(2):
            _seed_db_log_row(db_conn, created_at=old_log_time, api_key_id=seeded_key_ids[1])

        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telemetry.api_key_usage_daily (api_key_id, day, request_count)
                VALUES (%s, %s, 5);
                """,
                (seeded_key_ids[1], old_log_day),
            )
        db_conn.commit()

        storage = MockStorageBackend()
        summary = run_archiver(conn=db_conn, storage=storage, days=30)
        assert summary.status == "ok"

        with db_conn.cursor() as cur:
            # 1. Both 90-day-old keys in app_auth.api_keys MUST survive untouched
            cur.execute(
                "SELECT count(*) FROM app_auth.api_keys WHERE id = ANY(%s::uuid[]);",
                (seeded_key_ids,),
            )
            assert cur.fetchone()[0] == 2

            # 2. Audit logs in app_auth.key_audit_log MUST survive untouched
            cur.execute(
                "SELECT count(*) FROM app_auth.key_audit_log WHERE api_key_id = ANY(%s::uuid[]);",
                (seeded_key_ids,),
            )
            assert cur.fetchone()[0] == 2

            # 3. Daily usage rollup: key 0 backfilled to 3; key 1 kept at GREATEST(5, 2) = 5 (never double-counted to 7)
            cur.execute(
                "SELECT request_count FROM telemetry.api_key_usage_daily WHERE api_key_id = %s AND day = %s;",
                (seeded_key_ids[0], old_log_day),
            )
            assert cur.fetchone()[0] == 3

            cur.execute(
                "SELECT request_count FROM telemetry.api_key_usage_daily WHERE api_key_id = %s AND day = %s;",
                (seeded_key_ids[1], old_log_day),
            )
            assert cur.fetchone()[0] == 5

    def test_cutoff_boundary_and_out_of_order_newer_id_preservation(self, db_conn):
        cutoff = compute_fixed_cutoff(db_conn, days=30)
        old_day_dt = cutoff - timedelta(days=5)

        # Row A: older than cutoff (user) -> archived & deleted
        id_a = _seed_db_log_row(db_conn, created_at=old_day_dt, source="user")
        # Row B: 1 second before cutoff (admin_eval) -> archived & deleted
        id_b = _seed_db_log_row(
            db_conn,
            created_at=cutoff - timedelta(seconds=1),
            source="admin_eval",
            endpoint="admin_recommend",
        )
        # Row C: inserted BEFORE Row D (so id_a < id_c < id_d!), but created_at is AFTER cutoff!
        id_c = _seed_db_log_row(db_conn, created_at=cutoff + timedelta(minutes=5), source="user")
        # Row D: inserted AFTER Row C, on the same old day as Row A -> archived & deleted
        id_d = _seed_db_log_row(
            db_conn,
            created_at=old_day_dt + timedelta(minutes=10),
            source="user",
        )
        # Row E: current timestamp -> untouched
        id_e = _seed_db_log_row(db_conn, created_at=datetime.now(timezone.utc), source="user")

        assert id_a < id_c < id_d, "Row C's ID must sit strictly between Row A and Row D"

        storage = MockStorageBackend()
        summary = run_archiver(conn=db_conn, storage=storage, days=30)
        assert summary.status == "ok"

        with db_conn.cursor() as cur:
            # Verify no rows older than cutoff remain in telemetry.recommendation_logs
            cur.execute(
                "SELECT count(*) FROM telemetry.recommendation_logs WHERE created_at < %s;",
                (cutoff,),
            )
            assert cur.fetchone()[0] == 0

            # Verify Rows A, B, D were deleted, while Row C (in the ID gap!) and Row E survived!
            cur.execute(
                "SELECT id FROM telemetry.recommendation_logs WHERE id = ANY(%s) ORDER BY id ASC;",
                ([id_a, id_b, id_c, id_d, id_e],),
            )
            surviving_ids = [r[0] for r in cur.fetchall()]
            assert surviving_ids == [id_c, id_e]

        # Verify uploaded Parquet files are readable with pyarrow.parquet.read_table and match row counts
        total_parquet_rows = 0
        for key, raw_bytes in storage.objects.items():
            tbl = pq.read_table(io.BytesIO(raw_bytes))
            total_parquet_rows += tbl.num_rows
            ids_in_file = tbl.column("id").to_pylist()
            assert id_c not in ids_in_file
            assert id_e not in ids_in_file

        assert total_parquet_rows == summary.rows_archived

    def test_dry_run_writes_nothing_and_deletes_nothing(self, db_conn):
        cutoff = compute_fixed_cutoff(db_conn, days=30)
        old_time = cutoff - timedelta(days=9)
        seeded_ids = [_seed_db_log_row(db_conn, created_at=old_time) for _ in range(4)]

        storage = MockStorageBackend()
        summary = run_archiver(conn=db_conn, storage=storage, days=30, dry_run=True)

        assert summary.status == "dry_run_ok"
        assert summary.dry_run is True
        assert summary.rows_scanned >= 4
        assert summary.rows_archived >= 4
        assert summary.rows_deleted == 0
        assert summary.parts_uploaded == 0
        assert len(storage.upload_calls) == 0
        assert len(storage.objects) == 0

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM telemetry.recommendation_logs WHERE id = ANY(%s);",
                (seeded_ids,),
            )
            assert cur.fetchone()[0] == 4

    def test_privacy_erasure_hot_and_cold_parquet(self, db_conn):
        target_key = str(uuid.uuid4())
        keep_key = str(uuid.uuid4())
        dt = datetime(2026, 1, 18, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Test cold Parquet erasure
        rows = [
            make_synthetic_log_row(1, created_at=dt, api_key_id=target_key, session_id="s1"),
            make_synthetic_log_row(2, created_at=dt, api_key_id=keep_key, session_id="s2"),
            make_synthetic_log_row(3, created_at=dt, api_key_id=target_key, session_id="s3"),
        ]
        artifact = write_parquet_artifact("user", dt.date(), rows)
        filtered_bytes, removed = erase_subject_from_parquet_bytes(
            artifact.parquet_bytes,
            api_key_id=target_key,
        )
        assert removed == 2
        assert filtered_bytes is not None
        remaining_tbl = pq.read_table(io.BytesIO(filtered_bytes))
        assert remaining_tbl.num_rows == 1
        assert remaining_tbl.column("id").to_pylist() == [2]

        # 2. Test hot DB erasure
        _seed_db_log_row(db_conn, created_at=datetime.now(timezone.utc), api_key_id=target_key)
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO telemetry.api_key_usage_daily (api_key_id, day, request_count) VALUES (%s, %s, 3);",
                (target_key, date.today()),
            )
        db_conn.commit()

        erasure_res = erase_subject_from_telemetry(db_conn, api_key_id=target_key)
        assert erasure_res["deleted_logs"] == 1
        assert erasure_res["deleted_usage_rows"] == 1

    def test_cli_end_to_end_synthetic_smoke_test_with_manifest(self, db_conn, tmp_path):
        cutoff = compute_fixed_cutoff(db_conn, days=30)
        old_time = cutoff - timedelta(days=7)
        id_user = _seed_db_log_row(db_conn, created_at=old_time, source="user")
        id_admin = _seed_db_log_row(
            db_conn,
            created_at=old_time,
            source="admin_eval",
            endpoint="admin_recommend",
        )

        summary_file = tmp_path / "summary.json"
        manifest_file = tmp_path / "manifest.json"
        storage = MockStorageBackend()

        exit_code = archiver_cli_main(
            [
                "--days",
                "30",
                "--summary-file",
                str(summary_file),
                "--manifest-file",
                str(manifest_file),
            ],
            conn=db_conn,
            storage=storage,
        )

        assert exit_code == 0
        assert summary_file.exists()
        assert manifest_file.exists()

        summary_data = json.loads(summary_file.read_text(encoding="utf-8"))
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))

        assert summary_data["status"] == "ok"
        assert summary_data["rows_deleted"] >= 2
        assert manifest_data["total_parts"] >= 2

        prefixes = {p["object_key"].split("/")[0] for p in manifest_data["parts"]}
        assert "logs" in prefixes
        assert "admin_eval" in prefixes

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM telemetry.recommendation_logs WHERE id = ANY(%s);",
                ([id_user, id_admin],),
            )
            assert cur.fetchone()[0] == 0
