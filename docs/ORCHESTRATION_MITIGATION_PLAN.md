# Sprint Mitigation Plan: Orchestration & Intelligence Layer Implementation

**Document Status:** Production-Ready Architectural & Operational Specification  
**Target Systems:** Anime Recommender System (`iamcbn/anime-recommender`)  
**Deployment Infrastructure:** Modal Serverless, Supabase PostgreSQL (`pgvector`), OpenAI API, Upstash Redis  
**Author:** Principal Systems Architect & Cloud Infrastructure Auditor  
**Created:** October 2026  

---

## Executive Overview & Strategic Context

The architectural evaluation report (`orchestration_intelligence_layer_report.md`) established the domain necessity of an **Orchestration & Intelligence Layer** for conversational anime discovery. However, a rigorous cloud infrastructure and concurrency audit identified five critical system bottlenecks that would destabilize the existing production platform if implemented naively:

1. **Modal Serverless Monolith & GPU Waste:** The entire FastAPI application currently runs inside a single `gpu="T4"` container (`modal_deploy.py`). Running external OpenAI HTTPS round-trips (HyDE expansion + Grounded Synthesis) inside this container forces the GPU to sit idle for >90% of the request wall-clock time, inflating serverless compute costs by over 700%.
2. **FastAPI Event Loop Starvation:** Executing synchronous OpenAI API calls and synchronous PyTorch/`ThreadPoolExecutor` operations inside `async def` endpoints locks the single-threaded asyncio event loop, causing catastrophic latency compounding and HTTP 504 timeouts under concurrent load.
3. **Database Connection Pool Exhaustion:** `DatabaseManager` runs 9 parallel queries per RAG request using a `ThreadedConnectionPool(minconn=2, maxconn=10)`. Two concurrent requests immediately exhaust the pool, triggering unhandled `psycopg2.pool.PoolError` crashes.
4. **Ephemeral State Amnesia in Serverless:** Proposed "in-memory LRU" session storage fails across ephemeral Modal containers and multi-instance autoscaling. Furthermore, `llm_cache.py` is explicitly disabled in production Modal (`DISABLE_LLM_CACHE=true`), meaning no query caching currently operates in the cloud.
5. **Streaming vs. Structured Outputs Architectural Clash:** OpenAI's Pydantic Structured Outputs (`client.beta.chat.completions.parse`) requires full completion assembly before validation, making true token-by-token Server-Sent Events (SSE) streaming impossible without a dual-stream architecture.

This **Sprint Mitigation Plan** decomposes the remediation and implementation into **four decoupled, production-grade sprints**. Each sprint delivers self-contained, tested, and benchmarked capabilities while guaranteeing backward compatibility with existing headless `/recommend` consumers.

---

## Architecture Transformation Roadmap

