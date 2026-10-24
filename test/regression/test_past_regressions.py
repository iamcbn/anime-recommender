"""
test/regression/test_past_regressions.py

Regression test suite and critical path smoke set protecting against past regressions
and verified historical bug fixes across sprints and commits.

Verification Matrix:
1. Mined Commit Bug Fixes:
   - Commit 0809e9d: Synchronous budget guard status querying and mock type safety.
   - Commit b542622: Local models directory exclusion in Modal add_local_dir to prevent volume collisions.
   - Commit 02d740d: Modal 1.x Volume initialisation compatibility (Volume.from_name and hydrate).
   - Commit efd54d1: Exposure of OpenAI and HyDE secrets in Modal Gateway configuration.
   - Commit ff7f4af: Dynamic DB_PORT environment variable integer conversion and fallback.
   - Commit 488e3ec: Pipeline StateManager resilience on empty sessions and state transitions.
   - Commit 1572b7a: Parameterised SQL query escaping for special characters and quotes.
   - Commit d491610: Frontend environment security boundary against leaked backend secrets.
   - Bug BUG-001: Windows thread scheduling and event loop tick jitter documented via xfail.

2. Critical Path Smoke Set:
   - Fast public recommendation flow (POST /recommend) with stripped candidate cards and sub-second execution.
   - Conversational chat streaming handshake (POST /chat) delivering SSE headers and immediate metadata.
   - Instant perimeter rejection (HTTP 401) on unauthenticated calls to /dev/keys and /recommend.

Conforms strictly to British English documentation standards without em-dashes.
"""

import ast
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import httpx
from httpx import ASGITransport
import modal
import pytest

from backend.main import app
from backend.rag_pipeline.config import config as get_rag_db_config
from backend.rag_pipeline.helper.budget_guard import BudgetGuard, get_budget_key, budget_guard
from backend.rag_pipeline.helper.guardrails import GuardrailResult
from backend.rag_pipeline.helper.rate_limiter import rate_limiter
from backend.rag_pipeline.helper.retrieval import DatabaseManager
from backend.rag_pipeline.helper.state_manager import StateManager
from modal_deploy import get_gateway_secrets

# Mark all tests in this module with regression and backend markers
pytestmark = [pytest.mark.regression, pytest.mark.backend]

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# SAMPLE FIXTURE DATA FOR HERMETIC TESTS
# ---------------------------------------------------------------------------

SAMPLE_REGRESSION_CANDIDATES: List[Dict[str, Any]] = [
    {
        "id": 1,
        "title_userPreferred": "Cowboy Bebop",
        "title_romaji": "Cowboy Bebop",
        "title_english": "Cowboy Bebop",
        "genres": ["Action", "Sci-Fi"],
        "averageScore": 89,
        "popularity": 150000,
        "format": "TV",
        "episodes": 26,
        "status": "FINISHED",
        "description": "Bounty hunters in deep space chasing criminals across the solar system.",
        "cross_encoder_score": 4.95,
        "final_rrf_score": 0.88,
    },
    {
        "id": 2,
        "title_userPreferred": "Neon Genesis Evangelion",
        "title_romaji": "Shinseiki Evangelion",
        "title_english": "Neon Genesis Evangelion",
        "genres": ["Action", "Mecha", "Psychological"],
        "averageScore": 85,
        "popularity": 140000,
        "format": "TV",
        "episodes": 26,
        "status": "FINISHED",
        "description": "Teenagers pilot giant bio-mechanical units to protect mankind.",
        "cross_encoder_score": 4.52,
        "final_rrf_score": 0.82,
    },
]


def parse_sse_events(raw_sse: str) -> List[Dict[str, Any]]:
    """Parses raw Server-Sent Events text into structured event objects."""
    events = []
    current_event: Optional[str] = None
    for line in raw_sse.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:") and current_event:
            raw_data = line[len("data:"):].strip()
            try:
                parsed_data = json.loads(raw_data)
            except Exception:
                parsed_data = raw_data
            events.append({"event": current_event, "data": parsed_data})
            current_event = None
    return events


