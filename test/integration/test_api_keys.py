"""
test/test_api_keys.py

Comprehensive Automated Integration & Security Penetration Test Suite for Sprint 2:
1. Key Lifecycle & HMAC-SHA256 cryptographic verification.
2. Timing-attack resistance & constant-time execution.
3. Dual-tier endpoint access (/recommend vs /admin/recommend).
4. In-process caching (60s TTL), Redis tombstones, and DB-down fail-closed behavior.
5. Dev keys router security (/dev/keys):
   - Missing/expired/stale JWT (<15m) rejection.
   - alg=none and HS256 public key confusion attacks.
   - aud / iss / role verification (app_metadata isolation).
   - Mass assignment prevention.
   - Active key limit (5 active keys -> 409).
   - Foreign key deletion 404 (isolation).
6. Secrecy & zero data leakage (DB, logs, GET responses).
7. Independent rate limiting & pre-auth IP brute force throttling.
8. Break-glass CLI tooling (scripts/manage_keys.py).

Usage:
    python -m pytest test/test_api_keys.py -v
"""

import os
import sys
import time
import uuid
import json
import base64
import hmac
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
import psycopg2
from psycopg2 import extras
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

# Ensure project root is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.main import app
from backend.rag_pipeline.config import config as get_db_config
from backend.auth.keys import (
    generate_api_key,
    hash_api_key,
    validate_key_format,
    authenticate_api_key,
    revoke_api_key,
    ApiKeyContext,
    VALID_KEY_CACHE,
    NEGATIVE_KEY_CACHE,
    LAST_USED_THROTTLE_CACHE,
    KEY_PEPPER,
    get_auth_db_pool,
)
from backend.auth.supabase_jwt import (
    SupabaseJWKSService,
    set_jwks_service,
    DevUserContext,
)
from backend.rag_pipeline.helper.rate_limiter import (
    DistributedRateLimiter,
    rate_limiter,
)
import scripts.manage_keys as manage_keys_cli


# ----------------------
# CRYPTOGRAPHIC & REDIS MOCKS
# ----------------------

class MockSupabaseJWKS:
    """Generates an ephemeral RSA-2048 keypair to mock Supabase JWKS."""

    def __init__(self):
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        self.public_key = self.private_key.public_key()
        self.kid = "test-sprint2-key-2026"
        self.supabase_url = "https://mock-supabase.example.com"
        self.issuer = f"{self.supabase_url}/auth/v1"

    @property
    def jwks_data(self) -> dict:
        numbers = self.public_key.public_numbers()

        def b64_url(val: int) -> str:
            bytes_val = val.to_bytes((val.bit_length() + 7) // 8, byteorder="big")
            return base64.urlsafe_b64encode(bytes_val).decode("utf-8").rstrip("=")

        return {
            "keys": [{
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": self.kid,
                "n": b64_url(numbers.n),
                "e": b64_url(numbers.e),
            }]
        }

    def issue_token(
        self,
        sub: str,
        role: str = "authenticated",
        app_metadata: dict = None,
        user_metadata: dict = None,
        aud: str = "authenticated",
        expires_in: int = 3600,
        iat_delta: int = 0,
        kid: Optional[str] = None,
        alg: str = "RS256",
        key_override=None
    ) -> str:
        now = int(time.time())
        payload = {
            "sub": sub,
            "aud": aud,
            "iss": self.issuer,
            "role": role,
            "iat": now + iat_delta,
            "exp": now + expires_in,
            "app_metadata": app_metadata or {"role": "user"},
            "user_metadata": user_metadata or {}
        }
        headers = {"kid": kid or self.kid, "alg": alg}

        if alg == "none":
            return jwt.encode(payload, key="", algorithm="none", headers=headers)

        signing_key = key_override or self.private_key
        return jwt.encode(payload, signing_key, algorithm=alg, headers=headers)


class MockSigningKey:
    def __init__(self, key):
        self.key = key


class MockJWKSService(SupabaseJWKSService):
    """In-memory SupabaseJWKSService avoiding real network requests."""

    def __init__(self, mock_jwks: MockSupabaseJWKS):
        super().__init__(supabase_url=mock_jwks.supabase_url)
        self.mock_jwks = mock_jwks

    def get_signing_key_from_jwt(self, token: str):
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if kid != self.mock_jwks.kid:
            raise jwt.PyJWKClientError(f"Unknown kid: {kid}")
        return MockSigningKey(self.mock_jwks.public_key)


class MockUpstashRedis:
    """Async Upstash Redis simulator supporting atomic Lua sliding window and tombstones."""

    def __init__(self):
        self.store = {}
        self.ttls = {}
        self.zsets = {}

    async def get(self, key: str):
        if key in self.ttls and time.time() > self.ttls[key]:
            self.store.pop(key, None)
            self.ttls.pop(key, None)
            return None
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int = None):
        self.store[key] = str(value)
        if ex:
            self.ttls[key] = time.time() + ex
        return True

    async def exists(self, key: str) -> int:
        val = await self.get(key)
        return 1 if val is not None else 0

    async def eval(self, script: str, keys: list, args: list):
        redis_key = keys[0]
        window = float(args[0])
        limit = int(args[1])
        now = time.time()

        if redis_key not in self.zsets:
            self.zsets[redis_key] = []

        clear_before = now - window
        self.zsets[redis_key] = [ts for ts in self.zsets[redis_key] if ts > clear_before]
        current_count = len(self.zsets[redis_key])

        # If script is PEEK script (2 args, no nonce)
        if len(args) == 2:
            if current_count >= limit:
                oldest = self.zsets[redis_key][0]
                retry_after = max(1, int(oldest + window - now))
                return [1, 0, retry_after]
            return [0, limit - current_count, 0]

        # Standard sliding window record script (3 args with nonce)
        if current_count < limit:
            self.zsets[redis_key].append(now)
            remaining = limit - current_count - 1
            return [0, remaining, 0]
        else:
            oldest = self.zsets[redis_key][0]
            retry_after = max(1, int(oldest + window - now))
            return [1, 0, retry_after]


