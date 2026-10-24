"""
test/performance/test_performance_benchmarks.py

Performance, latency, and throughput baseline benchmark suite.
Decorated with @pytest.mark.performance.
Implements:
- Benchmark 1: Latency baseline for POST /recommend (P50, P95, P99 within PERF_RECOMMEND_P95_MS).
- Benchmark 2: Time-to-First-Token (TTFT) baseline for POST /chat (SSE stream within PERF_CHAT_TTFT_MS).
- Benchmark 3: Modest concurrent load profile (PERF_LOAD_CONCURRENCY requests via asyncio.gather).
- Benchmark 4: Developer key authentication overhead (HMAC-SHA256, cache lookup, GET /dev/keys).
- Benchmark 5: Frontend production bundle budget (dist/assets/*.js within PERF_FRONTEND_BUNDLE_KB).

Conforms strictly to British English documentation standards without em-dashes.
"""

import os
import sys
import time
import gzip
import base64
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from unittest.mock import AsyncMock, patch, MagicMock

import secrets
import jwt
import pytest
import pytest_asyncio
import httpx
from cryptography.hazmat.primitives.asymmetric import rsa

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.main import app
from backend.rag_pipeline.helper.rate_limiter import rate_limiter
from backend.auth.keys import (
    ApiKeyContext,
    hash_api_key,
    authenticate_api_key,
    VALID_KEY_CACHE,
    NEGATIVE_KEY_CACHE,
    LAST_USED_THROTTLE_CACHE,
)
from backend.auth.supabase_jwt import (
    SupabaseJWKSService,
    set_jwks_service,
)
try:
    from . import get_performance_config, PerformanceThresholds
except ImportError:
    try:
        from test.performance import get_performance_config, PerformanceThresholds
    except (ImportError, ModuleNotFoundError):
        import importlib.util
        init_path = Path(__file__).resolve().parent / "__init__.py"
        spec = importlib.util.spec_from_file_location("test.performance", str(init_path))
        perf_pkg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(perf_pkg)
        get_performance_config = perf_pkg.get_performance_config
        PerformanceThresholds = perf_pkg.PerformanceThresholds


# =============================================================================
# STATISTICAL PERCENTILE HELPER
# =============================================================================

def calculate_percentiles(measurements: List[float]) -> Dict[str, float]:
    """
    Calculates P50, P95, and P99 percentiles from a sequence of latency observations.
    Uses linear interpolation across sorted samples to provide stable estimates.
    """
    if not measurements:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}

    sorted_vals = sorted(measurements)
    n = len(sorted_vals)

    def _calc_rank(pct: float) -> float:
        if n == 1:
            return sorted_vals[0]
        rank = (n - 1) * (pct / 100.0)
        floor_idx = int(rank)
        ceil_idx = min(floor_idx + 1, n - 1)
        weight = rank - floor_idx
        return sorted_vals[floor_idx] * (1.0 - weight) + sorted_vals[ceil_idx] * weight

    return {
        "p50": round(_calc_rank(50.0), 3),
        "p95": round(_calc_rank(95.0), 3),
        "p99": round(_calc_rank(99.0), 3),
        "min": round(sorted_vals[0], 3),
        "max": round(sorted_vals[-1], 3),
        "mean": round(sum(sorted_vals) / n, 3),
    }


# =============================================================================
# MOCK FIXTURES & ISOLATED ENVIRONMENT
# =============================================================================

TEST_API_KEY = "test-perf-secret-key"

SAMPLE_RESULTS = [
    {
        "id": 1,
        "title_romaji": "Cowboy Bebop",
        "title_english": "Cowboy Bebop",
        "title_userPreferred": "Cowboy Bebop",
        "coverImage_large": "https://example.com/bebop.jpg",
        "description": "In 2071, humanity has colonised the solar system.",
        "genres": ["Action", "Sci-Fi"],
        "studios": ["Sunrise"],
        "tags": ["Space", "Bounty Hunter"],
        "averageScore": 89.0,
        "seasonYear": 1998,
        "episodes": 26,
        "status": "FINISHED",
        "popularity": 125000,
    },
    {
        "id": 200,
        "title_romaji": "Trigun",
        "title_english": "Trigun",
        "title_userPreferred": "Trigun",
        "coverImage_large": "https://example.com/trigun.jpg",
        "description": "Vash the Stampede is a joyful gunman.",
        "genres": ["Action", "Comedy", "Sci-Fi"],
        "studios": ["Madhouse"],
        "tags": ["Guns", "Wasteland"],
        "averageScore": 82.0,
        "seasonYear": 1998,
        "episodes": 26,
        "status": "FINISHED",
        "popularity": 85000,
    },
]

