"""
backend/migrations/004_feedback_events.py

Standalone, idempotent database migration for Loop 2 (First-Party Feedback Events):
1. Adds unique constraint on telemetry.recommendation_logs(request_id) if missing,
   enabling foreign key referencing from child event tables.
2. Creates table telemetry.feedback_events for tracking explicit ground-truth feedback:
   - recommendation_id: foreign key referencing telemetry.recommendation_logs(request_id) ON DELETE CASCADE
   - event_type: 'thumbs_up', 'thumbs_down', 'more_like_this', 'watchlist_add'
   - anime_id: optional target anime identifier
   - metadata: JSONB for arbitrary context
   - user_id: authenticated or anonymous user identifier
   - client_ip: hashed IP for privacy preservation
3. Creates performance indexes on recommendation_id, created_at DESC, event_type, and anime_id.
4. Enables Row Level Security (RLS) with default-deny against public PostgREST exposure.
5. Grants select permissions to admin JWT role and full access to telemetry_archiver.

Usage:
    python -m backend.migrations.004_feedback_events [--dry-run] [--check] [--verbose]
"""

import os
import sys
import argparse
import logging
from typing import Dict, Any
import psycopg2
from psycopg2 import extras

try:
    from backend.rag_pipeline.config import config
except ImportError:
    try:
        from rag_pipeline.config import config
    except ImportError:
        def config() -> dict:
            return {
                "host": os.getenv("DB_HOST", "localhost"),
                "port": os.getenv("DB_PORT", "5432"),
                "database": os.getenv("DB_NAME", "postgres"),
                "user": os.getenv("DB_USER", "postgres"),
                "password": os.getenv("DB_PASSWORD", ""),
            }

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("migration_004")


def get_db_connection(params: dict):
    """Establishes a direct connection with autocommit enabled for DDL operations."""
    try:
        conn = psycopg2.connect(**params)
        conn.autocommit = True
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