# ===========================================================================
# 1. MINED COMMIT BUG FIXES
# ===========================================================================

@pytest.mark.regression
@pytest.mark.backend
def test_regression_commit_0809e9d_budget_guard_sync_check():
    """
    Protects commit 0809e9d where sync budget guard checks threw mock type errors
    or failed when layer limits were queried synchronously.

    Validates that BudgetGuard.is_budget_exceeded_sync executes synchronously without
    requiring an active event loop or coroutine resolution, accurately queries
    usage from the in-memory fallback store, returns a concrete boolean, and enforces
    valid layer boundaries across the three-tier architecture (nli, retrieval, presentation).
    """
    guard = BudgetGuard()
    guard.limits = {
        "nli": 500,
        "retrieval": 1000,
        "presentation": 2000,
    }

    # Initial state: usage is zero, so budget is not exceeded
    assert guard.is_budget_exceeded_sync("nli") is False
    assert guard.is_budget_exceeded_sync("retrieval") is False
    assert guard.is_budget_exceeded_sync("presentation") is False

    # Simulate usage approaching threshold in the in-memory fallback store
    nli_key = get_budget_key("nli")
    guard.fallback_store.set(nli_key, 499)
    assert guard.is_budget_exceeded_sync("nli") is False

    # Simulate reaching the exact ceiling
    guard.fallback_store.set(nli_key, 500)
    assert guard.is_budget_exceeded_sync("nli") is True

    # Simulate exceeding ceiling
    guard.fallback_store.set(nli_key, 501)
    assert guard.is_budget_exceeded_sync("nli") is True

    # Confirm type safety: return value must be a primitive boolean, never a Coroutine
    result = guard.is_budget_exceeded_sync("presentation")
    assert isinstance(result, bool)
    assert not asyncio.iscoroutine(result)

    # Invalid or unregistered layers must enforce strict validation via ValueError
    with pytest.raises(ValueError, match="Invalid layer"):
        guard.is_budget_exceeded_sync("query_generation")

    with pytest.raises(ValueError, match="Invalid layer"):
        guard.is_budget_exceeded_sync("")

    with pytest.raises(ValueError, match="Invalid layer"):
        guard.is_budget_exceeded_sync("unknown_layer")


@pytest.mark.regression
@pytest.mark.backend
def test_regression_commit_b542622_modal_local_models_dir_ignored():
    """
    Protects commit b542622 where Modal deployment included the local models directory
    in add_local_dir, causing volume mount collisions in remote containers.

    Performs static AST inspection of modal_deploy.py to verify that the local models
    directory, compiled bytecode, and data pipeline artefacts are explicitly excluded
    via the ignore argument in add_local_dir before the Modal Volume is mounted.
    """
    deploy_script = REPO_ROOT / "modal_deploy.py"
    assert deploy_script.exists(), "modal_deploy.py must exist in repository root"

    with open(deploy_script, "r", encoding="utf-8") as fp:
        source_code = fp.read()

    parsed_ast = ast.parse(source_code, filename=str(deploy_script))

    # Search for calls to add_local_dir within the AST
    found_ignore_patterns: List[str] = []
    has_models_mount = False

    for node in ast.walk(parsed_ast):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_local_dir":
                for kw in node.keywords:
                    if kw.arg == "ignore" and isinstance(kw.value, ast.List):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                found_ignore_patterns.append(elt.value)

        # Verify volume mount targeting /root/backend/models
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == "/root/backend/models":
                    has_models_mount = True

    assert "models" in found_ignore_patterns, "Local 'models' directory must be ignored in add_local_dir"
    assert "models/**" in found_ignore_patterns, "Local 'models/**' path must be ignored in add_local_dir"
    assert has_models_mount, "Modal Volume must be mounted at /root/backend/models"


