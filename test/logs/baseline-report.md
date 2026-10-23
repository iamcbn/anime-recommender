# Sprint 0 Baseline and Discovery Report

**Sprint**: Sprint 0: Baseline and Discovery  
**Branch**: `test-suite-rebuild`  
**Date**: 2026-10-23  
**Standard**: British English; strict exclusion of em-dashes  

---

## 1. Executive Summary

This report establishes the verified baseline for the anime recommender test suite rebuild. It details the detected technology stack, captures baseline execution counts and code coverage across the repository, maps the complete backend and frontend architectural surfaces, and catalogues critical isolation, safety, and duplication findings across the existing test files.

---

## 2. Detected Stack and Tooling

| Domain | Technology / Component | Version / Specification | Role in Repository |
|---|---|---|---|
| **Runtime Environments** | Python | 3.11.0 (64-bit, Windows) | Core backend, pipeline, scripts, and existing test suite |
| | Node.js | v24.22.1 (64-bit, Windows) | Frontend build environment |
| **Package Managers** | pip | 26.2 (within `.\anime` virtual environment) | Python package management |
| | npm | 11.19.1 | Frontend package management |
| **Backend Frameworks** | FastAPI | 0.128.0 | Web application and API endpoints |
| | Starlette | 0.50.0 | Underlying ASGI toolkit |
| | Pydantic | 2.12.5 (Core 2.41.5) | Data validation, schemas, and settings |
| **Machine Learning & NLP** | PyTorch | 2.7.1+cu118 | Dense embedding and ranking model execution |
| | Sentence-Transformers | 5.2.0 | Bi-encoder retrieval and cross-encoder reranking |
| | FastText Wheel | 0.9.2 | Tokenisation and sparse query expansion |
| | RapidFuzz | 3.14.3 | Fuzzy string matching and candidate deduplication |
| **Databases & State** | PostgreSQL / psycopg2 | 2.9.11 | Primary relational catalogue, vector embeddings, telemetry |
| | Supabase Python SDK | 2.33.0 | Authentication verification and PostgREST client |
| | Upstash Redis | 1.8.0 | Sliding-window rate limiting and session state storage |
| | SQLite (Python standard library) | 3.x | Local HyDE query expansion and offline embedding cache |
| **Frontend Frameworks** | React | 18.3.1 | Single-page client portal |
| | Vite | 6.1.0 | Frontend build tool and development server |
| | TypeScript | 5.7.3 | Frontend type safety |
| | Tailwind CSS | 3.4.17 | Styling and responsive design |
| **Test Runners & Tools** | pytest | 9.1.1 | Python test framework (collected 419 items) |
| | pytest-asyncio | 1.4.0 | Coroutine fixture and async test execution |
| | pytest-cov / coverage | 7.1.0 / 7.17.0 | Code coverage instrumentation and reporting |
| | Frontend test runner | **None** | No Vitest, Jest, or browser automation configured |

---

## 3. Baseline Test Suite Execution

A full baseline execution of the existing test suite was conducted with coverage instrumentation across all `backend/` packages:

```bash
python -m pytest --junitxml=test/reports/baseline-junit.xml --cov=backend --cov-report=term --cov-report=xml:test/reports/baseline-cov.xml
```

### 3.1 Headline Metrics
* **Total Collected Tests:** 419 items
* **Passed Tests:** 417 items (99.52%)
* **Failed Tests:** 2 items (0.48%)
* **Skipped Tests:** 0 items
* **Execution Duration:** 93.58 seconds
* **Baseline Code Coverage:** 47% (5,132 statements, 2,731 missed)
* **Artefacts Produced:** `test/reports/baseline-junit.xml` and `test/reports/baseline-cov.xml`

### 3.2 Root Cause Analysis of Baseline Failures
Two tests failed during the initial coverage run. Both failures were thoroughly investigated:

