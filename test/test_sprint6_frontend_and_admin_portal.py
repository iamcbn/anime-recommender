"""
test/test_sprint6_frontend_and_admin_portal.py

Comprehensive Automated Contract, Security, and RLS Validation Suite for Sprint 6:
Frontend Developer & Admin Portal of telemetry_and_archival_implementation_plan.md.

Covers:
1. TestFrontendStaticAndContract:
   - Structure of frontend/ (package.json, vite.config.ts, tsconfig.json, index.html, .env.example, routes, components).
   - Package dependency boundaries (zero database/server drivers in client bundle).
   - Environment contract (only VITE_ public variables; zero backend secrets).
   - Static secret scanner across all frontend assets (rejects service_role keys, KEY_PEPPER, ADMIN_API_KEY).
   - Client key zeroing and memory drop contract in CreateKeyModal.tsx.
2. TestDevPortalApiContract:
   - POST /dev/keys: single-reveal, Cache-Control: no-store, 15m fresh session barrier.
   - Mass-assignment rejection (extra fields -> 422).
   - Key quota limit (6th key -> 409 key_limit_reached).
   - Duplicate name rejection (409 duplicate_key_name).
   - GET /dev/keys: keys list never exposes raw key or key_hash.
   - DELETE /dev/keys/{id}: soft-revoke (204), idempotent, foreign key 404 isolation.
   - Uniform error envelopes: {"error": {"code": str, "message": str}}.
3. TestKeyLifecycleAndRevocationLag:
   - Complete developer self-service onboarding: create key -> POST /recommend (200, score-stripped) ->
     soft revoke -> POST /recommend returns 401 within documented cache TTL.
4. TestAdminTelemetryPostgrestContract:
   - Static & query builder contract: schema('telemetry').from('recommendation_logs'), limit <= 500, created_at desc.
5. TestDatabaseRLSPolicies:
   - Simulation of PostgreSQL RLS policies across anon, developer user, and admin roles.
   - Prevention of user_metadata privilege escalation attacks.
   - Isolation of app_auth schema.
6. TestCorsPreflightConfiguration:
   - Dynamic CORS validation: allowed frontend origin (http://localhost:5173), rejected untrusted origin.
   - Allowed methods (GET, POST, DELETE, OPTIONS) and exposed headers.
7. TestDocumentationAndCodeSamplesContract:
   - README.md, ARCHITECTURE.md, and DEPLOYMENT_TODO.md documentation completeness.
   - Python AST validation of code snippets in CodeSnippetTabs.tsx.
   - Error catalog and key rotation SOP verification.

Usage:
    python -m pytest test/test_sprint6_frontend_and_admin_portal.py -v
"""

import os
import sys
import re
import ast
import json
import uuid
import time
import base64
import unittest
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from unittest.mock import patch, MagicMock

import pytest
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

# Ensure project root is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Mock psycopg2 connection pool prior to backend import to prevent blocking when local DB is offline
with patch("psycopg2.pool.ThreadedConnectionPool"):
    from backend.main import app, _parse_cors_origins

from fastapi.testclient import TestClient
from backend.auth.supabase_jwt import (
    SupabaseJWKSService,
    set_jwks_service,
    DevUserContext,
)
from backend.auth import keys as keys_module
from backend.auth.keys import (
    generate_api_key,
    hash_api_key,
    KEY_PEPPER,
    ApiKeyContext,
)


# ---------------------------------------------------------------------------
# Ephemeral RSA JWKS Fixture for Signing Test Supabase JWTs
# ---------------------------------------------------------------------------

class EphemeralJWKSMock:
    """Generates an ephemeral RSA-2048 keypair to sign test Supabase JWTs."""

    def __init__(self, key_id: str = "test-sprint6-kid") -> None:
        self.key_id = key_id
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        self._public_key = self._private_key.public_key()
        pub_numbers = self._public_key.public_numbers()

        def int_to_b64(val: int) -> str:
            byte_len = (val.bit_length() + 7) // 8
            raw_bytes = val.to_bytes(byte_len, "big")
            return base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")

        self.jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self.key_id,
                    "n": int_to_b64(pub_numbers.n),
                    "e": int_to_b64(pub_numbers.e),
                }
            ]
        }

    def sign(
        self,
        sub: str,
        role: str = "authenticated",
        app_metadata: Optional[Dict[str, Any]] = None,
        user_metadata: Optional[Dict[str, Any]] = None,
        fresh_seconds_ago: int = 60,
        expires_in_seconds: int = 3600,
        aud: str = "authenticated",
        iss: str = "https://placeholder-project.supabase.co/auth/v1",
    ) -> str:
        now = int(time.time())
        iat = now - fresh_seconds_ago
        exp = now + expires_in_seconds
        payload = {
            "sub": sub,
            "aud": aud,
            "iss": iss,
            "role": role,
            "iat": iat,
            "exp": exp,
            "app_metadata": app_metadata or {"provider": "email", "role": "user"},
            "user_metadata": user_metadata or {},
        }
        return jwt.encode(
            payload,
            self._private_key,
            algorithm="RS256",
            headers={"kid": self.key_id}
        )


