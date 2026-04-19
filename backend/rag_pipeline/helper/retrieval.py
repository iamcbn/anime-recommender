from psycopg2 import connect, extras
from typing import List, Tuple
from contextlib import contextmanager



class DatabaseManager:

    def __init__(self, PARAMS: dict):
        self.PARAMS = PARAMS
        

    # ----------------------
    # CONNECTION HANDLERS
    # ----------------------

    @contextmanager
    def get_cursor(self):
        conn = connect(**self.PARAMS, cursor_factory=extras.DictCursor)
        try:
            with conn:
                with conn.cursor() as cur:
                    yield cur
        finally:
            conn.close()

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
        sbert_result = self.semantic_search(sbert_embedding, 'sbert', top_k, allow_adult)
        fasttext_result = self.semantic_search(fasttext_embedding, 'fasttext', top_k, allow_adult)

        return sbert_result, fasttext_result









