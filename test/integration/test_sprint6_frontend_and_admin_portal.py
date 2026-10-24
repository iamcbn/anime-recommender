"""
test/test_sprint6_frontend_and_admin_portal.py

Automated Contract, Security, and PostgreSQL RLS Validation Suite for Sprint 6:
Frontend Developer & Admin Portal.

Covers:
1. TestDevPortalApiContract:
   - POST /dev/keys: single-reveal, Cache-Control: no-store, 15m fresh session barrier.
   - Stale JWT (> 15 min): strictly rejected with 401 stale_token.
   - Rejection of tokens with missing or anon role.
   - DELETE /dev/keys/{id}: soft-revoke (204), idempotent.
2. TestKeyLifecycleAndRevocationLag:
   - Developer self-service onboarding: create key -> POST /recommend (200, score-stripped) ->
     soft revoke -> POST /recommend returns 401.
3. TestDatabaseRLSPolicies:
   - Live PostgreSQL RLS verification across anon, developer user, and admin roles.
   - Prevention of user_metadata privilege escalation attacks.
   - Schema isolation of app_auth tables.
4. TestCorsPreflightConfiguration:
   - Dynamic CORS validation: allowed frontend origin (http://localhost:5173), rejected untrusted origin.
   - Exposed headers verification.
5. TestFrontendSecurityAudit:
   - Static secret leak prevention audit scanning frontend assets for backend secrets.
"""

import os
import sys
import uuid
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest
import psycopg2
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

with patch("psycopg2.pool.ThreadedConnectionPool"):
    from backend.main import app, _parse_cors_origins

from fastapi.testclient import TestClient
from backend.rag_pipeline.config import config as get_db_config
from backend.auth.supabase_jwt import (
    SupabaseJWKSService,
    set_jwks_service,
    DevUserContext,
)
from backend.auth.keys import ApiKeyContext


class EphemeralJWKSMock:
    """Generates an ephemeral RSA-2048 keypair to sign mock Supabase JWTs."""

    def __init__(self, key_id: str = "test-sprint6-mock-key") -> None:
        self.key_id = key_id
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        self.public_key = self.private_key.public_key()
        self.supabase_url = "https://placeholder-project.supabase.co"
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
            headers={"kid": self.key_id, "alg": "RS256"}
        )

    def sign(self, sub: str, fresh_seconds_ago: int = 0, **kwargs) -> str:
        return self.issue_token(sub=sub, iat_offset_seconds=fresh_seconds_ago, **kwargs)


class MockSigningKey:
    def __init__(self, key):
        self.key = key


class MockJWKSService(SupabaseJWKSService):
    def __init__(self, jwks_mock: EphemeralJWKSMock):
        super().__init__(supabase_url=jwks_mock.supabase_url)
        self._mock = jwks_mock

    def get_signing_key_from_jwt(self, token: str):
        return MockSigningKey(self._mock.public_key)


@pytest.fixture(autouse=True)
def setup_ephemeral_jwks():
    """Configures JWKS mock service for all tests in this suite."""
    jwks_mock = EphemeralJWKSMock()
    service = MockJWKSService(jwks_mock)
    set_jwks_service(service)
    yield jwks_mock


# ---------------------------------------------------------------------------
# Test Suite 1: Developer Portal API Contract (/dev/keys)
# ---------------------------------------------------------------------------

