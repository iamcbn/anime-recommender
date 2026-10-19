"""
backend/migrations/002_telemetry_and_api_keys.py

Standalone, idempotent database migration for Sprint 1:
1. Provisions `pgcrypto` extension for cryptographic UUID generation.
2. Creates isolated schemas: `app_auth` (developer API keys) and `telemetry` (observability & logs).
3. Polyfills `auth.jwt()` if absent (vanilla/local PostgreSQL compatibility).
4. Establishes core tables:
   - `app_auth.api_keys`: Hashed developer API keys, prefixes, rates, and scopes.
   - `app_auth.key_audit_log`: Audit trail for key generation/revocation.
   - `telemetry.recommendation_logs`: Performance, timings, model scores, and client metadata.
   - `telemetry.api_key_usage_daily`: Unpruned daily rollups for rate limits & quota accounting.
5. Builds performance indexes for temporal filtering and developer key lookup.
6. Enforces a concurrency-safe database trigger restricting active keys to <= 5 per developer.
7. Enables Row Level Security (RLS) and default-deny policies against public PostgREST exposure.
8. Configures admin read policies and provisions the restricted `telemetry_archiver` role.

Usage:
    python -m backend.migrations.002_telemetry_and_api_keys [--dry-run] [--check] [--verbose]
"""

import os
import sys
import time
import argparse
import logging
from typing import Dict, Any, List, Tuple
import psycopg2
from psycopg2 import extras, sql

