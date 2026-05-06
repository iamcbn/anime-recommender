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
| Semantic retrieval | `paraphrase-multilingual-MiniLM-L12-v2` | 384 |
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
│   │   └── Dockerfile
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
│   │   └── Dockerfile
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

The dataset version and timestamp are written to the `db_state` table in PostgreSQL, and the local `.dataset_state.json` is updated.

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

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL with the `pgvector` extension
- Kaggle API credentials at `~/.kaggle/kaggle.json` or in `.env` file
- Docker and Docker Compose

### Environment Variables

Create a `.env` file in the project root:

```env
MY_API_KEY=your_secret_api_key

DB_HOST=localhost
DB_PORT=your_db_port
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password

MODELS_DIR=/app/models

export KAGGLE_API_TOKEN=kaggle_api_key
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

```bash
docker compose up
```

Models are mounted from `./backend/models` into each container at `/app/models`. The `rag_pipeline` service picks up updated FastText models automatically after each `data_pipeline` run without a rebuild.

---

## Current Status

| Component | Status |
|-----------|--------|
| Data pipeline (fetch, preprocess, embed, load) | Done |
| Retrieval pipeline | Done |
| Reranking pipeline | Done |
| FastAPI backend | Done |
| API key auth + rate limiting | Done |
| Docker containerisation | In progress |
| Automatic data refresh | To Do |
| Live PostgreSQL database | To Do |
| LLM Integration | To Do |
| Frontend | To Do |

---

## Planned Improvements

- Fine-tune the cross-encoder on anime-specific relevance data
- Add query result caching for frequent searches
- Personalised recommendations based on user history
- WhatsApp integration