def check_status(conn) -> Dict[str, bool]:
    """Inspects PostgreSQL system catalogs to check whether 004 migration has been applied."""
    status = {
        "constraint_recommendation_logs_request_id": False,
        "table_feedback_events": False,
        "index_feedback_recommendation_id": False,
        "index_feedback_created_at": False,
        "index_feedback_event_type": False,
        "index_feedback_anime_id": False,
        "rls_feedback_events": False,
        "policy_admin_read_feedback_events": False,
    }

    with conn.cursor(cursor_factory=extras.DictCursor) as cur:
        # Check unique constraint on recommendation_logs
        cur.execute(
            """
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_recommendation_logs_request_id';
            """
        )
        status["constraint_recommendation_logs_request_id"] = cur.fetchone() is not None

        # Check table
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'telemetry' AND table_name = 'feedback_events';
            """
        )
        status["table_feedback_events"] = cur.fetchone() is not None

        # Check indexes
        cur.execute(
            """
            SELECT indexname FROM pg_indexes 
            WHERE schemaname = 'telemetry' AND tablename = 'feedback_events';
            """
        )
        existing_indexes = {row["indexname"] for row in cur.fetchall()}
        status["index_feedback_recommendation_id"] = "idx_feedback_recommendation_id" in existing_indexes
        status["index_feedback_created_at"] = "idx_feedback_created_at" in existing_indexes
        status["index_feedback_event_type"] = "idx_feedback_event_type" in existing_indexes
        status["index_feedback_anime_id"] = "idx_feedback_anime_id" in existing_indexes

        # Check RLS
        cur.execute(
            """
            SELECT rowsecurity FROM pg_tables 
            WHERE schemaname = 'telemetry' AND tablename = 'feedback_events';
            """
        )
        row = cur.fetchone()
        status["rls_feedback_events"] = bool(row and row["rowsecurity"])

        # Check Admin Policy
        cur.execute(
            """
            SELECT policyname FROM pg_policies 
            WHERE schemaname = 'telemetry' 
              AND tablename = 'feedback_events';
            """
        )
        policies = {row["policyname"] for row in cur.fetchall()}
        status["policy_admin_read_feedback_events"] = "admin_read_feedback_events" in policies

    return status


def apply_migration(conn, dry_run: bool = False):
    """Executes the DDL statements idempotently."""
    statements = [
        # 1. Unique constraint on telemetry.recommendation_logs(request_id)
        (
            "Add unique constraint on telemetry.recommendation_logs(request_id)",
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'uq_recommendation_logs_request_id'
                ) THEN
                    ALTER TABLE telemetry.recommendation_logs 
                    ADD CONSTRAINT uq_recommendation_logs_request_id UNIQUE (request_id);
                END IF;
            END $$;
            """
        ),
        # 2. Create telemetry.feedback_events table
        (
            "Create telemetry.feedback_events table",
            """
            CREATE TABLE IF NOT EXISTS telemetry.feedback_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                recommendation_id UUID NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
                event_type VARCHAR(32) NOT NULL,
                anime_id INT,
                metadata JSONB,
                user_id VARCHAR(128),
                client_ip VARCHAR(64),
                CONSTRAINT fk_feedback_recommendation
                    FOREIGN KEY (recommendation_id) 
                    REFERENCES telemetry.recommendation_logs(request_id) 
                    ON DELETE CASCADE,
                CONSTRAINT chk_feedback_event_type 
                    CHECK (event_type IN ('thumbs_up', 'thumbs_down', 'more_like_this', 'watchlist_add'))
            );
            """
        ),
        # 3. Create indexes
        (
            "Create idx_feedback_recommendation_id index",
            "CREATE INDEX IF NOT EXISTS idx_feedback_recommendation_id ON telemetry.feedback_events (recommendation_id);"
        ),
        (
            "Create idx_feedback_created_at index",
            "CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON telemetry.feedback_events (created_at DESC);"
        ),
        (
            "Create idx_feedback_event_type index",
            "CREATE INDEX IF NOT EXISTS idx_feedback_event_type ON telemetry.feedback_events (event_type);"
        ),
        (
            "Create idx_feedback_anime_id index",
            "CREATE INDEX IF NOT EXISTS idx_feedback_anime_id ON telemetry.feedback_events (anime_id) WHERE anime_id IS NOT NULL;"
        ),
        # 4. Enable RLS
        (
            "Enable Row Level Security on telemetry.feedback_events",
            "ALTER TABLE telemetry.feedback_events ENABLE ROW LEVEL SECURITY;"
        ),
        # 5. Create Admin Read Policy
        (
            "Create admin read policy on telemetry.feedback_events",
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies 
                    WHERE schemaname = 'telemetry' 
                      AND tablename = 'feedback_events' 
                      AND policyname = 'admin_read_feedback_events'
                ) THEN
                    CREATE POLICY admin_read_feedback_events ON telemetry.feedback_events
                        FOR SELECT
                        TO authenticated
                        USING ((auth.jwt()->'app_metadata'->>'role') = 'admin');
                END IF;
            END $$;
            """
        ),
        # 6. Role permissions
        (
            "Grant archiver and service permissions on telemetry.feedback_events",
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'telemetry_archiver') THEN
                    GRANT SELECT, INSERT ON telemetry.feedback_events TO telemetry_archiver;
                END IF;
            END $$;
            """
        ),
    ]

    with conn.cursor() as cur:
        for desc, stmt in statements:
            if dry_run:
                logger.info(f"[DRY-RUN] Would execute: {desc}")
                print(stmt.strip())
            else:
                logger.info(f"Executing: {desc}")
                cur.execute(stmt)

    if not dry_run:
        logger.info("Migration 004 completed successfully.")


def main():
    parser = argparse.ArgumentParser(description="Apply migration 004 (First-Party Feedback Events)")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL statements without applying")
    parser.add_argument("--check", action="store_true", help="Check current migration status and exit")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    db_params = config()
    conn = get_db_connection(db_params)

    try:
        status_before = check_status(conn)
        if args.check:
            logger.info("Current migration status:")
            for k, v in status_before.items():
                logger.info(f"  {k}: {'APPLIED' if v else 'PENDING'}")
            all_applied = all(status_before.values())
            sys.exit(0 if all_applied else 1)

        apply_migration(conn, dry_run=args.dry_run)

        if not args.dry_run:
            status_after = check_status(conn)
            logger.info("Post-migration status verification:")
            for k, v in status_after.items():
                logger.info(f"  {k}: {'APPLIED' if v else 'PENDING'}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
