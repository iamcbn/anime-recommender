# Architecture

A deep-dive into the technical design of the Anime Recommender System. For setup instructions and API usage, see [README.md](README.md).

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
│    • Drop HNSW indexes                                  │
│    • Promote temp ──► main tables                       │
│    • Rebuild HNSW indexes                               │
│    • Cleanup temp tables                                │
│    • Record dataset version + kaggle_version in db_state│
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
│  DatabaseManager (connection-pooled)                    │
│    • pgvector HNSW cosine search (SBERT) ──► top 50     │
│    • pgvector HNSW cosine search (FastText) ──► top 50  │
│    • Both searches run concurrently via ThreadPool      │
│       │                                                 │
│       ▼                                                 │
│  Ranker                                                 │
│    • Merge & deduplicate by anime ID                    │
│    • Cross-encoder reranking                            │
│    • Franchise collapse (fuzzy dedup)                   │
│    • Serialise to JSON                                  │
│       │                                                 │
│       ▼                                                 │
│  FastAPI Response (Deployed on Modal)                   │
└─────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ANIME_RECOMMENDER/
├── .github/
│   └── workflows/
│       └── update_data.yaml               # GitHub Actions: weekly data refresh & Supabase Sync
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
├── docs/
│   └── DEVELOPER_JOURNAL.md              # Personal dev log, blockers, and changelog
├── misc/
├── anime/
├── .env                                  # Single source of truth for all credentials
├── modal_deploy.py                       # Modal production deployment script
├── docker-compose.yaml                   # Wires services and shared model volume
├── ARCHITECTURE.md                       # Technical deep-dive (this file)
└── README.md                             # Setup, usage, and API reference
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

`KaggleDataVersionManager` queries the Kaggle API for the remote dataset version and compares it against the `kaggle_version` stored in the `db_state` table in PostgreSQL (falling back to the local `.dataset_state.json` if the database value is `NULL`). Using the database as the primary source of truth ensures the staleness check works correctly in ephemeral CI environments like GitHub Actions, where the local JSON file does not persist between runs. If the remote version is newer (or no known version exists), a new versioned directory is created under `artefacts/v{n}/`.

### Step 2: Download

The dataset (`anilist_anime_data_complete.xlsx`) is downloaded into `artefacts/v{n}/raw_data/`. The download uses exponential backoff retry (up to 5 attempts) to handle transient network errors.

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

Data is written to temporary tables (`t{table_name}`) first. If batch insertion fails on any row, the pipeline falls back to row-by-row insertion and logs the exact failing row and column. Once all temp tables are populated successfully, HNSW vector indexes are dropped to avoid row-by-row index updates during bulk insertion. Data is then promoted to the main tables via `TRUNCATE ... CASCADE` followed by `INSERT ... SELECT`. After promotion, HNSW indexes are rebuilt from scratch on the freshly populated table. Temp tables are dropped after promotion.

### Step 6: State Recording

The dataset version (`dataset_version`), the Kaggle remote version timestamp (`kaggle_version`), and the current timestamp are written to the `db_state` table in PostgreSQL. The local `.dataset_state.json` is also updated and committed back to the repository via a GitHub Actions step. State is only recorded after the entire pipeline completes successfully to prevent partial-run false positives.

---

## Recommendation Pipeline

### Embedding (`service_embedding.py`)

The query is embedded independently by both models:
- MiniLM: L2-normalised 384-dim dense vector
- FastText: sentence vector from the anime-trained model, L2-normalised to 300-dim

### Retrieval (`retrieval.py`)

Two pgvector cosine similarity queries run **concurrently** against `anime_embedding` using `concurrent.futures.ThreadPoolExecutor`, one per model, each returning the top 50 candidates. Both queries are accelerated by HNSW (Hierarchical Navigable Small World) indexes on the `sbert_embedding` and `fasttext_embedding` columns. The `DatabaseManager` uses a `psycopg2.pool.ThreadedConnectionPool` (min 2, max 5 connections) to eliminate per-request TCP connection overhead; each thread leases its own connection from the pool. Adult content is filtered at the database level via the `isAdult` flag in `anime_content`. Dimension validation is enforced before each query (384 for SBERT, 300 for FastText) and raises a `ValueError` before hitting the database if incorrect.

### Reranking and Franchise Collapse (`ranking.py`)

SBERT and FastText candidates are merged and deduplicated by anime ID. The cross-encoder scores every (query, candidate) pair simultaneously and results are sorted descending by score.

Before returning, a franchise collapse step removes near-duplicate entries from the same franchise. Titles are normalised by stripping subtitles after colons, removing bracketed content, and removing noise words (movie, season, part, arc, etc.). Normalised titles are compared using `rapidfuzz.token_set_ratio` with a threshold of 90. Only the highest-ranked entry per franchise cluster is kept. The final list is truncated to `top_k`.

---

## Production Architecture

The stack is designed for minimal operational overhead, cost efficiency, and fast inference:

1. **Database (Supabase):** Managed PostgreSQL running remotely, configured with native `pgvector` support for cosine similarity search.
2. **Data Pipeline (GitHub Actions):** Fully automated CI/CD pipeline triggered via cron (every Sunday at 3 AM UTC). It connects directly to Supabase to ingest and sync the latest Kaggle datasets without manual intervention.
3. **API Hosting (Modal):** The FastAPI RAG system is deployed serverless on Modal (`modal_deploy.py`), taking advantage of Modal's automatic scaling and T4 GPU allocation. The deployment securely mounts local models, injects environment secrets, and achieves fast cold-starts.
