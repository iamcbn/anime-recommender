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

### Authentication

All requests require an API key in the header:

```
access_token: <your_api_key>
```

Invalid or missing keys return `403 Forbidden`.

### Rate Limiting

20 requests per minute per API key. Exceeding this returns `429 Too Many Requests`.

### Endpoints

#### `GET /`

Health check.

```json
{
  "message": "Welcome to the Anime Recommendation API. Use the /recommend endpoint to get recommendations."
}
```

#### `POST /recommend`

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

**Response:**

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
      "coverImage_large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx152802-ENRcnqD5axhQ.jpg",
      "cross_encoder_score": -4.234375,
      "cosine_similarity": 0.8154253363609314
    }
  ],
  "extra": {
    "timings": {
      "embedding_ms": 563.45,
      "retrieval_ms": 338.23,
      "reranking_ms": 794.48
    },
    "total_ms": 1696.16
  }
}
```

The `extra.timings` field breaks down latency per pipeline stage in milliseconds.

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