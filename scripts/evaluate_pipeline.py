import json
import sys

def evaluate(sort_key, desc):
    hit_rates = {1: 0, 5: 0, 10: 0, 20: 0}
    mrr = 0.0
    total = 0

    with open("anime_results.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            data = json.loads(line)
            if "api_response" not in data or "results" not in data["api_response"]: continue
            if data.get("status_code") != 200: continue
            
            ground_truth = str(data.get("ground_truth", "")).lower().strip()
            
            # Sort results based on the specified key
            results = data["api_response"]["results"]
            results = sorted(results, key=lambda x: x.get(sort_key, 0), reverse=True)
            
            found_rank = -1
            for i, res in enumerate(results):
                titles = [
                    res.get("title_english"),
                    res.get("title_romaji"),
                    res.get("title_userPreferred")
                ]
                titles = [str(t).lower().strip() for t in titles if t and str(t).lower() != 'nan']
                
                # Check for exact match or substring match in titles
                if any(ground_truth == t or ground_truth in t or t in ground_truth for t in titles):
                    found_rank = i + 1
                    break
            
            total += 1
            if found_rank != -1:
                mrr += 1.0 / found_rank
                if found_rank <= 1: hit_rates[1] += 1
                if found_rank <= 5: hit_rates[5] += 1
                if found_rank <= 10: hit_rates[10] += 1
                if found_rank <= 20: hit_rates[20] += 1

    print(f"--- {desc} ---")
    print(f"Total queries: {total}")
    for k, v in hit_rates.items():
        print(f"Hit Rate @ {k}: {v/total*100:.2f}% ({v}/{total})")
    print(f"MRR: {mrr/total:.4f}\n")

evaluate("cross_encoder_score", "RERANKER (SECOND STAGE) EVALUATION")
evaluate("cosine_similarity", "RETRIEVAL (FIRST STAGE) EVALUATION (based on Cosine Similarity)")
