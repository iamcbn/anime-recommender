# Test & Evaluation Subsystem

This directory contains the testing, offline evaluation pipelines, research experiments, and benchmarking assets for the `anime_recommender` project.

## Directory Segmentation

```text
test/
├── pipeline/                   # Core evaluation pipeline
│   ├── evaluate_first_stage.py # Evaluates 1st-stage retrieval hit rates & reranking against test dataset
│   ├── evaluate_pipeline.py    # Offline MRR & Hit Rate analysis on test dataset
│   └── generate_report.py      # Aggregates evaluation history into formatted Markdown reports
│
├── experiments/                # Standalone research & exploratory sweeps
│   ├── compare_embeddings.py   # Head-to-head comparison of SentenceTransformer embedding models
│   └── experiment_k.py         # Reciprocal Rank Fusion (RRF) k-parameter sensitivity sweep
│
├── benchmarks/                 # Model selection benchmarks (migrated from backend)
│   ├── SBERT_TEST.py           # Historical SBERT candidate evaluation script
│   └── sberts_performance.xlsx # Benchmark results spreadsheet comparing SBERT models
│
├── data/                       # Evaluation datasets, ledgers and generated reports
│   ├── anime_results.jsonl     # Synthetic test query dataset (appended by hourly_run.py)
│   ├── evaluation_history.jsonl # Historical iteration benchmark records
│   ├── evaluation_report_v2.md # Latest evaluation report
│   └── llm_cache.db            # SQLite cache of HyDE LLM responses (testing only; LLM_CACHE_PATH overrides)
├── hourly_run.py               # Generates test queries (Gemini) and calls the live API
├── run_eval.ps1                # Orchestrates end-to-end evaluation runs
└── README.md                   # This documentation
```

## Running the Evaluation Pipeline & Tests

To run the end-to-end evaluation pipeline:
```powershell
.\test\run_eval.ps1
```
Or run individual stages manually from repository root:
```bash
# Run first-stage retrieval evaluation
python -u test/pipeline/evaluate_first_stage.py --data test/data/anime_results.jsonl --iteration 'my_iteration'

# Run offline MRR and hit-rate analysis
python test/pipeline/evaluate_pipeline.py

# Generate summary markdown report
python test/pipeline/generate_report.py

# Run live synthetic query probe (tests live endpoint)
python test/hourly_run.py
```