```
CURRENT MONOLITHIC TOPOLOGY (Vulnerable):
┌─────────────────────────────────────────────────────────────────────────────┐
│ Modal Container (gpu="T4") [$0.59/hr]                                       │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ FastAPI ASGI App (backend/main.py)                                      │ │
│ │  - async def recommend() [BLOCKS EVENT LOOP]                            │ │
│ │  - In-memory RateLimiter (Lost on cold-start)                           │ │
│ │  - ThreadedConnectionPool(maxconn=10) [CRASHES on 2 concurrent requests]│ │
│ │  - SBERT & Cross-Encoder PyTorch Inference                              │ │
│ │  - OpenAI HyDE & Synthesizer [GPU SITS IDLE WAITING ON NETWORK I/O]     │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘

TARGET DECOUPLED PRODUCTION ARCHITECTURE (Resilient & Cost-Optimized):
┌─────────────────────────────────────────────────────────────────────────────┐
│ Gateway Tier: Modal CPU App (@app.asgi_app) [cpu=1.0, RAM=1GB] [$0.05/hr]   │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ FastAPI Non-Blocking Async Engine                                       │ │
│ │  - Redis Sliding-Window Rate Limiter (Upstash)                          │ │
│ │  - Multi-Turn Session Memory & User State Manager (Upstash)             │ │
│ │  - Domain Guardrails Engine (Pre-retrieval scope & injection checks)    │ │
│ │  - AsyncOpenAI HyDE Query Generator                                     │ │
│ │  - Dual-Stream SSE Response Generator (Immediate Cards + Streamed Pitch)│ │
│ └────────────────────────────────────┬────────────────────────────────────┘ │
└──────────────────────────────────────┼──────────────────────────────────────┘
                                       │ Modal RPC (Micro-batched, Zero I/O Wait)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Inference Tier: Modal Model Worker (@app.cls) [gpu="T4", RAM=8GB]           │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Pinned CUDA PyTorch Models (Warm instances, Scales to Zero)             │ │
│ │  - SBERT Embeddings Batcher                                             │ │
│ │  - Cross-Encoder Reranker (mmarco-mMiniLMv2)                            │ │
│ └────────────────────────────────────┬────────────────────────────────────┘ │
└──────────────────────────────────────┼──────────────────────────────────────┘
                                       │ Async Connection Pool (Max 3 workers/req)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ External Persistence & Managed Services                                     │
│  - Supabase PostgreSQL (via PgBouncer Transaction Pooler on port 6543)     │
│  - Upstash Redis (Serverless HTTP/REST connection for State & Cache)        │
│  - OpenAI API (gpt-5.4-mini for HyDE and Taste Concierge Pitch)             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Sprint 1: Pipeline Hardening, Metadata Enrichment & DB Pool Resilience

### 1. Sprint Objective & Scope
Eliminate connection pool crashes, isolate destructive startup DDL migrations from container lifecycles, and enrich candidate payloads directly within the primary retrieval stage so that subsequent synthesis requires no secondary database hits.

### 2. Target Files & Architectural Changes
- `backend/rag_pipeline/helper/retrieval.py`: Bounded concurrency execution, connection checkout timeout, and Supabase PgBouncer pooler integration.
- `backend/rag_pipeline/rag_pipeline.py`: Remove startup DDL execution (`ensure_bm25_index`) from module import.
- `backend/migrations/001_bm25_index_and_metadata.py`: Dedicated, safe, idempotent database migration script.
- `backend/rag_pipeline/config.py`: Explicit pooler port and timeout settings.
- `backend/rag_pipeline/helper/ranking.py`: Enrich deduplicated candidate dictionaries with all grounding fields (synopsis, studios, genres, averageScore, year, format).

### 3. Concrete Implementation Tasks & User Stories

#### Task 1.1: Supabase PgBouncer Integration & Connection Pool Hardening
- **User Story:** As an API service under concurrent traffic, I want database queries to reuse a managed transaction pool with graceful wait queues so that requests do not crash with `PoolError: connection pool exhausted`.
- **Implementation Detail:**
  1. In `retrieval.py`, modify `DatabaseManager.__init__` to support non-blocking connection acquisition with a 5.0-second timeout.
  2. Bounded ThreadPool: In `retrieval.py:execute()`, constrain concurrent search worker threads to `max_workers=3` (or execute vector searches sequentially per query while batching) instead of spawning 9 simultaneous threads.
  3. Ensure database credentials in `config.py` default to port `6543` (Supabase PgBouncer transaction mode) rather than direct port `5432`.

```python
# Refactored DatabaseManager.get_cursor with timeout handling
@contextmanager
def get_cursor(self, timeout: float = 5.0):
    start_time = time.time()
    conn = None
    while conn is None:
        try:
            conn = self._pool.getconn()
        except PoolError:
            if time.time() - start_time > timeout:
                raise TimeoutError("Database connection pool checkout timed out after 5.0s")
            time.sleep(0.05)
    try:
        with conn:
            with conn.cursor() as cur:
                yield cur
    finally:
        self._pool.putconn(conn)