1. `test/pipeline/test_sprint11_smoke.py::TestGracefulDegradationUnderTokenCeilings::test_nli_budget_exhaustion_degrades_to_raw_query`:
   * **Root Cause:** Due to a Windows Application Control policy blocking the compiled C tracer DLL (`tracer.pyd`), coverage-7.17.0 defaulted to its pure-Python `PyTracer`. During execution, `PyTracer.data_stack` encountered an unexpected frame pop when `sys.settrace` was manipulated across coroutine task boundaries.
   * **Isolated Verification:** When executed independently, the test passed with 100% success (`1 passed in 20.34s`).
2. `test/pipeline/test_sprint2_async_concurrency.py::TestEventLoopLagAndConcurrency::test_ac2_2_event_loop_lag_remains_under_15ms`:
   * **Root Cause:** Pure-Python bytecode tracing introduced 3 to 5 ms of execution latency per event loop tick, pushing the observed maximum event loop lag to 18.53 ms against a strict assertion threshold of 15.0 ms.
   * **Isolated Verification:** When executed independently without tracer overhead, the test passed with 100% success (`1 passed in 15.62s`).

Both tests are functionally sound. The failures were induced by runtime instrumentation latency rather than application logic regressions.

### 3.3 Coverage Breakdown by Backend Package

| Package / Module | Statements | Missed Statements | Coverage Percentage |
|---|---|---|---|
| `backend/auth/keys.py` | 229 | 57 | 75% |
| `backend/auth/supabase_jwt.py` | 122 | 36 | 70% |
| `backend/data_pipeline/*` | 564 | 564 | 0% |
| `backend/main.py` | 274 | 49 | 82% |
| `backend/migrations/001_bm25_index_and_metadata.py` | 106 | 106 | 0% |
| `backend/migrations/002_telemetry_and_api_keys.py` | 133 | 116 | 13% |
| `backend/migrations/003_llm_usage.py` | 80 | 80 | 0% |
| `backend/rag_pipeline/config.py` | 25 | 4 | 84% |
| `backend/rag_pipeline/helper/budget_guard.py` | 159 | 34 | 79% |
| `backend/rag_pipeline/helper/guardrails.py` | 140 | 16 | 89% |
| `backend/rag_pipeline/helper/llm_cache.py` | 119 | 81 | 32% |
| `backend/rag_pipeline/helper/llm_clients.py` | 43 | 10 | 77% |
| `backend/rag_pipeline/helper/nli_parser.py` | 138 | 96 | 30% |
| `backend/rag_pipeline/helper/query_generator.py` | 137 | 98 | 28% |
| `backend/rag_pipeline/helper/ranking.py` | 223 | 89 | 60% |
| `backend/rag_pipeline/helper/rate_limiter.py` | 235 | 73 | 69% |
| `backend/rag_pipeline/helper/retrieval.py` | 104 | 25 | 76% |
| `backend/rag_pipeline/helper/service_embedding.py` | 64 | 16 | 75% |
| `backend/rag_pipeline/helper/state_manager.py` | 196 | 106 | 46% |
| `backend/rag_pipeline/helper/synthesizer.py` | 320 | 124 | 61% |
| `backend/rag_pipeline/inference_client.py` | 150 | 95 | 37% |
| `backend/rag_pipeline/main.py` | 51 | 51 | 0% |
| `backend/rag_pipeline/orchestrator.py` | 227 | 80 | 65% |
| `backend/rag_pipeline/rag_pipeline.py` | 71 | 50 | 30% |
| `backend/routers/admin_usage.py` | 112 | 13 | 88% |
| `backend/routers/dev_keys.py` | 84 | 7 | 92% |
| `backend/telemetry/archiver.py` | 637 | 510 | 20% |
| `backend/telemetry/db.py` | 59 | 13 | 78% |
| `backend/telemetry/logger.py` | 293 | 120 | 59% |
| **TOTAL** | **5,132** | **2,731** | **47%** |

---

## 4. Architectural Surface Mapping

### 4.1 Backend Surface

