# Developer Journal

A personal log of engineering decisions, issues encountered, and lessons learned while building the Anime Recommender System.

---

## Tradeoffs, Issues Encountered, & Blockers

During the containerisation and development phase, several critical engineering hurdles were tackled:

### 1. Host-Level DNS Blocking Docker Pulls
* **Issue:** Docker image builds failed with `dial tcp: lookup auth.docker.io: no such host`.
* **Cause/Fix:** The local router/ISP was silently blocking Docker Hub DNS resolution. Fixed by temporarily overriding Windows host Wi-Fi DNS to `8.8.8.8` (Google Public DNS).

### 2. Missing Dependencies (`openpyxl`)
* **Issue:** `pandas.read_excel()` threw a `ModuleNotFoundError` during the data pipeline.
* **Fix:** The Kaggle dataset is an `.xlsx` file. Added `openpyxl==3.1.5` (minimum version required by Pandas 3.0.0) to `requirements.txt`.

### 3. State Management Bug in Pipeline
* **Issue:** If the pipeline crashed mid-execution (e.g., during embedding), it still reported "Dataset already up to date" on the next run, preventing recovery.
* **Fix:** The dataset state was being recorded immediately after download (before processing). Moved `_record_version()` to the very end of the pipeline to ensure state is only saved after the entire pipeline succeeds.

### 4. Hugging Face Model Identifier Typo (401 Unauthorized)
* **Issue:** Docker container crashed with `Repository Not Found` when trying to download the SBERT model.
* **Cause:** The script used `paraphrase/multilingual-MiniLM-L12-v2`, which Hugging Face interpreted as a user named `paraphrase`. Locally, this bug was hidden because the model folder already existed on disk and the download path was never triggered.
* **Fix:** Changed to the correct identifier: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

### 5. CPU vs GPU Image Size Tradeoff
* **Tradeoff:** Installing PyTorch with CUDA support increases the Docker image size significantly (~4 GB vs ~1.5 GB for CPU-only).
* **Decision:** The RAG API uses the CUDA-enabled image for production inference speed. The Data Pipeline uses a lean CPU-only image since it runs on standard GitHub Actions runners. Both use multi-stage builds to strip out build tools (`build-essential`) from the final image.

---

## Changelog

> Keeping a changelog helps track architectural pivots, understand why certain decisions were made, and leaves a paper trail for future collaborators.

### v1.5.0 (Current): Sprint 3 Conversational Orchestration & Dual-Stream SSE
- **Pre-Retrieval Domain Guardrails:** Added `DomainGuardrails` executing in <0.05ms (AC 3.2). Unconditionally blocks prompt injections (overrides, system prompt extraction, jailbreaks) and conditionally blocks out-of-scope tasks (coding, math, politics, crypto, weather) with protected whitelist rules ensuring zero false positives on real anime titles (*Code Geass*, *Steins;Gate*, *Erased*, *Ghost in the Shell*, *Monster*, *Death Note*).
- **Dual-Stream Server-Sent Events (`POST /chat`):** Decoupled candidate card rendering from conversational pitch streaming. Reranked metadata cards emit immediately in `event: metadata` (TTFT < 1.5s, AC 3.1), followed by token-by-token streaming pitches (`event: token`) and final timing stats (`event: done`).
- **OpenAI Circuit Breaker & Fallback:** Integrated `tenacity` retry with timeout. If OpenAI returns HTTP 500, 429, or times out, the circuit breaker triggers a deterministic catalog fallback pitch, guaranteeing zero 500 crashes and 100% metadata card preservation (AC 3.3).
- **Retrieval Confidence Assessment:** If top Cross-Encoder rerank score is < -6.5 or empty, emits `event: warning` advising prompt refinement while suggesting canonical anime titles.
- **Active Spoiler Scrubber:** Regex-based plot twist filter redacting climax character deaths, mastermind/killer reveals, and `||spoiler||` tags with `[spoiler redacted]` across streamed token chunks without damaging markdown formatting or standard premise descriptions.
- **FastAPI Dual-Mode Dispatch:** Kept `POST /recommend` 100% backward compatible for headless consumers, while adding `POST /chat` with Starlette client disconnect monitoring (`request.is_disconnected()`).

