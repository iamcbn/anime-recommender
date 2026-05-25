# Anime Recommender System

A semantic anime recommendation system built on a two-stage neural retrieval and ranking pipeline. The system understands the meaning behind anime descriptions, genres, and titles to surface recommendations based on thematic and narrative similarity, not just keyword overlap.

Served through a FastAPI backend with API key authentication and rate limiting.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     DATA PIPELINE                       │
│                   (run_pipeline.py)                     │
│                                                         │
│  Kaggle API ──► Version Check ──► Download              │
│       │                                                 │
│       ▼                                                 │
│  Preprocessor                                           │
│    • Clean descriptions (HTML, encoding)                │
│    • Filter MUSIC format entries                        │
│    • Parse JSON columns                                 │
│    • Filter by relationship type                        │
│    • Build embedding_text (title + synopsis +           │
│      genres + tags)                                     │
│    • Split into 5 normalised tables                     │
│       │                                                 │
│       ▼                                                 │
│  Embedder                                               │
│    • Train / load FastText on corpus                    │
│    • Generate MiniLM embeddings (384-dim)               │
│    • Generate FastText embeddings (300-dim)             │
│       │                                                 │
│       ▼                                                 │
│  DatabaseManager                                        │
│    • Write to temp tables (staging)                     │
│    • Promote temp ──► main tables                       │
│    • Cleanup temp tables                                │
│    • Record dataset version in db_state                 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                RECOMMENDATION PIPELINE                  │
│                   (rag_pipeline.py)                     │
│                                                         │
│  User Query                                             │
│       │                                                 │
│       ▼                                                 │
│  Embedder                                               │
│    • MiniLM embedding (384-dim)                         │
│    • FastText embedding (300-dim)                       │
│       │                                                 │
│       ▼                                                 │
│  DatabaseManager                                        │
│    • pgvector cosine search (SBERT) ──► top 50          │
│    • pgvector cosine search (FastText) ──► top 50       │
│       │                                                 │
│       ▼                                                 │
│  Ranker                                                 │
│    • Merge & deduplicate by anime ID                    │
│    • Cross-encoder reranking                            │
│    • Franchise collapse (fuzzy dedup)                   │
│    • Serialise to JSON                                  │
│       │                                                 │
│       ▼                                                 │
│  FastAPI Response                                       │
└─────────────────────────────────────────────────────────┘
```

---

## Models

| Role | Model | Dimension |
|------|-------|-----------|
| Semantic retrieval | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 |
| Keyword / title retrieval | Custom FastText (`anime_fasttext.bin`) | 300 |
| Reranker | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | — |

**Why two retrieval models?**
MiniLM captures semantic meaning across multilingual text, making it strong for synopsis and thematic matching. The FastText model is trained directly on the anime corpus using a skipgram approach, making it stronger for anime titles, Romanji, and rare vocabulary. Together they provide broader candidate coverage before the reranker scores them.

**Why this cross-encoder?**
`mmarco-mMiniLMv2-L12-H384-v1` is trained on multilingual data and handles Romanji well. Unlike the bi-encoders which embed query and candidate independently, the cross-encoder reads both together and produces a relevance score that accounts for narrative similarity, genre overlap, and tone.

Models are downloaded from Hugging Face automatically on first run if not found locally. All models run on GPU if available, falling back to CPU automatically.

---

## Project Structure

```
ANIME_RECOMMENDER/
├── .github/
│   └── workflows/
│       └── update_data.yml               # GitHub Actions: weekly data refresh
├── backend/
│   ├── data_pipeline/
│   │   ├── artefacts/                    # Versioned local dataset storage
│   │   │   └── v{n}/
│   │   │       ├── raw_data/             # Downloaded .xlsx from Kaggle
│   │   │       └── metadata/             # Dataset and Kaggle metadata
│   │   ├── helper/
│   │   │   ├── fetch_data.py             # KaggleDataVersionManager
│   │   │   ├── preprocess.py             # Preprocessor
│   │   │   ├── embedding.py              # Embedder (pipeline version)
│   │   │   └── database.py              # DatabaseManager + SQL schemas
│   │   ├── __init__.py
│   │   ├── config.py                     # DB config loader (env-var based)
│   │   ├── requirements.txt
│   │   ├── run_pipeline.py              # Pipeline entry point
│   │   ├── .dockerignore
│   │   └── Dockerfile                    # Multi-stage build (CPU)
│   ├── models/                           # Shared model storage (mounted as volume)
│   │   ├── cross-encoder-mmarco-mMiniLMv2-L12-H384-v1/
│   │   ├── paraphrase-multilingual-MiniLM-L12-v2/
│   │   ├── anime_fasttext.bin            # Corpus-trained FastText model
│   │   └── anime_fasttext.txt            # FastText training corpus
│   ├── rag_pipeline/
│   │   ├── helper/
│   │   │   ├── service_embedding.py      # Embedder (inference version)
│   │   │   ├── retrieval.py              # DatabaseManager (query version)
│   │   │   └── ranking.py               # Ranker: reranking + franchise collapse
│   │   ├── __init__.py
│   │   ├── config.py                     # DB config loader (env-var based)
│   │   ├── main.py                       # FastAPI app entry point
│   │   ├── rag_pipeline.py              # Pipeline orchestrator
│   │   ├── requirements.txt
│   │   ├── .dockerignore
│   │   └── Dockerfile                    # Multi-stage build (CUDA)
│   └── __init__.py
├── misc/
├── anime/
├── .env                                  # Single source of truth for all credentials
├── docker-compose.yml                    # Wires services and shared model volume
└── README.md
```

---

## Database Schema

The dataset is split into five normalised tables, all linked by `id`:

| Table | Contents |
|-------|----------|
| `anime_core` | Titles (English, Romaji, native, preferred), synonyms, cover images, MAL ID, site URL |
| `anime_content` | Description, genres, tags, format, source, country, adult flag, studios, relationship type |
| `anime_temporal` | Season, year, episodes, duration, status, start/end dates |
| `anime_metrics` | Average score, mean score, popularity, favourites, trending, rankings, recommendations |
| `anime_embedding` | `embedding_text`, `sbert_embedding vector(384)`, `fasttext_embedding vector(300)` |

Embeddings are stored using the `pgvector` extension. Similarity search uses the `<=>` cosine distance operator directly in SQL.

---

## Data Pipeline

The pipeline in `run_pipeline.py` handles the full lifecycle from Kaggle to the database. It only runs when a newer dataset version is detected.

### Step 1: Version Check

`KaggleDataVersionManager` queries the Kaggle API for the remote dataset version and compares it against the local `.dataset_state.json`. If the remote version is newer (or no local version exists), a new versioned directory is created under `artefacts/v{n}/`.

### Step 2: Download

The dataset (`anilist_anime_data_complete.xlsx`) is downloaded into `artefacts/v{n}/raw_data/`. The download uses exponential backoff retry (up to 5 attempts) to handle SSL errors.

### Step 3: Preprocessing (`Preprocessor`)

- HTML entities decoded and tags stripped from descriptions
- MUSIC format entries removed
- JSON-stringified columns (`synonyms`, `genres`, `tags`, `studios`, `rankings`, `recommendations`) parsed into Python objects
- Entries with no description dropped
- Entries filtered by relationship type: SEQUEL, PREQUEL, SPIN_OFF, and SIDE_STORY are kept; ADAPTATION, ALTERNATIVE, CHARACTER, PARENT, OTHER, and SUMMARY are dropped
- Each anime is assigned a `relationship_type` label
- `embedding_text` constructed by joining: all title variants (separated by ` | `), synopsis, genres, and tag names

The preprocessed data is split into the five tables above and returned as a dictionary.

### Step 4: Embedding (`Embedder`)

- MiniLM encodes all `embedding_text` values in batches of 64 with L2 normalisation
- FastText is trained from scratch on the `embedding_text` corpus using skipgram (dim=300, 25 epochs, lr=0.03, minCount=2) if no model exists or `retrain_fasttext=True` is set; otherwise the saved model is loaded
- Both embedding columns are added to the `anime_embedding` DataFrame before database insertion

### Step 5: Staging and Promotion

Data is written to temporary tables (`t{table_name}`) first. If batch insertion fails on any row, the pipeline falls back to row-by-row insertion and logs the exact failing row and column. Once all temp tables are populated successfully, data is promoted to the main tables via `TRUNCATE ... CASCADE` followed by `INSERT ... SELECT`. Temp tables are dropped after promotion.

### Step 6: State Recording

The dataset version and timestamp are written to the `db_state` table in PostgreSQL, and the local `.dataset_state.json` is updated. State is only recorded after the entire pipeline completes successfully to prevent partial-run false positives.

---

## Recommendation Pipeline

### Embedding (`service_embedding.py`)

The query is embedded independently by both models:
- MiniLM: L2-normalised 384-dim dense vector
- FastText: sentence vector from the anime-trained model, L2-normalised to 300-dim

### Retrieval (`retrieval.py`)

Two separate pgvector cosine similarity queries run against `anime_embedding`, one per model, each returning the top 50 candidates. Adult content is filtered at the database level via the `isAdult` flag in `anime_content`. Dimension validation is enforced before each query (384 for SBERT, 300 for FastText) and raises a `ValueError` before hitting the database if incorrect.

### Reranking and Franchise Collapse (`ranking.py`)

SBERT and FastText candidates are merged and deduplicated by anime ID. The cross-encoder scores every (query, candidate) pair simultaneously and results are sorted descending by score.

Before returning, a franchise collapse step removes near-duplicate entries from the same franchise. Titles are normalised by stripping subtitles after colons, removing bracketed content, and removing noise words (movie, season, part, arc, etc.). Normalised titles are compared using `rapidfuzz.token_set_ratio` with a threshold of 90. Only the highest-ranked entry per franchise cluster is kept. The final list is truncated to `top_k`.

---

## API

### Authentication

All requests require an API key in the request header:

```
access_token: <your_api_key>
```

Invalid or missing keys return `403 Forbidden`.

### Rate Limiting

20 requests per minute per API key. Exceeding this returns `429 Too Many Requests`.

### Endpoints

#### `GET /`

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
      "id": 1535,
      "title_romaji": "Death Note",
      "title_userPreferred": "Death Note",
      "title_english": "Death Note",
      "coverImage_large": "https://...",
      "cross_encoder_score": 4.821,
      "cosine_similarity": 0.934
    }
  ],
  "extra": {
    "timings": {
      "embedding_ms": 12.4,
      "retrieval_ms": 38.7,
      "reranking_ms": 210.3
    },
    "total_ms": 261.4
  }
}
```

