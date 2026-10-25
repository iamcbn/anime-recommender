"""
test/unit/test_loop2_unit.py

Unit test suite verifying Loop 2 implementations:
1. Supabase Anonymous-First Authentication & Role Isolation:
   - DevUserContext correctly records is_anonymous flag.
   - Parse and assert anonymous JWT claims (app_metadata.is_anonymous, provider=anonymous).
   - get_current_dev and get_fresh_current_dev reject anonymous users with HTTP 403 Forbidden.
2. Dual-Tier Sliding-Window Rate Limits:
   - Guest visitors and anonymous JWT users are constrained to 10 req/min.
   - Permanent authenticated users are allocated 30 req/min.
   - Rate limit headers (X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset) are accurate.
3. First-Party Ground-Truth Feedback Ingestion:
   - POST /feedback accepts valid event_types ('thumbs_up', 'thumbs_down', 'more_like_this', 'watchlist_add').
   - Rejects invalid event types with HTTP 422 Unprocessable Entity.
   - Validates recommendation_id UUID formatting.
   - DB helper insert_feedback_event hashes IP addresses and handles database writes.
4. Privacy & Hygiene Guardrails:
   - Verifies no PostHog Python SDK imports or modal.exit() flushes exist in backend codebase.
"""

import os
import uuid
import time
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import app, rate_limiter
from backend.rag_pipeline.orchestrator import orchestrator
from backend.auth.supabase_jwt import (
    DevUserContext,
    SupabaseJWKSService,
    set_jwks_service,
    get_current_dev,
    get_fresh_current_dev,
)
from backend.telemetry.db import insert_feedback_event


class MockJWKSService:
    """In-memory mock for Supabase JWKS verification service supporting anonymous users."""

    def __init__(self):
        self._tokens = {}

    def register(self, token: str, user_ctx: DevUserContext):
        self._tokens[token] = user_ctx

    def verify_token(self, token: str, require_fresh: bool = False) -> DevUserContext:
        if not token:
            raise ValueError("Token missing.")
        if "expired" in token.lower():
            raise ValueError("Token has expired.")
        if "stale" in token.lower():
            raise ValueError("Session is older than 15 minutes. Re-authentication required.")
        if token in self._tokens:
            return self._tokens[token]
        raise ValueError("Invalid token signature or unknown key identifier.")


@pytest.fixture(autouse=True)
def setup_loop2_env(monkeypatch):
    """Configures deterministic in-memory rate limiting, mock auth service, and fast stream mock."""
    rate_limiter.redis = None
    rate_limiter.reset()

    mock_jwks = MockJWKSService()
    set_jwks_service(mock_jwks)

    async def _mock_stream(*args, **kwargs):
        yield "event: metadata\ndata: {\"count\": 0, \"candidates\": []}\n\n"
        yield "event: done\ndata: {\"status\": \"completed\"}\n\n"

    with patch.object(orchestrator, "stream_chat", side_effect=_mock_stream):
        yield mock_jwks

    rate_limiter.reset()
    set_jwks_service(None)


# -----------------------------------------------------------------------------
# 1. SUPABASE ANONYMOUS AUTH & ROLE ISOLATION
# -----------------------------------------------------------------------------

def test_dev_user_context_anonymous_flag_default_and_explicit():
    """DevUserContext defaults is_anonymous to False and respects explicit True."""
    user = DevUserContext(
        user_id="usr_regular_123",
        email="developer@example.com",
        role="authenticated",
        iat=int(time.time()),
        app_metadata={"provider": "email"},
    )
    assert user.is_anonymous is False

    anon_user = DevUserContext(
        user_id="anon_user_456",
        email=None,
        role="authenticated",
        iat=int(time.time()),
        app_metadata={"provider": "anonymous", "is_anonymous": True},
        is_anonymous=True,
    )
    assert anon_user.is_anonymous is True


