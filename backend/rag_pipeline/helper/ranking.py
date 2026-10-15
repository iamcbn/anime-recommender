from pathlib import Path
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
import pandas as pd, numpy as np
from typing import List, Tuple, Optional, Set, Any, Dict
import torch
import logging
import re
import json
import itertools
from rapidfuzz import fuzz



logger = logging.getLogger(__name__)

"""
cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 - HANDLES ROMANJI AND BETTER FOR SEARCHES
cross-encoder-stsb-distilroberta-base - UNDERSTANDS SEMANTICS 
"""

class Ranker:

    DIR = Path(__file__).parents[2].resolve()
    MODEL_PATH = DIR / "models"


    CROSS_ENCODER_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    CROSS_ENCODER_DIR = "cross-encoder-mmarco-mMiniLMv2-L12-H384-v1"

    # Ensuring cross encoder uses GPU
    DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
    MODEL_KWARGS = {"dtype": torch.float16} if DEVICE == "cuda" else {}

    

    def __init__(self, model_path: Path = MODEL_PATH):
        
        # Loading model path
        self.model_path = model_path
        
        self.cross_encoder_path = model_path / self.CROSS_ENCODER_DIR
        self.cross_encoder = self.load_cross_encoder()


    # ----------------------
    # MODEL LOADING
    # ----------------------

    def load_cross_encoder(self) -> CrossEncoder:
        # Check if model exists
        if not self.cross_encoder_path.exists():
            raise FileNotFoundError(
                f"Cross-encoder model not found at {self.cross_encoder_path}. "
                f"Run the data pipeline first to download models."
            )
        try:
            model =  CrossEncoder(str(self.cross_encoder_path),
                                  model_kwargs=self.MODEL_KWARGS, 
                                  device=self.DEVICE,
                                  tokenizer_kwargs={"fix_mistral_regex": True}
                                  )
            return model
        except Exception:
            logger.exception("CrossEncoder initialisation failed")
            raise


    # ------------------------
    # Merging and deduplicating
    # -------------------------

    def merge_deduplicate(
        self,
        all_results: list,
        seen_ids: Optional[set[int]] = None
    ) -> pd.DataFrame:
        """
        Takes a list of ranked lists from different searches (MiniLM, FastText, BM25),
        filters seen_ids in memory using O(1) set subtraction, calculates RRF scores
        across them, and deduplicates.
        """
        seen_set = set(seen_ids) if seen_ids else set()

        col = [
            'id', 'title_romaji', 'title_english', 'coverImage_large', 'isAdult',
            'embedding_text', 'title_userPreferred', 'synonyms', 'description',
            'genres', 'studios', 'tags', 'averageScore', 'seasonYear', 'episodes',
            'status', 'popularity', 'cosine_similarity'
        ]

        rrf_scores = {}
        row_data = {}
        k = 20

        for ranked_list in all_results:
            for rank, row in enumerate(ranked_list, start=1):
                # Handle DictRow, dict, or tuple/list safely
                if hasattr(row, "keys"):
                    anime_id = row["id"]
                else:
                    anime_id = row[0]

                # O(1) in-memory hash set subtraction: skip seen/dropped anime
                if anime_id in seen_set:
                    continue

                if anime_id not in rrf_scores:
                    rrf_scores[anime_id] = 0.0
                    if hasattr(row, "keys"):
                        row_dict = {c: row[c] for c in col if c in row}
                    elif len(row) == len(col):
                        row_dict = dict(zip(col, row))
                    elif len(row) == 11:
                        # Defensive handling for legacy 11-column tuples
                        legacy_cols = [
                            'id', 'title_romaji', 'title_english', 'coverImage_large', 'isAdult',
                            'embedding_text', 'title_userPreferred', 'synonyms', 'description',
                            'popularity', 'cosine_similarity'
                        ]
                        row_dict = dict(zip(legacy_cols, row))
                    else:
                        row_dict = dict(zip(col[:len(row)], row))

                    row_data[anime_id] = row_dict

                rrf_scores[anime_id] += 1.0 / (k + rank)

        if not row_data:
            return pd.DataFrame(columns=col + ['retrieval_rrf_score'])

        for anime_id in row_data:
            row_data[anime_id]['retrieval_rrf_score'] = rrf_scores[anime_id]

        df = pd.DataFrame(list(row_data.values()))
        for c in col:
            if c not in df.columns:
                df[c] = None

        df = df[col + ['retrieval_rrf_score']]
        df = df.sort_values(by='retrieval_rrf_score', ascending=False).reset_index(drop=True)
        return df


    # ----------------------
    # RE-RANKING
    # ----------------------

    @staticmethod
    def _creating_pairs(query : str, retrieved_results: pd.DataFrame) -> List[Tuple]:
        pairs = list(zip(
            itertools.repeat(query),
            retrieved_results["description"].fillna("").tolist()
            ))
       
        return pairs
    
    def rerank(self, query: str, retrieved_results: pd.DataFrame) -> np.ndarray:
        pairs = self._creating_pairs(query, retrieved_results)

        results = self.cross_encoder.predict(pairs, batch_size=32, show_progress_bar=False)

        return results
    

    # ----------------------
    # REORDERING
    # ----------------------

    def reorder(self, retrieved_results: pd.DataFrame, rerank: np.ndarray) -> pd.DataFrame:
        
        if retrieved_results.empty:
            reranked_results = retrieved_results.copy()
            reranked_results['cross_encoder_score'] = []
            reranked_results['final_rrf_score'] = []
            return reranked_results

        reranked_results = retrieved_results.copy()
        reranked_results['cross_encoder_score'] = rerank
        
        # 1. Get ranks from the initial retrieval (it's already sorted by retrieval_rrf_score, so index+1 is the rank)
        retrieval_ranks = np.arange(1, len(reranked_results) + 1)
        
        # 2. Get ranks from the Cross-Encoder (higher score = better rank)
        # argsort() twice gives the ranks (0-indexed, ascending), so we invert it for descending ranks
        ce_ranks = len(rerank) - np.argsort(np.argsort(rerank))
        
        # 3. Calculate Final RRF combining Retrieval consensus and Cross-Encoder
        k = 20
        final_rrf = (1.0 / (k + retrieval_ranks)) + (1.0 / (k + ce_ranks))
        
        # 4. Soft popularity boost
        pop_boost = np.log1p(reranked_results['popularity'].fillna(0)) / 100.0
        
        # Final hybrid score
        reranked_results['final_rrf_score'] = final_rrf + pop_boost

        return reranked_results.sort_values(by='final_rrf_score', ascending=False)
    

    # ----------------------
    # FINAL CLEANING
    # ----------------------

    @staticmethod
    def parse_json(x):
        """
        Parse stringified JSON into Python objects.
        Always returns a list (empty if missing or invalid).
        """
        if isinstance(x, list):
            return x
        if isinstance(x, dict):
            return [x]
        if pd.isna(x):
            return []
        if isinstance(x, str):
            try:
                parsed = json.loads(x)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    return [parsed]
            except Exception:
                return []
        return []

    def pick_title(self, row) -> str:
        for col in [
            "title_userPreferred",
            "title_romaji",
            "title_english"
        ]:
            val = row.get(col)
            if isinstance(val, str) and val.strip():
                return val.strip()

        synonyms = self.parse_json(row.get("synonyms"))
        if isinstance(synonyms, list) and synonyms:
            return synonyms[0]

        return ""
    
    def json_conversion(self, df: pd.DataFrame, include_metadata: bool = True) -> list:
        if df.empty:
            return []

        df = df.copy()
        base_cols = [
            'id', 'title_romaji', 'title_userPreferred', 'title_english',
            'coverImage_large', 'cross_encoder_score', 'final_rrf_score', 'retrieval_rrf_score'
        ]

        if include_metadata:
            meta_cols = [
                'description', 'genres', 'studios', 'tags',
                'averageScore', 'seasonYear', 'episodes', 'status'
            ]
            for col_name in meta_cols:
                if col_name in df.columns:
                    base_cols.append(col_name)

        target_cols = [c for c in base_cols if c in df.columns]
        df = df[target_cols]

        # Convert NaNs to None for valid JSON serialization
        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        return records

    # ----------------------
    # PUTTING THEM TOGETHER
    # ----------------------

    def execute(
        self,
        user_query: str,
        all_results: list,
        top_k: int,
        seen_ids: Optional[set[int]] = None,
        include_metadata: bool = True
    ) -> list:
        """
        Takes the flat pooled results from all retrieval searches, deduplicates,
        filters seen_ids in memory, reranks with the cross-encoder against the
        original user query, collapses franchises, and serialises to JSON.
        """
        if not all_results:
            return []

        df = self.merge_deduplicate(all_results, seen_ids=seen_ids)
        if df.empty:
            return []

        scores = self.rerank(query=user_query, retrieved_results=df)
        df = self.reorder(retrieved_results=df, rerank=scores)
        output = self.collapse_franchises2(reranked_df=df, top_k=top_k)
        final_output = self.json_conversion(output, include_metadata=include_metadata)

        return final_output



    @staticmethod
    def normalise_franchise_title(title: str) -> str:
        title = title.lower()

        # remove subtitles after colon
        title = title.split(":")[0]

        # remove brackets
        title = re.sub(r"\(.*?\)", "", title)

        # remove common noise
        title = re.sub(r"\b(movie|season|part|arc|chapter|the movie)\b", "", title)

        # collapse whitespace
        title = re.sub(r"\s+", " ", title).strip()

        return title



    def collapse_franchises2(
        self,
        reranked_df: pd.DataFrame,
        top_k: int = 20,
        threshold: int = 90
    ):
        df = reranked_df.copy()

        # 2. Pick display title
        df["canonical_title"] = df.apply(self.pick_title, axis=1)

        # 3. Build franchise comparison key
        df["franchise_key"] = df["canonical_title"].apply(self.normalise_franchise_title)

        kept_rows = []
        kept_keys = []

        for _, row in df.iterrows():
            key = row["franchise_key"]

            duplicate = False
            for kept_key in kept_keys:
                if fuzz.token_set_ratio(key, kept_key) >= threshold:
                    duplicate = True
                    break

            if not duplicate:
                kept_rows.append(row)
                kept_keys.append(key)

            if len(kept_rows) == top_k:
                break

        return pd.DataFrame(kept_rows).reset_index(drop=True)





    

