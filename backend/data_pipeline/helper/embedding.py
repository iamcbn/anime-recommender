from pathlib import Path
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
import pandas as pd, numpy as np
import fasttext
import torch
import os


"""
paraphrase-multilingual-MiniLM-L12-v2 is faster than all-mpnet-base-v2.
Both gives a not so good results on anime data.
"Lorg0n/hikka-forge-paraphrase-multilingual-MiniLM-L12-v2"
fastText will be used to complement SBERT embeddings.
"""

class Embedder:

    DIR = Path(__file__).parents[2].resolve()

    MODEL_PATH = DIR / "models"
    

    SBERT_NAME = "paraphrase/multilingual-MiniLM-L12-v2"
    SBERT_DIR = "paraphrase-multilingual-MiniLM-L12-v2"

    CROSS_ENCODER_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    CROSS_ENCODER_DIR = "cross-encoder-mmarco-mMiniLMv2-L12-H384-v1"

    FASTTEXT_MODEL = "anime_fasttext.bin"
    FASTTEXT_FILE = "anime_fasttext.txt"

    # Tell HuggingFace to cache downloads in our mounted volume -> For Docker
    os.environ['HF_HOME'] = str(MODEL_PATH)
    os.environ['TRANSFORMERS_CACHE'] = str(MODEL_PATH)
    os.environ['SENTENCE_TRANSFORMERS_HOME'] = str(MODEL_PATH)

    # Ensuring SBERT uses GPU
    DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
    

    def __init__(self, data: pd.DataFrame, model_path: Path = MODEL_PATH, retrain_fasttext: bool = False):
        self.data = data
        
        # Making model path
        self.model_path = model_path
        self.model_path.mkdir(exist_ok=True, parents=True)
        

        self.fasttext_path = model_path / self.FASTTEXT_MODEL
        self.sbert_path = model_path / self.SBERT_DIR
        self.cross_encoder_path = model_path / self.CROSS_ENCODER_DIR

        self.sbert = self.load_sbert()
        self.cross_encoder = self.load_cross_encoder()
        

        self.fasttext_file = model_path / self.FASTTEXT_FILE


        # Load or retrain fastText
        if retrain_fasttext or not self.fasttext_path.exists():
            self.fasttext = self.create_fasttext_model()
        else:
            self.fasttext = self.load_fasttext()

    # ----------------------
    # MODEL LOADING
    # ----------------------

    def load_cross_encoder(self) -> CrossEncoder:

        if not self.cross_encoder_path.exists():
            print('Downloading Cross Encoder from Hugging Face')

            reranker = CrossEncoder(self.CROSS_ENCODER_NAME, model_kwargs={"dtype": torch.float16}, tokenizer_kwargs={"fix_mistral_regex": True})
            reranker.save(str(self.cross_encoder_path))

        else:
            reranker = CrossEncoder(str(self.cross_encoder_path), tokenizer_kwargs={"fix_mistral_regex": True})

        return reranker
    
    def load_sbert(self) -> SentenceTransformer:

        if not self.sbert_path.exists():
            print('Downloading SBERT bi-encoder from Hugging Face')

            model = SentenceTransformer(self.SBERT_NAME,
                                        model_kwargs={"dtype":torch.float16}, 
                                        tokenizer_kwargs={"fix_mistral_regex": True}, 
                                        device=self.DEVICE)
            model.save(str(self.sbert_path))
        else:
            model = SentenceTransformer(str(self.sbert_path), 
                                        model_kwargs={"dtype":torch.float16}, 
                                        tokenizer_kwargs={"fix_mistral_regex": True}, 
                                        device=self.DEVICE)
  
        return model
    
    def load_fasttext(self):
        #if not self.fasttext_path.exists():
            #if not auto_train:
            #    raise FileNotFoundError("fastText model missing, train the model first")
            #return self.create_fasttext_model()
        return fasttext.load_model(str(self.fasttext_path))
    

    # ----------------------
    # CREATE FASTTEXT MODEL AND TRAINING FILE
    # ----------------------

    def create_fasttext_model(self, lr: float = 0.03, epoch: int = 25, thread: int = 16) -> fasttext.FastText:
        # Create training file
        self._create_fasttext_file()

        # Train fastText model
        ft_model = fasttext.train_unsupervised(
            input=str(self.fasttext_file),
            model='skipgram',
            dim=300,
            epoch=epoch,
            lr=lr,
            thread=thread,
            minCount= 2
        )
        ft_model.save_model(str(self.fasttext_path))
        return ft_model
    
    def _create_fasttext_file(self, text_column = 'embedding_text'):
        print(f"Creating fastText training corpus at {self.fasttext_file}")
        self.data[[text_column]].to_csv(self.fasttext_file, index=False, header=False, sep='\n')


    # ----------------------
    # EMBEDDING METHODS
    # ----------------------

    def embed_dataframe(self, text_column: str, batch_size: int = 64) -> pd.DataFrame:
        if text_column not in self.data.columns:
            raise ValueError(f"{text_column} not found in DataFrame")

        texts = self.data[text_column].tolist()
        
        sbert_embeddings = self.sbert.encode(
            texts, 
            batch_size=batch_size, 
            show_progress_bar=True, 
            normalize_embeddings=True,
            convert_to_numpy=True
            )      
        
        ft_embeddings = []
        for text in texts:
            emb = self.fasttext.get_sentence_vector(text.lower())
            emb = self._normalize(emb)
            ft_embeddings.append(emb)
        ft_embeddings = np.array(ft_embeddings)
        
        self.data['sbert_embedding'] = sbert_embeddings.tolist()
        self.data['fasttext_embedding'] = ft_embeddings.tolist()

        return self.data[['id', text_column, 'sbert_embedding', 'fasttext_embedding']]
    
    def embed_text(self, text: str, model: str) -> np.ndarray:
        if model == 'sbert':
            embedding = self.sbert.encode([text], 
                                          convert_to_numpy=True, 
                                          normalize_embeddings=True)[0]

        elif model == 'fasttext':
            embedding = self.fasttext.get_sentence_vector(text)
            embedding = self._normalize(embedding)

        return embedding
    

    def _normalize(self, vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        return vec if norm == 0 else vec / norm

    