```

#### Task 1.2: Decouple DDL Migrations from Server Startup
- **User Story:** As a cloud operator scaling serverless containers, I want container startup to perform zero table modifications so that simultaneous cold-starts do not lock database tables or cause deadlock errors.
- **Implementation Detail:**
  1. Remove `retriever.ensure_bm25_index()` from the module initialization in `backend/rag_pipeline/rag_pipeline.py` (Line 26).
  2. Create `backend/migrations/001_bm25_index_and_metadata.py` to run via CI/CD before any deployment.

#### Task 1.3: Candidate Metadata Enrichment for Grounded Synthesis
- **User Story:** As an LLM synthesizer, I require complete candidate context (studios, episodes, formats, scores) directly in the reranked candidate dictionary so that I can generate grounded pitches without additional database lookups.
- **Implementation Detail:**
  1. Expand the SQL projection in `semantic_search` and `bm25_search` (`retrieval.py`) to include `content.genres`, `content.studios`, `metrics.averageScore`, and `temporal.seasonYear`.
  2. Update `merge_deduplicate` in `ranking.py` to preserve these fields into the final top-$K$ candidate list.

### 4. Acceptance Criteria & Verification Tests
- **AC 1.1:** 10 simulated concurrent requests to `/recommend` execute without a single `PoolError` or database timeout.
- **AC 1.2:** Module import time of `rag_pipeline.py` drops by >50ms and emits zero DDL statements (`ALTER TABLE`, `CREATE INDEX`).
- **AC 1.3:** Output candidates from `rag_pipeline()` include `studios`, `genres`, `averageScore`, and `synopsis` populated for 100% of returned items.
- **Verification Commands:**
  ```powershell
  # Run concurrent load test on retrieval pool
  pytest test/benchmarks/test_retrieval_concurrency.py -v -k "test_concurrent_pool_saturation"
  ```

### 5. Risk Register, Failure Modes & Rollback Strategy
| Risk / Failure Mode | Likelihood | Impact | Mitigation Strategy | Rollback Trigger |
| :--- | :--- | :--- | :--- | :--- |
| PgBouncer transaction mode drops named prepared statements | Medium | High | Use unprepare/direct statement mode in psycopg2 (`cursor_factory=extras.DictCursor`) | Queries fail with `prepared statement does not exist` -> Revert to session pooler port 5432 with maxconn=15 |
| Metadata joins increase single-query execution time > 50ms | Low | Medium | Ensure foreign key indexes exist on `anime_content.id`, `anime_metrics.id`, `anime_temporal.id` | Single-query latency increases by >25% -> Drop optional temporal columns |

---

## Sprint 2: Modal Infrastructure Decoupling & Async Concurrency Engine

### 1. Sprint Objective & Scope
Decouple the monolithic Modal deployment into a high-concurrency, low-cost CPU Gateway container and an on-demand, GPU-accelerated PyTorch Inference Actor. Eliminate FastAPI event loop starvation by converting the pipeline to non-blocking async execution.

### 2. Target Files & Architectural Changes
- `modal_deploy.py`: Decompose into `@app.asgi_app` (CPU) and `@app.cls(gpu="T4")` (`ModelWorker`).
- `backend/rag_pipeline/helper/query_generator.py`: Refactor to `AsyncOpenAI` with non-blocking calls.
- `backend/main.py`: Refactor `async def recommend` and new endpoints to yield properly to the event loop.
- `backend/rag_pipeline/rag_pipeline.py`: Asynchronous pipeline orchestrator (`async_rag_pipeline`).

### 3. Concrete Implementation Tasks & User Stories

#### Task 2.1: Modal Architecture Decomposition
- **User Story:** As a cloud finance manager, I want the system to avoid billing T4 GPU time while waiting for external OpenAI HTTP calls so that operational costs remain strictly proportional to real inference workloads.
- **Implementation Detail:**
  1. Define `ModelWorker` class in `modal_deploy.py` decorated with `@app.cls(gpu="T4", timeout=300, keep_warm=1)`.
  2. Mount model volumes and load `Embedder` and `Ranker` once inside `__enter__` on the GPU worker.
  3. Define `fastapi_app` on a standard CPU container (`cpu=1.0, memory=1024`). The CPU gateway invokes `ModelWorker().rerank.remote(...)` or `ModelWorker().embed.remote(...)`.

```python
# modal_deploy.py (Decoupled Architecture)
import modal

app = modal.App("anime-recommender-api")
image = ... # Standard base image
volume = modal.Volume.from_name("anime-models-vol")

@app.cls(gpu="T4", volumes={"/root/backend/models": volume}, keep_warm=1)
class ModelWorker:
    @modal.enter()
    def load_models(self):
        from backend.rag_pipeline.helper.service_embedding import Embedder
        from backend.rag_pipeline.helper.ranking import Ranker
        self.embedder = Embedder()
        self.ranker = Ranker()

    @modal.method()
    def embed_queries(self, queries: list[str]):
        return self.embedder.execute(queries=queries)

    @modal.method()
    def rerank_candidates(self, query: str, candidates: list, top_k: int):
        return self.ranker.execute(user_query=query, all_results=candidates, top_k=top_k)