The `extra.timings` field breaks down latency per pipeline stage in milliseconds.

---

## Planned Production Architecture

To balance cost, performance, and automation, the production stack is designed as follows:

1. **Database (Supabase):** Managed PostgreSQL with native `pgvector` support.
2. **Data Pipeline (GitHub Actions):** Runs fully autonomously via a cron schedule (every Sunday at 3 AM UTC). It builds the multi-stage CPU Docker image, connects to the Supabase database, and pushes fresh Kaggle data.
3. **API Hosting (Modal / Hugging Face Spaces):** The `rag_pipeline` is deployed to a serverless GPU provider. This ensures blazing fast inference (sub-second) while scaling to zero when idle, keeping costs incredibly low.

---

## Setup & Local Development

### Prerequisites

- Python 3.11+
- PostgreSQL with the `pgvector` extension
- Kaggle API credentials in `.env` file
- Docker and Docker Compose

### Environment Variables

Create a `.env` file in the project root:

```env
MY_API_KEY=your_secret_api_key

DB_HOST=localhost
DB_PORT=5432
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

We use **multi-stage Docker builds** to keep images lean. The data pipeline uses a CPU-only image (optimised for GitHub Actions runners), while the RAG pipeline includes CUDA support for GPU acceleration.

```bash
docker compose up
```

Models are mounted from `./backend/models` into each container at `/app/models`. The `rag_pipeline` service picks up updated FastText models automatically after each `data_pipeline` run without a rebuild.

**Enabling GPU Acceleration (Optional):**
By default, `docker-compose.yml` runs on CPU so that anyone can clone and run the project without NVIDIA driver errors. If you have an NVIDIA GPU and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed, add this `deploy` block under the `rag_pipeline` service in `docker-compose.yml`:

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

The Python code automatically detects GPU availability at runtime (`torch.cuda.is_available()`), so no code changes are needed.

---

## Tradeoffs, Issues Encountered, & Blockers

During the containerisation and development phase, several critical engineering hurdles were tackled:

1. **Host-Level DNS Blocking Docker Pulls:**
   * **Issue:** Docker image builds failed with `dial tcp: lookup auth.docker.io: no such host`.
   * **Cause/Fix:** The local router/ISP was silently blocking Docker Hub DNS resolution. Fixed by temporarily overriding Windows host Wi-Fi DNS to `8.8.8.8` (Google Public DNS).

2. **Missing Dependencies (`openpyxl`):**
   * **Issue:** `pandas.read_excel()` threw a `ModuleNotFoundError` during the data pipeline.
   * **Fix:** The Kaggle dataset is an `.xlsx` file. Added `openpyxl==3.1.5` (minimum version required by Pandas 3.0.0) to `requirements.txt`.

3. **State Management Bug in Pipeline:**
   * **Issue:** If the pipeline crashed mid-execution (e.g., during embedding), it still reported "Dataset already up to date" on the next run, preventing recovery.
   * **Fix:** The dataset state was being recorded immediately after download (before processing). Moved `_record_version()` to the very end of the pipeline to ensure state is only saved after the entire pipeline succeeds.

4. **Hugging Face Model Identifier Typo (401 Unauthorized):**
   * **Issue:** Docker container crashed with `Repository Not Found` when trying to download the SBERT model.
   * **Cause:** The script used `paraphrase/multilingual-MiniLM-L12-v2`, which Hugging Face interpreted as a user named `paraphrase`. Locally, this bug was hidden because the model folder already existed on disk and the download path was never triggered.
   * **Fix:** Changed to the correct identifier: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

5. **CPU vs GPU Image Size Tradeoff:**
   * **Tradeoff:** Installing PyTorch with CUDA support increases the Docker image size significantly (~4 GB vs ~1.5 GB for CPU-only).
   * **Decision:** The RAG API uses the CUDA-enabled image for production inference speed. The Data Pipeline uses a lean CPU-only image since it runs on standard GitHub Actions runners. Both use multi-stage builds to strip out build tools (`build-essential`) from the final image.

---

## Change Management (Changelog)

> Keeping a changelog helps track architectural pivots, understand why certain decisions were made, and leaves a paper trail for future collaborators.

### v1.1.0 (Current): Dockerisation & CI/CD
- Added `docker-compose.yml` wiring PostgreSQL (pgvector), Data Pipeline, and RAG Pipeline
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

---

## Current Status

| Component | Status |
|-----------|--------|
| Data pipeline (fetch, preprocess, embed, load) | Done |
| Retrieval pipeline | Done |
| Reranking pipeline | Done |
| FastAPI backend | Done |
| API key auth + rate limiting | Done |
| Docker containerisation | Done |
| Automatic data refresh (GitHub Actions) | In progress |
| Live PostgreSQL database (Supabase) | In progress |
| Frontend | To Do |

---

## Planned Improvements

- Fine-tune the cross-encoder on anime-specific relevance data
- Add query result caching for frequent searches
- Personalised recommendations based on user history
- WhatsApp integration
- ONNX Runtime optimisation for faster CPU inference
