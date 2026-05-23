from pathlib import Path
from sentence_transformers import SentenceTransformer
import numpy as np, pandas as pd
import fasttext
import torch
import logging
from typing import Tuple

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
    

    SBERT_NAME = "paraphrase/multilingual-MiniLM-L12-v2"
    SBERT_DIR = "paraphrase-multilingual-MiniLM-L12-v2"

    FASTTEXT_MODEL = "anime_fasttext.bin"
    FASTTEXT_FILE = "anime_fasttext.txt"

    # Ensuring SBERT uses GPU
    DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
    

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
            model = SentenceTransformer(str(self.sbert_path),
                                        model_kwargs={"dtype":torch.float16}, 
                                        tokenizer_kwargs={"fix_mistral_regex": True}, 
                                        device=self.DEVICE)
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
                embedding = self.fasttext.get_sentence_vector(text)
                embedding = self._normalize(embedding)

            return embedding.tolist()
    

    def _normalize(self, vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        return vec if norm == 0 else vec / norm
    

    # ----------------------
    # PUTTING THEM TOGETHER
    # ----------------------

    def execute(self, query) -> Tuple[np.ndarray, np.ndarray]:
        sbert_embedding = self.embed_text(query, 'sbert')
        fasttext_embedding = self.embed_text(query, 'fasttext')

        return sbert_embedding, fasttext_embedding

    
    


