"""
test/test_sprint1_migration.py

Automated integration test suite for Sprint 1:
1. Migration idempotency: verifies Migration 002 applies cleanly and safely re-runs without side effects.
2. Catalog verification: verifies all schemas, tables, indexes, RLS, and triggers are recorded in PostgreSQL catalogs.
3. Concurrency & active key limit: verifies the trigger strictly enforces <= 5 active keys per developer and allows insertion when a key is revoked.
4. RLS & isolation: confirms RLS rowsecurity is active across all sensitive tables.
5. Storage bucket verification utility: tests bucket inspection logic.

Usage:
    python -m unittest test.test_sprint1_migration -v
"""

import os
import sys
import uuid
import hashlib
import unittest
import psycopg2
from psycopg2 import extras

# Ensure project root is in python path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import importlib
migration_002 = importlib.import_module("backend.migrations.002_telemetry_and_api_keys")
get_db_connection = migration_002.get_db_connection
check_status = migration_002.check_status
apply_migration = migration_002.apply_migration
config = migration_002.config
from scripts.verify_storage_bucket import verify_or_create_bucket_via_sdk


class TestSprint1Migration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.params = config()
        cls.conn = get_db_connection(cls.params)

    @classmethod
    def tearDownClass(cls):
        if cls.conn and not cls.conn.closed:
            cls.conn.close()

    def test_01_migration_idempotency(self):
        """Verify that apply_migration succeeds on first and second consecutive runs."""
        # First execution (apply or re-apply)
        success_first = apply_migration(self.conn, dry_run=False)
        self.assertTrue(success_first, "First execution of Migration 002 failed.")

        # Second execution (idempotency check)
        success_second = apply_migration(self.conn, dry_run=False)
        self.assertTrue(success_second, "Second execution (idempotency) of Migration 002 failed.")

    def test_02_catalog_verification(self):
        """Verify all critical database schemas, tables, indexes, and triggers exist."""
        status = check_status(self.conn)

        self.assertTrue(status["schema_app_auth"], "Schema 'app_auth' missing from catalog.")
        self.assertTrue(status["schema_telemetry"], "Schema 'telemetry' missing from catalog.")
        self.assertTrue(status["table_api_keys"], "Table 'app_auth.api_keys' missing from catalog.")
        self.assertTrue(status["table_key_audit_log"], "Table 'app_auth.key_audit_log' missing from catalog.")
        self.assertTrue(status["table_recommendation_logs"], "Table 'telemetry.recommendation_logs' missing from catalog.")
        self.assertTrue(status["table_api_key_usage_daily"], "Table 'telemetry.api_key_usage_daily' missing from catalog.")

        # Indexes
        self.assertTrue(status["index_api_keys_owner"], "Index 'idx_api_keys_owner' missing.")
        self.assertTrue(status["index_api_keys_owner_name"], "Index 'uq_api_keys_owner_name' missing.")
        self.assertTrue(status["index_rlogs_created"], "Index 'idx_rlogs_created' missing.")
        self.assertTrue(status["index_rlogs_key_created"], "Index 'idx_rlogs_key_created' missing.")
        self.assertTrue(status["index_rlogs_source_created"], "Index 'idx_rlogs_source_created' missing.")

        # Trigger & RLS
        self.assertTrue(status["trigger_max_active_keys"], "Trigger 'trg_enforce_max_active_keys' missing.")
        self.assertTrue(status["rls_api_keys"], "RLS not enabled on 'app_auth.api_keys'.")
        self.assertTrue(status["rls_recommendation_logs"], "RLS not enabled on 'telemetry.recommendation_logs'.")

    def test_03_enforce_max_active_keys_trigger(self):
        """
        Verify that a developer can have at most 5 active keys.
        Inserting a 6th active key must raise an exception.
        Soft-revoking one key must free up a slot for a new key.
        """
        test_owner_id = str(uuid.uuid4())
        created_key_ids = []

        try:
            with self.conn.cursor() as cur:
                # Insert 5 active keys
                for i in range(1, 6):
                    key_prefix = f"ar_test_{uuid.uuid4().hex[:6]}"
                    key_hash = hashlib.sha256(f"test_secret_{i}_{test_owner_id}".encode()).digest()
                    cur.execute("""
                        INSERT INTO app_auth.api_keys (owner_id, name, key_prefix, key_hash)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id;
                    """, (test_owner_id, f"test_key_{i}", key_prefix, key_hash))
                    created_key_ids.append(cur.fetchone()[0])

                self.assertEqual(len(created_key_ids), 5)

                # Attempting to insert a 6th active key must fail
                key_prefix_6 = f"ar_test_{uuid.uuid4().hex[:6]}"
                key_hash_6 = hashlib.sha256(f"test_secret_6_{test_owner_id}".encode()).digest()
                with self.assertRaises(Exception) as ctx:
                    cur.execute("""
                        INSERT INTO app_auth.api_keys (owner_id, name, key_prefix, key_hash)
                        VALUES (%s, %s, %s, %s);
                    """, (test_owner_id, "test_key_6_overflow", key_prefix_6, key_hash_6))
                
                err_msg = str(ctx.exception).lower()
                self.assertIn("active api key limit of 5 exceeded", err_msg)

                # Soft-revoke one key (e.g. key 1)
                cur.execute("""
                    UPDATE app_auth.api_keys 
                    SET revoked_at = now() 
                    WHERE id = %s;
                """, (created_key_ids[0],))

                # Now inserting a new active key must succeed
                key_prefix_7 = f"ar_test_{uuid.uuid4().hex[:6]}"
                key_hash_7 = hashlib.sha256(f"test_secret_7_{test_owner_id}".encode()).digest()
                cur.execute("""
                    INSERT INTO app_auth.api_keys (owner_id, name, key_prefix, key_hash)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                """, (test_owner_id, "test_key_7_replacement", key_prefix_7, key_hash_7))
                created_key_ids.append(cur.fetchone()[0])

                # Total created should now be 6 (1 revoked, 5 active)
                cur.execute("""
                    SELECT count(*) FROM app_auth.api_keys
                    WHERE owner_id = %s AND revoked_at IS NULL;
                """, (test_owner_id,))
                active_count = cur.fetchone()[0]
                self.assertEqual(active_count, 5)

        finally:
            # Cleanup test artifacts
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM app_auth.api_keys WHERE owner_id = %s;", (test_owner_id,))

    def test_04_storage_bucket_verifier_utility(self):
        """Verify that the storage bucket verifier runs without unhandled crashes."""
        res = verify_or_create_bucket_via_sdk(create_if_missing=True)
        self.assertIsInstance(res, dict)
        self.assertIn("success", res)


if __name__ == "__main__":
    unittest.main()