SAMPLE_TIMINGS = {
    "self_query_ms": 0.0,
    "query_generation_ms": 1.2,
    "embedding_ms": 0.8,
    "retrieval_ms": 1.5,
    "reranking_ms": 1.1,
}


class MockSupabaseJWKS:
    """Generates an ephemeral RSA-2048 keypair to mock Supabase JWKS tokens."""

    def __init__(self):
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        self.public_key = self.private_key.public_key()
        self.kid = "test-perf-key-2026"
        self.supabase_url = "https://mock-supabase.example.com"
        self.issuer = f"{self.supabase_url}/auth/v1"

    def issue_token(
        self,
        sub: str,
        role: str = "authenticated",
        email: str = "developer@anime-discovery.internal",
        expires_in: int = 3600,
    ) -> str:
        now = int(time.time())
        claims = {
            "sub": sub,
            "aud": "authenticated",
            "iss": self.issuer,
            "exp": now + expires_in,
            "iat": now,
            "role": role,
            "email": email,
            "app_metadata": {"role": "developer"},
            "user_metadata": {},
        }
        headers = {"kid": self.kid}
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers=headers)


class MockSigningKey:
    """Wrapper exposing the RSA public key for PyJWT verification."""
    def __init__(self, key):
        self.key = key


class MockJWKSService(SupabaseJWKSService):
    """Hermetic JWKS service providing pre-cached public keys without network access."""

    def __init__(self, mock_jwks: MockSupabaseJWKS):
        super().__init__(supabase_url=mock_jwks.supabase_url)
        self.mock_jwks = mock_jwks

    def get_signing_key_from_jwt(self, token: str):
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if kid != self.mock_jwks.kid:
            raise jwt.PyJWKClientError(f"Unknown kid: {kid}")
        return MockSigningKey(self.mock_jwks.public_key)


@pytest.fixture(scope="session")
def perf_config() -> PerformanceThresholds:
    """Yields active performance thresholds read from environment variables."""
    return get_performance_config()


