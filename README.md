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
| `query` | string | Yes | — | Minimum 2 characters |
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

The portal runs on `http://localhost:5173` and connects to the backend gateway at `http://localhost:8000`.

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

DB_HOST=your_db_host
DB_PORT=your_db_port
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password

MODELS_DIR=/app/models

KAGGLE_USERNAME=your_kaggle_username
KAGGLE_KEY=your_kaggle_api_key
HF_TOKEN=your_huggingface_token
```

Both services read from this file. No `database.ini` is needed.

### Running the Data Pipeline

```bash
cd backend
python -m data_pipeline.run_pipeline
```

The pipeline exits early with a message if the dataset is already up to date.

### Running the API

```bash
cd backend
uvicorn rag_pipeline.main:app --reload
```

### Running with Docker

By default, the `docker-compose.yaml` runs on CPU so anyone can clone and run without GPU drivers:

```bash
docker compose up
```

**GPU Acceleration (Optional):**
If you have an NVIDIA GPU and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed:

```bash
docker compose --profile gpu up
```

The API endpoints will be available at:
- `http://localhost:8000` — CPU (Standard)
- `http://localhost:8001` — GPU (Accelerated)

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