@app.function(image=image, secrets=[...], cpu=1.0, memory=1024)
@modal.asgi_app()
def fastapi_app():
    from backend.main import app as web_app
    return web_app
```

#### Task 2.2: Async Query Generator (`AsyncOpenAI`)
- **User Story:** As an API gateway processing concurrent requests, I want HyDE query generation to run asynchronously without blocking the event loop so that other incoming requests can be accepted simultaneously.
- **Implementation Detail:**
  1. Refactor `QueryGenerator` in `query_generator.py` to use `openai.AsyncOpenAI`.
  2. Implement `async def generate_async(self, user_query: str) -> list[str]`.
  3. Ensure failure gracefully returns `[user_query]` without throwing unhandled exceptions.

#### Task 2.3: Non-Blocking Event Loop in FastAPI Endpoints
- **User Story:** As an end user, I want my API requests to process concurrently without experiencing queue delays caused by other users' heavy queries.
- **Implementation Detail:**
  1. Wrap CPU/Database blocking operations (`DatabaseManager.execute`) in `asyncio.to_thread` to ensure worker threads do not starve the asyncio loop.
  2. Convert `backend/main.py` route handlers to await the async pipeline.

### 4. Acceptance Criteria & Verification Tests
- **AC 2.1:** Active GPU billing duration for a complete `/recommend` request drops from >3,500ms to <350ms.
- **AC 2.2:** FastAPI event loop lag during peak load remains under **15 milliseconds** (verified via `asyncio` loop lag monitor).
- **AC 2.3:** Running 20 concurrent requests produces an average response time of <2.2 seconds per request, with zero 504 timeouts.
- **Verification Benchmark Script:**
  ```powershell
  # Run locust load test verifying concurrency
  locust -f test/benchmarks/locustfile.py --headless -u 20 -r 5 --run-time 1m --host http://localhost:8000
  ```

### 5. Risk Register, Failure Modes & Rollback Strategy
| Risk / Failure Mode | Likelihood | Impact | Mitigation Strategy | Rollback Trigger |
| :--- | :--- | :--- | :--- | :--- |
| Modal RPC serialization overhead between CPU and GPU | Low | Medium | Pass raw string queries and scalar candidate rows; avoid serializing complex Pandas DataFrames | RPC latency overhead > 250ms -> Re-consolidate to single container with async threads |
| AsyncOpenAI network socket leak under extreme load | Low | High | Use a single module-level `AsyncOpenAI` instance with shared HTTP connection pool (`httpx.AsyncClient(limits=...)`) | Socket exhaustion / `Too many open files` -> Cap maximum client connections to 50 |

---

## Sprint 3: Hardened Guardrails, Dual-Stream SSE Synthesis & Resilience

### 1. Sprint Objective & Scope
Implement the full Conversational Orchestration layer featuring dual-mode dispatch (`/recommend` headless vs. `/chat` conversational), active multi-tier guardrails (prompt injection, out-of-scope, spoiler scrubbers, low-confidence fallback), and a **Dual-Stream SSE protocol** that renders metadata cards immediately while streaming conversational rationale tokens.

### 2. Target Files & Architectural Changes
- New: `backend/rag_pipeline/helper/guardrails.py`: Production-grade regex and confidence threshold engine.
- New: `backend/rag_pipeline/helper/synthesizer.py`: Async streaming recommendation taste concierge.
- New: `backend/rag_pipeline/orchestrator.py`: Typed pipeline orchestrator coordinating Intent -> Retrieval -> Synthesis.
- `backend/main.py`: Add `POST /chat` with `StreamingResponse(media_type="text/event-stream")`.

### 3. Concrete Implementation Tasks & User Stories

#### Task 3.1: Production Domain Guardrails & Active Spoiler Scrubbing
- **User Story:** As a service owner, I want out-of-domain prompts and prompt injections rejected immediately, and I want generated pitches scrubbed for spoilers, so that safety and quality are guaranteed.
- **Implementation Detail:**
  1. In `guardrails.py`, build compiled pre-retrieval patterns for non-anime queries, jailbreaks, and system prompt extractors.
  2. Implement `check_retrieval_confidence(results)`: If top Cross-Encoder score is $< -6.5$, trigger a graceful fallback recommending query refinement.
  3. Implement active post-synthesis spoiler scrubber: Clean out accidental plot twist reveals (`dies`, `killer`, `final outcome`) using keyword filtering and regex replacement.

```python
# backend/rag_pipeline/helper/guardrails.py
import re

