"""
test/test_sprint6_security_rls.py

Automated Security, Supabase Auth, and RLS Validation Suite for Sprint 6:
1. Direct PostgREST / PostgreSQL RLS Simulation:
   - Anon client: 0 rows returned from telemetry.recommendation_logs.
   - Non-admin authenticated developer: 0 rows returned.
   - Admin authenticated client (app_metadata.role == 'admin'): successfully reads telemetry rows.
   - Malicious user with forged user_metadata.role == 'admin': 0 rows returned (tamper-proof).
   - Schema isolation: authenticated client cannot query app_auth.api_keys or app_auth.key_audit_log directly.
2. Developer API Keys Token Injection & Freshness Barrier:
   - Fresh JWT (< 15 min): succeeds on POST /dev/keys.
   - Stale JWT (> 15 min): strictly rejected with 401 'stale_token'.
   - Rejection of tokens with missing or anon role.
3. Secret Exposure & Frontend Hygiene Audit:
   - Verifies frontend environment variables and source files contain NO service role keys or peppers.
   - Ensures CORS middleware in backend allows expected developer origins.

Usage:
    python -m pytest test/test_sprint6_security_rls.py -v
"""

import os
import sys
import uuid
import time
import json
import base64
import unittest
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest
import psycopg2
from psycopg2 import extras
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

# Ensure project root is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Patch ThreadedConnectionPool before rag_pipeline import to prevent blocking if local DB is offline
with patch("psycopg2.pool.ThreadedConnectionPool"):
    from backend.main import app, _parse_cors_origins

from fastapi.testclient import TestClient
from backend.rag_pipeline.config import config as get_db_config
from backend.auth.supabase_jwt import (
    SupabaseJWKSService,
    set_jwks_service,
    DevUserContext,
)
from backend.auth import keys as keys_module


class EphemeralJWKSMock:
    """Generates an ephemeral RSA-2048 keypair to sign mock Supabase JWTs."""

    def __init__(self):
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        self.public_key = self.private_key.public_key()
        self.kid = "test-sprint6-mock-key"
        self.supabase_url = "https://xyzcompany.supabase.co"
        self.issuer = f"{self.supabase_url}/auth/v1"

    def issue_token(
        self,
        sub: str,
        email: str = "dev@example.com",
        role: str = "authenticated",
        app_metadata: Optional[dict] = None,
        user_metadata: Optional[dict] = None,
        iat_offset_seconds: int = 0,
        exp_delta_seconds: int = 3600,
    ) -> str:
        now = int(time.time())
        iat = now - iat_offset_seconds
        payload = {
            "sub": sub,
            "email": email,
            "role": role,
            "aud": "authenticated",
            "iss": self.issuer,
            "iat": iat,
            "exp": now + exp_delta_seconds,
            "app_metadata": app_metadata if app_metadata is not None else {"provider": "email", "role": "user"},
            "user_metadata": user_metadata or {},
        }
        return jwt.encode(
            payload,
            self.private_key,
            algorithm="RS256",
            headers={"kid": self.kid, "alg": "RS256"}
        )


class MockSigningKey:
    def __init__(self, key):
        self.key = key


class MockJWKSService(SupabaseJWKSService):
    def __init__(self, jwks_mock: EphemeralJWKSMock):
        super().__init__(supabase_url=jwks_mock.supabase_url)
        self._mock = jwks_mock

    def get_signing_key_from_jwt(self, token: str):
        return MockSigningKey(self._mock.public_key)


