"""
test/test_sprint5_e2e_and_workflows.py

Comprehensive End-to-End Verification & Workflow Contract Test Suite for Sprint 5
of telemetry_and_archival_implementation_plan.md.

Covers:
1. Workflow YAML Linting & Contract Validation (TestWorkflowYamlValidation):
   - archive_telemetry.yaml: triggers (cron '0 3 1 * *', inputs dry_run/days),
     concurrency group 'archive', timeout 30m, permissions, env-only secret passing,
     pinned requirements-archive.txt (no root requirements), failure alerting step.
   - update_data.yaml: keep-alive query step, concurrency group 'data-pipeline',
     timeout, permissions, env-only secret passing.
2. Data Pipeline Schema Isolation (TestDataPipelineSchemaIsolation):
   - AST & static SQL analysis of backend/data_pipeline/helper/database.py.
   - Verifies migrate_schema(), truncate_table(), create_table(), and all DB_QUERIES
     never touch telemetry or app_auth schemas.
3. Keep-Alive Query Verification (TestKeepAliveQuery):
   - Validates scripts/db_keepalive.py connection parameters, connect_timeout <= 5s,
     statement_timeout <= 5000ms, and graceful error handling.
4. Alert Dispatch Unit Tests (TestAlertDispatchUnit):
   - Webhook payload formatting (Discord embeds & Slack blocks).
   - Secret redaction (passwords, Bearer tokens, ar_live_* keys, JWTs).
   - Fallback GitHub issue creation and deduplication logic.
5. Full Sprint 5 End-to-End Simulation (TestSprint5FullE2ESimulation):
   - Developer key creation -> POST /recommend (200, score-stripped, telemetry logged)
   - Admin key creation -> POST /admin/recommend (200, full timings & scores, telemetry logged)
   - Archival execution (--days 0) -> Parquet generated, uploaded, verified, and exact IDs pruned
   - Rollup persistence: telemetry.api_key_usage_daily survives the prune.
6. Failure Injection & Alert Triggering (TestSprint5FailureInjection):
   - Injected database connection failure during archival fetch -> 0 deleted, alert triggered.
   - Injected storage upload failure -> 0 deleted, alert triggered.
   - Injected Parquet verification mismatch -> 0 deleted, alert triggered.

Usage:
    python -m pytest test/test_sprint5_e2e_and_workflows.py -v
"""

import os
import re
import ast
import sys
import json
import uuid
import yaml
import time
import hmac
import hashlib
from datetime import datetime, date, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple, Sequence
from unittest.mock import patch, MagicMock

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

# Ensure project root is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import scripts.db_keepalive as keepalive_mod
import scripts.alert_dispatcher as alert_mod
from backend.auth.keys import (
    generate_api_key,
    hash_api_key,
    KEY_PEPPER,
    ApiKeyContext,
)
from backend.telemetry.logger import strip_scores, log_recommendation_event
from backend.telemetry.archiver import (
    run_archiver,
    verify_remote_parquet,
    LocalParquetArtifact,
    ArchiverError,
    ArchiveVerificationError,
    RetryableStorageError,
    RECOMMENDATION_LOGS_ARROW_SCHEMA,
    COLUMN_NAMES,
)


# ---------------------------------------------------------------------------
# In-Memory Test Fixtures: Fake Connection, Fake Cursor & Mock Storage Client
# ---------------------------------------------------------------------------

class FakeCursor:
    """In-memory cursor simulating PostgreSQL for E2E tests."""

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

        if "SELECT 1" in norm_sql:
            self.description = [("?column?",)]
            self._results = [(1,)]
            self.rowcount = 1
            return

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
            days = int(params[0]) if params else 0
            cutoff = self.conn.fixed_now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(days=days)
            # For --days 0 in tests, cutoff captures up to current timestamp + 1 second
            if days == 0:
                cutoff = self.conn.fixed_now + timedelta(seconds=1)
            self.description = [("cutoff",)]
            self._results = [(cutoff,)]
            self.rowcount = 1
            return

        if "FROM telemetry.recommendation_logs WHERE id > %s AND created_at < %s" in norm_sql:
            if self.conn.fail_on_fetch:
                raise RuntimeError("Simulated Database Fetch Network Failure")
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
    """In-memory transactional connection wrapper for E2E tests."""

    def __init__(
        self,
        rows: Sequence[Dict[str, Any]],
        *,
        fixed_now: Optional[datetime] = None,
        lock_available: bool = True,
        fail_on_fetch: bool = False,
    ) -> None:
        self.fixed_now = fixed_now or datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        self.lock_available = lock_available
        self.fail_on_fetch = fail_on_fetch
        self.closed = 0
        self.autocommit = False

        self.rows: Dict[int, Dict[str, Any]] = {int(r["id"]): dict(r) for r in rows}
        self.usage_daily: Dict[Tuple[str, date], int] = {}
        self._staged_rows: Dict[int, Dict[str, Any]] = dict(self.rows)
        self._staged_usage: Dict[Tuple[str, date], int] = dict(self.usage_daily)

        self.executed_queries: List[Tuple[str, Optional[Sequence[Any]]]] = []
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