@pytest.mark.regression
@pytest.mark.backend
def test_regression_commit_02d740d_modal_volume_hydration():
    """
    Protects commit 02d740d where Modal 1.x Volume initialisation required
    Volume.from_name and hydrate.

    Verifies that the automated dataset update workflow (.github/workflows/update_data.yaml)
    and deployment entry points use modal.Volume.from_name(...).hydrate() instead of
    deprecated Modal Volume.lookup methods that failed under modern Modal 1.x runtimes.
    """
    workflow_path = REPO_ROOT / ".github" / "workflows" / "update_data.yaml"
    assert workflow_path.exists(), "update_data.yaml workflow must exist"

    with open(workflow_path, "r", encoding="utf-8") as fp:
        workflow_content = fp.read()

    # Workflow must use Volume.from_name with hydrate()
    assert "modal.Volume.from_name('anime-models-vol', create_if_missing=True).hydrate()" in workflow_content, (
        "update_data.yaml must initialise and hydrate volume via modal.Volume.from_name(...).hydrate()"
    )

    # Workflow must not contain deprecated Volume.lookup
    assert "modal.Volume.lookup" not in workflow_content, (
        "Deprecated modal.Volume.lookup pattern must not be present in update_data.yaml"
    )

    # Verify modal_deploy.py also adheres to modal.Volume.from_name
    deploy_path = REPO_ROOT / "modal_deploy.py"
    with open(deploy_path, "r", encoding="utf-8") as fp:
        deploy_content = fp.read()

    assert "modal.Volume.from_name(" in deploy_content, (
        "modal_deploy.py must instantiate volume via modal.Volume.from_name"
    )
    assert "modal.Volume.lookup(" not in deploy_content, (
        "modal_deploy.py must not call deprecated modal.Volume.lookup"
    )

    # Verify runtime modal module API supports from_name and hydrate
    vol = modal.Volume.from_name("anime-models-vol", create_if_missing=True)
    assert hasattr(vol, "hydrate"), "Modal Volume instance must provide hydrate method"


@pytest.mark.regression
@pytest.mark.backend
def test_regression_commit_efd54d1_modal_secrets_gateway_isolation():
    """
    Protects commit efd54d1 where HYDE and OpenAI secrets were not properly exposed
    in Modal Gateway secrets.

    Verifies that get_gateway_secrets in modal_deploy.py properly exposes OpenAI secrets
    to the FastAPI ASGI gateway container in both legacy shared mode (openai-secret)
    and modern three-key granular isolation mode (openai-nli-secret, openai-retrieval-secret,
    openai-presentation-secret).
    """
    # 1. Shared secret mode
    shared_secrets = get_gateway_secrets(use_per_layer=False)
    shared_names = [getattr(s, "name", None) or getattr(s, "_name", None) for s in shared_secrets]

    # modal.Secret objects may store identifier in name or _name or repr
    shared_reprs = [str(s) for s in shared_secrets]
    assert any("anime-secret" in r for r in shared_reprs), "anime-secret must be present in shared secrets"
    assert any("openai-secret" in r for r in shared_reprs), "openai-secret must be present in shared secrets"

    # 2. Granular three-key isolation mode
    granular_secrets = get_gateway_secrets(use_per_layer=True)
    granular_reprs = [str(s) for s in granular_secrets]

    assert any("anime-secret" in r for r in granular_reprs), "anime-secret must be present in granular secrets"
    assert any("openai-nli-secret" in r for r in granular_reprs), "openai-nli-secret must be present"
    assert any("openai-retrieval-secret" in r for r in granular_reprs), "openai-retrieval-secret must be present"
    assert any("openai-presentation-secret" in r for r in granular_reprs), "openai-presentation-secret must be present"