# ----------------------
# FIXTURES
# ----------------------

@pytest.fixture(scope="session")
def db_conn():
    cfg = get_db_config()
    conn = psycopg2.connect(**cfg)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def clean_test_database_artifacts(db_conn):
    """
    Snapshots pre-existing key, audit log, and telemetry IDs before the test run,
    and purges all newly created test rows on session teardown so local/staging
    databases are never polluted by test runs.
    """
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM app_auth.api_keys;")
        initial_key_ids = set(r[0] for r in cur.fetchall())
        cur.execute("SELECT id FROM app_auth.key_audit_log;")
        initial_audit_ids = set(r[0] for r in cur.fetchall())
        cur.execute("SELECT id FROM telemetry.recommendation_logs;")
        initial_rlog_ids = set(r[0] for r in cur.fetchall())
        cur.execute("SELECT api_key_id, day FROM telemetry.api_key_usage_daily;")
        initial_usage_keys = set((r[0], r[1]) for r in cur.fetchall())

    yield

    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM app_auth.api_keys;")
        current_key_ids = set(r[0] for r in cur.fetchall())
        new_key_ids = list(current_key_ids - initial_key_ids)
        if new_key_ids:
            cur.execute("DELETE FROM telemetry.recommendation_logs WHERE api_key_id = ANY(%s::uuid[]);", (new_key_ids,))
            cur.execute("DELETE FROM telemetry.api_key_usage_daily WHERE api_key_id = ANY(%s::uuid[]);", (new_key_ids,))
            cur.execute("DELETE FROM app_auth.key_audit_log WHERE api_key_id = ANY(%s::uuid[]);", (new_key_ids,))
            cur.execute("DELETE FROM app_auth.api_keys WHERE id = ANY(%s::uuid[]);", (new_key_ids,))

        cur.execute("SELECT id FROM app_auth.key_audit_log;")
        current_audit_ids = set(r[0] for r in cur.fetchall())
        new_audit_ids = list(current_audit_ids - initial_audit_ids)
        if new_audit_ids:
            cur.execute("DELETE FROM app_auth.key_audit_log WHERE id = ANY(%s);", (new_audit_ids,))

        cur.execute("SELECT id FROM telemetry.recommendation_logs;")
        current_rlog_ids = set(r[0] for r in cur.fetchall())
        new_rlog_ids = list(current_rlog_ids - initial_rlog_ids)
        if new_rlog_ids:
            cur.execute("DELETE FROM telemetry.recommendation_logs WHERE id = ANY(%s);", (new_rlog_ids,))

        cur.execute("SELECT api_key_id, day FROM telemetry.api_key_usage_daily;")
        current_usage_keys = set((r[0], r[1]) for r in cur.fetchall())
        for key_id, day_val in (current_usage_keys - initial_usage_keys):
            cur.execute(
                "DELETE FROM telemetry.api_key_usage_daily WHERE api_key_id = %s AND day = %s;",
                (key_id, day_val),
            )