OOS_PATTERNS = re.compile(
    r"\b(write (a )?python|fix (my )?code|solve equation|president of|stock price|weather in|crypto|bitcoin)\b|"
    r"\b(ignore (all )?previous instructions|system prompt|dan mode)\b",
    re.IGNORECASE
)

SPOILER_PATTERNS = re.compile(
    r"\b(dies in the end|is actually the murderer|revealed to be the (killer|villain)|true identity is|kills .* at the end)\b",
    re.IGNORECASE
)

class DomainGuardrails:
    MIN_CONFIDENCE = -6.5

    @classmethod
    def validate_intent(cls, query: str) -> tuple[bool, str]:
        if OOS_PATTERNS.search(query):
            return False, "I specialize strictly in anime recommendations. Please ask an anime or narrative query!"
        return True, ""

    @classmethod
    def scrub_spoilers(cls, text: str) -> str:
        return SPOILER_PATTERNS.sub("[spoiler redacted]", text)
```

#### Task 3.2: Dual-Stream Server-Sent Events (SSE) Protocol
- **User Story:** As an interactive web/mobile user, I want anime metadata cards to appear on my screen immediately (~1.2s), followed by a live streamed explanation of why they match my mood (~1.4s TTFT).
- **Implementation Detail:**
  1. Build an asynchronous event generator in `backend/main.py` for `POST /chat`.
  2. **Event 1 (`event: metadata`):** Emitted immediately after Cross-Encoder reranking. Contains the top 5 anime cards (IDs, titles, images, scores, genres).
  3. **Event 2..N (`event: token`):** Emitted as tokens arrive from `AsyncOpenAI.chat.completions.create(stream=True)`.
  4. **Event Final (`event: done`):** Contains total latency timings and token consumption.

```python
# Dual-Stream SSE Generator in backend/main.py
@app.post("/chat")
async def chat_endpoint(request: ChatRequest, api_key: str = Depends(get_api_key)):
    async def sse_event_stream():
        # Step 1: Guardrail Check
        valid, msg = DomainGuardrails.validate_intent(request.query)
        if not valid:
            yield f"event: error\ndata: {json.dumps({'detail': msg})}\n\n"
            return

        # Step 2: Core Retrieval & Rerank (Non-blocking)
        candidates, timings = await orchestrator.execute_retrieval(request.query, request.top_k)
        
        # Immediate Event: Push deterministic metadata cards to UI (TTFT: ~1.2s)
        yield f"event: metadata\ndata: {json.dumps({'candidates': candidates})}\n\n"

        # Step 3: Stream Taste Concierge Rationale (Token by token)
        async for token_chunk in synthesizer.stream_pitch(request.query, candidates):
            scrubbed_chunk = DomainGuardrails.scrub_spoilers(token_chunk)
            yield f"event: token\ndata: {json.dumps({'text': scrubbed_chunk})}\n\n"

        yield f"event: done\ndata: {json.dumps({'timings': timings})}\n\n"

    return StreamingResponse(sse_event_stream(), media_type="text/event-stream")