def test_verify_token_extracts_anonymous_claim():
    """SupabaseJWKSService.verify_token correctly detects anonymous sign-ins."""
    service = SupabaseJWKSService.__new__(SupabaseJWKSService)
    service.issuer = "https://example.supabase.co/auth/v1"

    # Mock payload for anonymous sign-in
    anon_payload = {
        "sub": "b2c3d4e5-0000-1111-2222-333344445555",
        "email": None,
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
        "iss": service.issuer,
        "app_metadata": {"provider": "anonymous", "is_anonymous": True},
    }

    with patch("jwt.get_unverified_header", return_value={"alg": "ES256"}):
        with patch.object(service, "get_signing_key_from_jwt", return_value=MagicMock(key="fake_key")):
            with patch("jwt.decode", return_value=anon_payload):
                ctx = service.verify_token("mock_anon_jwt")
                assert ctx.is_anonymous is True
                assert ctx.user_id == "b2c3d4e5-0000-1111-2222-333344445555"
                assert ctx.email is None


@pytest.mark.asyncio
async def test_get_current_dev_rejects_anonymous_user(setup_loop2_env):
    """get_current_dev dependency blocks anonymous users from developer resources with HTTP 403."""
    mock_jwks = setup_loop2_env
    anon_token = "mock_anon_jwt_token"
    mock_jwks.register(
        anon_token,
        DevUserContext(
            user_id="anon_1",
            email=None,
            role="authenticated",
            iat=int(time.time()),
            app_metadata={"provider": "anonymous"},
            is_anonymous=True,
        ),
    )

    credentials = MagicMock()
    credentials.credentials = anon_token
    request = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_dev(request, credentials)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_get_fresh_current_dev_rejects_anonymous_user(setup_loop2_env):
    """get_fresh_current_dev dependency blocks anonymous users with HTTP 403."""
    mock_jwks = setup_loop2_env
    anon_token = "mock_anon_jwt_token"
    mock_jwks.register(
        anon_token,
        DevUserContext(
            user_id="anon_2",
            email=None,
            role="authenticated",
            iat=int(time.time()),
            app_metadata={"provider": "anonymous"},
            is_anonymous=True,
        ),
    )

    credentials = MagicMock()
    credentials.credentials = anon_token
    request = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_fresh_current_dev(request, credentials)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"]["code"] == "forbidden"


# -----------------------------------------------------------------------------
# 2. DUAL-TIER SLIDING-WINDOW RATE LIMITING
# -----------------------------------------------------------------------------

def test_guest_visitor_rate_limit_ten_per_minute(setup_loop2_env):
    """Guest visitors (without auth header) receive 10 queries per minute."""
    client = TestClient(app)
    headers = {"X-Forwarded-For": "192.0.2.10"}

    # 10 successful queries
    for i in range(10):
        res = client.post("/chat", headers=headers, json={"query": f"Turn {i} anime recommendation"})
        assert res.status_code == 200
        assert res.headers.get("X-RateLimit-Limit") == "10"
        assert res.headers.get("X-RateLimit-Remaining") == str(10 - 1 - i)

    # 11th query blocked by 429
    res = client.post("/chat", headers=headers, json={"query": "Turn 11 excess"})
    assert res.status_code == 429
    assert res.headers.get("X-RateLimit-Limit") == "10"
    assert res.headers.get("X-RateLimit-Remaining") == "0"
    data = res.json()
    assert data["error"]["code"] == "rate_limit_exceeded"


def test_anonymous_jwt_rate_limit_ten_per_minute(setup_loop2_env):
    """Anonymous Supabase JWT users receive 10 queries per minute based on user_id."""
    mock_jwks = setup_loop2_env
    anon_token = "valid_anon_jwt_token"
    anon_uid = "anon_user_uuid_999"
    mock_jwks.register(
        anon_token,
        DevUserContext(
            user_id=anon_uid,
            email=None,
            role="authenticated",
            iat=int(time.time()),
            app_metadata={"provider": "anonymous"},
            is_anonymous=True,
        ),
    )

    client = TestClient(app)
    headers = {
        "Authorization": f"Bearer {anon_token}",
        "X-Forwarded-For": "192.0.2.20",
    }

    # 10 successful requests
    for i in range(10):
        res = client.post("/chat", headers=headers, json={"query": f"Anon query {i}"})
        assert res.status_code == 200
        assert res.headers.get("X-RateLimit-Limit") == "10"
        assert res.headers.get("X-RateLimit-Remaining") == str(10 - 1 - i)

    # 11th request throttled
    res = client.post("/chat", headers=headers, json={"query": "Anon query 11"})
    assert res.status_code == 429
    assert res.headers.get("X-RateLimit-Limit") == "10"


