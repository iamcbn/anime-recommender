"""
backend/migrations/001_bm25_index_and_metadata.py

Standalone, idempotent database migration for Sprint 1:
1. Adds 'search_vector' tsvector generated column to 'anime_content'.
2. Builds the GIN index 'idx_anime_content_search_vector' for fast BM25 search.
3. Ensures index coverage on metadata join tables (anime_temporal, anime_metrics).
4. Verifies availability of enriched metadata fields for downstream LLM synthesis.

Usage:
    python -m backend.migrations.001_bm25_index_and_metadata [--dry-run] [--check] [--verbose]
"""

import os
import sys
import time
import argparse
import logging
from typing import Dict, Any, Tuple
import psycopg2
from psycopg2 import extras, sql

# Attempt relative or absolute import of config
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
logger = logging.getLogger("migration_001")


def get_db_connection(params: dict):
    """Establishes a direct connection with autocommit enabled for index creation."""
    try:
        conn = psycopg2.connect(**params)
        conn.autocommit = True
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


def check_status(conn) -> Dict[str, bool]:
    """
    Inspects PostgreSQL system catalogs to determine migration status.
    Returns dictionary with presence of columns and indexes.
    """
    status = {
        "search_vector_column": False,
        "search_vector_index": False,
        "temporal_id_index": False,
        "metrics_id_index": False,
        "content_genres": False,
        "content_studios": False,
        "temporal_episodes": False,
        "metrics_average_score": False,
    }

    with conn.cursor(cursor_factory=extras.DictCursor) as cur:
        # 1. Check search_vector column on anime_content
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'anime_content' AND column_name = 'search_vector';
        """)
        status["search_vector_column"] = cur.fetchone() is not None

        # 2. Check GIN index on search_vector
        cur.execute("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'anime_content' AND indexname = 'idx_anime_content_search_vector';
        """)
        status["search_vector_index"] = cur.fetchone() is not None

        # 3. Check indexes on join tables
        cur.execute("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'anime_temporal' AND indexname = 'idx_anime_temporal_id';
        """)
        status["temporal_id_index"] = cur.fetchone() is not None

        cur.execute("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'anime_metrics' AND indexname = 'idx_anime_metrics_id';
        """)
        status["metrics_id_index"] = cur.fetchone() is not None

        # 4. Check metadata columns exist
        cur.execute("""
            SELECT column_name, table_name 
            FROM information_schema.columns 
            WHERE (table_name = 'anime_content' AND column_name IN ('genres', 'studios'))
               OR (table_name = 'anime_temporal' AND column_name = 'episodes')
               OR (table_name = 'anime_metrics' AND column_name = 'averagescore');
        """)
        for row in cur.fetchall():
            tbl, col = row['table_name'], row['column_name'].lower()
            if tbl == 'anime_content' and col == 'genres':
                status["content_genres"] = True
            elif tbl == 'anime_content' and col == 'studios':
                status["content_studios"] = True
            elif tbl == 'anime_temporal' and col == 'episodes':
                status["temporal_episodes"] = True
            elif tbl == 'anime_metrics' and col == 'averagescore':
                status["metrics_average_score"] = True

    return status


def apply_migration(conn, dry_run: bool = False) -> bool:
    """
    Executes idempotent DDL statements safely.
    Uses IF NOT EXISTS guards to allow multiple re-runs without side effects.
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("Executing Migration 001: BM25 Index & Metadata Hardening")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")
    logger.info("=" * 60)

    pre_status = check_status(conn)
    logger.info(f"Pre-migration catalog status: {pre_status}")

    ddl_statements = [
        (
            "Ensure pgvector extension exists",
            "CREATE EXTENSION IF NOT EXISTS vector;"
        ),
        (
            "Add 'search_vector' tsvector generated column to 'anime_content'",
            """
            ALTER TABLE anime_content
            ADD COLUMN IF NOT EXISTS search_vector tsvector
            GENERATED ALWAYS AS (
                to_tsvector('english', coalesce(description, ''))
            ) STORED;
            """
        ),
        (
            "Build GIN index 'idx_anime_content_search_vector' for BM25 text search",
            """
            CREATE INDEX IF NOT EXISTS idx_anime_content_search_vector
            ON anime_content USING GIN (search_vector);
            """
        ),
        (
            "Ensure index on anime_temporal(id)",
            """
            CREATE INDEX IF NOT EXISTS idx_anime_temporal_id
            ON anime_temporal (id);
            """
        ),
        (
            "Ensure index on anime_metrics(id)",
            """
            CREATE INDEX IF NOT EXISTS idx_anime_metrics_id
            ON anime_metrics (id);
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
        
        all_passed = (
            post_status["search_vector_column"] and
            post_status["search_vector_index"]
        )
        if all_passed:
            total_duration = time.time() - start_time
            logger.info(f"Migration completed successfully in {total_duration:.2f}s.")
            return True
        else:
            logger.error("Migration verification failed: Required database objects not found in catalog.")
            return False
    else:
        logger.info("Dry-run inspection completed. No DDL modifications were applied.")
        return True


def main():
    parser = argparse.ArgumentParser(description="Migration 001: BM25 Index & Metadata Hardening")
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
            print("\nDatabase Migration 001 Status:")
            for k, v in status.items():
                print(f"  - {k}: {'[APPLIED]' if v else '[MISSING]'}")
            is_ready = status["search_vector_column"] and status["search_vector_index"]
            sys.exit(0 if is_ready else 2)

        success = apply_migration(conn, dry_run=args.dry_run)
        sys.exit(0 if success else 1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