```

#### Task 3.3: OpenAI Circuit Breaker & Fallback
- **User Story:** As an end user, if OpenAI is experiencing outages or rate limits, I want the system to fall back to returning my recommendation cards with a static pitch rather than crashing with an HTTP 500 error.
- **Implementation Detail:**
  1. Wrap all OpenAI calls in an asynchronous circuit breaker (`tenacity` retry with 3 attempts and 3.0s timeout).
  2. If the circuit opens or times out, yield a fallback message: *"Here are the highest-rated anime matching your request from our database"* alongside the retrieved metadata cards.

### 4. Acceptance Criteria & Verification Tests
- **AC 3.1:** Time-to-First-Token (TTFT) on `/chat` is $< 1.5$ seconds for the metadata event.
- **AC 3.2:** 100% of non-anime prompts (code execution requests, prompt injection attacks) are rejected within 15 milliseconds without invoking vector search or LLM APIs.
- **AC 3.3:** When OpenAI API is simulated to return HTTP 500 or times out, the `/chat` endpoint successfully completes and returns valid candidate cards with a fallback intro.
- **Verification Tests:**
  ```powershell
  # Unit tests for guardrails and SSE streaming
  pytest test/pipeline/test_guardrails.py -v
  pytest test/pipeline/test_streaming_synthesis.py -v
  ```

### 5. Risk Register, Failure Modes & Rollback Strategy
| Risk / Failure Mode | Likelihood | Impact | Mitigation Strategy | Rollback Trigger |
| :--- | :--- | :--- | :--- | :--- |
| Client disconnects mid-stream, leaving dangling background tasks | Medium | Low | Monitor `request.is_disconnected()` in the SSE generator loop; break immediately if client disconnects | Memory consumption steadily grows during long-lived streams |
| LLM pitch hallucinating plot details not in synopsis | Medium | Medium | Strict system prompt forbidding external lore, temperature set to `0.3`, context strictly truncated to provided synopses | Hallucination rate > 5% in evaluation sampling -> Reduce temperature to `0.1` |

---

## Sprint 4: Upstash Redis State & Conversational Web MVP Integration

### 1. Sprint Objective & Scope
Externalize all working session memory, distributed rate limiting, and production LLM caching to **Upstash Redis** (serverless HTTP/REST Redis). Implement short-term rolling conversation memory and long-term user watched/dropped filters for conversational web discovery (`POST /chat`). Deliver production-grade multi-turn session tracking for the Web MVP.

> [!NOTE]
> **Scope Realignment (MVP Focus):** Third-party messaging integrations (WhatsApp Business API / Twilio) are **explicitly deferred to a post-MVP growth milestone**. The MVP focuses 100% on delivering a high-performance, cost-efficient, and secure **Conversational Web API (`/chat`) and Interactive UI**.

### 2. Target Files & Architectural Changes
- New: `backend/rag_pipeline/helper/state_manager.py`: Upstash Redis state manager.
- `backend/rag_pipeline/helper/llm_cache.py`: Refactor to use Upstash Redis in cloud production when `DISABLE_LLM_CACHE=false`.
- `backend/main.py`: Replace in-memory `RateLimiter` with distributed sliding-window Redis rate limiter; finalize `POST /chat` multi-turn integration.
- `test/pipeline/test_state_manager.py`: Multi-turn session persistence and exclusion filter test harness.

### 3. Concrete Implementation Tasks & User Stories

#### Task 4.1: Upstash Redis State Integration
- **User Story:** As an API cluster scaling across multiple serverless container replicas, I want user session state and rate limits synchronized across all instances so that web users experience uninterrupted multi-turn memory regardless of container routing.
- **Implementation Detail:**
  1. Add `upstash-redis` to `requirements.txt`.
  2. Implement `StateManager` in `state_manager.py` using `upstash_redis.asyncio.Redis` (supports both connection pooling and serverless REST transport).
  3. Store multi-turn dialogue context: `SETEX session:{session_id} 1800 <json_history>` (30-minute rolling TTL).
  4. Track seen/recommended anime IDs: `SADD user:{user_id}:seen_ids <anime_id>`.

```python
# backend/rag_pipeline/helper/state_manager.py
import os
from upstash_redis.asyncio import Redis

class StateManager:
    def __init__(self):
        self.redis = Redis(
            url=os.getenv("UPSTASH_REDIS_REST_URL"),
            token=os.getenv("UPSTASH_REDIS_REST_TOKEN")
        )

    async def get_session_history(self, session_id: str) -> list[dict]:
        data = await self.redis.get(f"session:{session_id}")
        return data or []

    async def append_session_turn(self, session_id: str, turn: dict, ttl: int = 1800):
        history = await self.get_session_history(session_id)
        history.append(turn)
        history = history[-5:] # Retain rolling 5 turns
        await self.redis.set(f"session:{session_id}", history, ex=ttl)

    async def get_excluded_ids(self, user_id: str) -> list[int]:
        ids = await self.redis.smembers(f"user:{user_id}:seen_ids")
        return [int(x) for x in ids] if ids else []

    async def record_seen_ids(self, user_id: str, anime_ids: list[int]):
        if anime_ids:
            await self.redis.sadd(f"user:{user_id}:seen_ids", *anime_ids)
