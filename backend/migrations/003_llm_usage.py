"""
backend/migrations/003_llm_usage.py

Standalone, idempotent database migration for Sprint 7:
1. Creates table `telemetry.llm_usage` for tracking per-layer LLM token consumption & cost auditing:
   - layer: 'nli', 'retrieval', 'presentation'
   - prompt_tokens, completion_tokens, total_tokens
   - latency_ms, status ('ok', 'error', 'cached', 'fallback')
2. Creates performance indexes on (created_at DESC), (layer, created_at DESC), and request_id.
3. Enables Row Level Security (RLS) with default-deny against public PostgREST exposure.
4. Grants select permissions to admin JWT role and full access to telemetry_archiver.

Usage:
    python -m backend.migrations.003_llm_usage [--dry-run] [--check] [--verbose]
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
logger = logging.getLogger("migration_003")


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
    """Inspects PostgreSQL system catalogs to check whether 003 migration has been applied."""
    status = {
        "table_llm_usage": False,
        "index_llm_usage_created": False,
        "index_llm_usage_layer_created": False,
        "index_llm_usage_request_id": False,
        "rls_llm_usage": False,
        "policy_admin_read_llm_usage": False,
    }

    with conn.cursor(cursor_factory=extras.DictCursor) as cur:
        # Check table
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'telemetry' AND table_name = 'llm_usage';
            """
        )
        status["table_llm_usage"] = cur.fetchone() is not None

        # Check indexes
        cur.execute(
            """
            SELECT indexname FROM pg_indexes 
            WHERE schemaname = 'telemetry' AND tablename = 'llm_usage';
            """
        )
        existing_indexes = {row["indexname"] for row in cur.fetchall()}
        status["index_llm_usage_created"] = "idx_llm_usage_created_at" in existing_indexes
        status["index_llm_usage_layer_created"] = "idx_llm_usage_layer_created" in existing_indexes
        status["index_llm_usage_request_id"] = "idx_llm_usage_request_id" in existing_indexes

        # Check RLS
        cur.execute(
            """
            SELECT rowsecurity FROM pg_tables 
            WHERE schemaname = 'telemetry' AND tablename = 'llm_usage';
            """
        )
        row = cur.fetchone()
        status["rls_llm_usage"] = bool(row and row["rowsecurity"])

        # Check Admin Policy
        cur.execute(
            """
            SELECT policyname FROM pg_policies 
            WHERE schemaname = 'telemetry' AND tablename = 'llm_usage';
            """
        )
        policies = {row["policyname"] for row in cur.fetchall()}
        status["policy_admin_read_llm_usage"] = "admin_read_llm_usage" in policies

    return status


def apply_migration(conn, dry_run: bool = False):
    """Executes the DDL statements idempotently."""
    statements = [
        # 1. Create table
        (
            "Create telemetry.llm_usage table",
            """
            CREATE TABLE IF NOT EXISTS telemetry.llm_usage (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
                request_id VARCHAR(64),
                session_id VARCHAR(64),
                layer VARCHAR(32) NOT NULL,
                model VARCHAR(64) NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cached BOOLEAN NOT NULL DEFAULT FALSE,
                latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                status VARCHAR(32) NOT NULL DEFAULT 'ok',
                error TEXT,
                CONSTRAINT chk_llm_layer CHECK (layer IN ('nli', 'retrieval', 'presentation')),
                CONSTRAINT chk_llm_status CHECK (status IN ('ok', 'error', 'cached', 'fallback'))
            );
            """
        ),
        # 2. Indexes
        (
            "Create idx_llm_usage_created_at index",
            "CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON telemetry.llm_usage (created_at DESC);"
        ),
        (
            "Create idx_llm_usage_layer_created index",
            "CREATE INDEX IF NOT EXISTS idx_llm_usage_layer_created ON telemetry.llm_usage (layer, created_at DESC);"
        ),
        (
            "Create idx_llm_usage_request_id index",
            "CREATE INDEX IF NOT EXISTS idx_llm_usage_request_id ON telemetry.llm_usage (request_id) WHERE request_id IS NOT NULL;"
        ),
        # 3. Enable RLS
        (
            "Enable Row Level Security on telemetry.llm_usage",
            "ALTER TABLE telemetry.llm_usage ENABLE ROW LEVEL SECURITY;"
        ),
        # 4. Create Admin Read Policy
        (
            "Create admin read policy on telemetry.llm_usage",
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies 
                    WHERE schemaname = 'telemetry' 
                      AND tablename = 'llm_usage' 
                      AND policyname = 'admin_read_llm_usage'
                ) THEN
                    CREATE POLICY admin_read_llm_usage ON telemetry.llm_usage
                        FOR SELECT
                        TO authenticated
                        USING ((auth.jwt()->'app_metadata'->>'role') = 'admin');
                END IF;
            END $$;
            """
        ),
        # 5. Role permissions
        (
            "Grant archiver and service permissions on telemetry.llm_usage",
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'telemetry_archiver') THEN
                    GRANT SELECT, INSERT ON telemetry.llm_usage TO telemetry_archiver;
                END IF;
            END $$;
            """
        )
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
        logger.info("Migration 003 completed successfully.")


def main():
    parser = argparse.ArgumentParser(description="Apply migration 003 (LLM Usage Telemetry)")
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