#### Core Modules and Architecture
1. **API Layer (`backend/main.py`, `backend/routers/`)**:
   * Dual entrypoints: `backend/main.py` (FastAPI local/Modal application) and `backend/rag_pipeline/main.py` (standalone microservice).
   * Middleware: Dynamic CORS origin verification with regex validation, request ID propagation, global exception handlers with secret redaction.
2. **Authentication and Authorisation (`backend/auth/`)**:
   * `backend/auth/keys.py`: API key lifecycle management, SHA-256 HMAC peppered hashing, in-memory validation caches (`VALID_KEY_CACHE`, `NEGATIVE_KEY_CACHE`), soft revocation, rate limiting.
   * `backend/auth/supabase_jwt.py`: Supabase JWT verification, JWKS key retrieval and caching, PKCE auth validation, strict distinction between server-controlled `app_metadata` and client-mutable `user_metadata`.
3. **Recommendation Pipeline (`backend/rag_pipeline/`)**:
   * `orchestrator.py`: Central coordination layer managing candidate retrieval, HyDE query generation, cross-encoder reranking, heuristic NLI skips, dual SSE streaming, and fallback synthesis.
   * `helper/guardrails.py`: Fast pre-retrieval validation (instruction overrides, jailbreaks, prompt injection, out-of-scope domain filtering), confidence assessment, post-retrieval spoiler scrubbing.
   * `helper/budget_guard.py`: Tri-layer daily token ceilings (NLI: 100k, Retrieval: 200k, Presentation: 300k) with 80% soft alerts and 100% hard limit deterministic fallbacks.
   * `helper/state_manager.py`: Multi-turn conversational session history with rolling five-turn window, seen anime exclusion tracking, and automatic fallback from Redis to in-memory state.
   * `helper/rate_limiter.py`: Distributed sliding-window rate limiting backed by Redis sorted sets and Lua scripts, with in-memory fallback.
   * `helper/synthesizer.py`: Prose commentary generation with streaming citation validation (`[[anime:<id>]]`), candidate ID verification, and interactive spoiler formatting.
4. **Telemetry and Observability (`backend/telemetry/`)**:
   * `logger.py`: Fire-and-forget background logging for recommendation requests, streaming turns, and LLM token usage. Includes bounded queue and worker pool to prevent request latency degradation.
   * `archiver.py`: Keyset-paginated cold storage archival from PostgreSQL to Parquet files in Supabase Storage with cryptographic checksum verification and GDPR privacy erasure.
   * `db.py`: Dedicated threaded connection pool for telemetry logging.

#### HTTP API Endpoints
* `GET /`: Health check and service metadata.
* `POST /recommend`: Developer API recommendation endpoint with API key authentication and rate limiting.
* `POST /admin/recommend`: Privileged recommendation endpoint returning candidate scores and stage execution latencies.
* `POST /chat`: Consumer conversational discovery endpoint delivering Server-Sent Events (Stage 1 fast metadata event, Stage 2 token streaming, warning events, completion events).
* `GET /dev/keys`: List active API keys for authenticated developer.
* `POST /dev/keys`: Generate new API key with single-reveal plaintext return.
* `DELETE /dev/keys/{key_id}`: Soft-revoke developer API key.
* `GET /admin/llm-usage/current-budget`: Retrieve current daily token consumption and budget gauge statuses.
* `GET /admin/llm-usage/daily`: Retrieve historical daily token usage and cost aggregations.

#### Data Access and Schemas
* **PostgreSQL Schema `public`**: Core anime catalogue (`anime_core`), 384-dimensional dense vector embeddings (`anime_embedding`), sparse FastText vectors (`anime_fasttext`).
* **PostgreSQL Schema `app_auth`**: Developer API keys (`app_auth.api_keys`), key generation and revocation audit log (`app_auth.key_audit_log`).
* **PostgreSQL Schema `telemetry`**: Request logs with timing and scores (`telemetry.recommendation_logs`), daily rollup usage aggregates (`telemetry.api_key_usage_daily`).
* **Upstash Redis**: Sliding-window rate limit sorted sets, daily token budget counters, multi-turn session states.
* **SQLite Cache (`test/data/llm_cache.db`)**: Local cache for HyDE query expansions and extracted metadata.

