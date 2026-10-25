from psycopg2 import extras
from psycopg2.pool import ThreadedConnectionPool, PoolError
from typing import List, Tuple, Optional
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import time
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:

    def __init__(self, PARAMS: dict, min_conn: int = 2, max_conn: int = 5):
        self.PARAMS = PARAMS
        self.min_conn = min_conn
        self.max_conn = max_conn
        try:
            self._pool = ThreadedConnectionPool(
                minconn=min_conn,
                maxconn=max_conn,
                **PARAMS,
                cursor_factory=extras.DictCursor
            )
        except Exception as e:
            logger.warning(
                f"[DatabaseManager] Immediate connection pool creation failed ({e}); "
                "deferring initialization until first query."
            )
            self._pool = None

    def _ensure_pool(self) -> ThreadedConnectionPool:
        if self._pool is None:
            self._pool = ThreadedConnectionPool(
                minconn=self.min_conn,
                maxconn=self.max_conn,
                **self.PARAMS,
                cursor_factory=extras.DictCursor
            )
        return self._pool

    # ----------------------
    # CONNECTION HANDLERS
    # ----------------------

    @contextmanager
    def get_cursor(self, timeout: float = 5.0):
        """
        Thread-safe context manager for acquiring a cursor from the connection pool.

        Features:
        - Graceful retry loop up to `timeout` seconds to absorb momentary connection spikes
          without throwing unhandled psycopg2.pool.PoolError.
        - Automatically tests connection vitality and purges closed/broken connections from the pool.
        """
        start_time = time.monotonic()
        conn = None

        while conn is None:
            try:
                active_pool = self._ensure_pool()
                conn = active_pool.getconn()
            except PoolError:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    logger.error(
                        f"Database connection pool checkout timed out after {timeout:.1f}s. "
                        f"Pool capacity: min={self.min_conn}, max={self.max_conn}."
                    )
                    raise TimeoutError(
                        f"Database connection pool checkout timed out after {timeout:.1f}s. "
                        "All connections are currently in use."
                    )
                time.sleep(0.025)  # 25ms polling backoff

        try:
            with conn:
                with conn.cursor() as cur:
                    yield cur
        except Exception:
            raise
        finally:
            if conn is not None:
                # Discard broken or closed connections so the pool can recreate a healthy one
                is_closed = getattr(conn, "closed", 0) != 0
                self._pool.putconn(conn, close=is_closed)

    # ----------------------
    # DB MIGRATION
    # ----------------------

    def ensure_bm25_index(self):
        """
        One-time migration: adds a tsvector column to anime_content and builds
        a GIN index on it for BM25 full-text search.
        Safe to call on startup or via migration scripts — uses IF NOT EXISTS guards.
        """
        with self.get_cursor() as cur:
            cur.execute("""
                ALTER TABLE anime_content
                ADD COLUMN IF NOT EXISTS search_vector tsvector
                GENERATED ALWAYS AS (
                    to_tsvector('english', coalesce(description, ''))
                ) STORED;
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_anime_content_search_vector
                ON anime_content USING GIN (search_vector);
            """)
        logger.info("BM25 tsvector column and GIN index verified.")

    # ----------------------
    # SEARCH METHODS
    # ----------------------

    def semantic_search(
            self,
            query_embedding: List,
            model: str,
            top_k: int = 20,
            allow_adult: bool = False,
            extra_clauses: Optional[List[str]] = None,
            extra_params: Optional[List] = None,
            ):
        """
        Runs a pgvector cosine similarity search for a single embedding.
        Projects enriched metadata for grounded LLM recommendation synthesis.

        Args:
            query_embedding: The dense vector to search with.
            model: 'sbert' (384-dim) or 'fasttext' (300-dim).
            top_k: Number of results to return.
            allow_adult: Whether to include adult content.
            extra_clauses: Optional list of SQL WHERE clause fragments.
            extra_params: Corresponding parameter values for extra_clauses.
        """
        query_vector = str(query_embedding)

        if model == "sbert":
            if len(query_embedding) != 384:
                raise ValueError("SBERT embedding must be 384-dim")
            distance_col = "sbert_embedding"

        elif model == "fasttext":
            if len(query_embedding) != 300:
                raise ValueError("fastText embedding must be 300-dim")
            distance_col = "fasttext_embedding"

        else:
            raise ValueError(f"Unsupported model: {model}")

        internal_limit = max(top_k * 5, 200)

        extra_clauses = extra_clauses or []
        extra_params = extra_params or []

        extra_where = ""
        if extra_clauses:
            extra_where = "AND " + " AND ".join(extra_clauses)

        sql = f"""
            WITH top_embeddings AS (
                SELECT
                    id,
                    embedding_text,
                    {distance_col} <=> %s AS distance
                FROM anime_embedding
                ORDER BY {distance_col} <=> %s
                LIMIT {internal_limit}
            )
            SELECT
                core.id,
                core.title_romaji,
                core.title_english,
                core.coverImage_large AS "coverImage_large",
                content.isAdult AS "isAdult",
                embed.embedding_text,
                core.title_userPreferred AS "title_userPreferred",
                core.synonyms,
                content.description,
                metrics.popularity,
                1 - embed.distance AS cosine_similarity,
                content.genres,
                content.studios,
                content.tags,
                metrics.averageScore AS "averageScore",
                temporal.seasonYear AS "seasonYear",
                temporal.episodes AS "episodes",
                temporal.status AS "status"
            FROM top_embeddings AS embed
            JOIN anime_core AS core ON core.id = embed.id
            JOIN anime_content AS content ON core.id = content.id
            JOIN anime_metrics AS metrics ON core.id = metrics.id
            LEFT JOIN anime_temporal AS temporal ON core.id = temporal.id
            WHERE (%s OR content.isAdult = FALSE)
            {extra_where}
            ORDER BY embed.distance
            LIMIT %s;
        """

        params = [query_vector, query_vector, allow_adult] + extra_params + [top_k]

        with self.get_cursor() as cur:
            cur.execute(sql, params)
            results = cur.fetchall()

        return results

    def bm25_search(
            self,
            query_text: str,
            top_k: int = 20,
            allow_adult: bool = False,
            extra_clauses: Optional[List[str]] = None,
            extra_params: Optional[List] = None,
            ):
        """
        Runs a Postgres full-text (BM25-equivalent) search using tsvector/tsquery.
        Projects enriched metadata for grounded LLM recommendation synthesis.
        """
        extra_clauses = extra_clauses or []
        extra_params = extra_params or []

        extra_where = ""
        if extra_clauses:
            extra_where = "AND " + " AND ".join(extra_clauses)

        sql = f"""
            SELECT
                core.id,
                core.title_romaji,
                core.title_english,
                core.coverImage_large AS "coverImage_large",
                content.isAdult AS "isAdult",
                embed.embedding_text,
                core.title_userPreferred AS "title_userPreferred",
                core.synonyms,
                content.description,
                metrics.popularity,
                ts_rank(content.search_vector, websearch_to_tsquery('english', replace(%s, ' ', ' OR '))) AS cosine_similarity,
                content.genres,
                content.studios,
                content.tags,
                metrics.averageScore AS "averageScore",
                temporal.seasonYear AS "seasonYear",
                temporal.episodes AS "episodes",
                temporal.status AS "status"
            FROM anime_content AS content
            JOIN anime_core AS core ON core.id = content.id
            JOIN anime_embedding AS embed ON core.id = embed.id
            JOIN anime_metrics AS metrics ON core.id = metrics.id
            LEFT JOIN anime_temporal AS temporal ON core.id = temporal.id
            WHERE content.search_vector @@ websearch_to_tsquery('english', replace(%s, ' ', ' OR '))
            AND (%s OR content.isAdult = FALSE)
            {extra_where}
            ORDER BY cosine_similarity DESC
            LIMIT %s;
        """

        params = [query_text, query_text, allow_adult] + extra_params + [top_k]

        with self.get_cursor() as cur:
            cur.execute(sql, params)
            results = cur.fetchall()

        return results

    def get_candidate_by_id(self, anime_id: int) -> Optional[dict]:
        """
        Retrieves a single anime candidate record by ID from PostgreSQL.
        Returns a dictionary or None if not found or on database exception.
        """
        sql = """
            SELECT
                core.id,
                core.title_romaji,
                core.title_english,
                core.coverImage_large AS "coverImage_large",
                content.isAdult AS "isAdult",
                core.title_userPreferred AS "title_userPreferred",
                core.synonyms,
                content.description,
                metrics.popularity,
                content.genres,
                content.studios,
                content.tags,
                metrics.averageScore AS "averageScore",
                temporal.seasonYear AS "seasonYear",
                temporal.episodes AS "episodes",
                temporal.status AS "status"
            FROM anime_core AS core
            JOIN anime_content AS content ON core.id = content.id
            JOIN anime_metrics AS metrics ON core.id = metrics.id
            LEFT JOIN anime_temporal AS temporal ON core.id = temporal.id
            WHERE core.id = %s;
        """
        try:
            with self.get_cursor() as cur:
                cur.execute(sql, (anime_id,))
                row = cur.fetchone()
                if row:
                    return dict(row)
        except Exception as exc:
            logger.warning(f"[DatabaseManager] Failed to fetch candidate {anime_id} by ID: {exc}")
        return None

    # ----------------------
    # PUTTING THEM TOGETHER
    # ----------------------

    def execute(
            self,
            queries: List[str],
            embeddings: List[Tuple[List, List]],
            top_k: int = 20,
            allow_adult: bool = False,
            extra_clauses: Optional[List[str]] = None,
            extra_params: Optional[List] = None,
            max_workers: int = 3,
            ) -> List:
        """
        Runs all retrieval searches concurrently across all queries.

        Strategy:
          - MiniLM search + FastText search + BM25 search run for ALL queries (original + LLM-generated)
          - Concurrency is bounded to `max_workers=3` to ensure a single RAG request consumes
            at most 3 pool connections simultaneously, leaving sufficient capacity for concurrent
            requests and preventing connection exhaustion under multi-user traffic.

        Args:
            queries: List of query strings [original, query_b, query_c].
            embeddings: Parallel list of (sbert_emb, fasttext_emb) tuples from Embedder.
            top_k: Candidates to fetch per individual search.
            allow_adult: Whether to include adult content.
            extra_clauses: Optional SQL WHERE fragments applied to all searches.
            extra_params: Corresponding parameter values for extra_clauses.
            max_workers: Concurrency ceiling for thread execution (default: 3).

        Returns:
            A flat list of all result rows from all searches, ready for
            merge+deduplication in ranking.py.
        """
        extra_clauses = extra_clauses or []
        extra_params = extra_params or []

        futures = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for i, (query_text, (sbert_emb, fasttext_emb)) in enumerate(zip(queries, embeddings)):
                futures.append(executor.submit(
                    self.semantic_search,
                    sbert_emb, 'sbert', top_k, allow_adult, extra_clauses, extra_params
                ))
                futures.append(executor.submit(
                    self.semantic_search,
                    fasttext_emb, 'fasttext', top_k, allow_adult, extra_clauses, extra_params
                ))
                futures.append(executor.submit(
                    self.bm25_search,
                    query_text, top_k, allow_adult, extra_clauses, extra_params
                ))

            all_results = []
            for f in futures:
                try:
                    all_results.append(f.result())
                except Exception as e:
                    logger.warning(f"Retrieval sub-query failed: {e}", exc_info=True)
                    all_results.append([])

        return all_results

    def close(self):
        """Close all connections in the pool."""
        self._pool.closeall()