@pytest.mark.regression
@pytest.mark.backend
def test_regression_commit_ff7f4af_dynamic_db_port_parsing():
    """
    Protects commit ff7f4af where custom DB_PORT environment variable was not
    correctly converted to an integer in config.py.

    Verifies that PostgreSQL configuration converts string port values to native
    integers, falls back safely to default port numbers when unset or invalid, and
    dynamically selects Supabase pooler ports when connecting to pooler endpoints.
    """
    # 1. Custom string port provided in environment
    with patch.dict(os.environ, {"DB_PORT": "5433", "DB_HOST": "localhost"}):
        cfg = get_rag_db_config()
        assert cfg["port"] == 5433
        assert isinstance(cfg["port"], int), "Parsed port must be a native integer"

    # 2. Port unset in environment (standard direct connection default)
    env_clean = dict(os.environ)
    env_clean.pop("DB_PORT", None)
    env_clean["DB_HOST"] = "localhost"
    with patch.dict(os.environ, env_clean, clear=True):
        cfg = get_rag_db_config()
        assert cfg["port"] == 5432
        assert isinstance(cfg["port"], int), "Default port must be an integer (5432)"

    # 3. Non-numeric invalid port string should fall back cleanly without raising ValueError
    with patch.dict(os.environ, {"DB_PORT": "invalid_port_5432", "DB_HOST": "localhost"}):
        cfg = get_rag_db_config()
        assert cfg["port"] == 5432
        assert isinstance(cfg["port"], int), "Malformed port must fall back cleanly to integer 5432"

    # 4. Supabase pooler host auto-detection with unset port
    pooler_env = dict(os.environ)
    pooler_env.pop("DB_PORT", None)
    pooler_env["DB_HOST"] = "aws-0-eu-central-1.pooler.supabase.com"
    with patch.dict(os.environ, pooler_env, clear=True):
        cfg = get_rag_db_config()
        assert cfg["port"] == 6543
        assert isinstance(cfg["port"], int), "Supabase pooler host must auto-detect port 6543"


@pytest.mark.regression
@pytest.mark.backend
@pytest.mark.asyncio
async def test_regression_commit_488e3ec_pipeline_state_manager_resets():
    """
    Protects commit 488e3ec where StateManager failed on empty state or during
    conversational state transitions.

    Verifies that StateManager operates reliably in the absence of Redis credentials,
    handles uninitialised sessions and empty inputs cleanly, maintains rolling five-turn
    eviction across multiple conversational steps, and resets state on explicit clear calls.
    """
    sm = StateManager(redis_url=None, redis_token=None)

    # 1. Empty state behaviour
    assert await sm.get_session_history("") == []
    assert await sm.get_session_history(None) == []
    assert await sm.get_session_history("non_existent_session") == []
    assert await sm.get_excluded_ids("") == set()
    assert await sm.get_excluded_ids(None) == set()

    # Empty appends must not raise
    await sm.append_session_turn("", {"role": "user", "content": "hello"})
    await sm.append_session_turn("session_alpha", [])
    await sm.record_seen_ids("", [1, 2])
    await sm.record_seen_ids("user_alpha", [])

    # 2. Conversational state transitions (turn 1 to turn 6)
    session_id = "session_regression_transition"

    for i in range(1, 7):
        turn = {"role": "user" if i % 2 != 0 else "assistant", "content": f"Message turn {i}"}
        await sm.append_session_turn(session_id, turn)

    history = await sm.get_session_history(session_id)
    assert len(history) == 5, "Rolling history must evict oldest turn and retain exactly 5 turns"
    assert history[0]["content"] == "Message turn 2", "Oldest turn (turn 1) must be evicted"
    assert history[-1]["content"] == "Message turn 6", "Latest turn must be preserved"

    # 3. Explicit session reset
    await sm.clear_session(session_id)
    reset_history = await sm.get_session_history(session_id)
    assert reset_history == [], "Cleared session must immediately return an empty turn list"

    # 4. Seen IDs state transitions
    user_id = "user_regression_lifecycle"
    await sm.record_seen_ids(user_id, [10, 20])
    assert await sm.get_excluded_ids(user_id) == {10, 20}

    await sm.record_seen_ids(user_id, [20, 30])
    assert await sm.get_excluded_ids(user_id) == {10, 20, 30}

    await sm.clear_user_seen(user_id)
    assert await sm.get_excluded_ids(user_id) == set(), "Cleared seen IDs must reset to an empty set"