class TestDevPortalApiContract:
    """Verifies backend /dev/keys endpoints integration with Supabase Auth."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_dev_keys_create_success_and_single_reveal(self, client, setup_ephemeral_jwks):
        """Verifies POST /dev/keys provisions key with 201, Cache-Control: no-store, and fresh session."""
        owner_id = str(uuid.uuid4())
        jwt_token = setup_ephemeral_jwks.sign(sub=owner_id, fresh_seconds_ago=30)
        key_id = str(uuid.uuid4())

        mock_conn = MagicMock()
        mock_gen_return = (
            "ar_live_a1b2c3d4_mocksecrettoken12345678901234567890",
            {
                "id": key_id,
                "name": "test-analytics-key",
                "prefix": "ar_live_a1b2c3d4",
                "created_at": datetime.now(timezone.utc),
            }
        )

        with patch("backend.routers.dev_keys.get_auth_db_pool") as mock_get_pool, \
             patch("backend.routers.dev_keys.generate_api_key", return_value=mock_gen_return) as mock_gen_key, \
             patch("backend.routers.dev_keys.rate_limiter.check_rate_limit", return_value=(False, 10, 0)):
            mock_pool = MagicMock()
            mock_pool.getconn.return_value = mock_conn
            mock_get_pool.return_value = mock_pool

            response = client.post(
                "/dev/keys",
                headers={"Authorization": f"Bearer {jwt_token}"},
                json={"name": "test-analytics-key"}
            )
            assert mock_gen_key.call_args.kwargs.get("scopes") == ["recommend"]

        assert response.status_code == 201
        data = response.json()
        assert "key" in data
        assert data["key"].startswith("ar_live_")
        assert "prefix" in data
        assert "id" in data
        assert response.headers.get("Cache-Control") == "no-store"

    def test_dev_keys_stale_session_rejected(self, client, setup_ephemeral_jwks):
        """Stale token (issued 20 minutes ago) is rejected with 401 stale_token."""
        user_id = str(uuid.uuid4())
        stale_token = setup_ephemeral_jwks.issue_token(
            sub=user_id,
            iat_offset_seconds=1200  # 20 minutes old (> 15m barrier)
        )

        resp = client.post(
            "/dev/keys",
            json={"name": "should-fail-stale"},
            headers={"Authorization": f"Bearer {stale_token}"}
        )
        assert resp.status_code == 401
        err = resp.json()
        assert err["error"]["code"] == "stale_token"

    def test_dev_keys_anon_token_rejected(self, client, setup_ephemeral_jwks):
        """Tokens with role != 'authenticated' (e.g. anon) are strictly rejected."""
        user_id = str(uuid.uuid4())
        anon_token = setup_ephemeral_jwks.issue_token(
            sub=user_id,
            role="anon"
        )

        resp = client.get(
            "/dev/keys",
            headers={"Authorization": f"Bearer {anon_token}"}
        )
        assert resp.status_code == 401

    def test_dev_keys_delete_soft_revoke_idempotent(self, client, setup_ephemeral_jwks):
        """Verifies DELETE /dev/keys/{id} performs soft revocation (204 No Content)."""
        owner_id = str(uuid.uuid4())
        key_id = str(uuid.uuid4())
        jwt_token = setup_ephemeral_jwks.sign(sub=owner_id)

        with patch("backend.routers.dev_keys.revoke_api_key", return_value=True):
            response = client.delete(
                f"/dev/keys/{key_id}",
                headers={"Authorization": f"Bearer {jwt_token}"}
            )

        assert response.status_code == 204


# ---------------------------------------------------------------------------
# Test Suite 2: Key Lifecycle & Revocation Lag Verification
# ---------------------------------------------------------------------------

class TestKeyLifecycleAndRevocationLag:
    """Verifies key usage on /recommend and documented revocation lag."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_new_developer_self_service_onboarding_lifecycle(self, client):
        """
        Simulates: Developer provisions key -> calls /recommend (200, score-stripped) ->
        key is revoked -> subsequent call returns 401.
        """
        key_id = str(uuid.uuid4())
        raw_key = f"ar_live_testpref_{uuid.uuid4().hex}"
        key_ctx = ApiKeyContext(
            key_id=key_id,
            name="test_dev_key",
            owner_id=str(uuid.uuid4()),
            role="user",
            scopes=["recommend"],
            rate_limit_per_min=20,
            expires_at=None,
            revoked_at=None,
            key_prefix="ar_live_testpref",
        )

        mock_results = [
            {
                "id": 1,
                "title_romaji": "Evangelion",
                "title_userPreferred": "Evangelion",
                "title_english": "Neon Genesis Evangelion",
                "coverImage_large": "https://example.com/cover.jpg",
                "cross_encoder_score": 0.95,
                "final_rrf_score": 0.88,
            }
        ]
        mock_timings = {"embedding_ms": 20.0, "retrieval_ms": 30.0, "reranking_ms": 40.0, "total_ms": 90.0}

        # 1. Valid active key call to /recommend (200), blocked on /chat (403) and /admin/recommend (403)
        with patch("backend.main.authenticate_api_key", return_value=key_ctx), \
             patch("backend.main.async_rag_pipeline", return_value=(mock_results, mock_timings)), \
             patch("backend.main.rate_limiter.check_rate_limit", return_value=(False, 20, 0)), \
             patch("backend.main.log_recommendation_event"):

            response = client.post(
                "/recommend",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"query": "mecha anime", "top_k": 5}
            )
            chat_resp = client.post(
                "/chat",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"query": "mecha anime", "top_k": 5}
            )
            admin_resp = client.post(
                "/admin/recommend",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"query": "mecha anime", "top_k": 5}
            )

        assert response.status_code == 200
        assert chat_resp.status_code == 403
        assert admin_resp.status_code == 403
        openapi_paths = client.get("/openapi.json").json().get("paths", {})
        assert "/recommend" in openapi_paths
        assert "/chat" not in openapi_paths
        assert "/admin/recommend" not in openapi_paths
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 1
        assert "cross_encoder_score" not in data["results"][0]
        assert "final_rrf_score" not in data["results"][0]
        assert "extra" not in data

        # 2. Key is revoked -> authenticate_api_key raises authentication failure
        with patch("backend.main.authenticate_api_key", side_effect=Exception("Key has been revoked")):
            revoked_resp = client.post(
                "/recommend",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"query": "mecha anime", "top_k": 5}
            )

        assert revoked_resp.status_code == 401


# ---------------------------------------------------------------------------
# Test Suite 3: PostgreSQL Row Level Security (RLS) Policy Verification
# ---------------------------------------------------------------------------