---

### 4.2 Frontend Surface

#### Architecture and Components
The frontend is a single-page React application structured under `frontend/src/` (43 TypeScript and TSX files):
* **Routing and Guards (`frontend/src/routes/`)**:
  * `ChatPage.tsx`: Consumer conversational AI discovery interface (root route `/`).
  * `DevelopersPage.tsx`: Developer self-service key management portal.
  * `AdminTelemetryPage.tsx`: Telemetry query explorer with P95 latency metrics and payload inspection.
  * `AdminLlmUsagePage.tsx`: Real-time token budget gauges and daily cost analytics.
  * `LoginPage.tsx`, `SignUpPage.tsx`: Authentication flows.
  * `ProtectedRoute.tsx`: Route guard enforcing authenticated sessions.
  * `AdminRoute.tsx`: Route guard strictly verifying `app_metadata.role === 'admin'`.
* **State and Hooks (`frontend/src/hooks/`, `frontend/src/context/`)**:
  * `useUserPreferences.ts`: Synchronises watched IDs, disliked genres, and adult flags across browser tabs via `localStorage` and storage events.
  * `useApiKeys.ts`: Manages developer key lifecycle and quota limits (max 5 active keys).
  * `useLlmUsage.ts`: Concurrently queries current budget gauges and daily token costs.
  * `useTelemetryLogs.ts`: Queries PostgREST with chained filters, enforcing a 500-record query ceiling.
* **Client Libraries (`frontend/src/lib/`)**:
  * `chatStream.ts`: SSE stream consumer handling chunk fragmentation, candidate card mounting, real-time prose token streaming, and HTTP 429 countdowns.
  * `apiClient.ts`: Authenticated client with proactive JWT refresh (at 14 minutes) and automated error message sanitisation (scrubbing raw keys).
  * `env.ts`: Runtime environment validator throwing errors if any backend secrets appear in client variables.

#### Critical User Flows
1. **Conversational Anime Discovery**: Prompt input -> SSE stream initiation -> Stage 1 fast metadata event (<1.5s) immediately mounting candidate cards -> Stage 2 real-time token streaming with live cursor -> Interactive citation chips (`[[anime:<id>]]`) with smooth-scroll and highlight glow -> Interactive spoiler click-to-reveal badges -> Feedback loop updating user preferences and negative constraints.
2. **Developer Key Self-Service**: Protected portal -> Active quota evaluation -> Modal creation -> Single-reveal plaintext key display with mandatory acknowledgement checkbox -> State zeroing on unmount -> Soft revocation.
3. **Administrator Observability**: Admin route barrier -> PostgREST telemetry inspection under RLS -> Real-time token budget monitoring with 80% soft alert and 100% hard limit fallback indicators.

---

## 5. Non-Standard Scripts and Benchmark Inventory

The inventory classified all non-test files residing in `test/`:

| File | Nature / Purpose | Automated Test? | Action Recommended for Rebuild |
|---|---|---|---|
| `test/hourly_run.py` | Synthetic probe calling Google Gemini API and live Modal endpoint to append ground-truth records | No | Move to operational tools or GitHub Actions directory; remove from test discovery |
| `test/run_eval.ps1` | PowerShell pipeline orchestrating Kaggle data refresh, retrieval evaluation, and Markdown reporting | No | Retain under operational scripts; exclude from automated test suite |
| `test/benchmarks/SBERT_TEST.py` | Historical SentenceTransformer benchmark script | No | Orphaned script referencing nonexistent Excel file; delete in Sprint 2 |
| `test/benchmarks/sberts_performance.xlsx` | Static Excel spreadsheet storing historical benchmark results | No | Historical binary asset; delete or archive |
| `test/experiments/compare_embeddings.py` | Research script comparing dense embedding models against PostgreSQL | No | Move to research or archive directory; exclude from pytest |
| `test/experiments/experiment_k.py` | Research parameter sweep evaluating RRF constant k values | No | Move to research or archive directory; exclude from pytest |
| `test/pipeline/evaluate_pipeline.py` | Metric calculation script computing Hit Rate and MRR from JSONL | No | Move to evaluation tools; exclude from automated test suite |
| `test/pipeline/evaluate_first_stage.py` | Offline pipeline evaluation runner driving retrieval and cross-encoder | No | Move to evaluation tools; exclude from automated test suite |
| `test/pipeline/generate_report.py` | Markdown report generator producing `evaluation_report_v2.md` | No | Move to evaluation tools; exclude from automated test suite |
| `test/smoke/test_isolated_smoke.py` | Fast, hermetic unit and smoke test suite (46 tests) | **Yes** | Retain and promote as core foundation of rebuild suite |

