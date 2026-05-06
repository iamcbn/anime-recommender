from .helper.service_embedding import Embedder
from .helper.retrieval import DatabaseManager
from .helper.ranking import Ranker
from .config import config
from typing import Text
import time


PARAMS = config()

embedding = Embedder()
retriever = DatabaseManager(PARAMS=PARAMS)
reranker = Ranker()

# ----------------------
# LOGGING & TIMING
# ----------------------


class Timer:
    def __init__(self):
        self.start = time.perf_counter()

    def elapsed(self) -> float:
        return round((time.perf_counter() - self.start) * 1000, 2)  # milliseconds


# ----------------------
# RAG PIPELINE
# ----------------------

def rag_pipeline(query:Text, top_k: int, allow_adult: bool = False):

    timings = {}

    # ----------------------
    # EMBEDDING
    # ----------------------

    t = Timer()
    embedding_texts = embedding.execute(query=query)
    timings['embedding_ms'] = t.elapsed()


    # ----------------------
    # RETRIEVAL
    # ----------------------

    t = Timer()
    sbert, fasttext = retriever.execute(embedding=embedding_texts, allow_adult=allow_adult)
    timings['retrieval_ms'] = t.elapsed()

    # ----------------------
    # RE-RANKING
    # ----------------------

    t = Timer()
    output = reranker.execute(user_query=query, sbert_result=sbert, fasttext_result=fasttext, top_k=top_k)
    timings['reranking_ms'] = t.elapsed()

    return output, timings





