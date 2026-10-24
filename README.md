# Anime Recommender System

A semantic anime recommendation system built on a two-stage neural retrieval and ranking pipeline. The system understands the meaning behind anime descriptions, genres, and titles to surface recommendations based on thematic and narrative similarity, not just keyword overlap.

Served through a FastAPI backend with API key authentication and rate limiting, and fully deployed to production on Modal serverless GPUs.

> **📖 Further Reading:** For a deep-dive into the system design, models, database schema, and pipeline internals, see [ARCHITECTURE.md](ARCHITECTURE.md). For the development history and troubleshooting notes, see [docs/DEVELOPER_JOURNAL.md](docs/DEVELOPER_JOURNAL.md).

---

## How It Works

1. **You describe** what you want to watch in plain text (English only for now).
2. **Two embedding models** (MiniLM for semantics, FastText for anime-specific vocabulary) convert your query into vectors.
3. **pgvector HNSW indexes** retrieve the top candidates from a PostgreSQL database in milliseconds.
4. **A cross-encoder reranker** scores every candidate against your query and returns the best matches.

---

## API Usage

### Authentication & Developer Portal

Developers can self-service manage high-entropy API keys at the **Developer Portal** (`frontend/`).

All API requests authenticate via the HTTP Bearer header:

```http
Authorization: Bearer ar_live_a1b2c3d4_...
```

*(Note: Legacy `access_token` header is accepted during deprecation).*
- Missing, invalid, expired, or revoked keys return `401 Unauthorized`.
- Non-admin callers attempting to access `/admin/*` endpoints return `403 Forbidden`.

### Rate Limiting

20 requests per minute per API key (with sliding-window Redis accounting). Exceeding this returns `429 Too Many Requests` with a `Retry-After` header.

### Endpoints

#### `GET /`

Health check.

```json
{
  "message": "Welcome to the Anime Recommendation API. Use the /recommend endpoint to get recommendations."
}
```

#### `POST /recommend`

Public inference endpoint. Returns clean anime cards only (internal model scores, timings, and `extra` are strictly stripped from public responses and logged to asynchronous telemetry).

**Request body:**

```json
{
  "query": "a dark psychological thriller with moral ambiguity",
  "top_k": 20,
  "allow_adult": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | Yes | - | Minimum 2 characters |
| `top_k` | int | No | 20 | Number of recommendations to return |
| `allow_adult` | bool | No | false | Whether to include adult-rated anime |

**Response (Public):**

```json
{
  "query": "a dark psychological thriller with moral ambiguity",
  "count": 20,
  "allowed_adult": false,
  "results": [
    {
      "id": 152802,
      "title_romaji": "Dark Gathering",
      "title_userPreferred": "Dark Gathering",
      "title_english": "Dark Gathering",
      "coverImage_large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx152802-ENRcnqD5axhQ.jpg"
    }
  ]
}
```

#### `POST /admin/recommend`

Evaluation and benchmarking endpoint. Requires an **admin-role** key (`role='admin'`). Returns the full response payload including pipeline timings (`total_ms`, stage breakdowns) and model scores (`cross_encoder_score`, `final_rrf_score`, `retrieval_rrf_score`).

---

## Developer & Admin Portal (`frontend/`)

A modern, responsive developer portal built with Vite 6 + React 18 + TypeScript and styled with Tailwind CSS.

### Key Features
- **Developer Key Management (`/developers`)**:
  - Authenticate with Supabase Auth (Email Magic Link, Password, or GitHub OAuth).
  - Provision high-entropy API keys (`ar_live_<prefix>_<secret>`) with a secure single-reveal gated modal.
  - Revoke keys with instant invalidation (<= 60s cache TTL).
  - Maximum 5 active keys per developer account.
- **Admin Telemetry Explorer (`/admin/telemetry`)**:
  - Route-guarded with Row Level Security (RLS) enforcing `app_metadata.role = 'admin'`.
  - Queries `telemetry.recommendation_logs` directly through PostgREST.
  - Interactive filters by source (`user`, `admin_eval`), endpoint, status, date presets, and query search.
  - Interactive JSON inspector for pipeline stage latencies and candidate scores.
- **Interactive Documentation (`/docs`)**:
  - Multi-language copy-paste code snippets (cURL, Python, Node.js).
  - Status code error reference table (401, 403, 404, 409, 422, 429).
  - Zero-downtime 4-step key rotation SOP.

### Running the Frontend Locally

```bash
cd frontend
cp .env.example .env
# Edit .env with your VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
npm install
npm run dev
```

The portal runs on `http://localhost:5173` and connects to the backend gateway at `http://localhost:8001`.

---

## Architecture: Dual Entrypoints

This repository maintains two specialised entrypoints tailored for production serving and benchmark evaluation:

1. **Production & Docker Gateway (`backend/main.py`)**:
   - The primary gateway serving the Modal serverless CPU/GPU deployment, local development, and full-stack Docker.
   - Exposes the full application route tree: conversational discovery streaming (`POST /chat` with Server-Sent Events), public inference (`POST /recommend`), developer self-service key management (`/dev/keys`), and admin LLM usage telemetry (`/admin/llm-usage/*`).
   - Configures dynamic CORS middleware, secret redaction, and asynchronous PostgreSQL telemetry logging.