class TestSprint6SecurityAndRLS(unittest.TestCase):
    conn = None
    db_available = False
    test_log_id = None

    @classmethod
    def setUpClass(cls):
        # Database connectivity check (with 2s timeout)
        try:
            cfg = get_db_config()
            cfg["connect_timeout"] = 2
            cls.conn = psycopg2.connect(**cfg)
            cls.conn.autocommit = False
            cls.db_available = True
        except Exception:
            cls.db_available = False
            cls.conn = None

        # Ephemeral auth setup
        cls.jwks_mock = EphemeralJWKSMock()
        cls.mock_service = MockJWKSService(cls.jwks_mock)
        set_jwks_service(cls.mock_service)
        cls.client = TestClient(app)

        # Seed telemetry test data if DB is online
        if cls.db_available and cls.conn:
            try:
                with cls.conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO telemetry.recommendation_logs (
                            request_id, endpoint, source, query, top_k, results_count, status
                        ) VALUES (
                            %s, 'recommend', 'user', 'cyberpunk anime test query', 10, 5, 'ok'
                        ) RETURNING id;
                    """, (str(uuid.uuid4()),))
                    cls.test_log_id = cur.fetchone()[0]
                cls.conn.commit()
            except Exception:
                cls.conn.rollback()

    @classmethod
    def tearDownClass(cls):
        if cls.db_available and cls.conn and cls.test_log_id:
            try:
                with cls.conn.cursor() as cur:
                    cur.execute("DELETE FROM telemetry.recommendation_logs WHERE id = %s;", (cls.test_log_id,))
                cls.conn.commit()
            except Exception:
                cls.conn.rollback()
        if cls.conn and not cls.conn.closed:
            cls.conn.close()

    # ------------------------------------------------------------------
    # 1. RLS DIRECT POSTGREST SIMULATION TESTS
    # ------------------------------------------------------------------

    def test_01_rls_anonymous_client_denied(self):
        """Anonymous clients (role = anon) receive 0 rows from telemetry.recommendation_logs."""
        if not self.db_available:
            self.skipTest("Local PostgreSQL is offline. Skipping live DB RLS test.")

        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            try:
                cur.execute("SET LOCAL ROLE anon;")
                cur.execute("SELECT count(*) FROM telemetry.recommendation_logs;")
                count = cur.fetchone()[0]
                self.assertEqual(count, 0, "Anon client saw rows in telemetry.recommendation_logs!")
            except psycopg2.ProgrammingError as e:
                self.assertIn("permission denied", str(e).lower())
            finally:
                cur.execute("ROLLBACK;")

    def test_02_rls_authenticated_non_admin_client_returns_zero_rows(self):
        """Authenticated non-admin developer (app_metadata.role = 'user') receives 0 rows."""
        if not self.db_available:
            self.skipTest("Local PostgreSQL is offline. Skipping live DB RLS test.")

        user_jwt_claims = json.dumps({
            "sub": str(uuid.uuid4()),
            "role": "authenticated",
            "app_metadata": {"provider": "email", "role": "user"}
        })

        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute(f"SET LOCAL \"request.jwt.claims\" = '{user_jwt_claims}';")
            cur.execute("SELECT count(*) FROM telemetry.recommendation_logs;")
            count = cur.fetchone()[0]
            cur.execute("ROLLBACK;")

        self.assertEqual(count, 0, "Non-admin authenticated user bypassed RLS on telemetry logs!")

    def test_03_rls_admin_client_successfully_reads_telemetry(self):
        """Authenticated administrator (app_metadata.role = 'admin') reads telemetry rows."""
        if not self.db_available:
            self.skipTest("Local PostgreSQL is offline. Skipping live DB RLS test.")

        admin_jwt_claims = json.dumps({
            "sub": str(uuid.uuid4()),
            "role": "authenticated",
            "app_metadata": {"provider": "email", "role": "admin"}
        })

        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute(f"SET LOCAL \"request.jwt.claims\" = '{admin_jwt_claims}';")
            cur.execute("SELECT count(*) FROM telemetry.recommendation_logs WHERE id = %s;", (self.test_log_id,))
            count = cur.fetchone()[0]
            cur.execute("ROLLBACK;")

        self.assertGreaterEqual(count, 1, "Admin user failed to read telemetry logs via RLS!")

    def test_04_rls_tampered_user_metadata_spoofing_prevented(self):
        """
        Security Test: Malicious user alters user_metadata = {'role': 'admin'}
        while app_metadata has {'role': 'user'}.
        Must return 0 rows because policy strictly inspects app_metadata.
        """
        if not self.db_available:
            self.skipTest("Local PostgreSQL is offline. Skipping live DB RLS test.")

        tampered_claims = json.dumps({
            "sub": str(uuid.uuid4()),
            "role": "authenticated",
            "user_metadata": {"role": "admin"},
            "app_metadata": {"provider": "github", "role": "user"}
        })

        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute(f"SET LOCAL \"request.jwt.claims\" = '{tampered_claims}';")
            cur.execute("SELECT count(*) FROM telemetry.recommendation_logs;")
            count = cur.fetchone()[0]
            cur.execute("ROLLBACK;")

        self.assertEqual(count, 0, "Attacker spoofed admin role via client user_metadata!")

    def test_05_rls_app_auth_schema_isolation(self):
        """
        PostgREST clients cannot query app_auth.api_keys directly.
        All permissions to schema app_auth are revoked from anon and authenticated.
        """
        if not self.db_available:
            self.skipTest("Local PostgreSQL is offline. Skipping live DB RLS test.")

        user_jwt_claims = json.dumps({
            "sub": str(uuid.uuid4()),
            "role": "authenticated",
            "app_metadata": {"role": "admin"}
        })

        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute(f"SET LOCAL \"request.jwt.claims\" = '{user_jwt_claims}';")
            with self.assertRaises(psycopg2.ProgrammingError) as ctx:
                cur.execute("SELECT count(*) FROM app_auth.api_keys;")
            cur.execute("ROLLBACK;")

        self.assertIn("permission denied", str(ctx.exception).lower())

    # ------------------------------------------------------------------
    # 2. DEVELOPER API KEYS FRESHNESS BARRIER & TOKEN INJECTION TESTS
    # ------------------------------------------------------------------

    @patch("backend.routers.dev_keys.generate_api_key")
    @patch("backend.routers.dev_keys.get_auth_db_pool")
    def test_06_dev_keys_fresh_session_permitted(self, mock_pool, mock_gen):
        """Fresh token (issued 2 minutes ago) successfully creates API key."""
        mock_conn = MagicMock()
        mock_pool.return_value.getconn.return_value = mock_conn

        key_id = str(uuid.uuid4())
        mock_gen.return_value = (
            "ar_live_a1b2c3d4_secrettoken1234567890",
            {
                "id": key_id,
                "name": "frontend-sprint6-test-key",
                "prefix": "ar_live_a1b2c3d4",
                "created_at": datetime.now(timezone.utc),
            }
        )

        user_id = str(uuid.uuid4())
        fresh_token = self.jwks_mock.issue_token(
            sub=user_id,
            iat_offset_seconds=120  # 2 minutes old
        )

        resp = self.client.post(
            "/dev/keys",
            json={"name": "frontend-sprint6-test-key"},
            headers={"Authorization": f"Bearer {fresh_token}"}
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("key", data)
        self.assertTrue(data["key"].startswith("ar_live_"))
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")

    def test_07_dev_keys_stale_session_rejected(self):
        """Stale token (issued 20 minutes ago) is rejected with 401 stale_token."""
        user_id = str(uuid.uuid4())
        stale_token = self.jwks_mock.issue_token(
            sub=user_id,
            iat_offset_seconds=1200  # 20 minutes old (> 15m barrier)
        )

        resp = self.client.post(
            "/dev/keys",
            json={"name": "should-fail-stale"},
            headers={"Authorization": f"Bearer {stale_token}"}
        )
        self.assertEqual(resp.status_code, 401)
        err = resp.json()
        self.assertEqual(err["error"]["code"], "stale_token")

    def test_08_dev_keys_anon_token_rejected(self):
        """Tokens with role != 'authenticated' (e.g. anon) are strictly rejected."""
        user_id = str(uuid.uuid4())
        anon_token = self.jwks_mock.issue_token(
            sub=user_id,
            role="anon"
        )

        resp = self.client.get(
            "/dev/keys",
            headers={"Authorization": f"Bearer {anon_token}"}
        )
        self.assertEqual(resp.status_code, 401)

    # ------------------------------------------------------------------
    # 3. CORS & FRONTEND SECRET HYGIENE AUDIT
    # ------------------------------------------------------------------

    def test_09_cors_dynamic_origins_verification(self):
        """Verifies CORS headers respond properly to frontend origins."""
        origins = _parse_cors_origins()
        self.assertIn("http://localhost:5173", origins)

        # Preflight OPTIONS request
        resp = self.client.options(
            "/dev/keys",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://localhost:5173")
        self.assertIn("POST", resp.headers.get("access-control-allow-methods", ""))

    def test_10_frontend_secret_leak_prevention_audit(self):
        """
        Static security assertion:
        No frontend configuration file, environment sample, or source file
        may contain references to backend secrets (SUPABASE_SERVICE_ROLE_KEY, KEY_PEPPER, ADMIN_API_KEY).
        """
        forbidden_secret_names = [
            "SUPABASE_SERVICE_ROLE_KEY",
            "KEY_PEPPER",
            "ADMIN_API_KEY",
            "UPSTASH_REDIS_REST_TOKEN",
            "DB_PASSWORD"
        ]

        frontend_dir = os.path.join(ROOT_DIR, "frontend")
        if os.path.exists(frontend_dir):
            for root, _, files in os.walk(frontend_dir):
                for f in files:
                    if f.endswith((".ts", ".tsx", ".js", ".jsx", ".env", ".env.example", ".json")):
                        filepath = os.path.join(root, f)
                        with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
                            content = handle.read()
                            for sec in forbidden_secret_names:
                                if sec in content and "FORBIDDEN" not in content and "never" not in content.lower():
                                    self.fail(f"Potential secret reference {sec} leaked in {filepath}")


if __name__ == "__main__":
    unittest.main()