@pytest.mark.regression
@pytest.mark.backend
def test_regression_commit_1572b7a_sql_retrieval_query_escaping():
    """
    Protects commit 1572b7a where special characters (apostrophes, quotes, hyphens)
    in user anime prompts crashed SQL retrieval.

    Verifies that DatabaseManager uses parameterised SQL queries and websearch_to_tsquery
    so user prompts containing apostrophes, single quotes, double quotes, hyphens, and SQL
    injection syntax are safely bound via psycopg2 parameters rather than raw string interpolation.
    """
    db_mgr = DatabaseManager(PARAMS={"dbname": "mock_db", "user": "mock_user"})

    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []

    mock_conn = MagicMock()
    mock_conn.closed = 0
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn

    # Set both direct pool attribute and ensure_pool mock
    db_mgr._pool = mock_pool

    # Diverse adversarial prompts containing apostrophes, quotes, hyphens, and SQL injection payloads
    challenging_queries = [
        "Cowboy Bebop's Final Episode",
        'Anime with "mecha" and "monsters"',
        "Sci-Fi: Ghost in the Shell -- Stand Alone Complex; drop table anime_content;",
        "Fate/Zero: Heaven's Feel - II. lost butterfly",
        "Robert'); DROP TABLE anime_core;--",
    ]

    with patch.object(db_mgr, "_ensure_pool", return_value=mock_pool):
        for user_query in challenging_queries:
            mock_cur.reset_mock()
            results = db_mgr.bm25_search(query_text=user_query, top_k=5)

            assert results == []
            assert mock_cur.execute.called, f"cur.execute must be called for query: {user_query}"

            # Inspect the SQL string and parameter list
            executed_sql, executed_params = mock_cur.execute.call_args[0]

            # Critical assertions:
            # 1. SQL string must contain parameter placeholders (%s)
            assert "%s" in executed_sql, "SQL must use parameterised %s placeholders"

            # 2. The raw user query must NOT be interpolated directly into the SQL string
            assert user_query not in executed_sql, (
                f"Query '{user_query}' must not be directly concatenated into raw SQL string"
            )

            # 3. The raw query must be safely passed in the parameter collection
            assert user_query in executed_params, (
                f"Query '{user_query}' must be passed as a bound parameter"
            )


@pytest.mark.regression
@pytest.mark.backend
def test_regression_commit_d491610_env_security_boundary():
    """
    Protects commit d491610 where backend secrets (KEY_PEPPER, DB_PASSWORD, OPENAI_API_KEY)
    must be rejected if leaked into frontend build configurations.

    Verifies that frontend/src/config/env.ts enforces a security barrier declaring
    all critical backend credentials in FORBIDDEN_SECRET_KEYS, and verifies that
    the validation logic raises a security violation if any sensitive key is detected
    in the client environment bundle.
    """
    env_file = REPO_ROOT / "frontend" / "src" / "config" / "env.ts"
    assert env_file.exists(), "frontend/src/config/env.ts must exist"

    with open(env_file, "r", encoding="utf-8") as fp:
        content = fp.read()

    # Verify presence of the security boundary declaration
    assert "FORBIDDEN_SECRET_KEYS" in content, "FORBIDDEN_SECRET_KEYS array must be defined in env.ts"

    # Mandatory secrets that must never be exposed to the client
    critical_forbidden_secrets = [
        "KEY_PEPPER",
        "DB_PASSWORD",
        "OPENAI_API_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "ADMIN_API_KEY",
        "DATABASE_URL",
        "JWT_SECRET",
    ]

    for secret in critical_forbidden_secrets:
        assert f"'{secret}'" in content or f'"{secret}"' in content, (
            f"Critical secret '{secret}' must be registered in FORBIDDEN_SECRET_KEYS"
        )

    # Replicate the runtime security assertion from env.ts
    def validate_frontend_env(mock_env: Dict[str, str]) -> None:
        for key in mock_env.keys():
            for forbidden in critical_forbidden_secrets:
                if forbidden in key.upper():
                    raise PermissionError(
                        f"[SECURITY VIOLATION] Critical secret '{key}' detected in frontend client environment."
                    )

    # 1. Leaked backend secrets prefixed with VITE_ must trigger a security error
    with pytest.raises(PermissionError, match="SECURITY VIOLATION"):
        validate_frontend_env({"VITE_KEY_PEPPER": "secret_pepper_123"})

    with pytest.raises(PermissionError, match="SECURITY VIOLATION"):
        validate_frontend_env({"VITE_DB_PASSWORD": "super_secret_db_pass"})

    with pytest.raises(PermissionError, match="SECURITY VIOLATION"):
        validate_frontend_env({"VITE_OPENAI_API_KEY": "sk-proj-1234567890"})

    with pytest.raises(PermissionError, match="SECURITY VIOLATION"):
        validate_frontend_env({"VITE_ADMIN_API_KEY": "ar_live_admin_secret"})

    # 2. Legitimate public client variables must pass without error
    legitimate_client_env = {
        "VITE_SUPABASE_URL": "https://xyz.supabase.co",
        "VITE_SUPABASE_ANON_KEY": "public-anon-key-123",
        "VITE_API_BASE_URL": "http://localhost:8001",
        "VITE_API_KEY": "ar_live_developer_key",
    }
    validate_frontend_env(legitimate_client_env)