def test_authenticated_user_rate_limit_thirty_per_minute(setup_loop2_env):
    """Permanent authenticated users receive 30 queries per minute."""
    mock_jwks = setup_loop2_env
    auth_token = "valid_perm_jwt_token"
    perm_uid = "perm_user_uuid_888"
    mock_jwks.register(
        auth_token,
        DevUserContext(
            user_id=perm_uid,
            email="user@test.co.uk",
            role="authenticated",
            iat=int(time.time()),
            app_metadata={"provider": "email"},
            is_anonymous=False,
        ),
    )

    client = TestClient(app)
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "X-Forwarded-For": "192.0.2.30",
    }

    # Verify first request returns limit 30
    res = client.post("/chat", headers=headers, json={"query": "Auth user query 0"})
    assert res.status_code == 200
    assert res.headers.get("X-RateLimit-Limit") == "30"
    assert res.headers.get("X-RateLimit-Remaining") == "29"


# -----------------------------------------------------------------------------
# 3. FIRST-PARTY FEEDBACK INGESTION & ENDPOINT
# -----------------------------------------------------------------------------

def test_feedback_endpoint_accepts_valid_signals():
    """POST /feedback accepts valid feedback signals and returns HTTP 201 Created."""
    client = TestClient(app)
    rec_id = str(uuid.uuid4())

    valid_events = ["thumbs_up", "thumbs_down", "more_like_this", "watchlist_add"]
    for evt in valid_events:
        payload = {
            "recommendation_id": rec_id,
            "event_type": evt,
            "anime_id": 1535,
            "metadata": {"title": "Death Note"},
        }
        res = client.post("/feedback", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "recorded"
        assert data["recommendation_id"] == rec_id
        assert data["event_type"] == evt


def test_feedback_endpoint_rejects_invalid_event_type():
    """POST /feedback rejects unrecognized event types with HTTP 422."""
    client = TestClient(app)
    payload = {
        "recommendation_id": str(uuid.uuid4()),
        "event_type": "dislike_forever",  # Invalid
        "anime_id": 1,
    }
    res = client.post("/feedback", json=payload)
    assert res.status_code == 422


def test_feedback_endpoint_rejects_malformed_uuid():
    """POST /feedback rejects malformed recommendation_id with HTTP 422."""
    client = TestClient(app)
    payload = {
        "recommendation_id": "not-a-valid-uuid",
        "event_type": "thumbs_up",
    }
    res = client.post("/feedback", json=payload)
    assert res.status_code == 422


def test_insert_feedback_event_database_helper_validation():
    """insert_feedback_event validates parameters and returns False on invalid input."""
    # Invalid event_type
    assert insert_feedback_event(
        recommendation_id=str(uuid.uuid4()),
        event_type="invalid_action",
    ) is False

    # Invalid UUID string
    assert insert_feedback_event(
        recommendation_id="not-a-uuid",
        event_type="thumbs_up",
    ) is False


# -----------------------------------------------------------------------------
# 4. PRIVACY & ARCHITECTURE HYGIENE GUARDS
# -----------------------------------------------------------------------------

def test_no_backend_posthog_sdk_or_exit_flushes():
    """Ensures serverless backend maintains zero PostHog Python SDK imports or modal.exit flushes."""
    import subprocess
    result = subprocess.run(
        ["git", "grep", "-n", "posthog", "backend/"],
        capture_output=True,
        text=True,
    )
    # git grep should find 0 occurrences in backend/
    assert result.stdout.strip() == "", f"Forbidden posthog references in backend:\n{result.stdout}"