### v1.4.0: HyDE Query Expansion, Self-Query Removal & Test Reorganisation
- **HyDE Query Generation:** Added `QueryGenerator`, which asks OpenAI for 2 hypothetical anime descriptions per query. Retrieval now runs 9 concurrent searches (MiniLM, FastText and BM25 across the original + 2 generated queries). Falls back to the original query if the LLM call fails.
- **LLM Cache (testing only):** Added a SQLite cache for HyDE responses so repeated evaluation runs cost no OpenAI credits and are reproducible. It now lives at `test/data/llm_cache.db` (override with `LLM_CACHE_PATH`) and is disabled in production with `DISABLE_LLM_CACHE=true`. A cache failure can no longer stop the server from starting.
- **Self-Query Removed:** The LLM metadata-filter step (genres, year, format as SQL `WHERE` clauses) was dropped. It filtered too aggressively and added cost and latency. The module, its startup singleton and its imports were removed. The `/recommend` response keeps a `self_query_ms` timing (always `0.0`) for backward compatibility.
- **Test Reorganisation:** `test/` is now segmented into `pipeline/`, `experiments/`, `benchmarks/` and `data/`. The legacy `backend/data_pipeline/test/` files moved to `test/benchmarks/`, and evaluation history/reports moved to `test/data/`. `run_eval.ps1` was updated to match.
- **Evaluation Tooling:** Added `scripts/hourly_run.py` (Gemini-generated test queries sent to the live API, appended to `anime_results.jsonl`) and `scripts/evaluate_pipeline.py` (MRR / hit-rate analysis).

### v1.3.0: Retrieval Latency Optimization & Pipeline State Fixes
- **HNSW Vector Indexes:** Added pgvector HNSW indexes on `sbert_embedding` and `fasttext_embedding` columns, replacing sequential scans with fast approximate nearest-neighbour search. Indexes are automatically dropped before bulk data promotion and rebuilt after, avoiding row-by-row index update penalties during the weekly pipeline run.
- **Connection Pooling:** Refactored the RAG pipeline's `DatabaseManager` to use `psycopg2.pool.ThreadedConnectionPool`, eliminating ~50-100ms of TCP handshake overhead per request.
- **Concurrent Retrieval:** SBERT and FastText similarity searches now execute in parallel via `concurrent.futures.ThreadPoolExecutor`, cutting retrieval wall-clock time roughly in half.
- **Dataset Version Fix:** Fixed `dataset_version` in `db_state` always being `1` by deriving it from the database instead of the ephemeral local JSON file.
- **Kaggle Version Tracking:** Added `kaggle_version` column to `db_state` so the pipeline can skip unnecessary downloads when the Kaggle dataset hasn't changed between runs.
- **State Persistence in CI:** Updated the GitHub Actions workflow to mount a volume for the artefacts directory and commit `.dataset_state.json` back to the repository after each pipeline run.

### v1.2.0: Production Deployment & CI/CD Pipelines
- **Modal Integration:** Created `modal_deploy.py` to deploy the FastAPI app onto serverless T4 GPUs with built-in dependency management and local model syncing.
- **Supabase Connectivity:** Successfully pointed the data pipelines and recommendation system to the managed Supabase PostgreSQL instance.
- **Automated Sync:** Configured GitHub Actions to automatically run `data_pipeline` against the remote Supabase database without manual intervention.
- **Latency Diagnostics:** Profiled the `/recommend` endpoint, uncovering high retrieval latency due to missing `pgvector` indexes and sequential queries.

### v1.1.0: Dockerisation & CI/CD
- Added `docker-compose.yaml` wiring PostgreSQL (pgvector), Data Pipeline, and RAG Pipeline
- Implemented Docker Compose `gpu` profiles for seamless hardware switching
- Implemented multi-stage Docker builds to reduce image sizes
- Data Pipeline Dockerfile: CPU-only, optimised for GitHub Actions
- RAG Pipeline Dockerfile: CUDA-enabled, optimised for serverless GPU deployment
- Wrote GitHub Actions workflow (`update_data.yml`) for automated weekly pipeline execution
- Fixed Hugging Face model resolution paths for cold-start (empty volume) environments
- Fixed state management bug: `_record_version()` moved to end of pipeline
- Added `openpyxl` to data pipeline dependencies
- Updated `.env` variable names to align with Kaggle Python library (`KAGGLE_KEY`)

### v1.0.0: Core Pipeline Complete
- Implemented two-stage retrieval (MiniLM + FastText)
- Implemented Cross-Encoder reranking and Franchise Collapse (fuzzy matching via rapidfuzz)
- Designed normalised 5-table PostgreSQL schema using `pgvector`
- Built FastAPI wrapper with API key authentication and rate limiting (20 req/min)
