"""
test/system/test_api_system.py

System-level end-to-end integration test suite verifying backend API journeys:
1. User Journey 1: POST /recommend with valid developer API key (200 OK, stripped anime cards, no score leakage, verified status).
2. User Journey 2: POST /admin/recommend with admin credentials (200 OK, candidate scores and timings returned).
3. Auth and Error Journey 3:
   - Missing key on /recommend returns 401.
   - Invalid key on /recommend returns 401.
   - Missing token on /dev/keys returns 401.
   - Non-admin key on /admin/llm-usage/daily returns 403.
4. Streaming Chat Journey 4: POST /chat with valid query returning Server-Sent Events stream (metadata, token, done).
5. Developer Key Lifecycle Journey 5: Provision, list, and revoke API keys via /dev/keys.
6. Admin Telemetry Journey 6: Daily LLM usage and current budget status endpoints.

Conforms strictly to British English documentation standards without em-dashes.
"""

import os
import sys
import uuid
import json
import time
from typing import Generator, List, Dict, Any
from unittest.mock import patch

# Configure standard output encoding on Windows console to avoid encoding failures with emojis
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pytest
import psycopg2
import httpx
from httpx import ASGITransport

from backend.main import app
from backend.rag_pipeline.config import config as get_db_config
from backend.rag_pipeline.orchestrator import orchestrator
from backend.rag_pipeline.helper.guardrails import GuardrailResult
from backend.rag_pipeline.helper.budget_guard import budget_guard
from backend.rag_pipeline.helper.rate_limiter import rate_limiter
from backend.auth.supabase_jwt import set_jwks_service, DevUserContext

# Mark all tests in this module as system and backend scoped
pytestmark = [pytest.mark.system, pytest.mark.backend]


# ---------------------------------------------------------------------------
# TEST DATA & FIXTURES
# ---------------------------------------------------------------------------

SYSTEM_SAMPLE_CANDIDATES: List[Dict[str, Any]] = [
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
        "description": "Bounty hunters in space chasing criminals across the solar system.",
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
        "description": "Teens pilot giant mechs to defend humanity against enigmatic Angels.",
        "cross_encoder_score": 4.52,
        "final_rrf_score": 0.82,
    },
]


def parse_sse_events(sse_text: str) -> List[Dict[str, Any]]:
    """Parses raw Server-Sent Events text into structured event objects."""
    events = []
    current_event = None
    for line in sse_text.splitlines():
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


class MockSystemJWKSService:
    """In-memory mock for Supabase JWKS verification service during system tests."""

    def __init__(self):
        self._tokens: Dict[str, DevUserContext] = {}

    def register(self, token: str, user_context: DevUserContext) -> None:
        self._tokens[token] = user_context

    def verify_token(self, token: str, require_fresh: bool = False) -> DevUserContext:
        if not token:
            raise ValueError("Missing authentication token.")
        if "expired" in token.lower():
            raise ValueError("Token has expired.")
        if token in self._tokens:
            return self._tokens[token]
        raise ValueError("Invalid token signature or unknown key identifier.")


@pytest.fixture(scope="module")
def system_user_id() -> str:
    """Generates an isolated developer UUID for database lifecycle tests."""
    return str(uuid.uuid4())


