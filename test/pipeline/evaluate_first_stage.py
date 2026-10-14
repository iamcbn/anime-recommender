import json
import sys
import os
import argparse
import datetime

# Add the project root to the python path so it can find the backend module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from backend.rag_pipeline.rag_pipeline import embedding, retriever, reranker as ranker, query_generator as query_gen

def run_evaluation(data_path, use_full_pipeline=True):
    """
    Evaluates first-stage (retrieval) hit rate against the ground-truth dataset.

    Args:
        data_path:          Path to anime_results.jsonl.
        use_full_pipeline:  If True (default), mirrors production exactly by running
                            QueryGenerator (HyDE) before retrieval. Set False for a
                            fast, embedding-only baseline.
    """
    print("Models and DB connection are loaded via rag_pipeline singletons.")
    
    if use_full_pipeline:
        _query_gen = query_gen
        print("Full pipeline mode: QueryGenerator (HyDE) enabled.")
    else:
        _query_gen = None
        print("Baseline mode: embedding-only retrieval (no HyDE).")

    total = 0
    hit_in_first_stage = 0
    hit_in_final_stage = 0

    print("Evaluating first stage (MiniLM + FastText + BM25) hit rate...\n")

    try:
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                if "api_response" not in data or "results" not in data["api_response"]:
                    continue
                if data.get("status_code") != 200:
                    continue

                query = data["api_response"]["query"]
                ground_truth = str(data.get("ground_truth", "")).lower().strip()

                # --- Step 1: Metadata filters ---
                # None applied (self-query was removed from the pipeline)
                extra_clauses, extra_params = [], []

                # --- Step 2: Query generation (HyDE) ---
                if _query_gen is not None:
                    queries = _query_gen.generate(user_query=query)
                else:
                    queries = [query]

                # --- Step 3: Embed all queries ---
                embeds = embedding.execute(queries=queries)

                # --- Step 4: Retrieve candidates (all searches, top_k per search) ---
                all_results = retriever.execute(
                    queries=queries,
                    embeddings=embeds,
                    top_k=50,
                    allow_adult=False,
                    extra_clauses=extra_clauses,
                    extra_params=extra_params,
                )

                # --- Step 5: Merge and deduplicate ---
                merged_df = ranker.merge_deduplicate(all_results)

                # --- Step 6: Check First Stage hit ---
                def check_hit(df):
                    for _, row in df.iterrows():
                        titles = [
                            row.get("title_english"),
                            row.get("title_romaji"),
                            row.get("title_userPreferred"),
                        ]
                        # Account for list vs string in synonyms depending on where in the pipeline we are
                        syns = row.get("synonyms")
                        if isinstance(syns, str):
                            syns = ranker.parse_json(syns)
                        if isinstance(syns, list):
                            titles.extend(syns)

                        titles = [str(t).lower().strip() for t in titles if t and str(t).lower() != "nan"]

                        if any(ground_truth == t or ground_truth in t or t in ground_truth for t in titles):
                            return True
                    return False

                first_stage_hit = check_hit(merged_df)
                
                # --- Step 7: Rerank and Reorder (Final Stage) ---
                scores = ranker.rerank(query=query, retrieved_results=merged_df)
                reranked_df = ranker.reorder(retrieved_results=merged_df, rerank=scores)
                
                # Final pipeline cuts down to top 20 AFTER collapsing franchises!
                collapsed_df = ranker.collapse_franchises2(reranked_df, top_k=20)
                final_stage_hit = check_hit(collapsed_df)

                total += 1
                if first_stage_hit:
                    hit_in_first_stage += 1
                if final_stage_hit:
                    hit_in_final_stage += 1

                if total % 10 == 0:
                    print(f"Processed {total} queries... First Stage Hit: {hit_in_first_stage/total*100:.1f}% | Final Reranked Hit: {hit_in_final_stage/total*100:.1f}%")

    finally:
        retriever.close()

    first_rate = hit_in_first_stage / total * 100 if total > 0 else 0
    final_rate = hit_in_final_stage / total * 100 if total > 0 else 0

    print("\n--- EVALUATION RESULTS ---")
    print(f"Mode:          {'Full pipeline (HyDE + Self-Query)' if use_full_pipeline else 'Baseline (embedding only)'}")
    print(f"Total queries: {total}")
    print(f"First Stage Hit Rate (Top ~100): {first_rate:.2f}% ({hit_in_first_stage}/{total})")
    print(f"Final Stage Hit Rate (Top 20):   {final_rate:.2f}% ({hit_in_final_stage}/{total})")

    result_record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "iteration_name": args.iteration,
        "mode": "full_pipeline" if use_full_pipeline else "baseline",
        "data_path": data_path,
        "total_queries": total,
        "hit_in_first_stage": hit_in_first_stage,
        "hit_rate_pct": first_rate,
        "final_hit_rate_pct": final_rate
    }
    history_file = getattr(args, "history", None) or os.path.join(os.path.dirname(__file__), "..", "data", "evaluation_history.jsonl")
    os.makedirs(os.path.dirname(os.path.abspath(history_file)), exist_ok=True)
    with open(history_file, "a", encoding="utf-8") as hf:
        hf.write(json.dumps(result_record) + "\n")
    print(f"\nSaved evaluation result to {history_file}")


if __name__ == "__main__":
    default_data = os.path.join(os.path.dirname(__file__), "..", "data", "anime_results.jsonl")
    if not os.path.exists(default_data):
        root_data = os.path.join(os.path.dirname(__file__), "..", "..", "anime_results.jsonl")
        if os.path.exists(root_data):
            default_data = root_data
        elif os.path.exists("anime_results.jsonl"):
            default_data = "anime_results.jsonl"
    default_history = os.path.join(os.path.dirname(__file__), "..", "data", "evaluation_history.jsonl")

    parser = argparse.ArgumentParser(description="Evaluate first-stage retrieval")
    parser.add_argument("--data", type=str, default=default_data, help="Path to anime_results.jsonl")
    parser.add_argument("--history", type=str, default=default_history, help="Path to evaluation_history.jsonl")
    parser.add_argument("--iteration", type=str, default="baseline", help="Name of the iteration for tracking")
    parser.add_argument("--no-pipeline", action="store_true", help="Skip HyDE and self-query; run embedding-only baseline")
    args = parser.parse_args()

    run_evaluation(args.data, use_full_pipeline=not args.no_pipeline)
