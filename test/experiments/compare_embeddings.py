import json
import sys
import os
import torch
import pandas as pd
from sentence_transformers import SentenceTransformer, util

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from backend.rag_pipeline.config import config
from psycopg2 import connect
from backend.rag_pipeline.helper.ranking import Ranker

def main():
    print("Connecting to database to fetch anime corpus...")
    PARAMS = config()
    conn = connect(**PARAMS)
    
    # Fetch anime texts and title metadata for ground truth matching
    query = """
        SELECT e.id, e.embedding_text, core.title_english, core.title_romaji, core.title_userPreferred, core.synonyms
        FROM anime_embedding e
        JOIN anime_core core ON e.id = core.id
    """
    df = pd.read_sql(query, conn)
    conn.close()
    
    print(f"Loaded {len(df)} anime records from database.")
    
    corpus_texts = df['embedding_text'].astype(str).tolist()
    ranker = Ranker()
    
    # Check if GPU is available in this local environment
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"Using computation device: {device.upper()}")
    
    # Load Models
    print("\nLoading MiniLM (Current Model)...")
    model_minilm = SentenceTransformer('all-MiniLM-L6-v2', device=device)
    
    print("Loading BGE-Small (Challenger Model)...")
    model_bge = SentenceTransformer('BAAI/bge-small-en-v1.5', device=device)
    
    # Embed Corpus
    print("\nEmbedding 20,000+ anime with MiniLM...")
    corpus_emb_minilm = model_minilm.encode(corpus_texts, convert_to_tensor=True, show_progress_bar=True)
    
    print("Embedding 20,000+ anime with BGE-Small...")
    corpus_emb_bge = model_bge.encode(corpus_texts, convert_to_tensor=True, show_progress_bar=True)
    
    # Load Queries
    queries_data = []
    data_file = os.path.join(os.path.dirname(__file__), "..", "data", "anime_results.jsonl")
    if not os.path.exists(data_file):
        data_file = "anime_results.jsonl"
    with open(data_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            d = json.loads(line)
            if "api_response" not in d or "results" not in d["api_response"]: continue
            if d.get("status_code") != 200: continue
            q = d["api_response"]["query"]
            gt = str(d.get("ground_truth", "")).lower().strip()
            queries_data.append({"query": q, "ground_truth": gt})
            
    print(f"\nLoaded {len(queries_data)} evaluation queries.")
    
    def evaluate(model, corpus_embeddings, queries, is_bge=False):
        hits = 0
        total = len(queries)
        
        # BGE-Small requires this exact prefix for short queries to activate its asymmetric retrieval training
        instruction = "Represent this sentence for searching relevant passages: "
        
        for qd in queries:
            q_text = qd["query"]
            if is_bge:
                q_text = instruction + q_text
                
            q_emb = model.encode(q_text, convert_to_tensor=True, show_progress_bar=False)
            
            # Compute cosine similarity between query and all documents
            cos_scores = util.cos_sim(q_emb, corpus_embeddings)[0]
            
            # Get top 100 highest scores
            top_results = torch.topk(cos_scores, k=100)
            
            found = False
            for idx in top_results[1]:
                row = df.iloc[idx.item()]
                titles = [
                    row.get("title_english"),
                    row.get("title_romaji"),
                    row.get("title_userPreferred")
                ]
                synonyms = ranker.parse_json(row.get("synonyms"))
                if isinstance(synonyms, list):
                    titles.extend(synonyms)
                    
                titles = [str(t).lower().strip() for t in titles if pd.notna(t) and str(t).lower() != 'nan']
                
                gt = qd["ground_truth"]
                if any(gt == t or gt in t or t in gt for t in titles):
                    found = True
                    break
            
            if found:
                hits += 1
                
        return hits, total

    print("\nRunning evaluation on MiniLM...")
    hits_minilm, total = evaluate(model_minilm, corpus_emb_minilm, queries_data, is_bge=False)
    
    print("Running evaluation on BGE-Small...")
    hits_bge, total = evaluate(model_bge, corpus_emb_bge, queries_data, is_bge=True)
    
    print("\n=========================================")
    print("       HEAD-TO-HEAD RESULTS (@100)       ")
    print("=========================================")
    print(f"MiniLM:    {hits_minilm/total*100:.2f}% ({hits_minilm}/{total})")
    print(f"BGE-Small: {hits_bge/total*100:.2f}% ({hits_bge}/{total})")
    print("=========================================")
    
    # Note: These scores are purely Dense Vector scores (no FastText hybrid).
    # This isolates the embedding models to see which one is foundationally stronger.

if __name__ == "__main__":
    main()