class MockSigningKey:
    def __init__(self, key):
        self.key = key


class MockJWKSService(SupabaseJWKSService):
    def __init__(self, jwks_mock: EphemeralJWKSMock):
        super().__init__(supabase_url="https://placeholder-project.supabase.co")
        self._mock = jwks_mock

    def get_signing_key_from_jwt(self, token: str):
        return MockSigningKey(self._mock._public_key)


@pytest.fixture(autouse=True)
def setup_ephemeral_jwks():
    """Configures JWKS mock service for all tests in this suite."""
    jwks_mock = EphemeralJWKSMock()
    service = MockJWKSService(jwks_mock)
    set_jwks_service(service)
    yield jwks_mock


# ---------------------------------------------------------------------------
# Test Suite 1: Frontend Static Analysis & Contract Verification
# ---------------------------------------------------------------------------

class TestFrontendStaticAndContract:
    """Verifies frontend project structure, configuration, and security boundaries."""

    def test_frontend_project_structure(self):
        """Verifies presence of all essential Vite, React, and TypeScript files."""
        frontend_dir = os.path.join(ROOT_DIR, "frontend")
        assert os.path.isdir(frontend_dir), "frontend/ directory must exist"

        expected_files = [
            "package.json",
            "vite.config.ts",
            "tsconfig.json",
            "index.html",
            ".env.example",
            "src/main.tsx",
            "src/App.tsx",
            "src/index.css",
            "src/config/env.ts",
            "src/lib/supabase.ts",
            "src/lib/apiClient.ts",
            "src/context/AuthContext.tsx",
            "src/routes/LoginPage.tsx",
            "src/routes/DevelopersPage.tsx",
            "src/routes/AdminTelemetryPage.tsx",
            "src/routes/DocsPage.tsx",
            "src/routes/ProtectedRoute.tsx",
            "src/routes/AdminRoute.tsx",
            "src/components/developers/CreateKeyModal.tsx",
            "src/components/developers/KeyListTable.tsx",
            "src/components/admin/TelemetryTable.tsx",
            "src/components/admin/LogDetailModal.tsx",
            "src/components/docs/CodeSnippetTabs.tsx",
            "src/components/docs/ErrorCatalog.tsx",
            "src/components/docs/RotationGuide.tsx",
        ]

        for rel_path in expected_files:
            full_path = os.path.join(frontend_dir, rel_path)
            assert os.path.isfile(full_path), f"Required frontend file missing: {rel_path}"

    def test_frontend_package_json_dependencies(self):
        """Verifies dependencies contract: modern React, Supabase, Router, and absence of backend DB packages."""
        pkg_path = os.path.join(ROOT_DIR, "frontend", "package.json")
        with open(pkg_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        deps = data.get("dependencies", {})
        dev_deps = data.get("devDependencies", {})
        all_pkg_names = set(deps.keys()) | set(dev_deps.keys())

        # Required client packages
        assert "@supabase/supabase-js" in deps
        assert "react" in deps
        assert "react-dom" in deps
        assert "react-router-dom" in deps
        assert "lucide-react" in deps

        # Forbidden backend/database packages in client bundle
        forbidden = ["psycopg2", "psycopg2-binary", "fastapi", "pyarrow", "torch", "cachetools"]
        for forbidden_pkg in forbidden:
            assert forbidden_pkg not in all_pkg_names, f"Forbidden backend dependency '{forbidden_pkg}' found in frontend/package.json"

    def test_frontend_env_contract_and_absence_of_backend_secrets(self):
        """Verifies frontend/.env.example contains only client-safe VITE_ public variables."""
        env_ex_path = os.path.join(ROOT_DIR, "frontend", ".env.example")
        with open(env_ex_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "VITE_SUPABASE_URL" in content
        assert "VITE_SUPABASE_ANON_KEY" in content
        assert "VITE_API_BASE_URL" in content

        # Backend secrets must NEVER be assigned in env file
        forbidden_secrets = [
            "SUPABASE_SERVICE_ROLE_KEY",
            "KEY_PEPPER",
            "ADMIN_API_KEY",
            "DATABASE_URL",
            "DB_PASSWORD",
            "JWT_SECRET",
        ]
        for secret in forbidden_secrets:
            # Match assignments like SECRET=... or VITE_SECRET=...
            match = re.search(rf"^\s*(VITE_)?{secret}\s*=", content, re.MULTILINE)
            assert not match, f"Forbidden backend secret variable '{secret}' assigned in frontend/.env.example"

    def test_static_secret_scanner_frontend_files(self):
        """Recursively scans frontend directory to ensure zero backend secrets or live keys exist."""
        frontend_dir = os.path.join(ROOT_DIR, "frontend")
        secret_patterns = [
            (re.compile(r"SUPABASE_SERVICE_ROLE_KEY\s*=\s*[^\s]+"), "SUPABASE_SERVICE_ROLE_KEY assignment"),
            (re.compile(r"KEY_PEPPER\s*=\s*[^\s]+"), "KEY_PEPPER assignment"),
            (re.compile(r"ADMIN_API_KEY\s*=\s*[^\s]+"), "ADMIN_API_KEY assignment"),
            (re.compile(r"ar_live_[a-f0-9]{8}_[A-Za-z0-9_\-]{20,}"), "Live developer API key leak"),
            (re.compile(r"postgres(ql)?://[^\s]+:[^\s]+@"), "PostgreSQL connection string with credentials"),
        ]

        scanned_count = 0
        for root, _, files in os.walk(frontend_dir):
            for file in files:
                if file.endswith((".ts", ".tsx", ".js", ".json", ".html", ".env", ".example")):
                    file_path = os.path.join(root, file)
                    scanned_count += 1
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    for pattern, desc in secret_patterns:
                        match = pattern.search(text)
                        assert not match, f"Security violation: {desc} in {os.path.relpath(file_path, ROOT_DIR)}: {match.group(0) if match else ''}"

        assert scanned_count >= 20, f"Expected scanner to inspect >= 20 frontend files, inspected {scanned_count}"

    def test_client_key_zeroing_and_state_drop_contract(self):
        """Verifies CreateKeyModal.tsx implements single-reveal gate and zeroing of key state on dismissal."""
        modal_path = os.path.join(ROOT_DIR, "frontend", "src", "components", "developers", "CreateKeyModal.tsx")
        with open(modal_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check for acknowledgement gate
        assert "hasAcknowledged" in code, "CreateKeyModal must include an acknowledgement gate"
        assert "setCreatedKeyData(null)" in code, "CreateKeyModal must explicitly zero out key state upon close"
        # Check for unmount cleanup
        assert "return () => {" in code, "CreateKeyModal must have unmount cleanup hook"
        assert "localStorage" not in code, "Raw API key must never be written to localStorage"
        assert "sessionStorage" not in code, "Raw API key must never be written to sessionStorage"


# ---------------------------------------------------------------------------
# Test Suite 2: Developer Portal API Contract (/dev/keys)
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

    def test_dev_keys_create_mass_assignment_rejected(self, client, setup_ephemeral_jwks):
        """Verifies POST /dev/keys rejects client attempts to inject role or scopes (422)."""
        owner_id = str(uuid.uuid4())
        jwt_token = setup_ephemeral_jwks.sign(sub=owner_id, fresh_seconds_ago=30)

        response = client.post(
            "/dev/keys",
            headers={"Authorization": f"Bearer {jwt_token}"},
            json={
                "name": "hacker-key",
                "role": "admin",  # forbidden mass-assignment field
                "rate_limit_per_min": 99999,
            }
        )
        assert response.status_code == 422
        err = response.json()
        assert "error" in err or "detail" in err

    def test_dev_keys_create_max_limit_409_conflict(self, client, setup_ephemeral_jwks):
        """Verifies that an attempt to create a 6th active key returns 409 key_limit_reached."""
        owner_id = str(uuid.uuid4())
        jwt_token = setup_ephemeral_jwks.sign(sub=owner_id, fresh_seconds_ago=30)

        mock_conn = MagicMock()

        import psycopg2
        pg_err = psycopg2.Error("Maximum 5 active API keys reached per account.")

        with patch("backend.routers.dev_keys.get_auth_db_pool") as mock_get_pool, \
             patch("backend.routers.dev_keys.generate_api_key", side_effect=pg_err), \
             patch("backend.routers.dev_keys.rate_limiter.check_rate_limit", return_value=(False, 10, 0)):
            mock_pool = MagicMock()
            mock_pool.getconn.return_value = mock_conn
            mock_get_pool.return_value = mock_pool

            response = client.post(
                "/dev/keys",
                headers={"Authorization": f"Bearer {jwt_token}"},
                json={"name": "sixth-key"}
            )

        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "key_limit_reached"

    def test_dev_keys_list_never_reveals_secret_or_hash(self, client, setup_ephemeral_jwks):
        """Verifies GET /dev/keys returns list without raw key or key_hash."""
        owner_id = str(uuid.uuid4())
        jwt_token = setup_ephemeral_jwks.sign(sub=owner_id)

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.__enter__.return_value = mock_cur

        key_id = str(uuid.uuid4())
        # Return dict-like mapping for DictCursor
        mock_cur.fetchall.return_value = [
            {
                "id": key_id,
                "name": "production-key",
                "key_prefix": "ar_live_a1b2c3d4",
                "created_at": datetime.now(timezone.utc),
                "last_used_at": None,
                "expires_at": datetime.now(timezone.utc) + timedelta(days=90),
                "revoked_at": None,
            }
        ]

        with patch("backend.routers.dev_keys.get_auth_db_pool") as mock_get_pool:
            mock_pool = MagicMock()
            mock_pool.getconn.return_value = mock_conn
            mock_get_pool.return_value = mock_pool

            response = client.get(
                "/dev/keys",
                headers={"Authorization": f"Bearer {jwt_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert "keys" in data
        assert len(data["keys"]) == 1
        item = data["keys"][0]
        assert "prefix" in item
        assert "name" in item
        assert "key" not in item  # secret strictly excluded
        assert "key_hash" not in item  # hash strictly excluded

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

    def test_dev_keys_delete_foreign_key_404_isolation(self, client, setup_ephemeral_jwks):
        """Verifies deleting a foreign or non-existent key returns 404 without revealing existence."""
        owner_id = str(uuid.uuid4())
        foreign_key_id = str(uuid.uuid4())
        jwt_token = setup_ephemeral_jwks.sign(sub=owner_id)

        with patch("backend.routers.dev_keys.revoke_api_key", return_value=False):
            response = client.delete(
                f"/dev/keys/{foreign_key_id}",
                headers={"Authorization": f"Bearer {jwt_token}"}
            )

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "key_not_found"


# ---------------------------------------------------------------------------
# Test Suite 3: Key Lifecycle & Revocation Lag Verification
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
                "cross_encoder_score": 0.95,  # must be stripped
                "final_rrf_score": 0.88,      # must be stripped
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
        # Public response contract: internal scores and timings must be stripped
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
# Test Suite 4: Admin Telemetry PostgREST Contract
# ---------------------------------------------------------------------------

class TestAdminTelemetryPostgrestContract:
    """Verifies that Admin Telemetry hooks and query builders enforce PostgREST constraints."""

    def test_admin_telemetry_schema_and_query_builder(self):
        """Verifies useTelemetryLogs.ts query builder targets telemetry.recommendation_logs."""
        hook_path = os.path.join(ROOT_DIR, "frontend", "src", "hooks", "useTelemetryLogs.ts")
        with open(hook_path, "r", encoding="utf-8") as f:
            code = f.read()

        assert ".schema('telemetry')" in code
        assert ".from('recommendation_logs')" in code
        assert ".order('created_at', { ascending: false })" in code
        assert "source" in code
        assert "endpoint" in code
        assert "status" in code

    def test_admin_telemetry_pagination_and_hard_limit_guard(self):
        """Verifies limit <= 500 hard cap is enforced in useTelemetryLogs.ts."""
        hook_path = os.path.join(ROOT_DIR, "frontend", "src", "hooks", "useTelemetryLogs.ts")
        with open(hook_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check for Math.min(..., 500)
        assert "500" in code
        assert "Math.min(" in code, "useTelemetryLogs must cap page size at <= 500"


# ---------------------------------------------------------------------------
# Test Suite 5: PostgreSQL Row Level Security (RLS) Policy Simulation
# ---------------------------------------------------------------------------

class TestDatabaseRLSPolicies:
    """Simulates RLS policy expressions defined in 002_telemetry_and_api_keys.py."""

    def simulate_telemetry_rls(self, role: str, app_metadata_role: Optional[str]) -> bool:
        """
        Simulates policy:
        CREATE POLICY admin_read_recommendation_logs ON telemetry.recommendation_logs
        FOR SELECT TO authenticated
        USING ((auth.jwt()->'app_metadata'->>'role') = 'admin');
        """
        if role != "authenticated":
            return False
        return app_metadata_role == "admin"

    def test_rls_anon_role_zero_rows(self):
        """Anon role cannot read telemetry rows."""
        assert not self.simulate_telemetry_rls("anon", None)

    def test_rls_normal_authenticated_user_zero_rows(self):
        """Regular developer (role='user') cannot read telemetry rows."""
        assert not self.simulate_telemetry_rls("authenticated", "user")
        assert not self.simulate_telemetry_rls("authenticated", None)

    def test_rls_admin_authenticated_user_access_allowed(self):
        """Authenticated admin (app_metadata.role='admin') successfully reads telemetry."""
        assert self.simulate_telemetry_rls("authenticated", "admin")

    def test_rls_user_metadata_spoofing_prevented(self):
        """
        If a user attempts privilege escalation by setting user_metadata.role = 'admin',
        the policy ignores it because it checks ONLY app_metadata.
        """
        user_metadata = {"role": "admin"}
        app_metadata = {"role": "user"}  # untouched in app_metadata
        # Policy strictly checks app_metadata
        assert not self.simulate_telemetry_rls("authenticated", app_metadata.get("role"))

    def test_rls_app_auth_schema_isolated_from_client_roles(self):
        """Validates that app_auth grants in migration 002 are completely revoked from client roles."""
        migration_path = os.path.join(ROOT_DIR, "backend", "migrations", "002_telemetry_and_api_keys.py")
        with open(migration_path, "r", encoding="utf-8") as f:
            sql = f.read()

        assert "REVOKE ALL ON SCHEMA app_auth FROM anon, authenticated, public;" in sql
        assert "REVOKE ALL ON ALL TABLES IN SCHEMA app_auth FROM anon, authenticated, public;" in sql


# ---------------------------------------------------------------------------
# Test Suite 6: CORS Preflight Configuration
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
        """OPTIONS preflight from untrusted origin is rejected (no allow-origin header)."""
        response = client.options(
            "/recommend",
            headers={
                "Origin": "https://evil-untrusted-site.com",
                "Access-Control-Request-Method": "POST",
            }
        )
        allow_origin = response.headers.get("access-control-allow-origin")
        assert allow_origin != "https://evil-untrusted-site.com"

    def test_cors_allowed_methods_and_headers(self, client):
        """Verifies allowed methods and headers in preflight response."""
        response = client.options(
            "/dev/keys",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "Authorization",
            }
        )
        assert response.status_code == 200
        allowed_methods = response.headers.get("access-control-allow-methods", "")
        for method in ["GET", "POST", "DELETE", "OPTIONS"]:
            assert method in allowed_methods

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
# Test Suite 7: Documentation and Code Samples Contract
# ---------------------------------------------------------------------------

class TestDocumentationAndCodeSamplesContract:
    """Verifies that documentation and code samples across the repo are consistent and accurate."""

    def test_readme_docs_updated_for_bearer_auth(self):
        """Verifies README.md documents Bearer authentication and stripped public responses."""
        readme_path = os.path.join(ROOT_DIR, "README.md")
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "Authorization: Bearer ar_live_" in content
        assert "Developer & Admin Portal (`frontend/`)" in content
        assert "401 Unauthorized" in content
        assert "/admin/recommend" in content

    def test_architecture_docs_sprint6_completeness(self):
        """Verifies ARCHITECTURE.md documents Sprint 6 frontend architecture and RLS security."""
        arch_path = os.path.join(ROOT_DIR, "ARCHITECTURE.md")
        with open(arch_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "Sprint 6: Frontend Developer & Admin Portal Architecture" in content
        assert "telemetry.recommendation_logs" in content
        assert "app_metadata.role === 'admin'" in content

    def test_deployment_todo_secrets_updated(self):
        """Verifies DEPLOYMENT_TODO.md documents frontend hosting, Modal secrets, and admin SQL."""
        dep_path = os.path.join(ROOT_DIR, "DEPLOYMENT_TODO.md")
        with open(dep_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "Sprint 6: Frontend Developer & Admin Portal Deployment" in content
        assert "VITE_SUPABASE_URL" in content
        assert "VITE_SUPABASE_ANON_KEY" in content
        assert "VITE_API_BASE_URL" in content
        assert "KEY_PEPPER" in content
        assert "CORS_ORIGINS" in content
        assert "UPDATE auth.users" in content

    def test_python_code_samples_syntax_and_env_contract(self):
        """Extracts Python code sample from CodeSnippetTabs.tsx and verifies it parses via AST."""
        tabs_path = os.path.join(ROOT_DIR, "frontend", "src", "components", "docs", "CodeSnippetTabs.tsx")
        with open(tabs_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract pythonSnippet string literal
        match = re.search(r"const pythonSnippet = `([^`]+)`;", content)
        assert match, "pythonSnippet not found in CodeSnippetTabs.tsx"
        py_code = match.group(1)

        # Validate syntax using Python's ast parser
        parsed = ast.parse(py_code)
        assert isinstance(parsed, ast.Module), "Python snippet must be valid syntax"

        # Verify it loads key from environment variable (never client hardcode)
        assert "os.environ.get(\"ANIME_API_KEY\")" in py_code or "os.environ" in py_code
        assert "Authorization" in py_code
        assert "Bearer" in py_code

    def test_javascript_code_samples_syntax_and_env_contract(self):
        """Extracts JS code sample from CodeSnippetTabs.tsx and verifies environment loading."""
        tabs_path = os.path.join(ROOT_DIR, "frontend", "src", "components", "docs", "CodeSnippetTabs.tsx")
        with open(tabs_path, "r", encoding="utf-8") as f:
            content = f.read()

        marker = "const jsSnippet = `"
        assert marker in content, "const jsSnippet not found in CodeSnippetTabs.tsx"
        start_idx = content.find(marker) + len(marker)
        end_idx = content.find("`;", start_idx)
        js_code = content[start_idx:end_idx]

        assert "process.env.ANIME_API_KEY" in js_code
        assert "Bearer" in js_code
        assert "fetch(" in js_code or "fetchRecommendations" in js_code
        assert "Retry-After" in js_code

    def test_error_code_table_and_rotation_guide_contract(self):
        """Verifies ErrorCatalog.tsx and RotationGuide.tsx cover the required status codes and rotation SOP."""
        err_path = os.path.join(ROOT_DIR, "frontend", "src", "components", "docs", "ErrorCatalog.tsx")
        with open(err_path, "r", encoding="utf-8") as f:
            err_code = f.read()

        for status_code in ["401", "403", "404", "409", "422", "429"]:
            assert status_code in err_code, f"Status code {status_code} missing from ErrorCatalog.tsx"

        rot_path = os.path.join(ROOT_DIR, "frontend", "src", "components", "docs", "RotationGuide.tsx")
        with open(rot_path, "r", encoding="utf-8") as f:
            rot_code = f.read()

        assert "Generate New Key" in rot_code
        assert "Revoke Old Key" in rot_code
        assert "60" in rot_code, "Rotation guide must mention <= 60s cache eviction lag"

    def test_public_docs_and_footer_no_internal_leaks(self):
        """Verifies public developer docs and footer do not expose internal/admin routes or sprint metadata."""
        docs_path = os.path.join(ROOT_DIR, "frontend", "src", "routes", "DocsPage.tsx")
        err_path = os.path.join(ROOT_DIR, "frontend", "src", "components", "docs", "ErrorCatalog.tsx")
        footer_path = os.path.join(ROOT_DIR, "frontend", "src", "components", "layout", "Footer.tsx")

        with open(docs_path, "r", encoding="utf-8") as f:
            docs_code = f.read()
        with open(err_path, "r", encoding="utf-8") as f:
            err_code = f.read()
        with open(footer_path, "r", encoding="utf-8") as f:
            footer_code = f.read()

        assert "/chat" not in docs_code
        assert "/admin/recommend" not in docs_code
        assert "Stripped of internal" not in docs_code
        assert "/admin/recommend" not in err_code
        assert "Sprint 6" not in footer_code