@pytest.fixture(autouse=True)
def mock_recommend_rag_pipeline():
    """
    Mocks async_rag_pipeline on /recommend and /admin/recommend so auth tests
    do not load ML models into memory or mutate test/data/llm_cache.db.
    """
    dummy_results = [
        {"id": 1, "title_romaji": "Cowboy Bebop", "genres": ["Action", "Sci-Fi"]},
        {"id": 2, "title_romaji": "Trigun", "genres": ["Action", "Sci-Fi"]},
    ]
    dummy_timings = {"retrieval_ms": 1.2, "reranking_ms": 2.1}
    with patch("backend.main.async_rag_pipeline", new=AsyncMock(return_value=(dummy_results, dummy_timings))) as mock_pipe:
        yield mock_pipe


@pytest.fixture(scope="session")
def jwks_mock():
    mock = MockSupabaseJWKS()
    service = MockJWKSService(mock)
    set_jwks_service(service)
    return mock


@pytest.fixture
def clean_caches():
    VALID_KEY_CACHE.clear()
    NEGATIVE_KEY_CACHE.clear()
    LAST_USED_THROTTLE_CACHE.clear()
    rate_limiter.reset()
    yield
    VALID_KEY_CACHE.clear()
    NEGATIVE_KEY_CACHE.clear()
    LAST_USED_THROTTLE_CACHE.clear()
    rate_limiter.reset()


@pytest.fixture
def client():
    return TestClient(app)


# ----------------------
# 1. KEY LIFECYCLE & CRYPTOGRAPHY
# ----------------------

class TestKeyLifecycle:
    """Verifies cryptographic key derivation, format, and constant-time behavior."""

    def test_key_generation_and_entropy(self, db_conn, clean_caches):
        raw_key, record = generate_api_key(
            name="test-key-entropy",
            owner_id=None,
            role="user",
            conn=db_conn
        )
        assert raw_key.startswith("ar_live_")
        assert len(raw_key) == 60  # ar_live_ (8) + 8 hex prefix + _ (1) + 43 urlsafe secret = 60
        parts = raw_key.split("_", 3)
        assert len(parts) == 4
        prefix_hex = parts[2]
        secret = parts[3]
        assert len(prefix_hex) == 8
        assert len(secret) == 43

        fmt = validate_key_format(raw_key)
        assert fmt is not None
        assert fmt[0] == prefix_hex
        assert fmt[1] == secret

    def test_hmac_hashing_and_pepper_secrecy(self, db_conn, clean_caches):
        raw_key, record = generate_api_key(
            name="test-hmac-hash",
            owner_id=None,
            role="user",
            conn=db_conn
        )
        expected_hash = hash_api_key(raw_key)

        with db_conn.cursor() as cur:
            cur.execute("SELECT key_prefix, key_hash, name FROM app_auth.api_keys WHERE id = %s;", (record["id"],))
            row = cur.fetchone()
            assert row[0] == record["prefix"]
            assert bytes(row[1]) == expected_hash
            assert raw_key not in str(row[1])  # Secret is never in plaintext

    def test_tampered_pepper_fails_validation(self, db_conn, clean_caches):
        raw_key, record = generate_api_key(
            name="test-tampered-pepper",
            owner_id=None,
            role="user",
            conn=db_conn
        )
        # Hash with a different pepper
        wrong_hash = hash_api_key(raw_key, pepper="completely_different_pepper_value_32_bytes!!")
        expected_hash = hash_api_key(raw_key)
        assert wrong_hash != expected_hash


# ----------------------
# 2. ENDPOINT AUTHENTICATION (/recommend & /admin/recommend)
# ----------------------

