from psycopg2 import connect, extras
from psycopg2.pool import ThreadedConnectionPool
from typing import List, Tuple
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor



class DatabaseManager:

    def __init__(self, PARAMS: dict, min_conn: int = 2, max_conn: int = 5):
        self.PARAMS = PARAMS
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
    # EMBEDDING METHODS
    # ----------------------

    def semantic_search(
            self,
            query_embedding: List,
            model: str,
            top_k: int = 50,
            allow_adult: bool = False
            ):
        
        query_vector = str(query_embedding)
        #print(len(query_embedding))

        if model == "sbert":
            if len(query_embedding) != 384:
                raise ValueError("SBERT embedding must be 384-dim")

            distance_col = "embed.sbert_embedding"

        elif model == "fasttext":
            if len(query_embedding) != 300:
                raise ValueError("fastText embedding must be 300-dim")

            distance_col = "embed.fasttext_embedding"

        else:
            raise ValueError(f"Unsupported model: {model}")

        query = f"""
            SELECT
                core.id,
                core.title_romaji,
                core.title_english,
                core.coverImage_large,
                content.isAdult,
                embed.embedding_text,
                core.title_userPreferred,
                core.synonyms,
                1 - ({distance_col} <=> %s) AS cosine_similarity
            FROM anime_core AS core
            JOIN anime_embedding AS embed
                ON core.id = embed.id
            JOIN anime_content AS content
                ON core.id = content.id
            WHERE (%s OR content.isAdult = FALSE)
            ORDER BY {distance_col} <=> %s
            LIMIT %s;
        """

        with self.get_cursor() as cur:
            cur.execute(
                query,
                (
                    query_vector,
                    allow_adult,
                    query_vector,
                    top_k,
                ),
            )
            results = cur.fetchall()

        return results
    
    # ----------------------
    # PUTTING THEM TOGETHER
    # ----------------------

    def execute(self, embedding: Tuple, top_k:int =50, allow_adult: bool = False)-> Tuple:
        sbert_embedding, fasttext_embedding = embedding

        with ThreadPoolExecutor(max_workers=2) as executor:
            sbert_future = executor.submit(self.semantic_search, sbert_embedding, 'sbert', top_k, allow_adult)
            fasttext_future = executor.submit(self.semantic_search, fasttext_embedding, 'fasttext', top_k, allow_adult)

            sbert_result = sbert_future.result()
            fasttext_result = fasttext_future.result()

        return sbert_result, fasttext_result


    def close(self):
        """Close all connections in the pool."""
        self._pool.closeall()