### Protected Assets Verification
* `test/data/anime_results.jsonl`: Protected evaluation dataset containing 239 recorded queries. Preserved.
* `test/data/llm_cache.db`: Protected SQLite cache containing 483 pre-cached LLM responses. Preserved.
  * *Critical Finding:* The database stores legacy keys (`hyde_v1_{query}`). In Sprint 3, key migration must be applied to align with current `LLMCache._normalize_key()` (`llm:cache:...`) to prevent unintended cache misses during hermetic testing.

---

## 6. Critical Findings: Safety, Fixtures, and Redundancy

### 6.1 Total Absence of Global Fixtures (`conftest.py`)
There is currently no `conftest.py` in the repository. As a consequence:
* **Duplicated JWKS Mocking:** Six independent files implement their own RSA-2048 keypair generation and Supabase JWKS mocking (`test_api_keys.py`, `test_sprint6_frontend_and_admin_portal.py`, `test_sprint6_security_rls.py`, `test_sprint9_chat_tier.py`, `test_sprint11_admin_usage.py`, `test_sprint11_smoke.py`).
* **Duplicated Candidate Data:** Seven separate test files define duplicate sample anime candidate dictionaries.
* **Duplicated Redis Doubles:** Three separate files define custom in-memory Redis simulations.
* **Duplicated Database Cleanup:** Five files define independent teardown routines issuing raw SQL deletions.

### 6.2 Critical Safety Guard Absence
* There is no guard in place to verify database connection targets. If `DB_HOST` in `.env` is configured for remote Supabase (or if remote pooler settings are uncommented), five test suites (`test_api_keys.py`, `test_sprint1_migration.py`, `test_sprint3_telemetry.py`, `test_sprint6_security_rls.py`, `test_telemetry_and_archival.py`) will execute direct DDL migrations, `INSERT`, and `DELETE` queries against live production or staging databases.
* Mandatory safety guards must be established in `conftest.py` before Sprint 1 begins.

### 6.3 Frontend Test Reality
* The 119 "frontend" tests across the repository do not execute JavaScript or TypeScript code. They consist entirely of Python regular expression matching and AST parsing of TSX files.
* No test mounts a React component, evaluates a hook, simulates user interaction, or verifies browser SSE parsing.
* A native test runner (Vitest) must be introduced to provide genuine unit and integration test coverage for frontend components, hooks, and streaming libraries.

---

## 7. Sprint 0 Exit Gate Verification

* [x] Stack and tooling detected and recorded.
* [x] Baseline test suite executed with pass, fail, skip counts, runtime, and coverage baseline.
* [x] Failures investigated and verified in isolation.
* [x] Backend architectural surface mapped across modules, routes, schemas, and external calls.
* [x] Frontend architectural surface mapped across pages, components, hooks, and user flows.
* [x] Non-standard scripts, benchmarks, and protected assets catalogued.
* [x] Tracking documentation updated ([sprint-tracker.md](file:///c:/Dev/anime_recommender/test/logs/sprint-tracker.md), [run-log.jsonl](file:///c:/Dev/anime_recommender/test/logs/run-log.jsonl)).
* [x] Baseline report committed to repository.

**Sprint 0 Exit Gate: PASSED.**