# Attempt configuration import; fallback to direct environment variables
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
logger = logging.getLogger("migration_002")


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
    """
    Inspects PostgreSQL system catalogs to determine migration status across
    schemas, tables, indexes, triggers, roles, and RLS configurations.
    """
    status = {
        "extension_pgcrypto": False,
        "schema_app_auth": False,
        "schema_telemetry": False,
        "table_api_keys": False,
        "table_key_audit_log": False,
        "table_recommendation_logs": False,
        "table_api_key_usage_daily": False,
        "index_api_keys_owner": False,
        "index_api_keys_owner_name": False,
        "index_rlogs_created": False,
        "index_rlogs_key_created": False,
        "index_rlogs_source_created": False,
        "trigger_max_active_keys": False,
        "rls_api_keys": False,
        "rls_key_audit_log": False,
        "rls_recommendation_logs": False,
        "rls_api_key_usage_daily": False,
        "policy_admin_read_logs": False,
        "policy_admin_read_usage": False,
        "role_telemetry_archiver": False,
    }

    with conn.cursor(cursor_factory=extras.DictCursor) as cur:
        # 1. Extensions
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto';")
        status["extension_pgcrypto"] = cur.fetchone() is not None

        # 2. Schemas
        cur.execute("SELECT nspname FROM pg_namespace WHERE nspname IN ('app_auth', 'telemetry');")
        for row in cur.fetchall():
            if row["nspname"] == "app_auth":
                status["schema_app_auth"] = True
            elif row["nspname"] == "telemetry":
                status["schema_telemetry"] = True

        # 3. Tables
        cur.execute("""
            SELECT table_schema, table_name 
            FROM information_schema.tables 
            WHERE table_schema IN ('app_auth', 'telemetry');
        """)
        for row in cur.fetchall():
            schema, table = row["table_schema"], row["table_name"]
            if schema == "app_auth" and table == "api_keys":
                status["table_api_keys"] = True
            elif schema == "app_auth" and table == "key_audit_log":
                status["table_key_audit_log"] = True
            elif schema == "telemetry" and table == "recommendation_logs":
                status["table_recommendation_logs"] = True
            elif schema == "telemetry" and table == "api_key_usage_daily":
                status["table_api_key_usage_daily"] = True

        # 4. Indexes
        cur.execute("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE schemaname IN ('app_auth', 'telemetry');
        """)
        indexes = {row["indexname"] for row in cur.fetchall()}
        status["index_api_keys_owner"] = "idx_api_keys_owner" in indexes
        status["index_api_keys_owner_name"] = "uq_api_keys_owner_name" in indexes
        status["index_rlogs_created"] = "idx_rlogs_created" in indexes
        status["index_rlogs_key_created"] = "idx_rlogs_key_created" in indexes
        status["index_rlogs_source_created"] = "idx_rlogs_source_created" in indexes

        # 5. Triggers
        cur.execute("""
            SELECT trigger_name 
            FROM information_schema.triggers 
            WHERE trigger_schema = 'app_auth' AND trigger_name = 'trg_enforce_max_active_keys';
        """)
        status["trigger_max_active_keys"] = cur.fetchone() is not None

        # 6. Row-Level Security
        cur.execute("""
            SELECT schemaname, tablename, rowsecurity 
            FROM pg_tables 
            WHERE schemaname IN ('app_auth', 'telemetry');
        """)
        for row in cur.fetchall():
            sch, tbl, rls = row["schemaname"], row["tablename"], bool(row["rowsecurity"])
            if sch == "app_auth" and tbl == "api_keys" and rls:
                status["rls_api_keys"] = True
            elif sch == "app_auth" and tbl == "key_audit_log" and rls:
                status["rls_key_audit_log"] = True
            elif sch == "telemetry" and tbl == "recommendation_logs" and rls:
                status["rls_recommendation_logs"] = True
            elif sch == "telemetry" and tbl == "api_key_usage_daily" and rls:
                status["rls_api_key_usage_daily"] = True

        # 7. Policies
        cur.execute("""
            SELECT policyname 
            FROM pg_policies 
            WHERE schemaname = 'telemetry';
        """)
        policies = {row["policyname"] for row in cur.fetchall()}
        status["policy_admin_read_logs"] = "admin_read_recommendation_logs" in policies
        status["policy_admin_read_usage"] = "admin_read_api_key_usage_daily" in policies

        # 8. Archiver Role
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'telemetry_archiver';")
        status["role_telemetry_archiver"] = cur.fetchone() is not None

    return status


def apply_migration(conn, dry_run: bool = False) -> bool:
    """
    Executes idempotent DDL statements safely.
    Uses IF NOT EXISTS, procedural guards, and catalog queries to ensure
    safe repeated execution across local and Supabase cloud environments.
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("Executing Migration 002: Telemetry Schema, API Keys & RLS")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")
    logger.info("=" * 60)

    pre_status = check_status(conn)
    logger.info(f"Pre-migration catalog status: {pre_status}")

    ddl_statements: List[Tuple[str, str]] = [
        (
            "1. Ensure pgcrypto extension exists for UUIDs and hashing",
            "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
        ),
        (
            "2. Create dedicated schemas: app_auth and telemetry",
            """
            CREATE SCHEMA IF NOT EXISTS app_auth;
            CREATE SCHEMA IF NOT EXISTS telemetry;
            """
        ),
        (
            "3. Polyfill auth.jwt() for local/vanilla PostgreSQL environments",
            """
            CREATE SCHEMA IF NOT EXISTS auth;
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'jwt' AND pronamespace = 'auth'::regnamespace) THEN
                CREATE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql STABLE AS
                'SELECT coalesce(nullif(current_setting(''request.jwt.claims'', true), ''''), ''{}'')::jsonb;';
              END IF;
            END $$;
            """
        ),
        (
            "4. Create app_auth.api_keys table",
            """
            CREATE TABLE IF NOT EXISTS app_auth.api_keys (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              owner_id UUID,
              name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 64),
              key_prefix TEXT NOT NULL UNIQUE,
              key_hash BYTEA NOT NULL UNIQUE,
              role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
              scopes TEXT[] NOT NULL DEFAULT '{recommend,chat}',
              rate_limit_per_min INT NOT NULL DEFAULT 20 CHECK (rate_limit_per_min > 0),
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              expires_at TIMESTAMPTZ,
              revoked_at TIMESTAMPTZ,
              last_used_at TIMESTAMPTZ
            );
            """
        ),
        (
            "5. Conditionally attach FK constraint fk_api_keys_owner if auth.users exists",
            """
            DO $$ BEGIN
              IF to_regclass('auth.users') IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_api_keys_owner'
              ) THEN
                ALTER TABLE app_auth.api_keys
                ADD CONSTRAINT fk_api_keys_owner
                FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;
              END IF;
            END $$;
            """
        ),
        (
            "6. Create app_auth.key_audit_log table",
            """
            CREATE TABLE IF NOT EXISTS app_auth.key_audit_log (
              id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
              at TIMESTAMPTZ NOT NULL DEFAULT now(),
              actor TEXT NOT NULL,
              action TEXT NOT NULL,
              api_key_id UUID,
              detail JSONB
            );
            """
        ),
        (
            "7. Create telemetry.recommendation_logs table",
            """
            CREATE TABLE IF NOT EXISTS telemetry.recommendation_logs (
              id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
              request_id UUID NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              endpoint VARCHAR(16) NOT NULL CHECK (endpoint IN ('recommend','chat','admin_recommend')),
              source VARCHAR(20) NOT NULL CHECK (source IN ('user','admin_eval')),
              api_key_id UUID,
              session_id TEXT,
              query TEXT NOT NULL,
              top_k INT NOT NULL,
              allow_adult BOOLEAN NOT NULL DEFAULT false,
              results_count INT NOT NULL,
              status VARCHAR(12) NOT NULL DEFAULT 'ok',
              status_code INT,
              error TEXT,
              total_ms DOUBLE PRECISION,
              timings JSONB,
              candidate_scores JSONB,
              client_metadata JSONB
            );
            """
        ),
        (
            "8. Create telemetry.api_key_usage_daily rollup table",
            """
            CREATE TABLE IF NOT EXISTS telemetry.api_key_usage_daily (
              api_key_id UUID NOT NULL,
              day DATE NOT NULL,
              request_count INT NOT NULL DEFAULT 0,
              PRIMARY KEY (api_key_id, day)
            );
            """
        ),
        (
            "9. Create performance and constraint indexes",
            """
            CREATE INDEX IF NOT EXISTS idx_api_keys_owner 
              ON app_auth.api_keys(owner_id) WHERE revoked_at IS NULL;
              
            CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_owner_name 
              ON app_auth.api_keys(owner_id, name) WHERE revoked_at IS NULL;
              
            CREATE INDEX IF NOT EXISTS idx_rlogs_created 
              ON telemetry.recommendation_logs (created_at DESC);
              
            CREATE INDEX IF NOT EXISTS idx_rlogs_key_created 
              ON telemetry.recommendation_logs (api_key_id, created_at DESC);
              
            CREATE INDEX IF NOT EXISTS idx_rlogs_source_created 
              ON telemetry.recommendation_logs (source, created_at DESC);
            """
        ),
        (
            "10. Create concurrency-safe trigger function for active key limits (<= 5 active keys)",
            """
            CREATE OR REPLACE FUNCTION app_auth.enforce_max_active_keys() RETURNS TRIGGER AS $$
            DECLARE active_count INT;
            BEGIN
              IF NEW.owner_id IS NOT NULL AND NEW.revoked_at IS NULL AND (NEW.expires_at IS NULL OR NEW.expires_at > now()) THEN
                PERFORM 1 FROM app_auth.api_keys WHERE owner_id = NEW.owner_id FOR UPDATE;
                SELECT count(*) INTO active_count FROM app_auth.api_keys
                 WHERE owner_id = NEW.owner_id 
                   AND revoked_at IS NULL 
                   AND (expires_at IS NULL OR expires_at > now())
                   AND id <> coalesce(NEW.id, '00000000-0000-0000-0000-000000000000'::uuid);
                IF active_count >= 5 THEN
                  RAISE EXCEPTION 'Active API key limit of 5 exceeded for owner %', NEW.owner_id USING ERRCODE = 'check_violation';
                END IF;
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_enforce_max_active_keys ON app_auth.api_keys;
            CREATE TRIGGER trg_enforce_max_active_keys
            BEFORE INSERT OR UPDATE OF owner_id, revoked_at, expires_at ON app_auth.api_keys
            FOR EACH ROW EXECUTE FUNCTION app_auth.enforce_max_active_keys();
            """
        ),
        (
            "11. Enable Row-Level Security & default-deny on app_auth and telemetry schemas",
            """
            ALTER TABLE app_auth.api_keys ENABLE ROW LEVEL SECURITY;
            ALTER TABLE app_auth.key_audit_log ENABLE ROW LEVEL SECURITY;
            ALTER TABLE telemetry.recommendation_logs ENABLE ROW LEVEL SECURITY;
            ALTER TABLE telemetry.api_key_usage_daily ENABLE ROW LEVEL SECURITY;

            DO $$ BEGIN
              -- Revoke default public permissions to isolate app_auth
              REVOKE ALL ON ALL TABLES IN SCHEMA app_auth FROM anon, authenticated, public;
              REVOKE ALL ON SCHEMA app_auth FROM anon, authenticated, public;

              REVOKE ALL ON ALL TABLES IN SCHEMA telemetry FROM anon, authenticated, public;
              REVOKE ALL ON SCHEMA telemetry FROM anon, authenticated, public;
            EXCEPTION WHEN undefined_object THEN
              NULL;
            END $$;
            """
        ),
        (
            "12. Configure Admin read policies on telemetry for authenticated portal users",
            """
            DO $$ BEGIN
              -- Ensure standard Supabase roles exist for local/vanilla PostgreSQL
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                BEGIN
                  CREATE ROLE anon WITH NOLOGIN NOINHERIT;
                EXCEPTION WHEN insufficient_privilege THEN NULL;
                END;
              END IF;

              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                BEGIN
                  CREATE ROLE authenticated WITH NOLOGIN NOINHERIT;
                EXCEPTION WHEN insufficient_privilege THEN NULL;
                END;
              END IF;

              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                GRANT USAGE ON SCHEMA telemetry TO authenticated;
                GRANT SELECT ON telemetry.recommendation_logs TO authenticated;
                GRANT SELECT ON telemetry.api_key_usage_daily TO authenticated;

                IF NOT EXISTS (
                  SELECT 1 FROM pg_policies 
                  WHERE schemaname = 'telemetry' 
                    AND tablename = 'recommendation_logs' 
                    AND policyname = 'admin_read_recommendation_logs'
                ) THEN
                  CREATE POLICY admin_read_recommendation_logs 
                  ON telemetry.recommendation_logs 
                  FOR SELECT TO authenticated 
                  USING ((auth.jwt()->'app_metadata'->>'role') = 'admin');
                END IF;

                IF NOT EXISTS (
                  SELECT 1 FROM pg_policies 
                  WHERE schemaname = 'telemetry' 
                    AND tablename = 'api_key_usage_daily' 
                    AND policyname = 'admin_read_api_key_usage_daily'
                ) THEN
                  CREATE POLICY admin_read_api_key_usage_daily 
                  ON telemetry.api_key_usage_daily 
                  FOR SELECT TO authenticated 
                  USING ((auth.jwt()->'app_metadata'->>'role') = 'admin');
                END IF;
              END IF;
            END $$;
            """
        ),
        (
            "13. Provision restricted telemetry_archiver role and policies",
            """
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'telemetry_archiver') THEN
                BEGIN
                  CREATE ROLE telemetry_archiver WITH NOLOGIN NOINHERIT;
                EXCEPTION WHEN insufficient_privilege THEN
                  RAISE WARNING 'Role telemetry_archiver creation skipped (insufficient privilege)';
                END;
              END IF;

              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'telemetry_archiver') THEN
                GRANT USAGE ON SCHEMA telemetry TO telemetry_archiver;
                GRANT SELECT, DELETE ON telemetry.recommendation_logs TO telemetry_archiver;
                GRANT SELECT, INSERT, UPDATE ON telemetry.api_key_usage_daily TO telemetry_archiver;

                IF NOT EXISTS (
                  SELECT 1 FROM pg_policies 
                  WHERE schemaname = 'telemetry' 
                    AND tablename = 'recommendation_logs' 
                    AND policyname = 'archiver_access_recommendation_logs'
                ) THEN
                  CREATE POLICY archiver_access_recommendation_logs 
                  ON telemetry.recommendation_logs 
                  TO telemetry_archiver 
                  USING (true) WITH CHECK (true);
                END IF;

                IF NOT EXISTS (
                  SELECT 1 FROM pg_policies 
                  WHERE schemaname = 'telemetry' 
                    AND tablename = 'api_key_usage_daily' 
                    AND policyname = 'archiver_access_api_key_usage_daily'
                ) THEN
                  CREATE POLICY archiver_access_api_key_usage_daily 
                  ON telemetry.api_key_usage_daily 
                  TO telemetry_archiver 
                  USING (true) WITH CHECK (true);
                END IF;
              END IF;
            END $$;
            """
        )
    ]

    with conn.cursor() as cur:
        for description, query in ddl_statements:
            logger.info(f"Step: {description}...")
            if dry_run:
                logger.info(f"[DRY-RUN] Would execute:\n{query.strip()}\n")
            else:
                t0 = time.time()
                cur.execute(query)
                elapsed_ms = (time.time() - t0) * 1000
                logger.info(f"Done in {elapsed_ms:.2f}ms.")

    if not dry_run:
        post_status = check_status(conn)
        logger.info(f"Post-migration catalog status: {post_status}")

        critical_checks = [
            post_status["extension_pgcrypto"],
            post_status["schema_app_auth"],
            post_status["schema_telemetry"],
            post_status["table_api_keys"],
            post_status["table_key_audit_log"],
            post_status["table_recommendation_logs"],
            post_status["table_api_key_usage_daily"],
            post_status["index_api_keys_owner"],
            post_status["index_api_keys_owner_name"],
            post_status["index_rlogs_created"],
            post_status["index_rlogs_key_created"],
            post_status["index_rlogs_source_created"],
            post_status["trigger_max_active_keys"],
            post_status["rls_api_keys"],
            post_status["rls_recommendation_logs"],
            post_status["policy_admin_read_logs"],
        ]

        if all(critical_checks):
            total_duration = time.time() - start_time
            logger.info(f"Migration 002 completed successfully in {total_duration:.2f}s.")
            return True
        else:
            failed_keys = [k for k, v in post_status.items() if not v]
            logger.error(f"Migration verification failed: Missing catalog objects: {failed_keys}")
            return False
    else:
        logger.info("Dry-run inspection completed. No DDL modifications were applied.")
        return True


def main():
    parser = argparse.ArgumentParser(description="Migration 002: Telemetry Schema, API Keys & RLS")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and print statements without applying")
    parser.add_argument("--check", action="store_true", help="Check current migration status and exit")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    params = config()
    try:
        conn = get_db_connection(params)
    except Exception as e:
        logger.critical(f"Database connection failed: {e}")
        sys.exit(1)

    try:
        if args.check:
            status = check_status(conn)
            print("\nDatabase Migration 002 Status:")
            for k, v in status.items():
                print(f"  - {k}: {'[APPLIED]' if v else '[MISSING]'}")
            critical_passed = (
                status["table_api_keys"] and
                status["table_recommendation_logs"] and
                status["trigger_max_active_keys"] and
                status["rls_recommendation_logs"]
            )
            sys.exit(0 if critical_passed else 2)

        success = apply_migration(conn, dry_run=args.dry_run)
        sys.exit(0 if success else 1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