@pytest.fixture(autouse=True)
def setup_system_environment(monkeypatch, system_user_id: str):
    """
    Initialises clean in-memory rate limiting, deterministic budget guard,
    mocked JWKS service, and safe database isolation.
    Teardown removes any API keys or audit logs created by the test developer.
    """
    # Deterministic budget guard
    budget_guard.reset()
    budget_guard.limits = {
        "nli": 100000,
        "retrieval": 200000,
        "presentation": 300000,
    }

    # Deterministic in-memory rate limiting
    rate_limiter.redis = None
    rate_limiter.reset()

    # Configure mock JWKS service for developer and admin identities
    mock_jwks = MockSystemJWKSService()
    dev_user = DevUserContext(
        user_id=system_user_id,
        email="dev.system@otaku.internal",
        role="authenticated",
        iat=int(time.time()),
        app_metadata={"role": "developer"},
    )
    mock_jwks.register("valid-dev-system-jwt", dev_user)

    admin_user = DevUserContext(
        user_id="admin-system-uuid-1",
        email="admin.system@otaku.internal",
        role="authenticated",
        iat=int(time.time()),
        app_metadata={"role": "admin"},
    )
    mock_jwks.register("valid-admin-system-jwt", admin_user)

    set_jwks_service(mock_jwks)

    # Standard API keys for system testing
    admin_key = "ar_live_admin_secret_test_key_1234567890"
    dev_key = "ar_live_regular_user_key_1234567890"
    monkeypatch.setenv("ADMIN_API_KEY", admin_key)
    monkeypatch.setenv("MY_API_KEY", dev_key)
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,::1")

    # Mock RAG pipeline execution, streaming pitch, and telemetry to keep tests fast and hermetic
    async def _mock_async_rag(query, top_k=20, allow_adult=False):
        return [dict(c) for c in SYSTEM_SAMPLE_CANDIDATES[:top_k]], {
            "retrieval_ms": 14.5,
            "rerank_ms": 11.2,
        }

    async def _mock_retrieval_func(query, top_k=5, allow_adult=False, seen_ids=None, include_metadata=True, request_id=None):
        return [dict(c) for c in SYSTEM_SAMPLE_CANDIDATES[:top_k]], {"retrieval_ms": 14.5}

    async def _mock_stream_pitch(query, candidates, conversation_history=None, is_disconnected=None, request_id=None, session_id=None):
        yield "Based on your criteria, "
        yield "Cowboy Bebop "
        yield "delivers an exceptional space jazz atmosphere."

    with patch("backend.main.async_rag_pipeline", side_effect=_mock_async_rag), \
         patch.object(orchestrator, "_retrieval_func", side_effect=_mock_retrieval_func), \
         patch.object(orchestrator.synthesizer, "stream_pitch", side_effect=_mock_stream_pitch), \
         patch.object(orchestrator.guardrails, "validate_intent", return_value=GuardrailResult(True, "valid")), \
         patch("backend.telemetry.logger.log_recommendation_event"):
        yield {
            "admin_key": admin_key,
            "dev_key": dev_key,
            "dev_jwt": "valid-dev-system-jwt",
            "admin_jwt": "valid-admin-system-jwt",
        }

    # Reset in-memory state
    budget_guard.reset()
    rate_limiter.reset()
    set_jwks_service(None)

    # Database teardown: purge any records created by system_user_id
    try:
        cfg = get_db_config()
        conn = psycopg2.connect(**cfg)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM app_auth.api_keys WHERE owner_id = %s::uuid;", (system_user_id,))
            created_keys = [str(r[0]) for r in cur.fetchall()]
            if created_keys:
                cur.execute(
                    "DELETE FROM app_auth.key_audit_log WHERE api_key_id = ANY(%s::uuid[]);",
                    (created_keys,)
                )
                cur.execute(
                    "DELETE FROM app_auth.api_keys WHERE id = ANY(%s::uuid[]);",
                    (created_keys,)
                )
            cur.execute(
                "DELETE FROM app_auth.key_audit_log WHERE actor = %s;",
                (f"user:{system_user_id}",)
            )
        conn.close()
    except Exception as exc:
        sys.stderr.write(f"System test cleanup warning: {exc}\n")