```

#### Task 4.2: Seen/Watched Title Exclusion Filtering
- **User Story:** As a user refining my search in a web chat session ("Give me something else, I already saw that"), I want the recommender to guarantee that previously recommended or watched anime are never shown again.
- **Implementation Detail:**
  1. Pass `excluded_ids: set[int]` fetched from Redis into `rag_pipeline(..., seen_ids=excluded_ids)`.
  2. Candidate filtering is applied via $O(1)$ set subtraction in `Ranker.merge_deduplicate()`, keeping PostgreSQL vector search clean and unconstrained.

#### Task 4.3: Distributed Sliding-Window Rate Limiting
- **User Story:** As a system administrator, I want rate limits enforced globally across all Modal container instances so that abusive clients cannot exceed quota by hitting different container replicas.
- **Implementation Detail:**
  1. Replace the in-memory `RateLimiter` class in `backend/main.py` with an async Redis sliding-window counter using sorted sets (`ZADD`, `ZREMRANGEBYSCORE`, `ZCARD`), keyed by client IP or user API key.

#### Task 4.4: Conversational Web API Integration & Session Testing
- **User Story:** As a frontend engineer building the anime recommender web app, I want a unified `POST /chat` endpoint that supports multi-turn sessions and SSE streaming so that users can naturally refine recommendations.
- **Implementation Detail:**
  1. Wire `StateManager` into `POST /chat` route handler in `backend/main.py`.
  2. Ensure each incoming turn reads previous context, injects context into `HardenedRecommendationSynthesizer`, and commits the new turn back to Redis.
  3. Validate SSE event streaming end-to-end with session ID persistence.

### 4. Acceptance Criteria & Verification Tests
- **AC 4.1:** Multi-turn session persistence: When Turn 1 is processed by Container A and Turn 2 is processed by Container B, Turn 2 successfully accesses the query history and recommended IDs from Turn 1.
- **AC 4.2:** Watched title exclusion: Titles recommended in Turn 1 are **strictly excluded** from Turn 2 candidates (0% recurrence).
- **AC 4.3:** Distributed rate limiting: Generating 21 requests in 60 seconds across 3 independent container instances triggers an HTTP 429 response on the 21st request.
- **AC 4.4:** Web conversational integration test verifies valid multi-turn SSE streaming with card rendering.
- **Verification Tests:**
  ```powershell
  # Test distributed state, exclusion filtering, and conversational session flow
  pytest test/pipeline/test_state_manager.py -v
  pytest test/pipeline/test_web_chat_session.py -v
  ```

### 5. Risk Register, Failure Modes & Rollback Strategy
| Risk / Failure Mode | Likelihood | Impact | Mitigation Strategy | Rollback Trigger |
| :--- | :--- | :--- | :--- | :--- |
| Upstash Redis REST endpoint latency spike (>100ms) | Low | Medium | Use cache-aside pattern: If Redis call exceeds 150ms timeout, log warning and continue as stateless request | Redis latency > 200ms -> Temporarily disable session history lookups |
| Large user `seen_ids` list degrades performance | Low | Low | In-memory hash set lookup in Python executes in <1ms even for 10,000 IDs | Dedup step exceeds 10ms -> Cap checked set to latest 500 IDs |

---

### Deferred Scope (Post-MVP Growth Milestone)
- **WhatsApp Business API / Twilio Adapter:** To be implemented when user volume warrants external messaging channels. The architecture's decoupled design allows plugging in a WhatsApp webhook adapter into the existing Redis state and `POST /chat` pipeline with zero core rewrites.

---

## Production Verification & Benchmark Harness

To guarantee stability before deployment, the following automated benchmark suite must pass in staging:

### Concurrency & Event Loop Lag Benchmark
```python
# test/benchmarks/test_event_loop_lag.py
import asyncio
import time
import httpx
import pytest

