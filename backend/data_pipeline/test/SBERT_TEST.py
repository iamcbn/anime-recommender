# eval_embeddings.py
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Set
from sklearn.preprocessing import normalize
import math
import time
import torch



DATA_XLSX = "pipeline/artifacts/v1/raw_data/anilist_anime_data_complete.xlsx"  # adjust path

def parse_json_field(x):
    if isinstance(x, (list, dict)):
        return x
    try:
        return json.loads(x)
    except Exception:
        return []

def build_embed_text(row):
    parts = []
    for col in ["title_userPreferred", "title_english", "title_romaji", "synonyms"]:
        v = row.get(col)
        if not v:
            continue
        # synonyms might be list
        if isinstance(v, list):
            parts.append(" ".join(v))
        else:
            parts.append(str(v))
    # Put tags and genres and a short description
    genres = row.get("genres") or []
    if isinstance(genres, list):
        parts.append("Genres: " + ", ".join(genres))
    tags = row.get("tags") or []
    if isinstance(tags, list):
        # tags may be list of dicts; use names if dicts
        tag_names = []
        for t in tags:
            if isinstance(t, dict):
                tag_names.append(t.get("name"))
            else:
                tag_names.append(str(t))
        parts.append("Tags: " + ", ".join([x for x in tag_names if x]))
    desc = row.get("description")
    if pd.notna(desc) and desc:
        parts.append("Summary: " + (desc if len(desc) < 1000 else desc[:1000]))  # truncate long ones
    return " \n ".join(parts)

def build_ground_truth(df: pd.DataFrame) -> Dict[int, Set[int]]:
    """
    Build a mapping query_id -> set(positive_ids).
    Strategy:
      - use 'recommendations' if present (recommendations is usually a list of {id: ...})
      - fallback: use relations that are SEQUEL/PREQUEL/SPIN_OFF/SIDE_STORY
    """
    gt = {}
    for _, r in df.iterrows():
        qid = int(r["id"])
        positives = set()

        # recommendations
        recs = parse_json_field(r.get("recommendations"))
        for item in recs:
            if isinstance(item, dict):
                # try common keys
                candidate_id = item.get("id") or item.get("animeId") or item.get("node", {}).get("id")
                if candidate_id:
                    positives.add(int(candidate_id))

        # relations (use meaningful ones)
        rels = parse_json_field(r.get("relations"))
        for item in rels:
            if not isinstance(item, dict):
                continue
            relt = item.get("relationType", "").upper()
            if relt in {"SEQUEL", "PREQUEL", "SPIN_OFF", "SIDE_STORY"}:
                node = item.get("node") or item
                cid = node.get("id") if isinstance(node, dict) else None
                if cid:
                    positives.add(int(cid))

        # Only keep queries with at least one positive for evaluation
        if positives:
            gt[qid] = positives

    return gt

def embed_texts(model_name: str, texts: List[str], batch_size=64, normalize_emb=True):
    print(f"Loading model {model_name} ...")
    model = SentenceTransformer(model_name, model_kwargs={"dtype":torch.float16}, device='cuda')
    t0 = time.time()
    embs = model.encode(texts, batch_size=batch_size, show_progress_bar=True, convert_to_numpy=True)
    t1 = time.time()
    print(f"Encoded {len(texts)} texts into shape {embs.shape} in {t1-t0:.1f}s")
    if normalize_emb:
        embs = normalize(embs, axis=1)
    return embs

def retrieval_scores(emb_matrix: np.ndarray, query_vecs: np.ndarray, top_k=10):
    # emb_matrix: N x D (catalogue)
    # query_vecs: Q x D
    # we assume vectors are normalized; cosine similarity = dot product
    sims = np.dot(query_vecs, emb_matrix.T)  # Q x N
    top_idx = np.argpartition(-sims, range(top_k), axis=1)[:, :top_k]
    # sort those top_k rows
    top_sorted = np.zeros_like(top_idx)
    for i in range(top_idx.shape[0]):
        idxs = top_idx[i]
        top_sorted[i] = idxs[np.argsort(-sims[i, idxs])]
    top_scores = np.take_along_axis(sims, top_sorted, axis=1)
    return top_sorted, top_scores