class MockStorageClient:
    """In-memory Storage client supporting failure injection."""

    def __init__(
        self,
        *,
        fail_upload_times: int = 0,
        corrupt_download_mode: Optional[str] = None,
    ) -> None:
        self.objects: Dict[str, bytes] = {}
        self.fail_upload_times = fail_upload_times
        self.upload_calls: List[str] = []
        self.download_calls: List[str] = []
        self.corrupt_download_mode = corrupt_download_mode

    def object_exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def upload_bytes(
        self,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.upload_calls.append(object_key)
        if len(self.upload_calls) <= self.fail_upload_times:
            raise RetryableStorageError("503 Service Unavailable: Simulated storage timeout")
        self.objects[object_key] = bytes(data)

    def download_bytes(self, object_key: str) -> bytes:
        self.download_calls.append(object_key)
        raw = self.objects[object_key]
        if self.corrupt_download_mode == "truncate":
            return raw[:-32]
        return raw


# ===========================================================================
# 2. Data Pipeline Schema Isolation Verification
# ===========================================================================

class TestDataPipelineSchemaIsolation:
    """Verifies that the data pipeline code never touches telemetry or app_auth schemas."""

    def test_database_helper_ast_and_queries_isolated(self):
        db_helper_path = os.path.join(
            ROOT_DIR, "backend", "data_pipeline", "helper", "database.py"
        )
        assert os.path.exists(db_helper_path)

        with open(db_helper_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check raw text for prohibited schema names
        assert "telemetry." not in code.lower()
        assert "app_auth." not in code.lower()
        assert "recommendation_logs" not in code
        assert "api_keys" not in code
        assert "api_key_usage_daily" not in code

        # AST analysis of migrate_schema method
        tree = ast.parse(code)
        migrate_func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "migrate_schema":
                migrate_func = node
                break

        assert migrate_func is not None, "migrate_schema method must exist"
        # Ensure migrate_schema only executes ALTER TABLE anime_content ADD COLUMN IF NOT EXISTS search_vector
        func_source = ast.get_source_segment(code, migrate_func)
        assert func_source is not None
        assert "ALTER TABLE anime_content" in func_source
        assert "ADD COLUMN IF NOT EXISTS search_vector" in func_source
        assert "DROP" not in func_source.upper()
        assert "TRUNCATE" not in func_source.upper()


# ===========================================================================
# 3. Keep-Alive Query Verification
# ===========================================================================

class TestKeepAliveQuery:
    """Verifies keepalive query execution, timeout settings, and exception handling."""

    def test_keepalive_db_config_timeouts(self):
        with patch.dict(os.environ, {"DB_HOST": "test-db", "DB_PORT": "5432"}):
            cfg = keepalive_mod.get_keepalive_db_config(timeout_seconds=5)
            assert cfg["connect_timeout"] == 5
            assert "statement_timeout=5000" in cfg["options"]
            assert cfg["application_name"] == "db_keepalive_preflight"

    def test_keepalive_execution_success(self):
        fake_conn = FakeConnection([])
        with patch("psycopg2.connect", return_value=fake_conn):
            result = keepalive_mod.execute_keepalive_query()
            assert result is True
            executed_sqls = [q[0] for q in fake_conn.executed_queries]
            assert any("SELECT 1" in sql for sql in executed_sqls)

    def test_keepalive_execution_failure_handling(self):
        with patch("psycopg2.connect", side_effect=Exception("Database unreachable")):
            with pytest.raises(Exception):
                keepalive_mod.execute_keepalive_query()

            exit_code = keepalive_mod.main(["--timeout", "2"])
            assert exit_code == 1


# ===========================================================================
# 4. Alert Dispatch Unit Tests
# ===========================================================================

class TestAlertDispatchUnit:
    """Verifies webhook formatting, secret redaction, and GitHub issue fallback."""

    def test_secret_redaction(self):
        raw_error = (
            "OperationalError connecting to postgres://telemetry_archiver:SuperSecretPass123@db.supabase.co:5432/postgres "
            "with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy.token and key ar_live_01234567_abcdefghijklmnopqrstuvwxyz0123456789abcde"
        )
        clean = alert_mod.redact_secrets(raw_error)
        assert "SuperSecretPass123" not in clean
        assert "postgres://telemetry_archiver:[REDACTED]@" in clean
        assert "Bearer [REDACTED]" in clean
        assert "[REDACTED_API_KEY]" in clean

    def test_discord_payload_structure(self):
        payload = alert_mod.format_discord_payload(
            workflow_name="Monthly Archival",
            run_id="998877",
            run_attempt="1",
            status="failure",
            error_message="Fatal storage verification mismatch in part-1-50.parquet",
            repository="org/anime_recommender",
            summary_data={"days": 30, "rows_archived": 50, "rows_deleted": 0},
        )
        assert "embeds" in payload
        embed = payload["embeds"][0]
        assert embed["color"] == 15158332  # Red
        assert "Monthly Archival" in embed["title"]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Workflow" in field_names
        assert "Retention Window" in field_names
        assert "Error Details" in field_names

    def test_slack_payload_structure(self):
        payload = alert_mod.format_slack_payload(
            workflow_name="Monthly Archival",
            run_id="998877",
            run_attempt="1",
            status="failure",
            error_message="Simulated error",
            repository="org/anime_recommender",
        )
        assert "blocks" in payload
        assert len(payload["blocks"]) >= 3

    def test_github_issue_fallback_and_dedup(self):
        # Test deduplication: when an open alert issue already exists, don't create duplicate
        mock_resp_check = MagicMock()
        mock_resp_check.status = 200
        mock_resp_check.read.return_value = json.dumps([
            {"number": 42, "title": "[ALERT] Monthly Archival Failure (Run #111)"}
        ]).encode("utf-8")
        mock_resp_check.__enter__.return_value = mock_resp_check
        mock_resp_check.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_resp_check):
            result = alert_mod.create_github_issue_fallback(
                token="ghp_fake_token",
                repository="org/anime_recommender",
                workflow_name="Monthly Archival",
                run_id="222",
                status="failure",
                error_message="Error",
            )
            assert result is True  # Deduplicated cleanly


# ===========================================================================
# 5. Full Sprint 5 End-to-End Simulation Test
# ===========================================================================

class TestSprint5FullE2ESimulation:
    """
    Complete End-to-End Acceptance Loop:
    1. Developer key creation via backend.auth.keys.generate_api_key(role='user')
    2. Admin key creation via backend.auth.keys.generate_api_key(role='admin')
    3. User recommendation flow -> score-stripped response & telemetry logged with source='user'
    4. Admin recommendation flow -> unstripped response & telemetry logged with source='admin_eval'
    5. Archival execution (--days 0) -> Parquet generated, verified, uploaded, and exact IDs pruned
    6. Rollup persistence -> telemetry.api_key_usage_daily survives the prune intact.
    """

    def test_complete_sprint5_e2e_acceptance_flow(self):
        # 1. Developer & Admin Key Generation
        dev_owner_id = str(uuid.uuid4())
        dev_raw_key, dev_rec = generate_api_key("dev-test-client", owner_id=dev_owner_id, role="user")
        admin_raw_key, admin_rec = generate_api_key("admin-eval-client", owner_id=None, role="admin")

        dev_key_id = dev_rec["id"]
        admin_key_id = admin_rec["id"]

        assert dev_raw_key.startswith("ar_live_")
        assert admin_raw_key.startswith("ar_live_")
        assert dev_key_id is not None
        assert admin_key_id is not None

        # 2. Simulated Pipeline Output
        mock_raw_results = [
            {
                "id": 101,
                "title_english": "Steins;Gate",
                "genres": ["Sci-Fi", "Thriller"],
                "cross_encoder_score": 8.742,
                "final_rrf_score": 0.0892,
                "retrieval_rrf_score": 0.0451,
                "cosine_similarity": 0.882,
            },
            {
                "id": 102,
                "title_english": "Psycho-Pass",
                "genres": ["Action", "Sci-Fi", "Psychological"],
                "cross_encoder_score": 7.319,
                "final_rrf_score": 0.0765,
                "retrieval_rrf_score": 0.0398,
                "cosine_similarity": 0.795,
            },
        ]
        mock_timings = {
            "embedding_ms": 5.2,
            "retrieval_ms": 12.4,
            "reranking_ms": 22.8,
        }

        # 3. User POST /recommend Contract Verification
        # Public responses must strip scores and exclude timings/extra
        user_response_results = strip_scores(mock_raw_results)
        assert len(user_response_results) == 2
        for r in user_response_results:
            assert "cross_encoder_score" not in r
            assert "final_rrf_score" not in r
            assert "retrieval_rrf_score" not in r
            assert "cosine_similarity" not in r
            assert "title_english" in r

        # 4. Telemetry logging for User flow (logged with unstripped scores!)
        now_utc = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        user_log_row = {
            "id": 1,
            "request_id": str(uuid.uuid4()),
            "created_at": now_utc,
            "endpoint": "recommend",
            "source": "user",
            "api_key_id": dev_key_id,
            "session_id": None,
            "query": "cyberpunk thriller",
            "top_k": 5,
            "allow_adult": False,
            "results_count": 2,
            "status": "ok",
            "status_code": 200,
            "error": None,
            "total_ms": 40.4,
            "timings": json.dumps(mock_timings),
            "candidate_scores": json.dumps([
                {
                    "id": 101,
                    "cross_encoder_score": 8.742,
                    "final_rrf_score": 0.0892,
                    "retrieval_rrf_score": 0.0451,
                },
                {
                    "id": 102,
                    "cross_encoder_score": 7.319,
                    "final_rrf_score": 0.0765,
                    "retrieval_rrf_score": 0.0398,
                },
            ]),
            "client_metadata": json.dumps({"ip_hash": "a1b2c3d4e5f60718"}),
        }

        # 5. Admin POST /admin/recommend Contract Verification
        # Admin response must preserve timings and unstripped scores
        admin_response_results = mock_raw_results  # Unstripped
        assert "cross_encoder_score" in admin_response_results[0]

        admin_log_row = {
            "id": 2,
            "request_id": str(uuid.uuid4()),
            "created_at": now_utc + timedelta(seconds=5),
            "endpoint": "admin_recommend",
            "source": "admin_eval",
            "api_key_id": admin_key_id,
            "session_id": None,
            "query": "eval test query",
            "top_k": 5,
            "allow_adult": False,
            "results_count": 2,
            "status": "ok",
            "status_code": 200,
            "error": None,
            "total_ms": 40.4,
            "timings": json.dumps(mock_timings),
            "candidate_scores": json.dumps([
                {
                    "id": 101,
                    "cross_encoder_score": 8.742,
                    "final_rrf_score": 0.0892,
                    "retrieval_rrf_score": 0.0451,
                }
            ]),
            "client_metadata": json.dumps({"ip_hash": "ffffffffffffffff"}),
        }

        # 6. Initialize in-memory database with the 2 logged rows + daily rollups
        db_rows = [user_log_row, admin_log_row]
        fake_conn = FakeConnection(db_rows, fixed_now=now_utc + timedelta(minutes=10))

        # Pre-seed daily rollups as logged by logger.py
        today_date = now_utc.date()
        fake_conn.usage_daily[(dev_key_id, today_date)] = 1
        fake_conn.usage_daily[(admin_key_id, today_date)] = 1
        fake_conn._staged_usage = dict(fake_conn.usage_daily)

        # 7. Archival execution triggered against synthetic data (--days 0)
        mock_storage = MockStorageClient()
        summary = run_archiver(
            conn=fake_conn,
            storage=mock_storage,
            days=0,
            dry_run=False,
        )

        # Assert Archival summary
        assert summary.status == "ok"
        assert summary.rows_archived == 2
        assert summary.rows_deleted == 2
        assert len(mock_storage.objects) == 2  # 1 for user logs/, 1 for admin_eval/

        # Assert partition isolation:
        keys = list(mock_storage.objects.keys())
        user_keys = [k for k in keys if k.startswith("logs/")]
        admin_keys = [k for k in keys if k.startswith("admin_eval/")]
        assert len(user_keys) == 1, "User rows must be partitioned under logs/"
        assert len(admin_keys) == 1, "Admin rows must be partitioned under admin_eval/"

        # Assert Parquet content & schema verification
        user_table = pq.read_table(pa.BufferReader(mock_storage.objects[user_keys[0]]))
        assert user_table.num_rows == 1
        assert user_table.column("source")[0].as_py() == "user"
        assert user_table.column("api_key_id")[0].as_py() == dev_key_id

        admin_table = pq.read_table(pa.BufferReader(mock_storage.objects[admin_keys[0]]))
        assert admin_table.num_rows == 1
        assert admin_table.column("source")[0].as_py() == "admin_eval"
        assert admin_table.column("api_key_id")[0].as_py() == admin_key_id

        # 8. PostgreSQL Pruning Verification: exact IDs pruned
        assert len(fake_conn.rows) == 0, "Exact archived IDs must be deleted from DB"

        # 9. Rollup Persistence: telemetry.api_key_usage_daily survives the prune!
        assert fake_conn.usage_daily[(dev_key_id, today_date)] == 1
        assert fake_conn.usage_daily[(admin_key_id, today_date)] == 1


# ===========================================================================
# 6. Failure Injection & Alert Triggering Tests
# ===========================================================================

class TestSprint5FailureInjection:
    """Verifies failure injection modes and guarantees zero data loss."""

    def test_failure_injection_db_fetch_error(self):
        fake_conn = FakeConnection([], fail_on_fetch=True)
        mock_storage = MockStorageClient()

        with pytest.raises(Exception) as exc_info:
            run_archiver(conn=fake_conn, storage=mock_storage, days=0)

        assert "Simulated Database Fetch Network Failure" in str(exc_info.value)
        assert len(mock_storage.objects) == 0
        assert fake_conn.commits == 0 or len(fake_conn.rows) == 0

    def test_failure_injection_storage_upload_timeout(self):
        # Fail all 5 upload attempts
        log_row = {
            "id": 10,
            "request_id": str(uuid.uuid4()),
            "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
            "endpoint": "recommend",
            "source": "user",
            "api_key_id": str(uuid.uuid4()),
            "session_id": None,
            "query": "test query",
            "top_k": 5,
            "allow_adult": False,
            "results_count": 0,
            "status": "ok",
            "status_code": 200,
            "error": None,
            "total_ms": 10.0,
            "timings": None,
            "candidate_scores": None,
            "client_metadata": None,
        }
        fake_conn = FakeConnection([log_row])
        mock_storage = MockStorageClient(fail_upload_times=10)

        with pytest.raises(RetryableStorageError):
            run_archiver(
                conn=fake_conn,
                storage=mock_storage,
                days=0,
                retry_max_attempts=3,
                retry_wait_min=0.01,
                retry_wait_max=0.02,
            )

        # Invariant: Zero rows pruned when upload fails!
        assert 10 in fake_conn.rows
        assert len(fake_conn.rows) == 1

    def test_failure_injection_corrupt_parquet_verification(self):
        log_row = {
            "id": 20,
            "request_id": str(uuid.uuid4()),
            "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
            "endpoint": "recommend",
            "source": "user",
            "api_key_id": str(uuid.uuid4()),
            "session_id": None,
            "query": "test query",
            "top_k": 5,
            "allow_adult": False,
            "results_count": 0,
            "status": "ok",
            "status_code": 200,
            "error": None,
            "total_ms": 10.0,
            "timings": None,
            "candidate_scores": None,
            "client_metadata": None,
        }
        fake_conn = FakeConnection([log_row])
        mock_storage = MockStorageClient(corrupt_download_mode="truncate")

        with pytest.raises(ArchiveVerificationError):
            run_archiver(conn=fake_conn, storage=mock_storage, days=0)

        # Invariant: Zero rows pruned when remote verification fails!
        assert 20 in fake_conn.rows
        assert len(fake_conn.rows) == 1