@pytest.mark.asyncio
async def test_event_loop_lag_under_load():
    """Verifies that FastAPI event loop remains responsive under concurrent load."""
    max_lag = 0.0
    stop_monitor = False

    async def monitor_loop():
        nonlocal max_lag
        while not stop_monitor:
            t0 = time.perf_counter()
            await asyncio.sleep(0.01)
            lag = (time.perf_counter() - t0) - 0.01
            if lag > max_lag:
                max_lag = lag

    monitor_task = asyncio.create_task(monitor_loop())

    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # Launch 20 concurrent requests
        tasks = [
            client.post("/recommend", json={"query": "psychological thriller with mystery", "top_k": 10}, headers={"access_token": "test-key"})
            for _ in range(20)
        ]
        responses = await asyncio.gather(*tasks)

    stop_monitor = True
    await monitor_task

    assert all(r.status_code == 200 for r in responses), "Some requests failed under load"
    assert max_lag < 0.050, f"Event loop starved! Max lag was {max_lag*1000:.2f}ms (must be < 50ms)"
```

---

## Operations, Telemetry & Cost Model

### Operational Telemetry
Each request to `/recommend` or `/chat` will emit structured OpenTelemetry / Datadog timing spans:
- `timings.guardrails_ms`: Scope & safety check duration.
- `timings.memory_lookup_ms`: Upstash Redis session retrieval.
- `timings.hyde_ms`: AsyncOpenAI hypothetical query generation.
- `timings.embedding_ms`: Bi-encoder vector computation (Modal RPC).
- `timings.retrieval_ms`: PostgreSQL multi-vector and BM25 search.
- `timings.reranking_ms`: Cross-encoder scoring and franchise collapse (Modal RPC).
- `timings.synthesis_ttft_ms`: Time to first token for conversational rationale.

### Cost Model Analysis (Per 100,000 Monthly Queries)

| Architecture Model | Serverless Compute (Modal) | OpenAI API (HyDE + Pitch) | Redis & DB (Upstash + Supabase) | Total Monthly Cost |
| :--- | :--- | :--- | :--- | :--- |
| **Current Monolithic Proposal** (T4 GPU active during all I/O) | \$327.70 *(3.5s T4 GPU @ \$0.59/hr per query)* | \$180.00 *(gpt-5.4-mini no caching)* | \$25.00 | **\$532.70** |
| **Decoupled Architecture (Target)** (CPU Gateway + On-Demand GPU Reranker) | **\$38.20** *(0.3s T4 GPU + 1.2s CPU)* | **\$108.00** *(40% cache hit rate on common queries)* | \$25.00 | **\$171.20** |
| **Net Savings** | **-88.3% Compute Cost** | **-40.0% LLM Cost** | — | **67.8% Total Cost Reduction** |

---

## Rollout Schedule & Milestone Summary

```mermaid
gantt
    title Orchestration & Intelligence Layer Implementation Timeline
    dateFormat  YYYY-MM-DD
    section Sprint 1: Pipeline Hardening
    PgBouncer Pooler & Concurrency Bounds    :a1, 2026-11-01, 4d
    Remove Startup DDL & Migration Script   :a2, after a1, 3d
    Candidate Metadata Enrichment           :a3, after a2, 3d
    section Sprint 2: Modal Decoupling
    Modal CPU Gateway & GPU ModelWorker     :b1, 2026-11-11, 5d
    AsyncOpenAI & Non-blocking FastAPI Loop :b2, after b1, 4d
    Load & Concurrency Benchmarking         :b3, after b2, 3d
    section Sprint 3: Guardrails & SSE
    Compiled Domain Guardrails & Spoilers   :c1, 2026-11-23, 4d
    Dual-Stream SSE Endpoint (/chat)        :c2, after c1, 5d
    Circuit Breaker & Fallback Engine       :c3, after c2, 3d
    section Sprint 4: State & Web MVP
    Upstash Redis Session State Manager     :d1, 2026-12-05, 4d
    Seen IDs In-Memory Exclusion Filter     :d2, after d1, 3d
    Web Chat /chat Session Integration      :d3, after d2, 5d
    End-to-End Production Verification      :d4, after d3, 2d
```

### Sign-off & Approval
- **Lead Systems Architect:** *Approved for Execution*
- **Cloud Infrastructure Auditor:** *Approved for Execution*
