from psycopg2 import connect, extras
from psycopg2.pool import ThreadedConnectionPool
from typing import List, Tuple, Optional
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:

    def __init__(self, PARAMS: dict, min_conn: int = 2, max_conn: int = 10):
        self.PARAMS = PARAMS
        # Increased max_conn from 5 to 10 to handle up to 7 concurrent searches
        self._pool = ThreadedConnectionPool(
            minconn=min_conn,
            maxconn=max_conn,
            **PARAMS,
            cursor_factory=extras.DictCursor
        )


    # ----------------------
    # CONNECTION HANDLERS
    # ----------------------

    @contextmanager
    def get_cursor(self):
        conn = self._pool.getconn()
        try:
            with conn:
                with conn.cursor() as cur:
                    yield cur
        finally:
            self._pool.putconn(conn)

    # ----------------------
    # DB MIGRATION
    # ----------------------

    def ensure_bm25_index(self):
        """
        One-time migration: adds a tsvector column to anime_content and builds
        a GIN index on it for BM25 full-text search.
        Safe to call on every startup — uses IF NOT EXISTS guards.
        """
        with self.get_cursor() as cur:
            # Add the column if it doesn't already exist
            cur.execute("""
                ALTER TABLE anime_content
                ADD COLUMN IF NOT EXISTS search_vector tsvector
                GENERATED ALWAYS AS (
                    to_tsvector('english', coalesce(description, ''))
                ) STORED;
            """)
            # Create GIN index if it doesn't already exist
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

        Args:
            query_embedding: The dense vector to search with.
            model: 'sbert' (384-dim) or 'fasttext' (300-dim).
            top_k: Number of results to return.
            allow_adult: Whether to include adult content.
            extra_clauses: Optional list of SQL WHERE clause fragments (currently
                           unused; the pipeline passes none). These join
                           the existing anime_temporal and anime_metrics tables.
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

        # Build optional self-query filter block
        extra_clauses = extra_clauses or []
        extra_params = extra_params or []

        needs_temporal = any("temporal." in c for c in extra_clauses)
        # metrics is always joined unconditionally now to fetch popularity for the reranker
        temporal_join = (
            'JOIN anime_temporal AS temporal ON core.id = temporal.id'
            if needs_temporal else ''
        )
        metrics_join = 'JOIN anime_metrics AS metrics ON core.id = metrics.id'

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
                core.coverImage_large,
                content.isAdult,
                embed.embedding_text,
                core.title_userPreferred,
                core.synonyms,
                content.description,
                metrics.popularity,
                1 - embed.distance AS cosine_similarity
            FROM top_embeddings AS embed
            JOIN anime_core AS core ON core.id = embed.id
            JOIN anime_content AS content ON core.id = content.id
            {temporal_join}
            {metrics_join}
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
        """
        extra_clauses = extra_clauses or []
        extra_params = extra_params or []

        needs_temporal = any("temporal." in c for c in extra_clauses)
        # metrics is always joined unconditionally now to fetch popularity for the reranker

        temporal_join = (
            'JOIN anime_temporal AS temporal ON core.id = temporal.id'
            if needs_temporal else ''
        )
        metrics_join = 'JOIN anime_metrics AS metrics ON core.id = metrics.id'

        extra_where = ""
        if extra_clauses:
            extra_where = "AND " + " AND ".join(extra_clauses)

        sql = f"""
            SELECT
                core.id,
                core.title_romaji,
                core.title_english,
                core.coverImage_large,
                content.isAdult,
                embed.embedding_text,
                core.title_userPreferred,
                core.synonyms,
                content.description,
                metrics.popularity,
                ts_rank(content.search_vector, websearch_to_tsquery('english', replace(%s, ' ', ' OR '))) AS cosine_similarity
            FROM anime_content AS content
            JOIN anime_core AS core ON core.id = content.id
            JOIN anime_embedding AS embed ON core.id = embed.id
            {temporal_join}
            {metrics_join}
            WHERE content.search_vector @@ websearch_to_tsquery('english', replace(%s, ' ', ' OR '))
            AND (%s OR content.isAdult = FALSE)
            {extra_where}
            ORDER BY cosine_similarity DESC
            LIMIT %s;
        """

        # We pass query_text directly; the SQL `replace()` turns it into "word1 OR word2"
        params = [query_text, query_text, allow_adult] + extra_params + [top_k]

        with self.get_cursor() as cur:
            cur.execute(sql, params)
            results = cur.fetchall()

        return results

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
            ) -> List:
        """
        Runs all retrieval searches concurrently across all queries.

        Strategy:
          - MiniLM search + FastText search + BM25 search run for ALL queries (original + LLM-generated)

        Args:
            queries: List of query strings [original, query_b, query_c].
            embeddings: Parallel list of (sbert_emb, fasttext_emb) tuples from Embedder.
            top_k: Candidates to fetch per individual search.
            allow_adult: Whether to include adult content.
            extra_clauses: Optional SQL WHERE fragments applied to all searches (currently unused).
            extra_params: Corresponding parameter values for extra_clauses.

        Returns:
            A flat list of all result rows from all searches, ready for
            merge+deduplication in ranking.py.
        """
        extra_clauses = extra_clauses or []
        extra_params = extra_params or []

        futures = []

        with ThreadPoolExecutor(max_workers=10) as executor:
            for i, (query_text, (sbert_emb, fasttext_emb)) in enumerate(zip(queries, embeddings)):
                # MiniLM and FastText run for ALL queries
                futures.append(executor.submit(
                    self.semantic_search,
                    sbert_emb, 'sbert', top_k, allow_adult, extra_clauses, extra_params
                ))
                futures.append(executor.submit(
                    self.semantic_search,
                    fasttext_emb, 'fasttext', top_k, allow_adult, extra_clauses, extra_params
                ))
                # BM25 now runs for ALL queries (original + HyDE hypotheticals)
                # This drastically improves recall by matching keywords from the LLM-generated synopsis
                futures.append(executor.submit(
                    self.bm25_search,
                    query_text, top_k, allow_adult, extra_clauses, extra_params
                ))

            all_results = []
            for f in futures:
                all_results.append(f.result())

        return all_results


    def close(self):
        """Close all connections in the pool."""
        self._pool.closeall()






