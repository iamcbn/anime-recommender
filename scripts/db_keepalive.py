#!/usr/bin/env python
# scripts/db_keepalive.py
"""
PostgreSQL Free-Tier Keep-Alive & Pre-Flight Liveness Check (Sprint 5).

Executes a lightweight 'SELECT 1' against PostgreSQL with strict connect
and statement timeouts (5s) to:
1. Prevent Supabase free-tier project pausing caused by 7+ days of inactivity.
2. Act as a pre-flight liveness check in GitHub Actions workflows before
   launching heavy Docker containers or data pipeline runs.
3. Prevent GitHub Actions scheduled workflows from being disabled after
   60 days of repo inactivity.

Usage:
    python scripts/db_keepalive.py
    python scripts/db_keepalive.py --timeout 3
"""

import os
import sys
import time
import argparse
import logging
from typing import Dict, Any, Optional

import psycopg2
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("db_keepalive")


def get_keepalive_db_config(timeout_seconds: int = 5) -> Dict[str, Any]:
    """Builds connection parameters with strictly enforced timeouts."""
    host = os.getenv("ARCHIVER_DB_HOST") or os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("ARCHIVER_DB_PORT") or os.getenv("DB_PORT", "5432"))
    database = os.getenv("ARCHIVER_DB_NAME") or os.getenv("DB_NAME", "postgres")
    user = os.getenv("ARCHIVER_DB_USER") or os.getenv("DB_USER", "postgres")
    password = (
        os.getenv("ARCHIVER_DB_PASSWORD")
        if "ARCHIVER_DB_PASSWORD" in os.environ
        else os.getenv("DB_PASSWORD", "")
    )

    default_ssl = "require" if ("pooler" in host or "supabase.co" in host) else "prefer"
    sslmode = os.getenv("ARCHIVER_DB_SSLMODE") or os.getenv("DB_SSLMODE") or default_ssl

    stmt_timeout_ms = timeout_seconds * 1000
    options = f"-c statement_timeout={stmt_timeout_ms} -c timezone=UTC"

    return {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "connect_timeout": timeout_seconds,
        "options": options,
        "sslmode": sslmode,
        "application_name": "db_keepalive_preflight",
    }


def execute_keepalive_query(
    db_config: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 5,
) -> bool:
    """
    Executes 'SELECT 1' against PostgreSQL.
    Returns True on success, raises or returns False on failure.
    """
    cfg = db_config or get_keepalive_db_config(timeout_seconds=timeout_seconds)
    safe_host = cfg.get("host", "unknown")
    safe_port = cfg.get("port", "unknown")
    safe_db = cfg.get("database", "unknown")
    logger.info(f"Executing keep-alive query against {safe_host}:{safe_port}/{safe_db} (timeout: {timeout_seconds}s)...")

    t0 = time.perf_counter()
    conn = None
    try:
        conn = psycopg2.connect(**cfg)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            row = cur.fetchone()
            if not row or row[0] != 1:
                raise RuntimeError(f"Unexpected query result: {row}")

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(f"Keep-alive query succeeded in {elapsed_ms} ms (SELECT 1 == 1).")
        return True
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.error(f"Keep-alive query failed after {elapsed_ms} ms: {exc}")
        raise
    finally:
        if conn is not None and getattr(conn, "closed", 1) == 0:
            try:
                conn.close()
            except Exception:
                pass


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="PostgreSQL Keep-Alive & Liveness Check")
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Connect and statement timeout in seconds (default: 5)",
    )
    args = parser.parse_args(argv)

    try:
        execute_keepalive_query(timeout_seconds=args.timeout)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