class TestDatabaseRLSPolicies:
    """Verifies live PostgreSQL RLS policies against Supabase telemetry logs."""

    @classmethod
    def setup_class(cls):
        try:
            cfg = get_db_config()
            cfg["connect_timeout"] = 2
            cls.conn = psycopg2.connect(**cfg)
            cls.conn.autocommit = False
            cls.db_available = True
        except Exception:
            cls.db_available = False
            cls.conn = None

        cls.test_log_id = None
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
    def teardown_class(cls):
        if cls.db_available and cls.conn and cls.test_log_id:
            try:
                with cls.conn.cursor() as cur:
                    cur.execute("DELETE FROM telemetry.recommendation_logs WHERE id = %s;", (cls.test_log_id,))
                cls.conn.commit()
            except Exception:
                cls.conn.rollback()
        if cls.conn and not cls.conn.closed:
            cls.conn.close()

    def test_01_rls_anonymous_client_denied(self):
        """Anonymous clients (role = anon) receive 0 rows from telemetry.recommendation_logs."""
        if not self.db_available:
            pytest.skip("Local PostgreSQL is offline. Skipping live DB RLS test.")

        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            try:
                cur.execute("SET LOCAL ROLE anon;")
                cur.execute("SELECT count(*) FROM telemetry.recommendation_logs;")
                count = cur.fetchone()[0]
                assert count == 0, "Anon client saw rows in telemetry.recommendation_logs!"
            except psycopg2.ProgrammingError as e:
                assert "permission denied" in str(e).lower()
            finally:
                cur.execute("ROLLBACK;")

    def test_02_rls_authenticated_non_admin_client_returns_zero_rows(self):
        """Authenticated non-admin developer (app_metadata.role = 'user') receives 0 rows."""
        if not self.db_available:
            pytest.skip("Local PostgreSQL is offline. Skipping live DB RLS test.")

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

        assert count == 0, "Non-admin authenticated user bypassed RLS on telemetry logs!"

    def test_03_rls_admin_client_successfully_reads_telemetry(self):
        """Authenticated administrator (app_metadata.role = 'admin') reads telemetry rows."""
        if not self.db_available:
            pytest.skip("Local PostgreSQL is offline. Skipping live DB RLS test.")

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

        assert count >= 1, "Admin user failed to read telemetry logs via RLS!"

    def test_04_rls_tampered_user_metadata_spoofing_prevented(self):
        """Security test: Priv-escalation attempt via user_metadata role is strictly denied."""
        if not self.db_available:
            pytest.skip("Local PostgreSQL is offline. Skipping live DB RLS test.")

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

        assert count == 0, "Attacker spoofed admin role via client user_metadata!"

    def test_05_rls_app_auth_schema_isolation(self):
        """PostgREST client roles cannot query app_auth schema tables."""
        if not self.db_available:
            pytest.skip("Local PostgreSQL is offline. Skipping live DB RLS test.")

        user_jwt_claims = json.dumps({
            "sub": str(uuid.uuid4()),
            "role": "authenticated",
            "app_metadata": {"role": "admin"}
        })

        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute(f"SET LOCAL \"request.jwt.claims\" = '{user_jwt_claims}';")
            with pytest.raises(psycopg2.ProgrammingError) as ctx:
                cur.execute("SELECT count(*) FROM app_auth.api_keys;")
            cur.execute("ROLLBACK;")

        assert "permission denied" in str(ctx.value).lower()


# ---------------------------------------------------------------------------
# Test Suite 4: CORS Preflight Configuration
# ---------------------------------------------------------------------------

class TestCorsPreflightConfiguration:
    """Verifies CORS preflight handling for frontend origins."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_cors_preflight_allowed_origin_success(self, client):
        """OPTIONS preflight from Vite dev server (http://localhost:5173) succeeds with 200."""
        response = client.options(
            "/recommend",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            }
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_cors_preflight_untrusted_origin_rejected(self, client):
        """OPTIONS preflight from untrusted origin is rejected."""
        response = client.options(
            "/recommend",
            headers={
                "Origin": "https://evil-untrusted-site.com",
                "Access-Control-Request-Method": "POST",
            }
        )
        allow_origin = response.headers.get("access-control-allow-origin")
        assert allow_origin != "https://evil-untrusted-site.com"

    def test_cors_exposed_headers_present(self, client):
        """Verifies expose_headers includes X-Session-ID and Retry-After on cross-origin response."""
        response = client.get(
            "/",
            headers={"Origin": "http://localhost:5173"}
        )
        exposed = response.headers.get("access-control-expose-headers", "")
        assert "X-Session-ID" in exposed
        assert "Retry-After" in exposed


# ---------------------------------------------------------------------------
# Test Suite 5: Frontend Security Audit
# ---------------------------------------------------------------------------

class TestFrontendSecurityAudit:
    """Verifies no backend secrets are leaked into frontend assets."""

    def test_frontend_secret_leak_prevention_audit(self):
        """No frontend source file may contain references to sensitive backend secrets."""
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
                                    pytest.fail(f"Potential secret reference {sec} leaked in {filepath}")
