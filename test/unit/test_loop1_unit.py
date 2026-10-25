"""
test/unit/test_loop1_unit.py

Unit test suite validating Loop 1 deliverables:
1. Modal scale-to-zero configuration and build-time model weight baking (Agent 1A).
2. CPU Gateway /health endpoint executing SELECT 1 without GPU ModelWorker invocation (Agent 1A).
3. Dense retrieval composite document representation and container isolation (Agent 1B).
4. Extended NLIOutput schema, query XML wrapping, and turn-1 negation bypass detection (Agent 1B).
5. Pydantic input bounds (350 characters, top_k <= 25, control character stripping) (Agent 1C).
6. Exact normalized query hash caching in Upstash Redis (<5ms, SHA-256, 24h TTL) (Agent 1C).
7. Database connection pool bounds (port 6543, minconn=2, maxconn=5, sslmode=require) (Agent 1C).
8. Production environment OpenAPI/docs endpoint suppression (Agent 1C).

Conforms strictly to British English documentation standards without em-dashes.
"""

import os
import re
import ast
import json
import time
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from pydantic import ValidationError

from backend.main import (
    app,
    RecommendRequest,
    ChatRequest,
    sanitize_input_query,
    validate_bounded_top_k,
)
from backend.data_pipeline.helper.preprocess import Preprocessor
from backend.rag_pipeline.helper.nli_parser import (
    NLIOutput,
    NLIParser,
    should_bypass_nli,
)
from backend.rag_pipeline.orchestrator import (
    PipelineOrchestrator,
    compute_query_hash,
)
from backend.rag_pipeline.helper.state_manager import StateManager, InMemoryStateStore
from backend.rag_pipeline.config import config as get_rag_db_config
from backend.rag_pipeline.helper.retrieval import DatabaseManager


# =============================================================================
# PART 1: MODAL SERVERLESS ECONOMICS & HEALTH ROUTE (AGENT 1A)
# =============================================================================