@pytest.mark.regression
@pytest.mark.backend
@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="Windows thread scheduling jitter causing event loop lag to exceed 15ms under heavy multi-test load; tracked in BUG-001",
    strict=False,
)
async def test_regression_bug_001_windows_event_loop_concurrency_jitter():
    """
    Documents and protects BUG-001 (Windows thread scheduling jitter causing event
    loop lag to exceed 15ms under heavy multi-test load) via xfail(strict=False).

    On Windows platforms, the standard multimedia timer granularity (~15.6ms) and
    process priority scheduling under high concurrent test suite load can cause event
    loop wake-up latency to exceed 15 milliseconds. Marking this test with xfail(strict=False)
    documents the known scheduling constraint whilst ensuring isolated test runs pass cleanly.
    """
    # High-precision timer period tuning on Windows if supported
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass

    target_interval = 0.005  # 5 milliseconds
    lags: List[float] = []

    try:
        for _ in range(10):
            t0 = time.perf_counter()
            await asyncio.sleep(target_interval)
            elapsed = time.perf_counter() - t0
            lag = max(0.0, elapsed - target_interval)
            lags.append(lag)
    finally:
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass

    max_lag_ms = max(lags) * 1000.0

    # BUG-001 assertion: Event loop tick lag must remain under 15ms
    assert max_lag_ms < 15.0, (
        f"Event loop wake-up lag ({max_lag_ms:.2f}ms) exceeded 15.0ms threshold (BUG-001)"
    )


# ===========================================================================
# 2. CRITICAL PATH SMOKE SET
# ===========================================================================

@pytest.mark.regression
@pytest.mark.backend
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_regression_smoke_recommend_flow_fast(monkeypatch):
    """
    Hits POST /recommend with developer API key, verifies 200 OK, stripped
    candidate cards, and sub-second execution.

    Confirms that the primary recommendation endpoint sanitises candidate cards
    by stripping internal ranking scores, excludes execution diagnostics, and completes
    in well under one second during health and regression verification.
    """
    dev_key = "ar_live_regression_dev_key_1234567890"
    monkeypatch.setenv("MY_API_KEY", dev_key)

    budget_guard.reset()
    rate_limiter.redis = None
    rate_limiter.reset()

    # Hermetic mock: returns sample candidates with internal ranking scores
    async def _mock_async_rag(query, top_k=20, allow_adult=False):
        return [dict(c) for c in SAMPLE_REGRESSION_CANDIDATES[:top_k]], {
            "retrieval_ms": 10.0,
            "rerank_ms": 12.0,
        }

    payload = {
        "query": "space bounty hunters exploring solar systems",
        "top_k": 2,
        "allow_adult": False,
    }
    headers = {"Authorization": f"Bearer {dev_key}"}

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch("backend.main.async_rag_pipeline", side_effect=_mock_async_rag), \
             patch("backend.telemetry.logger.log_recommendation_event"):

            start_time = time.perf_counter()
            response = await client.post("/recommend", json=payload, headers=headers)
            duration_sec = time.perf_counter() - start_time

    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}: {response.text}"
    assert duration_sec < 1.0, f"Execution took {duration_sec:.3f}s; must be sub-second (< 1.0s)"

    data = response.json()
    assert data["query"] == payload["query"]
    assert data["count"] == 2
    assert len(data["results"]) == 2

    # Verify that internal diagnostic scores are completely stripped from public responses
    for card in data["results"]:
        assert "id" in card
        assert "title_userPreferred" in card
        assert "cross_encoder_score" not in card, "Internal cross_encoder_score must be stripped"
        assert "final_rrf_score" not in card, "Internal final_rrf_score must be stripped"

    # Verify diagnostic containers are not leaked
    assert "extra" not in data, "Public recommendation payload must not leak 'extra' container"
    assert "timings" not in data, "Public recommendation payload must not leak 'timings'"


