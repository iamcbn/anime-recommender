# backend/rag_pipeline/helper/llm_cache.py
"""
Shared LLM response cache backed by a local SQLite database.

Behaviour by environment:
  - Local / evaluation: caches HyDE responses to test/data/llm_cache.db
    so that repeated evaluation runs cost  in OpenAI credits.
    Override the location with the LLM_CACHE_PATH environment variable.
  - Production (Modal + Supabase): set DISABLE_LLM_CACHE=true in the Modal
    deployment secrets/config. Every method becomes a no-op - real user
    queries always go to OpenAI as normal.

Why not SQLite in production?
  Modal containers are ephemeral - the local filesystem is wiped on every cold
  start, so a file-based cache provides zero benefit. The correct production
  caching strategy (Redis / Supabase table) is a separate concern.
"""

import os
import json
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# The cache exists for testing/evaluation, so it lives in the test data dir at the
# repo root. Resolved from this file so it is stable regardless of CWD.
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "test" / "data" / "llm_cache.db"


class LLMCache:
    """
    Key-value cache backed by SQLite.
    All methods are no-ops when DISABLE_LLM_CACHE=true (set this in production).
    """

    def __init__(self, db_path: Path = None):
        self._disabled = os.getenv("DISABLE_LLM_CACHE", "false").lower() == "true"
        if self._disabled:
            logger.info("LLM cache disabled (DISABLE_LLM_CACHE=true)")
            self.conn = None
            return

        db_path = Path(db_path or os.getenv("LLM_CACHE_PATH") or _DEFAULT_DB_PATH)
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT)"
            )
            self.conn.commit()
            logger.info(f"LLM cache initialised at {db_path}")
        except Exception:
            # A cache is an optimisation - never let it stop the server from starting.
            logger.warning("LLM cache unavailable; continuing without caching.", exc_info=True)
            self.conn = None

    def get(self, key: str):
        """Return cached value or None if not cached / cache is disabled."""
        if self._disabled or self.conn is None:
            return None
        try:
            cur = self.conn.execute("SELECT value FROM cache WHERE key = ?", (key,))
            row = cur.fetchone()
            return json.loads(row[0]) if row else None
        except Exception:
            logger.warning("LLM cache read failed; treating as cache miss.", exc_info=True)
            return None

    def set(self, key: str, value) -> None:
        """Store a value. Silently skips if cache is disabled or write fails."""
        if self._disabled or self.conn is None:
            return
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
            self.conn.commit()
        except Exception:
            logger.warning("LLM cache write failed; continuing without caching.", exc_info=True)


# Module-level singleton shared by QueryGenerator
llm_cache = LLMCache()