def compute_metrics(top_idxs: np.ndarray, id_list: List[int], gt_map: Dict[int, Set[int]], k_list=[1,5,10]):
    """
    top_idxs: Q x K with indices into id_list
    id_list: list of catalog ids aligned with embedding matrix
    gt_map: query_id -> set of positive ids
    """
    id_by_pos = {i: int(id_list[i]) for i in range(len(id_list))}
    recalls = {k: 0 for k in k_list}
    rr_total = 0.0
    ndcg = {k: 0.0 for k in k_list}
    valid_q = 0
    Q = top_idxs.shape[0]

    for qpos in range(Q):
        query_id = query_ids[qpos]
        if query_id not in gt_map:
            continue
        valid_q += 1
        positives = gt_map[query_id]

        ranks = []
        hits = []
        for rank_pos, idx in enumerate(top_idxs[qpos]):
            cand_id = id_by_pos[int(idx)]
            if cand_id in positives:
                ranks.append(rank_pos + 1)
                hits.append(1)
            else:
                hits.append(0)

        # MRR
        if ranks:
            rr_total += 1.0 / (min(ranks))
        else:
            rr_total += 0.0

        # Recall@k and nDCG@k
        for k in k_list:
            topk = top_idxs[qpos, :k]
            found = any(int(id_by_pos[int(i)]) in positives for i in topk)
            if found:
                recalls[k] += 1

            # nDCG: DCG = sum((2^rel -1)/log2(pos+1)); rel = 1 if in positives else 0
            dcg = 0.0
            for pos_i, idx in enumerate(topk):
                rel = 1 if int(id_by_pos[int(idx)]) in positives else 0
                if rel:
                    dcg += (2 ** rel - 1) / math.log2(pos_i + 2)
            # ideal DCG: min(len(positives), k) ones at top
            ideal = 0.0
            ideal_rel = min(len(positives), k)
            for i in range(ideal_rel):
                ideal += (2**1 - 1) / math.log2(i + 2)
            ndcg[k] += (dcg / ideal) if ideal > 0 else 0.0

    # finalise
    results = {}
    if valid_q == 0:
        raise RuntimeError("No queries with ground truth positives found. Check your GT construction.")
    for k in k_list:
        results[f"Recall@{k}"] = recalls[k] / valid_q
        results[f"nDCG@{k}"] = ndcg[k] / valid_q
    results["MRR"] = rr_total / valid_q
    results["EvaluatedQueries"] = valid_q
    return results

if __name__ == "__main__":
    # 1. Load data
    df = pd.read_excel(DATA_XLSX)
    # parse json fields into python objects
    for col in ["genres", "tags", "synonyms", "recommendations", "relations", "studios"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_json_field)

    # Build embed text and id list
    df["embed_text"] = df.apply(build_embed_text, axis=1)
    catalog_ids = df["id"].astype(int).tolist()
    catalog_texts = df["embed_text"].tolist()

    # Build ground-truth map
    gt_map = build_ground_truth(df)
    print(f"Number of queries with positives in GT: {len(gt_map)}")

    # Optionally limit evaluation to a subset to iterate quickly
    # choose up to 1000 queries randomly
    random_seed = 42
    query_ids_all = list(gt_map.keys())
    np.random.seed(random_seed)
    sample_queries = np.random.choice(query_ids_all, size=min(500, len(query_ids_all)), replace=False)
    query_ids = list(sample_queries)

    # Build query_texts (we use the embed_text of the query anime itself as proxy user query)
    query_texts = []
    for qid in query_ids:
        row = df[df["id"] == qid].iloc[0]
        query_texts.append(row["embed_text"])

    # Models to compare
    models = [
        "all-mpnet-base-v2",
        "paraphrase-multilingual-MiniLM-L12-v2",
        "Lorg0n/hikka-forge-paraphrase-multilingual-MiniLM-L12-v2"
    ]

    results_table = []
    for model_name in models:
        emb_catalog = embed_texts(model_name, catalog_texts, batch_size=64, normalize_emb=True)
        emb_queries = embed_texts(model_name, query_texts, batch_size=64, normalize_emb=True)

        # retrieval
        top_k = 50
        top_idxs, top_scores = retrieval_scores(emb_catalog, emb_queries, top_k=top_k)

        # compute metrics (we'll compute for top 1, 5, 10, 25, 50)
        metrics = compute_metrics(top_idxs[:, :50], catalog_ids, gt_map, k_list=[1, 5, 10, 25, 50])
        metrics["model"] = model_name
        results_table.append(metrics)

        # Qualitative sample for first 5 queries
        print("\nQUALITATIVE SAMPLE (model={}):".format(model_name))
        for i in range(min(5, len(query_ids))):
            qid = query_ids[i]
            print(f"\nQuery anime id={qid} Title={df[df['id']==qid]['title_userPreferred'].iloc[0]}")
            for rankpos, idx in enumerate(top_idxs[i, :10], start=1):
                cid = catalog_ids[int(idx)]
                title = df[df["id"]==cid]["title_userPreferred"].iloc[0]
                print(f"  {rankpos:02d}. {cid} - {title}")

    # Summarise
    print("\nSUMMARY")
    print(pd.DataFrame(results_table))
    df = pd.DataFrame(results_table)
    df.to_excel('pipeline/test/sberts_performance.xlsx')