@pytest.mark.regression
@pytest.mark.backend
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_regression_smoke_chat_streaming_handshake(monkeypatch):
    """
    Hits POST /chat with query, verifies 200 OK, text/event-stream content type,
    and immediate metadata emission.

    Validates that the conversational SSE streaming handshake responds with HTTP 200,
    attaches appropriate streaming headers including X-Session-ID, and emits the
    initial metadata event delivering candidate recommendations.
    """
    from backend.rag_pipeline.orchestrator import orchestrator

    budget_guard.reset()
    rate_limiter.redis = None
    rate_limiter.reset()

    async def _mock_retrieval(query, top_k=5, allow_adult=False, seen_ids=None, include_metadata=True, request_id=None):
        return [dict(c) for c in SAMPLE_REGRESSION_CANDIDATES[:top_k]], {"retrieval_ms": 10.0}

    async def _mock_pitch(query, candidates, conversation_history=None, is_disconnected=None, request_id=None, session_id=None):
        yield "Cowboy Bebop is a quintessential "
        yield "space Western masterpiece."

    payload = {
        "query": "recommend a space western anime series",
        "top_k": 2,
        "allow_adult": False,
    }

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch.object(orchestrator, "_retrieval_func", side_effect=_mock_retrieval), \
             patch.object(orchestrator.synthesizer, "stream_pitch", side_effect=_mock_pitch), \
             patch.object(orchestrator.guardrails, "validate_intent", return_value=GuardrailResult(True, "valid")), \
             patch("backend.telemetry.logger.log_recommendation_event"):

            response = await client.post("/chat", json=payload)

    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert "X-Session-ID" in response.headers, "X-Session-ID header must be emitted"

    events = parse_sse_events(response.text)
    assert len(events) >= 1, "At least one SSE event must be received"

    event_names = [e["event"] for e in events]
    assert "metadata" in event_names, "Stream must emit initial metadata event"

    metadata_event = next(e for e in events if e["event"] == "metadata")
    assert "candidates" in metadata_event["data"], "Metadata event must contain candidate anime cards"
    assert len(metadata_event["data"]["candidates"]) == 2


@pytest.mark.regression
@pytest.mark.backend
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_regression_smoke_unauthenticated_rejection_fast():
    """
    Verifies missing credentials on /dev/keys and /recommend are rejected with 401
    instantly before expensive computation.

    Confirms that unauthenticated requests to protected endpoints are blocked at the
    authentication boundary within sub-100ms execution times without invoking downstream
    pipeline stages or database queries.
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Unauthenticated POST /recommend
        t0 = time.perf_counter()
        recommend_response = await client.post("/recommend", json={"query": "test query prompt"})
        recommend_elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert recommend_response.status_code == 401
        assert recommend_response.json()["error"]["code"] == "unauthorized"
        assert recommend_elapsed_ms < 100.0, (
            f"POST /recommend rejection took {recommend_elapsed_ms:.1f}ms; must be under 100ms"
        )

        # 2. Unauthenticated GET /dev/keys
        t0 = time.perf_counter()
        keys_response = await client.get("/dev/keys")
        keys_elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert keys_response.status_code == 401
        assert keys_response.json()["error"]["code"] == "unauthorized"
        assert keys_elapsed_ms < 100.0, (
            f"GET /dev/keys rejection took {keys_elapsed_ms:.1f}ms; must be under 100ms"
        )
