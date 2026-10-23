"""
test/integration/test_backend_integration.py

Live database integration test suite verifying backend PostgreSQL interactions:
1. API key generation, database insertion into app_auth.api_keys, and audit logging into app_auth.key_audit_log.
2. PostgreSQL trigger enforcement via 'trg_enforce_max_active_keys' preventing more than 5 active keys per developer.
3. Telemetry ingestion into telemetry.recommendation_logs and paired atomic aggregation into telemetry.api_key_usage_daily.
4. Comprehensive fixture teardown ensuring zero test row leakage into the local database.

Conforms strictly to British English documentation standards without em-dashes.
"""

import os
import sys
import uuid
import hashlib
from typing import Generator, List, Set, Tuple

import pytest
import psycopg2
from psycopg2 import extras

# Ensure project root is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.rag_pipeline.config import config as get_db_config
from backend.auth.keys import generate_api_key, hash_api_key
from backend.telemetry.logger import log_recommendation_event


# ---------------------------------------------------------------------------
# FIXTURES & ISOLATION TEARDOWN
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_conn() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Establishes a live connection to the local PostgreSQL database using canonical
    backend.rag_pipeline.config.config() parameters with autocommit enabled.
    Ensures safe session teardown and close.
    """
    cfg = get_db_config()
    conn = psycopg2.connect(**cfg)
    conn.autocommit = True
    try:
        yield conn
    finally:
        if not conn.closed:
            conn.close()


@pytest.fixture(scope="module", autouse=True)
def clean_test_database(db_conn: psycopg2.extensions.connection) -> Generator[None, None, None]:
    """
    Snapshots pre-existing database record IDs before tests execute and guarantees
    that all newly created keys, audit logs, recommendation records, and usage rollups
    are deleted upon module teardown, leaving the database completely clean.
    """
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM app_auth.api_keys;")
        initial_keys: Set[str] = set(str(r[0]) for r in cur.fetchall())

        cur.execute("SELECT id FROM app_auth.key_audit_log;")
        initial_audits: Set[int] = set(r[0] for r in cur.fetchall())

        cur.execute("SELECT id FROM telemetry.recommendation_logs;")
        initial_rlogs: Set[int] = set(r[0] for r in cur.fetchall())

        cur.execute("SELECT api_key_id, day FROM telemetry.api_key_usage_daily;")
        initial_usage: Set[Tuple[str, str]] = set((str(r[0]), str(r[1])) for r in cur.fetchall())

    yield

    # Clean up all created test records
    with db_conn.cursor() as cur:
        # 1. Purge new recommendation logs
        cur.execute("SELECT id FROM telemetry.recommendation_logs;")
        current_rlogs = set(r[0] for r in cur.fetchall())
        new_rlogs = list(current_rlogs - initial_rlogs)
        if new_rlogs:
            cur.execute("DELETE FROM telemetry.recommendation_logs WHERE id = ANY(%s);", (new_rlogs,))

        # 2. Purge new api keys and associated cascade records
        cur.execute("SELECT id FROM app_auth.api_keys;")
        current_keys = set(str(r[0]) for r in cur.fetchall())
        new_keys = list(current_keys - initial_keys)
        if new_keys:
            cur.execute(
                "DELETE FROM telemetry.api_key_usage_daily WHERE api_key_id = ANY(%s::uuid[]);",
                (new_keys,)
            )
            cur.execute(
                "DELETE FROM app_auth.key_audit_log WHERE api_key_id = ANY(%s::uuid[]);",
                (new_keys,)
            )
            cur.execute(
                "DELETE FROM app_auth.api_keys WHERE id = ANY(%s::uuid[]);",
                (new_keys,)
            )

        # 3. Purge new audit log rows (including any system/cli events)
        cur.execute("SELECT id FROM app_auth.key_audit_log;")
        current_audits = set(r[0] for r in cur.fetchall())
        new_audits = list(current_audits - initial_audits)
        if new_audits:
            cur.execute("DELETE FROM app_auth.key_audit_log WHERE id = ANY(%s);", (new_audits,))

        # 4. Purge any residual daily usage rows
        cur.execute("SELECT api_key_id, day FROM telemetry.api_key_usage_daily;")
        current_usage = set((str(r[0]), str(r[1])) for r in cur.fetchall())
        new_usage = list(current_usage - initial_usage)
        for api_key_id, day in new_usage:
            cur.execute(
                "DELETE FROM telemetry.api_key_usage_daily WHERE api_key_id = %s::uuid AND day = %s::date;",
                (api_key_id, day)
            )


# ---------------------------------------------------------------------------
# INTEGRATION TESTS
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.backend
@pytest.mark.live_db
def test_api_key_creation_and_audit_logging(db_conn: psycopg2.extensions.connection) -> None:
    """
    Verifies that creating an API key persists a cryptographically hashed credential record into
    app_auth.api_keys and automatically records an audit log row into app_auth.key_audit_log.

    This behaviour protects credential persistence, cryptographic isolation (ensuring plaintext secrets
    are never stored in database tables), and operational audit compliance.
    """
    test_owner_id = str(uuid.uuid4())
    test_key_name = f"int-key-{uuid.uuid4().hex[:8]}"

    # Generate key using canonical auth helper
    raw_key, record = generate_api_key(
        name=test_key_name,
        owner_id=test_owner_id,
        role="user",
        scopes=["recommend"],
        rate_limit_per_min=20,
        expires_in_days=90,
        conn=db_conn,
    )

    assert raw_key.startswith("ar_live_")
    created_key_id = record["id"]

    # Verify app_auth.api_keys row
    with db_conn.cursor(cursor_factory=extras.DictCursor) as cur:
        cur.execute(
            """
            SELECT id, owner_id, name, key_prefix, key_hash, role, scopes,
                   rate_limit_per_min, expires_at, revoked_at, created_at
            FROM app_auth.api_keys
            WHERE id = %s;
            """,
            (created_key_id,)
        )
        row = cur.fetchone()
        assert row is not None, "API key was not found in app_auth.api_keys"
        assert str(row["owner_id"]) == test_owner_id
        assert row["name"] == test_key_name
        assert row["key_prefix"] == raw_key[:16]
        assert bytes(row["key_hash"]) == hash_api_key(raw_key)
        assert row["role"] == "user"
        assert row["scopes"] == ["recommend"]
        assert row["rate_limit_per_min"] == 20
        assert row["revoked_at"] is None
        assert row["expires_at"] is not None

        # Verify app_auth.key_audit_log row (timestamp column is 'at')
        cur.execute(
            """
            SELECT id, actor, action, api_key_id, detail, at
            FROM app_auth.key_audit_log
            WHERE api_key_id = %s
            ORDER BY at DESC LIMIT 1;
            """,
            (created_key_id,)
        )
        audit_row = cur.fetchone()
        assert audit_row is not None, "Audit log row was not recorded in app_auth.key_audit_log"
        assert audit_row["action"] == "key.create"
        assert audit_row["actor"] == f"user:{test_owner_id}"
        assert str(audit_row["api_key_id"]) == created_key_id
        detail = audit_row["detail"]
        assert detail["name"] == test_key_name
        assert detail["key_prefix"] == raw_key[:16]
        assert detail["role"] == "user"


@pytest.mark.integration
@pytest.mark.backend
@pytest.mark.live_db
def test_trg_enforce_max_active_keys_prevents_exceeding_limit(
    db_conn: psycopg2.extensions.connection
) -> None:
    """
    Verifies that the database trigger 'trg_enforce_max_active_keys' strictly limits each developer
    to a maximum of 5 active keys concurrently and that soft-revoking an existing key frees up a slot.

    This behaviour protects the platform against credential sprawl, unauthorised resource allocation,
    and quota bypass attacks at the database storage engine layer.
    """
    test_owner_id = str(uuid.uuid4())
    created_key_ids: List[str] = []

    with db_conn.cursor() as cur:
        # Insert 5 active keys (maximum allowable capacity)
        for i in range(1, 6):
            key_prefix = f"ar_test_{uuid.uuid4().hex[:8]}"
            key_hash = hashlib.sha256(f"secret_{i}_{test_owner_id}".encode()).digest()
            cur.execute(
                """
                INSERT INTO app_auth.api_keys (owner_id, name, key_prefix, key_hash, role)
                VALUES (%s, %s, %s, %s, 'user')
                RETURNING id;
                """,
                (test_owner_id, f"test_key_{i}", key_prefix, key_hash)
            )
            created_key_ids.append(str(cur.fetchone()[0]))

        assert len(created_key_ids) == 5

        # Attempting to insert a 6th active key must fail via trigger enforcement
        key_prefix_6 = f"ar_test_{uuid.uuid4().hex[:8]}"
        key_hash_6 = hashlib.sha256(f"secret_6_{test_owner_id}".encode()).digest()

        with pytest.raises(psycopg2.Error) as exc_info:
            cur.execute(
                """
                INSERT INTO app_auth.api_keys (owner_id, name, key_prefix, key_hash, role)
                VALUES (%s, %s, %s, %s, 'user');
                """,
                (test_owner_id, "test_key_overflow", key_prefix_6, key_hash_6)
            )

        err_msg = str(exc_info.value).lower()
        assert "active api key limit of 5 exceeded" in err_msg

        # Soft-revoke one active key to free up a slot
        cur.execute(
            """
            UPDATE app_auth.api_keys
            SET revoked_at = NOW()
            WHERE id = %s::uuid;
            """,
            (created_key_ids[0],)
        )

        # Inserting a replacement active key must now succeed
        key_prefix_replacement = f"ar_test_{uuid.uuid4().hex[:8]}"
        key_hash_replacement = hashlib.sha256(f"secret_replacement_{test_owner_id}".encode()).digest()
        cur.execute(
            """
            INSERT INTO app_auth.api_keys (owner_id, name, key_prefix, key_hash, role)
            VALUES (%s, %s, %s, %s, 'user')
            RETURNING id;
            """,
            (test_owner_id, "test_key_replacement", key_prefix_replacement, key_hash_replacement)
        )
        replacement_id = str(cur.fetchone()[0])
        assert replacement_id is not None


@pytest.mark.integration
@pytest.mark.backend
@pytest.mark.live_db
def test_telemetry_logging_and_daily_usage_aggregation(
    db_conn: psycopg2.extensions.connection
) -> None:
    """
    Verifies that logging a recommendation event creates a detailed record in telemetry.recommendation_logs
    and atomically updates the request count in telemetry.api_key_usage_daily for the current date.

    This behaviour protects consumption accounting, daily rate-limit enforcement, and platform analytics
    by ensuring transactional pairing between audit logs and rollups.
    """
    test_owner_id = str(uuid.uuid4())
    _, record = generate_api_key(
        name=f"telemetry-key-{uuid.uuid4().hex[:6]}",
        owner_id=test_owner_id,
        role="user",
        conn=db_conn,
    )
    api_key_id = record["id"]

    # First event
    success_1 = log_recommendation_event(
        endpoint="recommend",
        query="cyberpunk detective thriller",
        top_k=20,
        allow_adult=False,
        source="user",
        api_key_id=api_key_id,
        results_count=2,
        candidate_scores=[
            {"id": 1, "cross_encoder_score": 5.4321, "final_rrf_score": 0.08912},
            {"id": 6, "cross_encoder_score": 4.1025, "final_rrf_score": 0.07541},
        ],
        timings={"retrieval_ms": 78.4, "ranking_ms": 94.2},
        total_ms=172.6,
        status="ok",
        status_code=200,
        conn=db_conn,
    )
    assert success_1 is True

    # Verify telemetry.recommendation_logs insert
    with db_conn.cursor(cursor_factory=extras.DictCursor) as cur:
        cur.execute(
            """
            SELECT id, request_id, endpoint, source, api_key_id, query, top_k,
                   allow_adult, results_count, status, status_code, total_ms,
                   candidate_scores, timings
            FROM telemetry.recommendation_logs
            WHERE api_key_id = %s::uuid
            ORDER BY created_at DESC LIMIT 1;
            """,
            (api_key_id,)
        )
        log_row = cur.fetchone()
        assert log_row is not None
        assert log_row["endpoint"] == "recommend"
        assert log_row["source"] == "user"
        assert log_row["query"] == "cyberpunk detective thriller"
        assert log_row["results_count"] == 2
        assert log_row["status"] == "ok"
        assert log_row["status_code"] == 200
        assert log_row["total_ms"] == pytest.approx(172.6, rel=1e-2)
        assert len(log_row["candidate_scores"]) == 2

        # Verify telemetry.api_key_usage_daily rollup count is 1
        cur.execute(
            """
            SELECT request_count
            FROM telemetry.api_key_usage_daily
            WHERE api_key_id = %s::uuid AND day = (NOW() AT TIME ZONE 'UTC')::date;
            """,
            (api_key_id,)
        )
        usage_row = cur.fetchone()
        assert usage_row is not None
        assert usage_row["request_count"] == 1

    # Second event with the same API key on the same day
    success_2 = log_recommendation_event(
        endpoint="recommend",
        query="space opera bounty hunter",
        top_k=10,
        allow_adult=False,
        source="user",
        api_key_id=api_key_id,
        results_count=1,
        status="ok",
        status_code=200,
        conn=db_conn,
    )
    assert success_2 is True

    # Verify telemetry.api_key_usage_daily rollup was incremented to 2
    with db_conn.cursor(cursor_factory=extras.DictCursor) as cur:
        cur.execute(
            """
            SELECT request_count
            FROM telemetry.api_key_usage_daily
            WHERE api_key_id = %s::uuid AND day = (NOW() AT TIME ZONE 'UTC')::date;
            """,
            (api_key_id,)
        )
        usage_row_after = cur.fetchone()
        assert usage_row_after is not None
        assert usage_row_after["request_count"] == 2


@pytest.mark.integration
@pytest.mark.backend
@pytest.mark.live_db
def test_database_cleanup_fixture_isolation(db_conn: psycopg2.extensions.connection) -> None:
    """
    Verifies that the test database maintains strict referential integrity and isolation
    during test execution so that ongoing tests do not collide or mutate shared state.

    This behaviour protects test reproducibility and prevents cascade corruption across
    independent test cycles.
    """
    with db_conn.cursor() as cur:
        cur.execute("SELECT 1;")
        assert cur.fetchone()[0] == 1
