from pathlib import Path
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
import pandas as pd, numpy as np
from typing import List, Tuple
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

    def merge_deduplicate(self, sbert_result, fasttext_result) -> pd.DataFrame :
        result = sbert_result + fasttext_result
        col = ['id', 'title_romaji', 'title_english', 'coverImage_large', 'isAdult',
               'embedding_text', 'title_userPreferred', 'synonyms', 'cosine_similarity']
        df = pd.DataFrame(result, columns=col)

        return df.drop_duplicates('id')


    # ----------------------
    # RE-RANKING
    # ----------------------

    @staticmethod
    def _creating_pairs(query : str, retrieved_results: pd.DataFrame) -> List[Tuple]:
        pairs = list(zip(
            itertools.repeat(query),
            retrieved_results["embedding_text"].tolist()
            ))
       
        return pairs
    
    def rerank(self, query: str, retrieved_results: pd.DataFrame) -> np.ndarray:
        pairs = self._creating_pairs(query, retrieved_results)

        results = self.cross_encoder.predict(pairs)

        return results
    

    # ----------------------
    # REORDERING
    # ----------------------

    def reorder(self, retrieved_results: pd.DataFrame, rerank: np.ndarray) -> pd.DataFrame:
        
        reranked_results = retrieved_results.copy()
        reranked_results['cross_encoder_score'] = rerank

        return reranked_results.sort_values(by='cross_encoder_score', ascending=False)
    

    # ----------------------
    # FINAL CLEANING
    # ----------------------

    @staticmethod
    def parse_json(x):
        """
        Parse stringified JSON into Python objects.
        Always returns a list (empty if missing or invalid).
        """
        if pd.isna(x):
            return []
        if isinstance(x, list):
            return x
        if isinstance(x, dict):
            return [x]
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
    

    def collapse_franchises_old(
        self,
        reranked_df,
        top_k: int = 20,
        threshold=85
    ):

        reranked_df["canonical_title"] = reranked_df.apply(self.pick_title, axis=1)

        kept_rows = []

        for _, row in reranked_df.iterrows():
            current_title = row["canonical_title"]

            is_duplicate = False
            for kept in kept_rows:
                kept_title = kept['canonical_title']

                similarity = fuzz.token_set_ratio(
                    current_title.lower(),
                    kept_title.lower()
                )

                if similarity <= threshold:
                    is_duplicate = True
                    break

            if not is_duplicate:
                kept_rows.append(row)

        return pd.DataFrame(kept_rows).head(top_k).reset_index(drop=True)

    
    def json_conversion(self, df: pd.DataFrame) -> json:
        df = df.copy()
        df = df[['id', 'title_romaji','title_userPreferred','title_english', 'coverImage_large', 'cross_encoder_score',
                  'cosine_similarity']]
        return df.to_dict(orient="records")
    
    # ----------------------
    # PUTTING THEM TOGETHER
    # ----------------------

    def execute(self, user_query, sbert_result, fasttext_result, top_k) -> pd.DataFrame:
        df = self.merge_deduplicate(sbert_result, fasttext_result)
        scores = self.rerank(query=user_query, retrieved_results=df)
        df = self.reorder(retrieved_results=df, rerank=scores)
        output = self.collapse_franchises2(reranked_df=df, top_k=top_k)
        final_output = self.json_conversion(output)

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
    