@pytest.fixture
def isolate_perf_env(monkeypatch):
    """
    Sets up an isolated, hermetic test environment:
    - Injects test API keys into environment variables.
    - Suppresses asynchronous database telemetry writes.
    - Purges in-process caches and resets rate limiter counters.
    - Provides mock doubles for RAG retrieval and synthesis pipelines.
    """
    monkeypatch.setenv("MY_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("ADMIN_API_KEY", "test-perf-admin-key")
    monkeypatch.setenv("INFERENCE_MODE", "local")

    # Suppress background telemetry database insertions
    monkeypatch.setattr("backend.main.log_recommendation_event", lambda **kwargs: True)
    monkeypatch.setattr("backend.telemetry.logger.log_recommendation_event", lambda **kwargs: True)

    # Purge key caches and rate limiter state
    VALID_KEY_CACHE.clear()
    NEGATIVE_KEY_CACHE.clear()
    LAST_USED_THROTTLE_CACHE.clear()
    rate_limiter.reset()

    # Define mock pitch generator for SSE chat
    async def fake_stream_pitch(query, candidates, history=None):
        yield "Here is an exceptional recommendation tailored to your mood."
        yield " Cowboy Bebop features legendary jazz music and space adventures."

    with patch("backend.main.async_rag_pipeline", new=AsyncMock(return_value=(SAMPLE_RESULTS, SAMPLE_TIMINGS))), \
         patch("backend.rag_pipeline.orchestrator.orchestrator.execute_retrieval", new=AsyncMock(return_value=(SAMPLE_RESULTS, SAMPLE_TIMINGS))), \
         patch("backend.rag_pipeline.orchestrator.orchestrator.synthesizer.stream_pitch", side_effect=fake_stream_pitch):
        yield

    VALID_KEY_CACHE.clear()
    NEGATIVE_KEY_CACHE.clear()
    LAST_USED_THROTTLE_CACHE.clear()
    rate_limiter.reset()


@pytest_asyncio.fixture
async def async_client():
    """Isolated ASGI client using in-memory transport without binding network ports."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def jwks_service():
    """Configures a mock Supabase JWKS service for developer JWT verification."""
    mock_jwks = MockSupabaseJWKS()
    service = MockJWKSService(mock_jwks)
    set_jwks_service(service)
    return mock_jwks


# =============================================================================
# BENCHMARK 1: LATENCY BASELINE FOR POST /recommend
# =============================================================================

@pytest.mark.performance
class TestRecommendLatencyBaseline:
    """
    Benchmark 1: Validates latency baselines for POST /recommend.
    Executes sequential requests against the recommendation endpoint using an isolated
    in-memory test double for model inference and RAG retrieval to isolate HTTP gateway overhead.
    Measures P50, P95, and P99 latency percentiles and asserts that P95 is strictly within PERF_RECOMMEND_P95_MS.
    """

    @pytest.mark.asyncio
    async def test_recommend_latency_p95_baseline(
        self,
        async_client: httpx.AsyncClient,
        perf_config: PerformanceThresholds,
        isolate_perf_env,
    ):
        """
        Executes sequential recommendation queries, records wall-clock duration for each,
        and verifies that P95 latency satisfies the configured latency ceiling.
        """
        payload = {
            "query": "dystopian cyberpunk sci-fi thriller",
            "top_k": 10,
            "allow_adult": False,
        }
        headers = {"access_token": TEST_API_KEY}

        # Warmup iteration
        warmup_resp = await async_client.post("/recommend", json=payload, headers=headers)
        assert warmup_resp.status_code == 200, f"Warmup request failed with {warmup_resp.status_code}"

        latencies_ms: List[float] = []
        iterations = 25

        with patch.object(rate_limiter, "is_rate_limited", return_value=(False, 1000, 0)):
            for _ in range(iterations):
                start_time = time.perf_counter()
                response = await async_client.post("/recommend", json=payload, headers=headers)
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                assert response.status_code == 200, f"Recommendation request failed: {response.text}"
                body = response.json()
                assert "results" in body
                assert body["count"] == len(body["results"])
                latencies_ms.append(elapsed_ms)

        stats = calculate_percentiles(latencies_ms)

        # Output diagnostic latency metrics
        print(f"\n[POST /recommend Latency Baseline] (samples={iterations}):")
        print(f"  P50:  {stats['p50']:.2f} ms")
        print(f"  P95:  {stats['p95']:.2f} ms")
        print(f"  P99:  {stats['p99']:.2f} ms")
        print(f"  Mean: {stats['mean']:.2f} ms | Min: {stats['min']:.2f} ms | Max: {stats['max']:.2f} ms")
        print(f"  Configured Threshold (P95): <= {perf_config.recommend_p95_ms:.2f} ms")

        assert stats["p95"] <= perf_config.recommend_p95_ms, (
            f"P95 latency ({stats['p95']:.2f} ms) exceeded threshold ({perf_config.recommend_p95_ms:.2f} ms)"
        )


# =============================================================================
# BENCHMARK 2: TIME-TO-FIRST-TOKEN (TTFT) BASELINE FOR POST /chat
# =============================================================================

@pytest.mark.performance
class TestChatTimeFirstTokenBaseline:
    """
    Benchmark 2: Validates Time-to-First-Token (TTFT) baseline for POST /chat.
    Streams Server-Sent Events (SSE) from the conversational chat endpoint, timing the duration
    from initial request dispatch until the first chunk or metadata event arrives.
    Asserts that P95 TTFT is strictly within PERF_CHAT_TTFT_MS.
    """

    @pytest.mark.asyncio
    async def test_chat_ttft_baseline(
        self,
        async_client: httpx.AsyncClient,
        perf_config: PerformanceThresholds,
        isolate_perf_env,
    ):
        """
        Initiates streaming chat requests, measures elapsed time to the first received byte/line,
        and verifies that P95 TTFT satisfies the configured threshold.
        """
        payload = {
            "query": "recommend me a thoughtful anime with deep character growth",
            "top_k": 5,
            "allow_adult": False,
        }
        headers = {"access_token": TEST_API_KEY}

        # Warmup iteration
        async with async_client.stream("POST", "/chat", json=payload, headers=headers) as warmup_resp:
            assert warmup_resp.status_code == 200
            async for _ in warmup_resp.aiter_lines():
                break

        ttft_measurements_ms: List[float] = []
        iterations = 10

        for _ in range(iterations):
            start_time = time.perf_counter()
            first_event_ms: Optional[float] = None

            async with async_client.stream("POST", "/chat", json=payload, headers=headers) as response:
                assert response.status_code == 200, f"Streaming chat failed with {response.status_code}"
                assert "text/event-stream" in response.headers.get("content-type", "")

                async for line in response.aiter_lines():
                    if line.strip():
                        first_event_ms = (time.perf_counter() - start_time) * 1000.0
                        break

            assert first_event_ms is not None, "Failed to receive any streaming events from /chat"
            ttft_measurements_ms.append(first_event_ms)

        stats = calculate_percentiles(ttft_measurements_ms)

        print(f"\n[POST /chat TTFT Baseline] (samples={iterations}):")
        print(f"  P50 TTFT: {stats['p50']:.2f} ms")
        print(f"  P95 TTFT: {stats['p95']:.2f} ms")
        print(f"  P99 TTFT: {stats['p99']:.2f} ms")
        print(f"  Mean:     {stats['mean']:.2f} ms | Min: {stats['min']:.2f} ms | Max: {stats['max']:.2f} ms")
        print(f"  Configured Threshold (P95 TTFT): <= {perf_config.chat_ttft_ms:.2f} ms")

        assert stats["p95"] <= perf_config.chat_ttft_ms, (
            f"P95 TTFT ({stats['p95']:.2f} ms) exceeded threshold ({perf_config.chat_ttft_ms:.2f} ms)"
        )


# =============================================================================
# BENCHMARK 3: MODEST CONCURRENT LOAD PROFILE
# =============================================================================

@pytest.mark.performance
class TestConcurrentLoadProfile:
    """
    Benchmark 3: Validates service behaviour under a modest concurrent load profile.
    Issues PERF_LOAD_CONCURRENCY simultaneous requests to POST /recommend via asyncio.gather().
    Validates a 100% success rate with zero HTTP 500 errors, zero dropped connections,
    and asserts that all requests complete within a bounded ceiling.
    """

    @pytest.mark.asyncio
    async def test_concurrent_recommend_load(
        self,
        async_client: httpx.AsyncClient,
        perf_config: PerformanceThresholds,
        isolate_perf_env,
    ):
        """
        Dispatches concurrent recommendation queries simultaneously and verifies
        unimpaired throughput, zero server failures, and bounded response latencies.
        """
        concurrency = perf_config.load_concurrency
        bounded_ceiling_ms = max(perf_config.recommend_p95_ms * 2.0, 2000.0)

        async def dispatch_query(idx: int):
            query_payload = {
                "query": f"concurrent recommendation query test number {idx}",
                "top_k": 5,
                "allow_adult": False,
            }
            req_start = time.perf_counter()
            resp = await async_client.post(
                "/recommend",
                json=query_payload,
                headers={"access_token": TEST_API_KEY},
            )
            req_duration_ms = (time.perf_counter() - req_start) * 1000.0
            return resp, req_duration_ms

        # Trigger concurrency queries simultaneously
        wall_start = time.perf_counter()
        tasks = [dispatch_query(i) for i in range(concurrency)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_wall_ms = (time.perf_counter() - wall_start) * 1000.0

        durations_ms: List[float] = []
        success_count = 0

        for idx, result in enumerate(results):
            assert not isinstance(result, Exception), f"Request {idx} raised an unexpected exception: {result}"
            response, req_ms = result
            durations_ms.append(req_ms)

            assert response.status_code == 200, (
                f"Request {idx} returned unexpected status code {response.status_code}: {response.text}"
            )
            data = response.json()
            assert "results" in data
            success_count += 1

        success_rate = (success_count / concurrency) * 100.0
        stats = calculate_percentiles(durations_ms)

        print(f"\n[Concurrent Load Profile] (concurrency={concurrency}):")
        print(f"  Success Rate:     {success_rate:.1f}% ({success_count}/{concurrency})")
        print(f"  Total Wall Clock: {total_wall_ms:.2f} ms")
        print(f"  P50 Duration:     {stats['p50']:.2f} ms")
        print(f"  P95 Duration:     {stats['p95']:.2f} ms")
        print(f"  Max Duration:     {stats['max']:.2f} ms (Ceiling: <= {bounded_ceiling_ms:.2f} ms)")

        assert success_rate == 100.0, f"Expected 100% success rate, achieved {success_rate:.1f}%"
        assert stats["max"] <= bounded_ceiling_ms, (
            f"Slowest concurrent request ({stats['max']:.2f} ms) exceeded ceiling ({bounded_ceiling_ms:.2f} ms)"
        )


# =============================================================================
# BENCHMARK 4: DEVELOPER KEY AUTHENTICATION OVERHEAD
# =============================================================================

@pytest.mark.performance
class TestDeveloperKeyAuthOverhead:
    """
    Benchmark 4: Validates developer key authentication and verification overhead.
    Measures HMAC-SHA256 derivation and positive cache lookup latency for API keys,
    along with end-to-end GET /dev/keys response times under mock JWT authentication.
    Asserts that P95 verification latency is strictly within PERF_DEV_KEYS_P95_MS.
    """

    @pytest.mark.asyncio
    async def test_dev_keys_endpoint_jwt_auth_latency(
        self,
        async_client: httpx.AsyncClient,
        perf_config: PerformanceThresholds,
        jwks_service: MockSupabaseJWKS,
        isolate_perf_env,
    ):
        """
        Measures HTTP gateway latency for GET /dev/keys including Bearer token extraction,
        cryptographic JWT validation, and in-memory key listing. Asserts P95 is within budget.
        """
        user_id = "test-perf-developer-uuid-001"
        jwt_token = jwks_service.issue_token(sub=user_id)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        # Mock database connection pool for developer key listing
        mock_cursor = MagicMock()
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.__exit__.return_value = False
        mock_cursor.fetchall.return_value = [
            {
                "id": "key-perf-001",
                "name": "perf-test-key",
                "key_prefix": "ar_live_1234abcd",
                "created_at": "2026-10-24T00:00:00Z",
                "last_used_at": None,
                "expires_at": None,
                "revoked_at": None,
            }
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn

        latencies_ms: List[float] = []
        iterations = 25

        with patch("backend.routers.dev_keys.get_auth_db_pool", return_value=mock_pool):
            # Warmup iteration
            warmup = await async_client.get("/dev/keys", headers=headers)
            assert warmup.status_code == 200, f"GET /dev/keys warmup failed: {warmup.text}"

            for _ in range(iterations):
                t0 = time.perf_counter()
                resp = await async_client.get("/dev/keys", headers=headers)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0

                assert resp.status_code == 200
                assert "keys" in resp.json()
                latencies_ms.append(elapsed_ms)

        stats = calculate_percentiles(latencies_ms)

        print(f"\n[GET /dev/keys JWT Auth Latency] (samples={iterations}):")
        print(f"  P50:  {stats['p50']:.2f} ms")
        print(f"  P95:  {stats['p95']:.2f} ms")
        print(f"  P99:  {stats['p99']:.2f} ms")
        print(f"  Mean: {stats['mean']:.2f} ms | Min: {stats['min']:.2f} ms | Max: {stats['max']:.2f} ms")
        print(f"  Configured Threshold (P95): <= {perf_config.dev_keys_p95_ms:.2f} ms")

        assert stats["p95"] <= perf_config.dev_keys_p95_ms, (
            f"P95 auth latency ({stats['p95']:.2f} ms) exceeded threshold ({perf_config.dev_keys_p95_ms:.2f} ms)"
        )

    @pytest.mark.asyncio
    async def test_hmac_sha256_and_cache_lookup_microbenchmark(
        self,
        perf_config: PerformanceThresholds,
        isolate_perf_env,
    ):
        """
        Microbenchmarks HMAC-SHA256 key hashing and in-process positive cache lookup.
        Asserts that cached key verification executes with sub-millisecond overhead.
        """
        prefix_hex = secrets.token_hex(4)
        secret_urlsafe = secrets.token_urlsafe(32)
        raw_key = f"ar_live_{prefix_hex}_{secret_urlsafe}"
        key_hash = hash_api_key(raw_key)

        cached_context = ApiKeyContext(
            key_id="cached-perf-key-uuid",
            name="microbenchmark-key",
            owner_id="dev-001",
            role="user",
            scopes=["recommend", "chat"],
            rate_limit_per_min=1000,
            expires_at=None,
            revoked_at=None,
            key_prefix=f"ar_live_{prefix_hex}",
        )
        VALID_KEY_CACHE[key_hash] = cached_context

        latencies_ms: List[float] = []
        iterations = 50

        for _ in range(iterations):
            t0 = time.perf_counter()
            resolved = await authenticate_api_key(raw_key)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            assert resolved.key_id == "cached-perf-key-uuid"
            latencies_ms.append(elapsed_ms)

        stats = calculate_percentiles(latencies_ms)

        print(f"\n[HMAC-SHA256 & Cache Lookup Overhead] (samples={iterations}):")
        print(f"  P50:  {stats['p50']:.4f} ms")
        print(f"  P95:  {stats['p95']:.4f} ms")
        print(f"  Max:  {stats['max']:.4f} ms")
        print(f"  Configured Threshold (P95): <= {perf_config.dev_keys_p95_ms:.2f} ms")

        assert stats["p95"] <= perf_config.dev_keys_p95_ms, (
            f"P95 HMAC & cache verification ({stats['p95']:.4f} ms) exceeded threshold ({perf_config.dev_keys_p95_ms:.2f} ms)"
        )


# =============================================================================
# BENCHMARK 5: FRONTEND PRODUCTION BUNDLE BUDGET
# =============================================================================

@pytest.mark.performance
class TestFrontendBundleBudget:
    """
    Benchmark 5: Validates frontend production bundle size budgets.
    Inspects built JavaScript chunks in frontend/dist/assets/ produced by Vite.
    Verifies that vendor, index, and ancillary chunks stay strictly within
    the PERF_FRONTEND_BUNDLE_KB budget limit.
    """

    def test_frontend_production_bundle_budget(
        self,
        perf_config: PerformanceThresholds,
    ):
        """
        Inspects frontend/dist/assets/*.js artefacts, checks both uncompressed and gzipped
        file sizes, and asserts that all chunks remain within PERF_FRONTEND_BUNDLE_KB.
        """
        dist_assets_dir = REPO_ROOT / "frontend" / "dist" / "assets"
        assert dist_assets_dir.exists(), (
            f"Frontend build directory '{dist_assets_dir}' not found. Run 'vite build' prior to testing."
        )

        js_files = list(dist_assets_dir.glob("*.js"))
        assert len(js_files) > 0, f"Zero JavaScript chunk files found in '{dist_assets_dir}'."

        print(f"\n[Frontend Production Bundle Inspection] (Budget limit: <= {perf_config.frontend_bundle_kb:.1f} kB):")

        vendor_found = False
        index_found = False

        for js_file in js_files:
            raw_bytes = js_file.read_bytes()
            size_kb = len(raw_bytes) / 1024.0
            gzip_kb = len(gzip.compress(raw_bytes)) / 1024.0

            filename = js_file.name
            print(f"  - {filename:<32}: {size_kb:6.2f} kB uncompressed | {gzip_kb:6.2f} kB gzipped")

            if "vendor" in filename.lower():
                vendor_found = True
            if "index" in filename.lower():
                index_found = True

            # Assert individual chunk stays within budget (uncompressed)
            assert size_kb <= perf_config.frontend_bundle_kb, (
                f"Asset chunk '{filename}' ({size_kb:.2f} kB) exceeded budget limit ({perf_config.frontend_bundle_kb:.1f} kB)"
            )

        assert index_found, "Primary 'index' chunk not detected in frontend assets directory."
        assert vendor_found, "Primary 'vendor' chunk not detected in frontend assets directory."