# DEPRECATED METHODS FOR FRANCHISE COLLAPSING
"""
    @staticmethod
    def normalise_franchise(title: str) -> str:
        t = title.lower()

        # common sequel patterns
        t = re.sub(r"\bseason\s*\d+\b", "", t)
        t = re.sub(r"\bpart\s*\d+\b", "", t)
        t = re.sub(r"\bmovie\s*\d+\b", "", t)
        t = re.sub(r"\b\d+(st|nd|rd|th)\b", "", t)

        # anime-specific patterns
        t = t.replace("shippuden", "")
        t = t.replace("final season", "")
        t = t.replace("the movie", "")
        t = t.replace("arc", "")

        # remove punctuation and extra whitespace
        t = re.sub(r"[^\w\s]", "", t)
        t = re.sub(r"\s+", " ", t)

        return t.strip()
    
    def _attach_franchise_key(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df["canonical_title"] = df.apply(self.pick_title, axis=1)
        df["franchise_key"] = df["canonical_title"].apply(self.normalise_franchise)

        return df



    

    def _collapse_franchises(self, ranked_df: pd.DataFrame, top_k: int = None) -> pd.DataFrame:
        idx = (
            ranked_df
            .groupby("franchise_key")["cross_encoder_score"]
            .idxmax()
        )

        collapsed = ranked_df.loc[idx]

        if not top_k:
            reordered = collapsed.sort_values("cross_encoder_score", ascending=False)
        else:
            reordered = collapsed.sort_values("cross_encoder_score", ascending=False).head(top_k)

        return reordered
    
    def final_cleaning(self, df: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
        result = self._attach_franchise_key(df)
        return self._collapse_franchises(result, top_k)
"""
    