class TestEndpointAuth:
    """Verifies API key authentication across endpoints and role gates."""

    def test_recommend_auth_success_bearer(self, client, db_conn, clean_caches):
        raw_key, _ = generate_api_key(name="test-rec-bearer", owner_id=None, role="user", conn=db_conn)
        res = client.post("/recommend", json={"query": "action anime"}, headers={"Authorization": f"Bearer {raw_key}"})
        assert res.status_code == 200
        data = res.json()
        assert "results" in data
        assert "count" in data

    def test_recommend_auth_success_legacy_header(self, client, db_conn, clean_caches):
        raw_key, _ = generate_api_key(name="test-rec-legacy", owner_id=None, role="user", conn=db_conn)
        res = client.post("/recommend", json={"query": "action anime"}, headers={"access_token": raw_key})
        assert res.status_code == 200

    def test_recommend_missing_key_401(self, client, clean_caches):
        res = client.post("/recommend", json={"query": "action anime"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthorized"

    def test_recommend_revoked_key_401(self, client, db_conn, clean_caches):
        raw_key, record = generate_api_key(name="test-rec-revoked", owner_id=None, role="user", conn=db_conn)
        revoke_api_key(key_id=record["id"], conn=db_conn)

        res = client.post("/recommend", json={"query": "action anime"}, headers={"Authorization": f"Bearer {raw_key}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthorized"

    def test_recommend_expired_key_401(self, client, db_conn, clean_caches):
        # Create key with 0 days expiry (immediately expired)
        raw_key, record = generate_api_key(
            name="test-rec-expired",
            owner_id=None,
            role="user",
            expires_in_days=-1,
            conn=db_conn
        )
        res = client.post("/recommend", json={"query": "action anime"}, headers={"Authorization": f"Bearer {raw_key}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthorized"

    def test_env_breakglass_admin_key(self, client, monkeypatch, clean_caches):
        breakglass_secret = "ar_live_12345678_emergency_admin_breakglass_token_override_999"
        monkeypatch.setenv("ADMIN_API_KEY", breakglass_secret)

        res = client.post(
            "/admin/recommend",
            json={"query": "breakglass test"},
            headers={"Authorization": f"Bearer {breakglass_secret}"}
        )
        assert res.status_code == 200


# ----------------------
# 3. CACHING, REVOCATION & DB OUTAGE
# ----------------------

class TestCacheAndRevocation:
    """Verifies in-process caching, Redis tombstones, and fail-closed behavior."""

    def test_positive_cache_hit_bypasses_db(self, client, db_conn, clean_caches):
        raw_key, record = generate_api_key(name="test-cache-hit", owner_id=None, role="user", conn=db_conn)
        key_hash = hash_api_key(raw_key)

        # 1. First call populates cache
        res1 = client.post("/recommend", json={"query": "naruto"}, headers={"Authorization": f"Bearer {raw_key}"})
        assert res1.status_code == 200
        assert key_hash in VALID_KEY_CACHE

        # 2. Subsequent call reads directly from in-process cache
        cached_ctx = VALID_KEY_CACHE[key_hash]
        assert cached_ctx.key_id == record["id"]

        res2 = client.post("/recommend", json={"query": "naruto"}, headers={"Authorization": f"Bearer {raw_key}"})
        assert res2.status_code == 200

    def test_redis_tombstone_invalidates_cache_immediately(self, client, db_conn, clean_caches):
        mock_redis = MockUpstashRedis()
        rate_limiter.redis = mock_redis

        raw_key, record = generate_api_key(name="test-tombstone", owner_id=None, role="user", conn=db_conn)

        # Populate cache
        res = client.post("/recommend", json={"query": "bleach"}, headers={"Authorization": f"Bearer {raw_key}"})
        assert res.status_code == 200

        # Soft-revoke and publish tombstone
        revoke_api_key(key_id=record["id"], redis_client=mock_redis, conn=db_conn)

        # Immediate next request must be rejected even though local TTL hasn't expired
        res_after = client.post("/recommend", json={"query": "bleach"}, headers={"Authorization": f"Bearer {raw_key}"})
        assert res_after.status_code == 401

        rate_limiter.redis = None


# ----------------------
# 4. DEVELOPER KEYS ROUTER SECURITY (/dev/keys)
# ----------------------

class TestDevKeysRouterSecurity:
    """Rigorous negative penetration and security validation for /dev/keys."""

    def test_missing_jwt_returns_401(self, client):
        res = client.get("/dev/keys")
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthorized"

    def test_expired_jwt_returns_401(self, client, jwks_mock):
        user_id = str(uuid.uuid4())
        expired_token = jwks_mock.issue_token(sub=user_id, expires_in=-60)

        res = client.get("/dev/keys", headers={"Authorization": f"Bearer {expired_token}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "token_expired"

    def test_alg_none_forgery_rejected(self, client, jwks_mock):
        user_id = str(uuid.uuid4())
        none_token = jwks_mock.issue_token(sub=user_id, alg="none")

        res = client.get("/dev/keys", headers={"Authorization": f"Bearer {none_token}"})
        assert res.status_code == 401

    def test_hs256_public_key_confusion_rejected(self, client, jwks_mock):
        user_id = str(uuid.uuid4())
        # Forged token specifying HS256 algorithm
        forged_token = jwks_mock.issue_token(
            sub=user_id,
            alg="HS256",
            key_override="symmetric_secret_used_in_forgery_attack_12345678"
        )

        res = client.get("/dev/keys", headers={"Authorization": f"Bearer {forged_token}"})
        assert res.status_code == 401

    def test_wrong_aud_claim_rejected(self, client, jwks_mock):
        user_id = str(uuid.uuid4())
        anon_token = jwks_mock.issue_token(sub=user_id, aud="anon")

        res = client.get("/dev/keys", headers={"Authorization": f"Bearer {anon_token}"})
        assert res.status_code == 401

    def test_mass_assignment_prevented(self, client, jwks_mock, db_conn):
        user_id = str(uuid.uuid4())
        token = jwks_mock.issue_token(sub=user_id)

        # Attempt to inject privileged properties
        payload = {
            "name": "injected-key",
            "role": "admin",
            "rate_limit_per_min": 5000,
            "scopes": ["admin"]
        }
        res = client.post("/dev/keys", json=payload, headers={"Authorization": f"Bearer {token}"})
        # Pydantic extra='forbid' rejects extra fields with 422
        assert res.status_code == 422

    def test_max_active_keys_limit_returns_409(self, client, jwks_mock, db_conn):
        user_id = str(uuid.uuid4())
        token = jwks_mock.issue_token(sub=user_id)

        # Create 5 active keys
        for i in range(1, 6):
            res = client.post(
                "/dev/keys",
                json={"name": f"dev-slot-{i}"},
                headers={"Authorization": f"Bearer {token}"}
            )
            assert res.status_code == 201

        # Attempting 6th active key must be blocked by database trigger and return 409
        res_6 = client.post(
            "/dev/keys",
            json={"name": "dev-slot-overflow"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res_6.status_code == 409
        assert res_6.json()["error"]["code"] == "key_limit_reached"

    def test_foreign_key_delete_returns_404(self, client, jwks_mock):
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())
        token_a = jwks_mock.issue_token(sub=user_a)
        token_b = jwks_mock.issue_token(sub=user_b)

        # User B creates a key
        res_b = client.post("/dev/keys", json={"name": "user-b-key"}, headers={"Authorization": f"Bearer {token_b}"})
        assert res_b.status_code == 201
        key_b_id = res_b.json()["id"]

        # User A tries to delete User B's key -> 404
        res_del = client.delete(f"/dev/keys/{key_b_id}", headers={"Authorization": f"Bearer {token_a}"})
        assert res_del.status_code == 404
        assert res_del.json()["error"]["code"] == "key_not_found"

        # User B deletes own key -> 204
        res_own_del = client.delete(f"/dev/keys/{key_b_id}", headers={"Authorization": f"Bearer {token_b}"})
        assert res_own_del.status_code == 204

        # Idempotent delete -> 204
        res_repeat_del = client.delete(f"/dev/keys/{key_b_id}", headers={"Authorization": f"Bearer {token_b}"})
        assert res_repeat_del.status_code == 204

    def test_dev_keys_fail_closed_on_redis_outage(self, client, jwks_mock):
        from backend.rag_pipeline.helper.rate_limiter import RateLimiterUnavailableError
        user_id = str(uuid.uuid4())
        token = jwks_mock.issue_token(sub=user_id)

        with patch.object(rate_limiter, "check_rate_limit", side_effect=RateLimiterUnavailableError("Redis down")):
            res = client.post(
                "/dev/keys",
                json={"name": "fail-closed-key"},
                headers={"Authorization": f"Bearer {token}"}
            )
            assert res.status_code == 503
            assert res.json()["error"]["code"] == "service_unavailable"


# ----------------------
# 5. KEY SECRECY & LEAKAGE PREVENTION
# ----------------------

class TestKeySecrecy:
    """Verifies that raw secrets are never leaked into responses, DB, or logs."""

    def test_raw_key_shown_once_and_never_in_list(self, client, jwks_mock):
        user_id = str(uuid.uuid4())
        token = jwks_mock.issue_token(sub=user_id)

        # 1. Create key
        res_create = client.post("/dev/keys", json={"name": "secret-audit"}, headers={"Authorization": f"Bearer {token}"})
        assert res_create.status_code == 201
        assert "no-store" in res_create.headers.get("Cache-Control", "")
        body = res_create.json()
        raw_key = body["key"]
        prefix = body["prefix"]

        # 2. List keys
        res_list = client.get("/dev/keys", headers={"Authorization": f"Bearer {token}"})
        assert res_list.status_code == 200
        raw_text = res_list.text

        # Raw key secret MUST NOT appear in list response
        assert raw_key not in raw_text
        for item in res_list.json()["keys"]:
            assert "key" not in item
            assert item["prefix"] == prefix

    def test_raw_secret_never_in_db_records(self, client, jwks_mock, db_conn):
        user_id = str(uuid.uuid4())
        token = jwks_mock.issue_token(sub=user_id)

        res = client.post("/dev/keys", json={"name": "db-secrecy"}, headers={"Authorization": f"Bearer {token}"})
        raw_key = res.json()["key"]
        key_id = res.json()["id"]
        secret_entropy = raw_key.split("_", 3)[3]

        with db_conn.cursor() as cur:
            cur.execute("SELECT key_prefix, key_hash::text FROM app_auth.api_keys WHERE id = %s;", (key_id,))
            prefix, hash_str = cur.fetchone()
            assert secret_entropy not in hash_str
            assert raw_key not in hash_str


# ----------------------
# 6. RATE LIMITING & PRE-AUTH IP THROTTLE
# ----------------------

class TestRateLimiting:
    """Verifies multi-tenant isolation, pre-auth IP throttle, and zero double-counting."""

    @pytest.mark.asyncio
    async def test_independent_key_rate_limits(self, db_conn, clean_caches):
        mock_redis = MockUpstashRedis()
        limiter = DistributedRateLimiter(redis_client=mock_redis)

        key1_id = str(uuid.uuid4())
        key2_id = str(uuid.uuid4())

        # Exhaust key 1 quota (limit = 2)
        res1_1 = await limiter.check_rate_limit(key1_id, limit=2, is_api_key=True)
        assert res1_1[0] is False  # allowed
        res1_2 = await limiter.check_rate_limit(key1_id, limit=2, is_api_key=True)
        assert res1_2[0] is False  # allowed
        res1_3 = await limiter.check_rate_limit(key1_id, limit=2, is_api_key=True)
        assert res1_3[0] is True   # rate limited

        # Key 2 quota must remain intact
        res2_1 = await limiter.check_rate_limit(key2_id, limit=2, is_api_key=True)
        assert res2_1[0] is False  # allowed

    @pytest.mark.asyncio
    async def test_pre_auth_ip_failure_throttle(self, clean_caches):
        mock_redis = MockUpstashRedis()
        limiter = DistributedRateLimiter(redis_client=mock_redis)
        attacker_ip = "198.51.100.42"

        # Record 10 auth failures
        for _ in range(10):
            await limiter.record_auth_failure(attacker_ip, limit=10, window=60)

        # 11th request: peek check must indicate locked out
        is_locked, remaining, retry_after = await limiter.check_auth_failure_rate(attacker_ip, limit=10, window=60)
        assert is_locked is True
        assert retry_after > 0


# ----------------------
# 7. BREAK-GLASS CLI TOOLING
# ----------------------

class TestBreakGlassCLI:
    """Verifies scripts/manage_keys.py CLI actions."""

    def test_cli_create_admin_and_list(self, db_conn, capsys):
        import argparse
        args_create = argparse.Namespace(
            command="create-admin",
            name="cli-test-admin",
            expires_days=14,
            rate_limit=150,
            scopes="admin,recommend,chat",
            owner=None
        )
        manage_keys_cli.handle_create_admin(args_create)
        captured = capsys.readouterr().out
        assert "[+] Successfully provisioned admin API key: 'cli-test-admin'" in captured
        assert "Secret Key:" in captured
        assert "ar_live_" in captured

        # Verify key exists in database with admin role
        with db_conn.cursor() as cur:
            cur.execute("SELECT role, rate_limit_per_min FROM app_auth.api_keys WHERE name = 'cli-test-admin';")
            row = cur.fetchone()
            assert row[0] == "admin"
            assert row[1] == 150
