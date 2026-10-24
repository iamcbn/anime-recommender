"""
test/pipeline/test_sprint1_hardening.py

Sprint 1 Verification Test Suite:
- AC 1.1: Database Connection Pool Checkout Timeout & Retry Resilience.
- AC 1.2: Decoupled Startup: Module import executes without invoking DDL migrations.
- AC 1.3: Metadata Enrichment: Verification that include_metadata=True returns
          description, genres, studios, averageScore, episodes, seasonYear, etc.
- In-Memory seen_ids Subtraction: Verification that excluded anime IDs are never returned.
"""

import sys
import time
import importlib
import unittest
from unittest.mock import MagicMock, patch, call
from collections import namedtuple
import pandas as pd

# Ensure project root is in sys.path
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from psycopg2.pool import PoolError
from backend.rag_pipeline.helper.retrieval import DatabaseManager
from backend.rag_pipeline.helper.ranking import Ranker


class TestSprint1Hardening(unittest.TestCase):

    # =========================================================================
    # AC 1.1: Database Connection Pool Checkout Timeout & Retry Handling
    # =========================================================================

    def test_ac1_1_pool_saturation_and_timeout(self):
        """
        Simulates pool saturation where getconn() continuously raises PoolError.
        Verifies that get_cursor() retries with backoff and raises TimeoutError
        after the specified timeout period, without hanging indefinitely.
        """
        mock_pool = MagicMock()
        mock_pool.getconn.side_effect = PoolError("connection pool exhausted")

        db_manager = DatabaseManager.__new__(DatabaseManager)
        db_manager._pool = mock_pool
        db_manager.min_conn = 2
        db_manager.max_conn = 10

        t0 = time.monotonic()
        with self.assertRaises(TimeoutError) as ctx:
            with db_manager.get_cursor(timeout=0.15):
                pass
        elapsed = time.monotonic() - t0

        self.assertGreaterEqual(elapsed, 0.15, "Did not wait for the full timeout duration")
        self.assertIn("connection pool checkout timed out", str(ctx.exception).lower())
        self.assertGreater(mock_pool.getconn.call_count, 1, "Should have attempted multiple retries before timing out")

    def test_ac1_1_pool_saturation_recovers_when_connection_released(self):
        """
        Simulates temporary pool saturation that recovers within the timeout window.
        Verifies that get_cursor() successfully acquires the connection on a retry attempt.
        """
        mock_conn = MagicMock()
        mock_conn.closed = 0  # Flag as healthy (not closed)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_pool = MagicMock()
        # Fails twice with PoolError, then succeeds on 3rd attempt
        mock_pool.getconn.side_effect = [
            PoolError("connection pool exhausted"),
            PoolError("connection pool exhausted"),
            mock_conn
        ]

        db_manager = DatabaseManager.__new__(DatabaseManager)
        db_manager._pool = mock_pool
        db_manager.min_conn = 2
        db_manager.max_conn = 10

        with db_manager.get_cursor(timeout=1.0) as cur:
            self.assertEqual(cur, mock_cursor)

        self.assertEqual(mock_pool.getconn.call_count, 3)
        mock_pool.putconn.assert_called_once_with(mock_conn, close=False)

    def test_ac1_1_putconn_closes_broken_connection(self):
        """
        Verifies that broken/closed connections are discarded with close=True
        on pool check-in, preventing corrupted connections from being reused.
        """
        mock_conn = MagicMock()
        mock_conn.closed = 1  # Flag as closed/broken
        mock_conn.cursor.return_value.__enter__.return_value = MagicMock()

        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn

        db_manager = DatabaseManager.__new__(DatabaseManager)
        db_manager._pool = mock_pool
        db_manager.min_conn = 2
        db_manager.max_conn = 10

        with db_manager.get_cursor(timeout=0.5):
            pass

        mock_pool.putconn.assert_called_once_with(mock_conn, close=True)

    # =========================================================================
    # AC 1.2: Decoupled Startup: Module import executes without invoking DDL
    # =========================================================================

    def test_ac1_2_import_rag_pipeline_does_not_execute_ddl(self):
        """
        Verifies that importing or reloading rag_pipeline executes cleanly
        WITHOUT calling retriever.ensure_bm25_index() or executing DDL at module scope.
        """
        with patch.object(DatabaseManager, 'ensure_bm25_index') as mock_ensure_bm25:
            mod_name = "backend.rag_pipeline.rag_pipeline"
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
            else:
                importlib.import_module(mod_name)

            mock_ensure_bm25.assert_not_called()

    # =========================================================================
    # AC 1.3: Metadata Enrichment Verification
    # =========================================================================

    def _create_mock_candidates_df(self):
        """Helper to create a realistic DataFrame simulating merged retrieval results."""
        return pd.DataFrame([
            {
                "id": 152802,
                "title_romaji": "Dark Gathering",
                "title_userPreferred": "Dark Gathering",
                "title_english": "Dark Gathering",
                "coverImage_large": "https://example.com/cover1.jpg",
                "description": "Keitarou Gentouga is a college freshman who hates ghosts...",
                "genres": ["Horror", "Supernatural"],
                "studios": ["OLM"],
                "tags": ["Ghost", "Exorcism"],
                "averageScore": 76.5,
                "seasonYear": 2023,
                "episodes": 25,
                "status": "FINISHED",
                "popularity": 45000,
                "cross_encoder_score": 4.85,
                "final_rrf_score": 0.048,
                "retrieval_rrf_score": 0.048,
            },
            {
                "id": 101,
                "title_romaji": "Mieruko-chan",
                "title_userPreferred": "Mieruko-chan",
                "title_english": "Mieruko-chan",
                "coverImage_large": "https://example.com/cover2.jpg",
                "description": "Miko is a typical high school student whose life turns upside down...",
                "genres": ["Horror", "Comedy"],
                "studios": ["Passione"],
                "tags": ["School", "Monsters"],
                "averageScore": 73.0,
                "seasonYear": 2021,
                "episodes": 12,
                "status": "FINISHED",
                "popularity": 38000,
                "cross_encoder_score": 3.92,
                "final_rrf_score": 0.035,
                "retrieval_rrf_score": 0.035,
            }
        ])

    def test_ac1_3_json_conversion_includes_metadata_when_flag_true(self):
        """
        Verifies that json_conversion(df, include_metadata=True) returns candidate
        dictionaries containing all rich metadata fields for downstream LLM synthesis:
        - description, genres, studios, averageScore, episodes, seasonYear, tags, status.
        """
        ranker = Ranker.__new__(Ranker)
        df = self._create_mock_candidates_df()

        records = ranker.json_conversion(df, include_metadata=True)

        self.assertEqual(len(records), 2)
        first = records[0]

        # Verify Core Display Fields
        self.assertEqual(first["id"], 152802)
        self.assertEqual(first["title_romaji"], "Dark Gathering")
        self.assertIn("cross_encoder_score", first)

        # Verify Enriched Metadata Fields (AC 1.3 requirement)
        self.assertIn("description", first)
        self.assertEqual(first["description"], "Keitarou Gentouga is a college freshman who hates ghosts...")
        self.assertIn("genres", first)
        self.assertEqual(first["genres"], ["Horror", "Supernatural"])
        self.assertIn("studios", first)
        self.assertEqual(first["studios"], ["OLM"])
        self.assertIn("averageScore", first)
        self.assertEqual(first["averageScore"], 76.5)
        self.assertIn("seasonYear", first)
        self.assertEqual(first["seasonYear"], 2023)
        self.assertIn("episodes", first)
        self.assertEqual(first["episodes"], 25)

    def test_ac1_3_json_conversion_backward_compatibility_when_flag_false(self):
        """
        Verifies that json_conversion(df, include_metadata=False) preserves the
        original backward-compatible card structure without metadata bloat.
        """
        ranker = Ranker.__new__(Ranker)
        df = self._create_mock_candidates_df()

        records = ranker.json_conversion(df, include_metadata=False)

        self.assertEqual(len(records), 2)
        first = records[0]

        # Core fields must be present
        self.assertIn("id", first)
        self.assertIn("title_romaji", first)
        self.assertIn("cross_encoder_score", first)

        # Enriched metadata fields must NOT be present
        self.assertNotIn("genres", first)
        self.assertNotIn("studios", first)
        self.assertNotIn("averageScore", first)
        self.assertNotIn("episodes", first)
        self.assertNotIn("seasonYear", first)

    # =========================================================================
    # Verification of In-Memory seen_ids Set Subtraction
    # =========================================================================

    def test_seen_ids_set_subtraction_excludes_specified_anime(self):
        """
        Verifies that merge_deduplicate() filters out all IDs present in seen_ids
        using in-memory O(1) set subtraction, and that list input is coerced to a set.
        """
        ranker = Ranker.__new__(Ranker)

        # Candidate pool contains anime IDs: 152802, 101, 202
        retrieved_list = [
            {"id": 152802, "title_romaji": "Dark Gathering", "description": "Ghost hunting"},
            {"id": 101, "title_romaji": "Mieruko-chan", "description": "Can see ghosts"},
            {"id": 202, "title_romaji": "Ghost Hunt", "description": "Paranormal investigations"},
        ]
        all_results = [retrieved_list]

        # User has already watched or dismissed ID 152802
        seen_ids = {152802}

        df = ranker.merge_deduplicate(all_results, seen_ids=seen_ids)

        returned_ids = set(df["id"].tolist())
        self.assertNotIn(152802, returned_ids, "Excluded ID 152802 must not appear in candidate DataFrame")
        self.assertIn(101, returned_ids)
        self.assertIn(202, returned_ids)
        self.assertEqual(len(df), 2)

        # seen_ids supplied as a python list is coerced to a set and filters identically
        df_from_list = ranker.merge_deduplicate(all_results, seen_ids=[152802, 101])
        self.assertEqual(df_from_list["id"].tolist(), [202])

    def test_seen_ids_subtraction_when_all_candidates_seen(self):
        """
        Verifies that if all retrieved candidates are in seen_ids, an empty DataFrame
        is returned cleanly without crashing.
        """
        ranker = Ranker.__new__(Ranker)

        retrieved_list = [
            {"id": 10, "title_romaji": "Anime X"},
            {"id": 20, "title_romaji": "Anime Y"},
        ]
        all_results = [retrieved_list]

        df = ranker.merge_deduplicate(all_results, seen_ids={10, 20})
        self.assertTrue(df.empty)


if __name__ == "__main__":
    unittest.main()