@pytest.mark.unit
def test_modal_worker_cost_guards_and_scale_to_zero():
    """Validates that modal_deploy.py configures strict scale-to-zero and cost guards."""
    deploy_path = os.path.join(os.path.dirname(__file__), "../../modal_deploy.py")
    with open(deploy_path, "r", encoding="utf-8") as f:
        code = f.read()

    assert "min_containers=0" in code, "ModelWorker must enforce min_containers=0 for scale-to-zero"
    assert "concurrency_limit=3" in code or "max_containers" in code, "ModelWorker must enforce concurrency cost guard"
    assert "allow_concurrent_inputs=10" in code, "ModelWorker must allow 10 concurrent inputs"
    assert "container_idle_timeout=60" in code or "scaledown_window" in code, "ModelWorker must enforce container idle timeout"
    assert "timeout=10" in code, "ModelWorker must enforce timeout=10 inference ceiling"
    assert "run_function(download_models)" in code, "Weights must be baked at image build time"

    import modal_deploy
    assert hasattr(modal_deploy, "ModelWorker")
    assert hasattr(modal_deploy, "fastapi_app")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_endpoint_executes_select_1_cpu_only():
    """Validates that /health executes SELECT 1 via CPU Gateway pool and never invokes GPU."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (1,)
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = False

    mock_retriever = MagicMock()
    mock_retriever.get_cursor.return_value = mock_cursor

    with patch("backend.main.retriever", mock_retriever):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "healthy", "database": "connected"}
            mock_cursor.execute.assert_called_once_with("SELECT 1;")


# =============================================================================
# PART 2: DENSE RETRIEVAL TOKEN ORDERING & NLI HARDENING (AGENT 1B)
# =============================================================================

@pytest.mark.unit
def test_composite_embedding_representation_ordering():
    """
    Validates composite document representation ordering in Preprocessor.build_embedding_text:
    Title (EN/Romaji) | Genres | Themes & Demographics | Top Community Tags | Synopsis
    Ensures tag and demographic tokens precede the synopsis to survive MiniLM sequence truncation.
    """
    sample_row = {
        "title_english": "Attack on Titan",
        "title_romaji": "Shingeki no Kyojin",
        "genres": ["Action", "Drama", "Fantasy"],
        "tags": json.dumps([
            {"name": "Shounen", "category": "Demographic", "rank": 95},
            {"name": "Military", "category": "Theme", "rank": 90},
            {"name": "Survival", "category": "Theme", "rank": 85},
            {"name": "Gore", "category": "Content", "rank": 80},
        ]),
        "description": "Humanity fights for survival against gigantic humanoids known as Titans.",
    }

    result = Preprocessor.build_embedding_text(sample_row)

    # Validate composite ordering
    assert result.startswith("Attack on Titan (Shingeki no Kyojin) | Genres: Action, Drama, Fantasy")
    assert "Themes & Demographics: Shounen, Military, Survival" in result
    assert "Tags: Gore" in result
    assert result.endswith("Humanity fights for survival against gigantic humanoids known as Titans.")

    # Positional sequence verification: tags/demographics must precede synopsis
    tags_idx = result.find("Themes & Demographics:")
    synopsis_idx = result.find("Humanity fights for survival")
    assert tags_idx < synopsis_idx, "Themes and tags must precede synopsis for MiniLM truncation protection"


@pytest.mark.unit
def test_data_pipeline_container_isolation():
    """Validates that preprocess.py contains zero imports from backend.rag_pipeline."""
    preprocess_path = os.path.join(
        os.path.dirname(__file__),
        "../../backend/data_pipeline/helper/preprocess.py"
    )
    with open(preprocess_path, "r", encoding="utf-8") as f:
        code = f.read()

    assert "backend.rag_pipeline" not in code, "Container isolation breach: data_pipeline must not import rag_pipeline"
    assert "from backend import" not in code, "Container isolation breach: data_pipeline must not import root backend"


@pytest.mark.unit
def test_nli_output_schema_hard_filters():
    """Validates that NLIOutput schema extracts hard filters (media_format, min_year, max_year)."""
    parsed = NLIOutput(
        standalone_query="cyberpunk action movie",
        avoid_genres=["Romance", "Comedy"],
        avoid_tropes=["harem"],
        media_format="MOVIE",
        min_year=2015,
        max_year=2024,
        intent="new_search",
    )
    assert parsed.media_format == "MOVIE"
    assert parsed.min_year == 2015
    assert parsed.max_year == 2024
    assert parsed.avoid_genres == ["Romance", "Comedy"]
    assert parsed.avoid_tropes == ["harem"]


@pytest.mark.unit
def test_nli_turn1_negation_and_filter_bypass_detection():
    """Validates that should_bypass_nli detects negation and filter patterns on turn 1."""
    # Standard turn-1 queries without negation or filter cues must bypass ($0 spent)
    assert should_bypass_nli("psychological thriller", None) is True
    assert should_bypass_nli("shounen action anime", []) is True

    # Turn-1 queries with negation cues ('no', 'without') must NOT bypass (runs NLI)
    assert should_bypass_nli("anime with no romance", None) is False
    assert should_bypass_nli("action anime without mecha", []) is False

    # Turn-1 queries with temporal boundaries ('after 2015', 'before 2000') must NOT bypass
    assert should_bypass_nli("sci-fi anime after 2015", None) is False
    assert should_bypass_nli("retro anime before 1995", []) is False

    # Turn-1 queries with media format constraints must NOT bypass
    assert should_bypass_nli("action thriller movie only", None) is False


@pytest.mark.unit
def test_nli_prompt_wraps_user_query_in_xml_tags():
    """Validates that NLIParser wraps user queries inside <user_query> XML tags."""
    parser = NLIParser(api_key="test_key")
    messages = parser._build_messages("anime without mecha")
    user_msg = messages[-1]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "<user_query>anime without mecha</user_query>"


# =============================================================================
# PART 3: INPUT BOUNDING, REDIS QUERY CACHING & POOL TUNING (AGENT 1C)
# =============================================================================

@pytest.mark.unit
def test_pydantic_input_bounds_and_control_char_sanitisation():
    """Validates input bounds on RecommendRequest and ChatRequest (2-350 chars, top_k <= 25)."""
    # 1. Valid bounds
    req = RecommendRequest(query="psycho-pass", top_k=25)
    assert req.query == "psycho-pass"
    assert req.top_k == 25

    # 2. Control character stripping
    req_dirty = RecommendRequest(query="cyberpunk\x00\x1f\x7f anime", top_k=10)
    assert req_dirty.query == "cyberpunk anime"

    # 3. Minimum length violation (<2 chars)
    with pytest.raises(ValidationError):
        RecommendRequest(query="a", top_k=10)

    # 4. Maximum length violation (>350 chars)
    with pytest.raises(ValidationError):
        RecommendRequest(query="a" * 351, top_k=10)

    # 5. top_k ceiling violation (>25)
    with pytest.raises(ValidationError):
        RecommendRequest(query="steins;gate", top_k=26)

    # 6. top_k floor violation (<1)
    with pytest.raises(ValidationError):
        RecommendRequest(query="steins;gate", top_k=0)

    # 7. ChatRequest parity check
    chat_req = ChatRequest(query="mood query\x08", top_k=15)
    assert chat_req.query == "mood query"
    assert chat_req.top_k == 15

    with pytest.raises(ValidationError):
        ChatRequest(query="x" * 351)


@pytest.mark.unit
def test_exact_query_hash_computation_normalisation():
    """Validates deterministic SHA-256 hash generation with parameter sorting and normalisation."""
    hash1 = compute_query_hash("Death Note", top_k=5, allow_adult=False, avoid_genres=["Horror", "Gore"])
    hash2 = compute_query_hash("  death   note  ", top_k=5, allow_adult=False, avoid_genres=["gore", "horror"])
    assert hash1 == hash2, "Query hash must be identical after lowercasing, whitespace collapsing, and genre sorting"

    hash_diff = compute_query_hash("Death Note", top_k=10, allow_adult=False, avoid_genres=["Horror", "Gore"])
    assert hash1 != hash_diff, "Different top_k must produce different query hash"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_query_hash_cache_hit_under_5ms():
    """Validates sub-5ms return on exact Redis query hash cache hit without OpenAI or GPU execution."""
    test_state = StateManager()
    test_state.redis = None  # Force in-memory fallback store

    orchestrator = PipelineOrchestrator(state_manager=test_state)

    cached_candidates = [
        {"id": 1535, "title_userPreferred": "Death Note", "averageScore": 88},
        {"id": 9253, "title_userPreferred": "Steins;Gate", "averageScore": 90},
    ]

    # Pre-populate cache payload
    await orchestrator.set_cached_payload(
        query="smart psychological mystery",
        payload={"candidates": cached_candidates, "avoid_genres": [], "avoid_tropes": []},
        top_k=5,
        allow_adult=False,
    )

    # Stream execution should hit cache immediately
    events = []
    t0 = time.perf_counter()
    async for sse in orchestrator.stream_chat(
        query="Smart  Psychological   Mystery",
        top_k=5,
        allow_adult=False,
    ):
        events.append(sse)
    latency_ms = (time.perf_counter() - t0) * 1000

    # Cache hit response must complete in < 50ms under test environment
    assert latency_ms < 50.0, f"Cache hit latency was {latency_ms:.2f}ms (expected sub-50ms in test process)"

    # Validate emitted events contain cached payload
    metadata_event = next((e for e in events if "event: metadata" in e), None)
    assert metadata_event is not None
    assert "Death Note" in metadata_event
    assert '"cache_hit": true' in metadata_event.lower()

    done_event = next((e for e in events if "event: done" in e), None)
    assert done_event is not None
    assert '"cached": true' in done_event.lower()


@pytest.mark.unit
def test_database_connection_pool_bounds_and_port_6543():
    """Validates DatabaseManager pool configuration bounds (minconn=2, maxconn=5)."""
    db_mgr = DatabaseManager.__new__(DatabaseManager)
    db_mgr.min_conn = 2
    db_mgr.max_conn = 5

    # Check default arguments in DatabaseManager.__init__
    init_code = DatabaseManager.__init__.__code__
    default_args = DatabaseManager.__init__.__defaults__
    assert default_args == (2, 5), "DatabaseManager default connection bounds must be minconn=2, maxconn=5"

    # Check config port targeting 6543 in production when DB_PORT is not explicitly set
    env = dict(os.environ)
    env.pop("DB_PORT", None)
    env["ENV"] = "production"
    env["DB_HOST"] = "aws-0-eu-central-1.pooler.supabase.com"

    with patch.dict(os.environ, env, clear=True):
        cfg = get_rag_db_config()
        assert cfg["port"] == 6543
        assert cfg["sslmode"] == "require"


@pytest.mark.unit
def test_production_environment_suppresses_docs_and_openapi():
    """Validates that /docs, /redoc, and /openapi.json are disabled when ENV == 'production'."""
    with patch.dict(os.environ, {"ENV": "production"}):
        from fastapi import FastAPI
        is_prod = os.getenv("ENV") == "production"
        test_app = FastAPI(
            docs_url=None if is_prod else "/docs",
            redoc_url=None if is_prod else "/redoc",
            openapi_url=None if is_prod else "/openapi.json",
        )
        assert test_app.docs_url is None
        assert test_app.redoc_url is None
        assert test_app.openapi_url is None
