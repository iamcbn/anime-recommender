import sys
import os
import json
import numpy as np
import pandas as pd
from tqdm import tqdm

# Add repo root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from backend.rag_pipeline.rag_pipeline import embedding, retriever, reranker as ranker, query_generator

def compute_rrf_hit_rates(data_path: str, k_values: list):
    print("Loading pipeline singletons (LLM Cache will be used)...")
    
    # 1. Load dataset
    queries_data = []
    with open(data_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            data = json.loads(line)
            if 'api_response' not in data or 'results' not in data['api_response']: continue
            if data.get('status_code') != 200: continue
            queries_data.append({
                'query': data['api_response']['query'],
                'ground_truth': str(data.get('ground_truth', '')).lower().strip()
            })

    print(f"Loaded {len(queries_data)} queries.")
    print("Phase 1: Running retrieval & cross-encoder (This will take a few minutes...)")
    
    # Store the raw outputs so we don't have to re-run the heavy models for every k!
    raw_eval_data = []
    
    for item in tqdm(queries_data, desc="Processing Queries"):
        query = item['query']
        
        # --- Run LLMs (Instant via cache) ---
        # No metadata filters (self-query was removed from the pipeline).
        extra_clauses, extra_params = [], []
        
        llm_queries = query_generator.generate(user_query=query)
        
        # --- Run Embeddings ---
        embeddings = embedding.execute(queries=llm_queries)
        
        # --- Run Initial Retrieval ---
        all_results = retriever.execute(
            queries=llm_queries, 
            embeddings=embeddings, 
            top_k=50,
            allow_adult=False,
            extra_clauses=extra_clauses, 
            extra_params=extra_params
        )
        
        col = ['id', 'title_romaji', 'title_english', 'coverImage_large', 'isAdult',
               'embedding_text', 'title_userPreferred', 'synonyms', 'description', 'popularity', 'cosine_similarity']
        
        has_results = any(len(lst) > 0 for lst in all_results)
        if not has_results:
            # We still need to record this query as having 0 results so hit rate calculation is accurate
            raw_eval_data.append({
                'ground_truth': item['ground_truth'],
                'all_results': all_results,
                'df_unique': pd.DataFrame(columns=col),
                'ce_scores': []
            })
            continue
        
        # --- Compute Cross-Encoder Scores ONCE ---
        # We temporarily deduplicate just to get the unique items to pass to the cross-encoder
        unique_items = {row[0]: dict(zip(col, row)) for ranked_list in all_results for row in ranked_list}
        df_unique = pd.DataFrame(list(unique_items.values()), columns=col)
        
        pairs = list(zip([query]*len(df_unique), df_unique["description"].fillna("").tolist()))
        ce_scores = ranker.cross_encoder.predict(pairs, batch_size=32, show_progress_bar=False)
        
        raw_eval_data.append({
            'ground_truth': item['ground_truth'],
            'all_results': all_results,
            'df_unique': df_unique,
            'ce_scores': ce_scores
        })

    # --- Compute First Stage Hit Rate ---
    first_stage_hits = 0
    for data in raw_eval_data:
        gt = data['ground_truth']
        hit = False
        for _, row in data['df_unique'].iterrows():
            titles = [row.get("title_english"), row.get("title_romaji"), row.get("title_userPreferred")]
            syns = row.get("synonyms")
            if isinstance(syns, str): syns = ranker.parse_json(syns)
            if isinstance(syns, list): titles.extend(syns)
            titles = [str(t).lower().strip() for t in titles if t and str(t).lower() != "nan"]
            if any(gt == t or gt in t or t in gt for t in titles):
                hit = True
                break
        if hit:
            first_stage_hits += 1
            
    first_stage_hr = (first_stage_hits / len(queries_data)) * 100
    print(f"\n---> FIRST STAGE HIT RATE (No Self-Query): {first_stage_hr:.2f}% ({first_stage_hits}/{len(queries_data)}) <---")

    print("\nPhase 2: Rapidly simulating different k values...")
    best_k = None
    best_hit_rate = 0.0

    for k in k_values:
        hits = 0
        
        for data in raw_eval_data:
            # 1. Compute Retrieval RRF with current k
            rrf_scores = {}
            for ranked_list in data['all_results']:
                for rank, row in enumerate(ranked_list, start=1):
                    anime_id = row[0]
                    if anime_id not in rrf_scores:
                        rrf_scores[anime_id] = 0.0
                    rrf_scores[anime_id] += 1.0 / (k + rank)
            
            # Update dataframe
            df = data['df_unique'].copy()
            if df.empty:
                continue
                
            df['retrieval_rrf_score'] = df['id'].map(rrf_scores)
            df = df.sort_values(by='retrieval_rrf_score', ascending=False).reset_index(drop=True)
            
            # The cross-encoder scores need to be mapped to the new sorted order
            ce_score_map = dict(zip(data['df_unique']['id'], data['ce_scores']))
            aligned_ce_scores = np.array([ce_score_map[aid] for aid in df['id']])
            
            # 2. Compute Final RRF with current k
            retrieval_ranks = np.arange(1, len(df) + 1)
            ce_ranks = len(aligned_ce_scores) - np.argsort(np.argsort(aligned_ce_scores))
            
            final_rrf = (1.0 / (k + retrieval_ranks)) + (1.0 / (k + ce_ranks))
            pop_boost = np.log1p(df['popularity'].fillna(0)) / 100.0
            
            df['final_rrf_score'] = final_rrf + pop_boost
            final_df = df.sort_values(by='final_rrf_score', ascending=False)
            
            # 3. Collapse franchises (Top 20)
            collapsed_df = ranker.collapse_franchises2(final_df, top_k=20)
            
            # Check Hit
            hit = False
            gt = data['ground_truth']
            for _, row in collapsed_df.iterrows():
                titles = [
                    row.get("title_english"),
                    row.get("title_romaji"),
                    row.get("title_userPreferred"),
                ]
                syns = row.get("synonyms")
                if isinstance(syns, str):
                    syns = ranker.parse_json(syns)
                if isinstance(syns, list):
                    titles.extend(syns)

                titles = [str(t).lower().strip() for t in titles if t and str(t).lower() != "nan"]

                if any(gt == t or gt in t or t in gt for t in titles):
                    hit = True
                    break
            
            if hit:
                hits += 1
                
        hit_rate = (hits / len(queries_data)) * 100
        print(f"k = {k:3d} | Final Hit Rate: {hit_rate:.2f}% ({hits}/{len(queries_data)})")
        
        if hit_rate > best_hit_rate:
            best_hit_rate = hit_rate
            best_k = k

    print(f"\n🏆 Best k value: {best_k} (Hit Rate: {best_hit_rate:.2f}%)")

if __name__ == "__main__":
    test_k_values = [1, 5, 10, 20, 40, 60, 80, 100, 150]
    data_file = os.path.join(os.path.dirname(__file__), "..", "data", "anime_results.jsonl")
    if not os.path.exists(data_file):
        data_file = "anime_results.jsonl"
    compute_rrf_hit_rates(data_file, test_k_values)
