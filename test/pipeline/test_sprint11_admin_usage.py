# test/pipeline/test_sprint11_admin_usage.py
"""
Sprint 11 Task 11.2 Test Suite:
Admin LLM Usage Explorer (/admin/llm-usage) & Budget Guard

Verifies:
1. Admin Authentication Enforcement (401 unauthenticated, 403 non-admin):
   - No token / header -> 401
   - Invalid JWT -> 401
   - Non-admin JWT (app_metadata.role == 'user') -> 403
   - Admin JWT (app_metadata.role == 'admin') -> 200
   - Non-admin API Key (role == 'user') -> 403
   - Admin API Key (role == 'admin') -> 200
2. Data formatting, aggregation, and cost formula:
   - Standard gpt-5.4-mini pricing ($0.15/1M prompt, $0.60/1M completion tokens).
   - Verification of all response fields.
   - Filter query parameters: days and layer.
   - Graceful degradation when database query fails or raises exceptions (returns []).
3. Live Budget Ceilings Endpoint (/admin/llm-usage/current-budget):
   - Returns live status of daily token ceilings for nli, retrieval, and presentation.
   - Verification of current_usage, limit, remaining, soft_limit_hit, hard_limit_hit, usage_ratio.
   - Soft limit trigger at 80% of ceiling.
   - Hard limit trigger at 100% of ceiling.
"""

import os
import sys
import re
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock, patch
from contextlib import contextmanager
import pytest
import httpx
from httpx import ASGITransport

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.main import app
from backend.auth.supabase_jwt import set_jwks_service, DevUserContext
from backend.auth.keys import ApiKeyContext
from backend.rag_pipeline.helper.budget_guard import budget_guard, BudgetGuard, LayerBudgetStatus
from backend.routers.admin_usage import calculate_llm_cost


class MockJWKSService:
    """In-memory mock for Supabase JWKS verification service."""

    def __init__(self):
        self._tokens: Dict[str, DevUserContext] = {}

    def register(self, token: str, user_ctx: DevUserContext):
        self._tokens[token] = user_ctx

    def verify_token(self, token: str, require_fresh: bool = False) -> DevUserContext:
        if not token:
            raise ValueError("Token missing.")
        if "expired" in token.lower():
            raise ValueError("Token has expired.")
        if token in self._tokens:
            return self._tokens[token]
        raise ValueError("Invalid token signature or unknown key identifier.")


@pytest.fixture(autouse=True)
def setup_admin_test_env(monkeypatch):
    """Sets up deterministic authentication and budget guard environment."""
    mock_jwks = MockJWKSService()

    # Register admin user JWT
    admin_user = DevUserContext(
        user_id="admin-user-uuid-1234",
        email="admin@example.com",
        role="admin",
        iat=1700000000,
        app_metadata={"role": "admin"},
    )
    mock_jwks.register("valid-admin-jwt", admin_user)

    # Register non-admin user JWT
    regular_user = DevUserContext(
        user_id="regular-user-uuid-5678",
        email="user@example.com",
        role="user",
        iat=1700000000,
        app_metadata={"role": "user"},
    )
    mock_jwks.register("valid-user-jwt", regular_user)

    set_jwks_service(mock_jwks)

    # Reset in-memory budget guard
    budget_guard.reset()
    budget_guard.limits = {"nli": 100000, "retrieval": 200000, "presentation": 300000}

    # Set admin API key in env
    monkeypatch.setenv("ADMIN_API_KEY", "ar_live_admin_secret_test_key_1234567890")
    monkeypatch.setenv("MY_API_KEY", "ar_live_regular_user_key_1234567890")

    yield mock_jwks

    budget_guard.reset()
    set_jwks_service(None)


@pytest.fixture
def transport():
    return ASGITransport(app=app)


# ============================================================================
# 1. Cost Formula Unit Tests
# ============================================================================

def test_cost_formula_calculation():
    """Verifies standard gpt-5.4-mini pricing ($0.15/1M prompt, $0.60/1M completion)."""
    # 1,000,000 prompt tokens = $0.15
    assert calculate_llm_cost(1_000_000, 0) == 0.15

    # 1,000,000 completion tokens = $0.60
    assert calculate_llm_cost(0, 1_000_000) == 0.60

    # 1,000,000 prompt + 1,000,000 completion = $0.75
    assert calculate_llm_cost(1_000_000, 1_000_000) == 0.75

    # 10,000 prompt + 2,000 completion = 0.0015 + 0.0012 = 0.0027
    assert calculate_llm_cost(10_000, 2_000) == 0.0027

    # 0 tokens = $0.0
    assert calculate_llm_cost(0, 0) == 0.0