@pytest.fixture
async def async_client():
    """Provides an isolated HTTPX async client connected to the FastAPI application."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# ---------------------------------------------------------------------------
# SYSTEM TEST SUITE
# ---------------------------------------------------------------------------

class TestApiSystemJourneys:
    """Comprehensive system-level test suite covering public, admin, streaming, and auth journeys."""

    @pytest.mark.system
    @pytest.mark.backend
    async def test_user_journey_1_recommend_with_valid_developer_key(
        self,
        async_client: httpx.AsyncClient,
        setup_system_environment: Dict[str, str],
    ):
        """
        Protects the public recommendation contract for external developers.
        Verifies that POST /recommend with a valid developer key returns HTTP 200,
        properly sanitises candidate cards by stripping internal ranking scores,
        and does not leak diagnostic timings or extra metadata in the response.
        """
        dev_key = setup_system_environment["dev_key"]
        payload = {
            "query": "space bounty hunters exploring galaxies",
            "top_k": 2,
            "allow_adult": False,
        }
        headers = {"Authorization": f"Bearer {dev_key}"}

        response = await async_client.post("/recommend", json=payload, headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["query"] == payload["query"]
        assert data["count"] == 2
        assert data["allowed_adult"] is False
        assert len(data["results"]) == 2

        # Crucial security check: internal model ranking scores must be stripped from public output
        for card in data["results"]:
            assert "id" in card
            assert "title_userPreferred" in card
            assert "genres" in card
            assert "cross_encoder_score" not in card
            assert "final_rrf_score" not in card

        # Diagnostic timings and extra metadata must be omitted from public recommendations
        assert "extra" not in data
        assert "timings" not in data

    @pytest.mark.system
    @pytest.mark.backend
    async def test_user_journey_2_admin_recommend_with_admin_credentials(
        self,
        async_client: httpx.AsyncClient,
        setup_system_environment: Dict[str, str],
    ):
        """
        Protects the administrative evaluation pipeline contract.
        Verifies that POST /admin/recommend with valid administrator credentials returns HTTP 200,
        retains unstripped candidate ranking scores, and includes detailed pipeline execution timings.
        """
        admin_key = setup_system_environment["admin_key"]
        payload = {
            "query": "mecha psychological anime series",
            "top_k": 2,
            "allow_adult": False,
        }
        headers = {"Authorization": f"Bearer {admin_key}"}

        response = await async_client.post("/admin/recommend", json=payload, headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["query"] == payload["query"]
        assert data["count"] == 2
        assert len(data["results"]) == 2

        # Admin responses must preserve model evaluation scores for diagnostic analysis
        for card in data["results"]:
            assert "cross_encoder_score" in card

        # Admin responses must include timing telemetry in the extra container
        assert "extra" in data
        assert "timings" in data["extra"]
        assert "total_ms" in data["extra"]
        assert data["extra"]["timings"]["retrieval_ms"] > 0

    @pytest.mark.system
    @pytest.mark.backend
    async def test_auth_error_journey_3_missing_key_recommend_returns_401(
        self,
        async_client: httpx.AsyncClient,
    ):
        """
        Protects authentication boundary on the public recommendation endpoint.
        Verifies that calling POST /recommend without credentials returns HTTP 401 Unauthorized.
        """
        payload = {"query": "anime recommendation prompt"}
        response = await async_client.post("/recommend", json=payload)

        assert response.status_code == 401
        data = response.json()
        assert data["error"]["code"] == "unauthorized"

    @pytest.mark.system
    @pytest.mark.backend
    async def test_auth_error_journey_3_invalid_key_recommend_returns_401(
        self,
        async_client: httpx.AsyncClient,
    ):
        """
        Protects against brute-force or fraudulent access attempts.
        Verifies that calling POST /recommend with an invalid key returns HTTP 401 Unauthorized.
        """
        headers = {"Authorization": "Bearer ar_live_bogus_unregistered_key_00000000000"}
        payload = {"query": "cyberpunk anime"}

        response = await async_client.post("/recommend", json=payload, headers=headers)
        assert response.status_code == 401
        data = response.json()
        assert data["error"]["code"] == "unauthorized"

    @pytest.mark.system
    @pytest.mark.backend
    async def test_auth_error_journey_3_missing_token_dev_keys_returns_401(
        self,
        async_client: httpx.AsyncClient,
    ):
        """
        Protects the developer key management portal from unauthenticated access.
        Verifies that requesting GET /dev/keys without a JWT returns HTTP 401 Unauthorized.
        """
        response = await async_client.get("/dev/keys")
        assert response.status_code == 401
        data = response.json()
        assert data["error"]["code"] == "unauthorized"

    @pytest.mark.system
    @pytest.mark.backend
    async def test_auth_error_journey_3_non_admin_key_admin_usage_returns_403(
        self,
        async_client: httpx.AsyncClient,
        setup_system_environment: Dict[str, str],
    ):
        """
        Protects administrative telemetry and cost reporting from privilege escalation.
        Verifies that querying GET /admin/llm-usage/daily with a non-admin key or token returns HTTP 403 Forbidden.
        """
        dev_jwt = setup_system_environment["dev_jwt"]
        headers = {"Authorization": f"Bearer {dev_jwt}"}

        response = await async_client.get("/admin/llm-usage/daily", headers=headers)
        assert response.status_code == 403
        data = response.json()
        assert data["error"]["code"] == "forbidden"

    @pytest.mark.system
    @pytest.mark.backend
    async def test_streaming_chat_journey_4_sse_events(
        self,
        async_client: httpx.AsyncClient,
    ):
        """
        Protects the conversational SSE streaming discovery protocol.
        Verifies that POST /chat returns a valid text/event-stream delivering:
        1. An initial 'metadata' event with candidate anime cards.
        2. Streamed 'token' events containing grounded pitch prose.
        3. A final 'done' event signaling stream completion.
        """
        payload = {
            "query": "recommend a classic 90s sci-fi anime",
            "top_k": 2,
            "allow_adult": False,
        }

        response = await async_client.post("/chat", json=payload)
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert "X-Session-ID" in response.headers

        events = parse_sse_events(response.text)
        event_types = [e["event"] for e in events]

        # 1. Candidate cards delivered in metadata event
        assert "metadata" in event_types
        meta = next(e["data"] for e in events if e["event"] == "metadata")
        assert meta["count"] == 2
        assert len(meta["candidates"]) == 2
        for card in meta["candidates"]:
            assert "cross_encoder_score" not in card

        # 2. Token events streaming prose pitch
        assert "token" in event_types
        tokens = [e["data"]["text"] for e in events if e["event"] == "token"]
        full_text = "".join(tokens)
        assert "Cowboy Bebop" in full_text

        # 3. Done event marking turn completion
        assert "done" in event_types
        done = next(e["data"] for e in events if e["event"] == "done")
        assert done["status"] == "completed"

    @pytest.mark.system
    @pytest.mark.backend
    async def test_developer_key_lifecycle_journey_5_provision_list_revoke(
        self,
        async_client: httpx.AsyncClient,
        setup_system_environment: Dict[str, str],
    ):
        """
        Protects the complete self-service API key lifecycle:
        1. Provisions a new API key via POST /dev/keys (HTTP 201 Created, secret shown once).
        2. Lists developer keys via GET /dev/keys (HTTP 200 OK, secret never leaked).
        3. Revokes the API key via DELETE /dev/keys/{id} (HTTP 204 No Content).
        4. Confirms that subsequent listing marks the key as revoked.
        """
        dev_jwt = setup_system_environment["dev_jwt"]
        auth_headers = {"Authorization": f"Bearer {dev_jwt}"}

        # Step 1: Provision key
        create_payload = {"name": "system-lifecycle-key"}
        create_res = await async_client.post("/dev/keys", json=create_payload, headers=auth_headers)
        assert create_res.status_code == 201
        assert "no-store" in create_res.headers.get("Cache-Control", "")

        created_data = create_res.json()
        assert created_data["name"] == "system-lifecycle-key"
        key_id = created_data["id"]
        raw_secret = created_data["key"]
        assert raw_secret.startswith("ar_live_")

        # Step 2: List keys and ensure secret is not leaked in metadata
        list_res = await async_client.get("/dev/keys", headers=auth_headers)
        assert list_res.status_code == 200

        key_list = list_res.json()["keys"]
        found_key = next((k for k in key_list if k["id"] == key_id), None)
        assert found_key is not None
        assert found_key["name"] == "system-lifecycle-key"
        assert found_key["revoked_at"] is None
        # Raw secret must never be exposed in list queries
        assert "key" not in found_key

        # Step 3: Revoke key
        del_res = await async_client.delete(f"/dev/keys/{key_id}", headers=auth_headers)
        assert del_res.status_code == 204

        # Step 4: Verify soft-revocation status in subsequent listing
        verify_res = await async_client.get("/dev/keys", headers=auth_headers)
        assert verify_res.status_code == 200
        revoked_item = next((k for k in verify_res.json()["keys"] if k["id"] == key_id), None)
        assert revoked_item is not None
        assert revoked_item["revoked_at"] is not None

    @pytest.mark.system
    @pytest.mark.backend
    async def test_admin_telemetry_journey_6_daily_usage_and_budget(
        self,
        async_client: httpx.AsyncClient,
        setup_system_environment: Dict[str, str],
    ):
        """
        Protects administrative telemetry visibility and budget tracking:
        1. GET /admin/llm-usage/daily returns aggregated items or empty list cleanly.
        2. GET /admin/llm-usage/current-budget returns active layer budget ceilings.
        """
        admin_key = setup_system_environment["admin_key"]
        headers = {"Authorization": f"Bearer {admin_key}"}

        # 1. Daily LLM usage telemetry aggregation
        daily_res = await async_client.get("/admin/llm-usage/daily?days=7", headers=headers)
        assert daily_res.status_code == 200
        assert isinstance(daily_res.json(), list)

        # 2. Current budget guard status across layers
        budget_res = await async_client.get("/admin/llm-usage/current-budget", headers=headers)
        assert budget_res.status_code == 200

        budget_data = budget_res.json()
        assert "nli" in budget_data
        assert "retrieval" in budget_data
        assert "presentation" in budget_data

        for layer_name in ["nli", "retrieval", "presentation"]:
            layer_status = budget_data[layer_name]
            assert "limit" in layer_status
            assert "current_usage" in layer_status
            assert "remaining" in layer_status
            assert layer_status["limit"] > 0
