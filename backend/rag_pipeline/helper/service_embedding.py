import os
from pathlib import Path
from sentence_transformers import SentenceTransformer
import numpy as np
import fasttext
import torch
import logging
from typing import Tuple, List

logger = logging.getLogger(__name__)

"""
paraphrase-multilingual-MiniLM-L12-v2 is faster than all-mpnet-base-v2.
Both gives a not so good results on anime data.
fastText will be used to complement SBERT embeddings.
"""

class Embedder:

    DIR = Path(__file__).parents[2].resolve()

    MODEL_PATH = DIR / "models"

    #MODEL_PATH = Path("models").resolve()
    

    SBERT_DIR = "paraphrase-multilingual-MiniLM-L12-v2"

    FASTTEXT_MODEL = "anime_fasttext.bin"

    # Ensuring SBERT uses GPU
    DEVICE = os.getenv('TORCH_DEVICE') or ('cuda' if torch.cuda.is_available() else 'cpu')
    

    def __init__(self, model_path: Path = MODEL_PATH):
        
        # Loading model path
        self.model_path = model_path
        
        self.fasttext_path = model_path / self.FASTTEXT_MODEL
        self.sbert_path = model_path / self.SBERT_DIR

        self.sbert = self.load_sbert()
        self.fasttext = self.load_fasttext()


    # ----------------------
    # MODEL LOADING
    # ----------------------
    
    def load_sbert(self) -> SentenceTransformer:
        # Check if model exists
        if not self.sbert_path.exists():
            raise FileNotFoundError(
                f"SBERT model not found at {self.sbert_path}. "
                f"Run the data pipeline first to download models."
            )
        
        try:
            device_name = (
                torch.cuda.get_device_name(0)
                if "cuda" in self.DEVICE and torch.cuda.is_available()
                else "CPU"
            )
            logger.info(f"[Embedder] SBERT Bi-encoder loaded on device: {self.DEVICE} ({device_name})")
            model = SentenceTransformer(
                str(self.sbert_path),
                model_kwargs={"dtype": torch.float16} if "cuda" in self.DEVICE else {}, 
                tokenizer_kwargs={"fix_mistral_regex": True}, 
                device=self.DEVICE,
            )
            return model
        except Exception:
            logger.exception("SBERT Bi-encoder initialisation failed")
            raise
    
    def load_fasttext(self):
        # Check if model exists
        if not self.fasttext_path.exists():
            raise FileNotFoundError(
                f"FastText model not found at {self.fasttext_path}. "
                f"Run the data pipeline first to train the FastText model."
            )
        
        try:
            model =  fasttext.load_model(str(self.fasttext_path))
            return model
        except Exception:
            logger.exception("fastText initialisation failed")
            raise


    # ----------------------
    # EMBEDDING METHODS
    # ----------------------
    
    def embed_text(self, text: str, model: str) -> np.ndarray:
        if model == 'sbert':
            embedding = self.sbert.encode([text], 
                                          convert_to_numpy=True, 
                                          normalize_embeddings=True)[0]

        elif model == 'fasttext':
            text = text.replace('\n', ' ').replace('\r', ' ')
            embedding = self.fasttext.get_sentence_vector(text)
            embedding = self._normalize(embedding)

        return embedding.tolist()
    

    def _normalize(self, vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        return vec if norm == 0 else vec / norm
    

    # ----------------------
    # PUTTING THEM TOGETHER
    # ----------------------

    def execute(self, queries: List[str]) -> List[Tuple[List, List]]:
        """
        Embeds a list of query strings with both SBERT and FastText.
        Uses batched GPU inference for SBERT to maximize throughput.
        """
        if not queries:
            return []

        sbert_embeddings = self.sbert.encode(
            queries,
            batch_size=len(queries),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
            device=self.DEVICE,
        )

        results = []
        for i, query in enumerate(queries):
            cleaned_text = query.replace('\n', ' ').replace('\r', ' ')
            ft_vec = self.fasttext.get_sentence_vector(cleaned_text)
            ft_emb = self._normalize(ft_vec).tolist()
            results.append((sbert_embeddings[i].tolist(), ft_emb))

        return results