# ============================================================================
# 2. Admin Authentication Enforcement Tests
# ============================================================================

@pytest.mark.asyncio
async def test_auth_unauthenticated_requests(transport):
    """Endpoints reject requests without authentication with 401 Unauthorized."""
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /admin/llm-usage/daily
        res1 = await client.get("/admin/llm-usage/daily")
        assert res1.status_code == 401
        assert res1.json()["error"]["code"] == "unauthorized"

        # GET /admin/llm-usage/current-budget
        res2 = await client.get("/admin/llm-usage/current-budget")
        assert res2.status_code == 401
        assert res2.json()["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_auth_invalid_token(transport):
    """Endpoints reject invalid or expired JWT with 401 Unauthorized."""
    headers = {"Authorization": "Bearer invalid-garbage-jwt"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/admin/llm-usage/daily", headers=headers)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_auth_non_admin_jwt_forbidden(transport):
    """Endpoints reject authenticated non-admin users (role='user') with 403 Forbidden."""
    headers = {"Authorization": "Bearer valid-user-jwt"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res1 = await client.get("/admin/llm-usage/daily", headers=headers)
        assert res1.status_code == 403
        assert res1.json()["error"]["code"] == "forbidden"

        res2 = await client.get("/admin/llm-usage/current-budget", headers=headers)
        assert res2.status_code == 403
        assert res2.json()["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_auth_admin_jwt_success(transport):
    """Endpoints grant access to admin users (role='admin' in app_metadata) with 200 OK."""
    headers = {"Authorization": "Bearer valid-admin-jwt"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res1 = await client.get("/admin/llm-usage/current-budget", headers=headers)
        assert res1.status_code == 200
        data1 = res1.json()
        assert "nli" in data1
        assert "retrieval" in data1
        assert "presentation" in data1

        res2 = await client.get("/admin/llm-usage/daily", headers=headers)
        assert res2.status_code == 200
        assert isinstance(res2.json(), list)


@pytest.mark.asyncio
async def test_auth_admin_api_key_env_success(transport):
    """Admin API key via ADMIN_API_KEY environment variable grants access."""
    headers = {"Authorization": "Bearer ar_live_admin_secret_test_key_1234567890"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/admin/llm-usage/current-budget", headers=headers)
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_auth_admin_api_key_db_lookup(transport):
    """Admin API key authenticated via database lookup succeeds if role == 'admin'."""
    admin_ctx = ApiKeyContext(
        key_id="key-uuid-admin",
        name="test_admin_key",
        owner_id="owner-admin",
        role="admin",
        scopes=["recommend", "chat", "admin"],
        rate_limit_per_min=60,
        expires_at=None,
        revoked_at=None,
    )

    with patch("backend.routers.admin_usage.authenticate_api_key", return_value=admin_ctx):
        headers = {"x-api-key": "ar_live_db_admin_key_1234567890123456789012"}
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/admin/llm-usage/current-budget", headers=headers)
            assert res.status_code == 200


@pytest.mark.asyncio
async def test_auth_non_admin_api_key_db_lookup(transport):
    """Non-admin API key from database returns 403 Forbidden."""
    dev_ctx = ApiKeyContext(
        key_id="key-uuid-dev",
        name="test_dev_key",
        owner_id="owner-dev",
        role="user",
        scopes=["recommend", "chat"],
        rate_limit_per_min=60,
        expires_at=None,
        revoked_at=None,
    )

    with patch("backend.routers.admin_usage.authenticate_api_key", return_value=dev_ctx):
        headers = {"x-api-key": "ar_live_db_user_key_1234567890123456789012"}
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/admin/llm-usage/current-budget", headers=headers)
            assert res.status_code == 403
            assert res.json()["error"]["code"] == "forbidden"


# ============================================================================
# 3. Daily Usage Aggregation & Cost Formula Tests
# ============================================================================

@pytest.mark.asyncio
async def test_daily_usage_aggregation_and_formatting(transport):
    """Verifies formatting, calculations, and properties returned by GET /admin/llm-usage/daily."""
    # Mock database rows: (usage_date, layer, request_count, prompt_tokens, completion_tokens, total_tokens, cache_hit_count, fallback_count)
    mock_db_rows = [
        ("2026-10-22", "presentation", 100, 10000, 5000, 15000, 12, 1),
        ("2026-10-22", "retrieval", 80, 8000, 4000, 12000, 5, 0),
        ("2026-10-22", "nli", 60, 3000, 1000, 4000, 20, 2),
    ]

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = mock_db_rows
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    @contextmanager
    def mock_get_conn():
        yield mock_conn

    with patch("backend.telemetry.db.get_telemetry_connection", side_effect=mock_get_conn):
        headers = {"Authorization": "Bearer valid-admin-jwt"}
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/admin/llm-usage/daily?days=7", headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert len(data) == 3

            # Check presentation record
            pres = data[0]
            assert pres["date"] == "2026-10-22"
            assert pres["layer"] == "presentation"
            assert pres["request_count"] == 100
            assert pres["prompt_tokens"] == 10000
            assert pres["completion_tokens"] == 5000
            assert pres["total_tokens"] == 15000
            # Cost = (10000 * 0.15 + 5000 * 0.60) / 1,000,000 = (1500 + 3000) / 1,000,000 = 0.0045
            assert pres["estimated_cost_usd"] == 0.0045
            assert pres["cache_hit_count"] == 12
            assert pres["fallback_count"] == 1

            # Check retrieval record
            ret = data[1]
            assert ret["layer"] == "retrieval"
            assert ret["request_count"] == 80
            # Cost = (8000 * 0.15 + 4000 * 0.60) / 1,000,000 = (1200 + 2400) / 1,000,000 = 0.0036
            assert ret["estimated_cost_usd"] == 0.0036

            # Check nli record
            nli = data[2]
            assert nli["layer"] == "nli"
            assert nli["request_count"] == 60
            # Cost = (3000 * 0.15 + 1000 * 0.60) / 1,000,000 = (450 + 600) / 1,000,000 = 0.00105
            assert nli["estimated_cost_usd"] == 0.00105
            assert nli["cache_hit_count"] == 20
            assert nli["fallback_count"] == 2


@pytest.mark.asyncio
async def test_daily_usage_layer_filtering(transport):
    """Verifies that layer query parameter filters the SQL query."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("2026-10-22", "nli", 15, 1500, 500, 2000, 3, 0)
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    @contextmanager
    def mock_get_conn():
        yield mock_conn

    with patch("backend.telemetry.db.get_telemetry_connection", side_effect=mock_get_conn):
        headers = {"Authorization": "Bearer valid-admin-jwt"}
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/admin/llm-usage/daily?days=7&layer=nli", headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert len(data) == 1
            assert data[0]["layer"] == "nli"

            # Verify executed SQL contains layer condition
            sql_arg, params_arg = mock_cursor.execute.call_args[0]
            assert "LOWER(layer) = %s" in sql_arg
            assert "nli" in params_arg


@pytest.mark.asyncio
async def test_daily_usage_graceful_database_fallback(transport):
    """When database raises an error or table is missing, returns [] gracefully without 500."""
    def broken_conn():
        raise RuntimeError("Postgres database connection timeout or relation does not exist")

    with patch("backend.telemetry.db.get_telemetry_connection", side_effect=broken_conn):
        headers = {"Authorization": "Bearer valid-admin-jwt"}
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/admin/llm-usage/daily", headers=headers)
            assert res.status_code == 200
            assert res.json() == []


# ============================================================================
# 4. Live Budget Ceilings Endpoint Tests
# ============================================================================

@pytest.mark.asyncio
async def test_current_budget_default_status(transport):
    """Verifies default zero-usage budget structure and properties."""
    headers = {"Authorization": "Bearer valid-admin-jwt"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/admin/llm-usage/current-budget", headers=headers)
        assert res.status_code == 200
        data = res.json()

        for layer, limit in [("nli", 100000), ("retrieval", 200000), ("presentation", 300000)]:
            assert layer in data
            entry = data[layer]
            assert entry["layer"] == layer
            assert entry["current_usage"] == 0
            assert entry["limit"] == limit
            assert entry["remaining"] == limit
            assert entry["soft_limit_hit"] is False
            assert entry["hard_limit_hit"] is False
            assert entry["usage_ratio"] == 0.0


@pytest.mark.asyncio
async def test_current_budget_soft_and_hard_limit_triggers(transport):
    """Verifies soft (80%) and hard (100%) limit triggers."""
    # Set NLI to 85,000 tokens (limit=100,000 -> 85% > 80% soft limit)
    budget_guard.set_usage("nli", 85000)

    # Set Retrieval to 210,000 tokens (limit=200,000 -> hard limit exceeded)
    budget_guard.set_usage("retrieval", 210000)

    # Set Presentation to 15,000 tokens (limit=300,000 -> healthy 5%)
    budget_guard.set_usage("presentation", 15000)

    headers = {"Authorization": "Bearer valid-admin-jwt"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/admin/llm-usage/current-budget", headers=headers)
        assert res.status_code == 200
        data = res.json()

        # NLI: soft limit hit, not hard limit
        nli = data["nli"]
        assert nli["current_usage"] == 85000
        assert nli["limit"] == 100000
        assert nli["remaining"] == 15000
        assert nli["soft_limit_hit"] is True
        assert nli["hard_limit_hit"] is False
        assert nli["usage_ratio"] == 0.85

        # Retrieval: hard limit hit, remaining is 0
        ret = data["retrieval"]
        assert ret["current_usage"] == 210000
        assert ret["limit"] == 200000
        assert ret["remaining"] == 0
        assert ret["soft_limit_hit"] is True
        assert ret["hard_limit_hit"] is True
        assert ret["usage_ratio"] == 1.05

        # Presentation: healthy
        pres = data["presentation"]
        assert pres["current_usage"] == 15000
        assert pres["remaining"] == 285000
        assert pres["soft_limit_hit"] is False
        assert pres["hard_limit_hit"] is False
        assert pres["usage_ratio"] == 0.05


# ============================================================================
# 5. Frontend Static Analysis & Contract Verification Tests
# ============================================================================

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")


class TestFrontendSprint11Architecture:
    """Verifies that all required frontend files and contracts exist for Task 11.2."""

    EXPECTED_FILES = [
        "src/types/llmUsage.ts",
        "src/hooks/useLlmUsage.ts",
        "src/components/admin/LlmUsageView.tsx",
        "src/routes/AdminLlmUsagePage.tsx",
    ]

    def test_frontend_files_exist(self):
        for rel_path in self.EXPECTED_FILES:
            full_path = os.path.join(FRONTEND_DIR, rel_path)
            assert os.path.isfile(full_path), f"Frontend file missing: {rel_path}"

    def test_use_llm_usage_hook_contract(self):
        hook_path = os.path.join(FRONTEND_DIR, "src", "hooks", "useLlmUsage.ts")
        with open(hook_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Endpoints called
        assert "/admin/llm-usage/current-budget" in content
        assert "/admin/llm-usage/daily" in content
        # Auth header
        assert "Authorization" in content
        assert "Bearer" in content
        # Filters and state
        assert "selectedLayer" in content
        assert "setDays" in content
        assert "refetch" in content
        assert "summary" in content

    def test_llm_usage_view_contract(self):
        view_path = os.path.join(FRONTEND_DIR, "src", "components", "admin", "LlmUsageView.tsx")
        with open(view_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Top Summary Cards
        assert "Tokens Today" in content
        assert "Est. Cost Today" in content
        assert "Total LLM Requests" in content
        assert "Layer Health Status" in content

        # Live Budget Gauges
        assert "Daily Token Ceilings" in content
        assert "Soft Alert" in content or "Soft limit" in content
        assert "80%" in content

        # Three layers
        assert "nli" in content.lower()
        assert "retrieval" in content.lower()
        assert "presentation" in content.lower()

        # Table headers and badges
        assert "Daily Usage" in content and "Cost Breakdown" in content
        assert "Prompt Tokens" in content
        assert "Completion Tokens" in content
        assert "Cache Hits" in content
        assert "Fallbacks" in content

    def test_app_and_navbar_routing(self):
        # App.tsx route mounting
        app_path = os.path.join(FRONTEND_DIR, "src", "App.tsx")
        with open(app_path, "r", encoding="utf-8") as f:
            app_content = f.read()

        assert "AdminLlmUsagePage" in app_content
        assert "admin/llm-usage" in app_content

        # Navbar.tsx link
        nav_path = os.path.join(FRONTEND_DIR, "src", "components", "layout", "Navbar.tsx")
        with open(nav_path, "r", encoding="utf-8") as f:
            nav_content = f.read()

        assert "/admin/llm-usage" in nav_content
        assert "LLM Usage" in nav_content
        assert "isAdmin" in nav_content

    def test_zero_secrets_in_frontend(self):
        """Scans all new/modified frontend files for leaked credentials."""
        secret_patterns = [
            re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
            re.compile(r"service_role", re.IGNORECASE),
        ]

        for rel_path in self.EXPECTED_FILES + ["src/App.tsx", "src/components/layout/Navbar.tsx"]:
            full_path = os.path.join(FRONTEND_DIR, rel_path)
            with open(full_path, "r", encoding="utf-8") as f:
                code = f.read()
                for pattern in secret_patterns:
                    matches = pattern.findall(code)
                    assert not matches, f"Secret pattern matched in {rel_path}: {matches}"