2. **Standalone RAG Microservice (`backend/rag_pipeline/main.py`)**:
   - A lightweight, unencumbered inference microservice exposing only `/` and `/recommend`.
   - Used for isolated benchmark evaluations, offline accuracy auditing, and standalone integration testing without authentication, Redis rate limiting, or gateway middleware overhead.

---

## Setup & Local Development

### Prerequisites

- Python 3.11+
- PostgreSQL with the `pgvector` extension
- Kaggle API credentials
- Docker and Docker Compose

### Environment Variables

Create a `.env` file in the project root:

```env
MY_API_KEY=your_secret_api_key
ADMIN_API_KEY=your_admin_secret_key

DB_HOST=localhost
DB_PORT=5432
DB_NAME=anime_db
DB_USER=postgres
DB_PASSWORD=your_db_password

KAGGLE_USERNAME=your_kaggle_username
KAGGLE_KEY=your_kaggle_api_key
HF_TOKEN=your_huggingface_token
OPENAI_API_KEY=your_openai_api_key

COMPOSE_PROFILES=cpu
```

---

## Running the Application

### Option 1: Full-Stack Docker (CPU - Runs on Any Laptop)

The default configuration starts PostgreSQL + pgvector, the Backend Gateway on port `8001`, and the Frontend Portal on port `5173`. No host dependencies (such as Python or Node.js) are required:

```bash
docker compose up -d
```

Verify service status:

```bash
docker compose ps
```

The services are accessible at:
- **Frontend Portal**: `http://localhost:5173`
- **Backend Gateway**: `http://localhost:8001` (API documentation at `http://localhost:8001/docs`)
- **Database**: `localhost:5432`

To shut down:

```bash
docker compose down
```

### Option 2: Full-Stack Docker (GPU - NVIDIA Container Toolkit)

If your host machine has an NVIDIA GPU and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed, run the GPU-accelerated gateway on port `8001`:

```bash
docker compose --profile gpu up -d rag_pipeline_gpu
```

The gateway automatically detects CUDA and initialises PyTorch on the GPU while maintaining identical route and CORS behaviour.

### Option 3: Hybrid Local Development

Run the PostgreSQL database in Docker while developing the backend and frontend locally:

1. **Start the database container:**

   ```bash
   docker compose up -d db
   ```

2. **Start the Backend Gateway on port 8001:**

   > **Note for Windows:** Set `PYTHONUTF8=1` to prevent Unicode encoding errors with emoji logs in standard Windows consoles (`cp1252`).

   ```powershell
   # Windows PowerShell
   $env:PYTHONUTF8 = "1"
   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload

   # Linux / macOS Bash
   export PYTHONUTF8=1
   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
   ```

3. **Start the Frontend Portal on port 5173:**

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

### Standalone Microservice (Isolated Benchmarks)

To launch the isolated RAG microservice without the full gateway:

```powershell
# Windows PowerShell
$env:PYTHONPATH = "backend"
python -m uvicorn rag_pipeline.main:app --host 0.0.0.0 --port 8000 --reload

# Linux / macOS Bash
PYTHONPATH=backend python -m uvicorn rag_pipeline.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Admin Observability

An authenticated Admin user has access to comprehensive system telemetry:

1. **Real-Time Telemetry Logs (`/admin/telemetry`)**:
   - Requires Supabase authentication where the user possesses `app_metadata.role = 'admin'`.
   - PostgREST queries `telemetry.recommendation_logs` protected by database Row Level Security (RLS).
   - Inspect individual query latencies, vector similarity scores, Cross-Encoder reranker scores, and client metadata.

2. **LLM Token Usage & Budget Metrics (`/admin/llm-usage`)**:
   - Queries `GET /admin/llm-usage/daily` and `GET /admin/llm-usage/current-budget` on the backend gateway (`:8001`).
   - Accessible via an admin Supabase session or an admin API key passed in the `Authorization: Bearer <key>` header (configured via `ADMIN_API_KEY`).
   - Displays real-time token burn rates, estimated USD costs, cache hit ratios, and budget ceiling consumption across pipeline layers (`nli`, `retrieval`, and `presentation`).

---

### Deploying to Modal

```bash
modal deploy modal_deploy.py
```

---

## Current Status

| Component | Status |
|-----------|--------|
| Data pipeline (fetch, preprocess, embed, load) | ✅ Done |
| Retrieval pipeline | ✅ Done |
| Reranking pipeline | ✅ Done |
| FastAPI backend | ✅ Done |
| API key auth + rate limiting | ✅ Done |
| Docker containerisation | ✅ Done |
| Automatic data refresh (GitHub Actions) | ✅ Done |
| Live PostgreSQL database (Supabase) | ✅ Done |
| Serverless API hosting (Modal) | ✅ Done |
| Retrieval latency optimizations | ✅ Done |
| LLM integration | 🔄 In Progress |
| Frontend | 📋 To Do |

---

## Planned Improvements

- Fine-tune the cross-encoder on anime-specific relevance data
- Add query result caching for frequent searches
- Personalised recommendations based on user history
- WhatsApp integration
- ONNX Runtime optimisation for faster CPU inference