import json
import sys
import argparse
import pandas as pd
from backend.rag_pipeline.helper.service_embedding import Embedder
from backend.rag_pipeline.helper.retrieval import DatabaseManager
from backend.rag_pipeline.helper.ranking import Ranker
from backend.rag_pipeline.config import config

def run_evaluation(data_path):
    print(f"Loading models and connecting to database from config...")
    PARAMS = config()
    embedding = Embedder()
    retriever = DatabaseManager(PARAMS=PARAMS)
    ranker = Ranker()
    
    total = 0
    hit_in_first_stage = 0
    
    print("Evaluating first stage (MiniLM + FastText) hit rate...")
    
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                data = json.loads(line)
                if "api_response" not in data or "results" not in data["api_response"]: continue
                if data.get("status_code") != 200: continue
                
                query = data["api_response"]["query"]
                ground_truth = str(data.get("ground_truth", "")).lower().strip()
                
                # 1. Embed query
                embeds = embedding.execute(query=query)
                
                # 2. Retrieve candidates (First Stage - 50 from each)
                sbert_res, fasttext_res = retriever.execute(embedding=embeds, top_k=50, allow_adult=False)
                
                # Merge and deduplicate
                merged_df = ranker.merge_deduplicate(sbert_res, fasttext_res)
                
                found = False
                for _, row in merged_df.iterrows():
                    titles = [
                        row.get("title_english"),
                        row.get("title_romaji"),
                        row.get("title_userPreferred")
                    ]
                    # Also check synonyms if available
                    synonyms = ranker.parse_json(row.get("synonyms"))
                    if isinstance(synonyms, list):
                        titles.extend(synonyms)
                        
                    titles = [str(t).lower().strip() for t in titles if t and str(t).lower() != 'nan']
                    
                    if any(ground_truth == t or ground_truth in t or t in ground_truth for t in titles):
                        found = True
                        break
                
                total += 1
                if found:
                    hit_in_first_stage += 1
                
                if total % 10 == 0:
                    print(f"Processed {total} queries... Hit Rate so far: {hit_in_first_stage/total*100:.2f}%")
                    
    finally:
        retriever.close()
        
    hit_rate_pct = hit_in_first_stage / total * 100 if total > 0 else 0
    print("\n--- FIRST STAGE (RETRIEVAL) EVALUATION ---")
    print(f"Total queries: {total}")
    print(f"Hit Rate @ 100: {hit_rate_pct:.2f}% ({hit_in_first_stage}/{total})")
    
    # Store the evaluation result
    import datetime
    import os
    result_record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "iteration_name": args.iteration,
        "data_path": data_path,
        "total_queries": total,
        "hit_in_first_stage": hit_in_first_stage,
        "hit_rate_pct": hit_rate_pct
    }
    history_file = "evaluation_history.jsonl"
    with open(history_file, "a", encoding="utf-8") as hf:
        hf.write(json.dumps(result_record) + "\n")
    print(f"\nSaved evaluation result to {history_file}")
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate first-stage retrieval")
    parser.add_argument("--data", type=str, default="anime_results.jsonl", help="Path to anime_results.jsonl")
    parser.add_argument("--iteration", type=str, default="baseline", help="Name of the iteration for tracking")
    args = parser.parse_args()
    
    run_evaluation(args.data)
