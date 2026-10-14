param(
    [switch]$SkipRefresh   # Pass -SkipRefresh to skip the data pipeline and evaluate with existing DB data
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

try {
    Write-Host "=== Anime Recommender - Local Evaluation ===" -ForegroundColor Cyan

    # ──────────────────────────────────────────────
    # STEP 1: Run the data pipeline
    # Pulls the latest dataset from Kaggle, preprocesses it, retrains FastText,
    # and loads everything into the local Postgres DB — the same work the
    # data_pipeline Docker service used to do, now run directly.
    # ──────────────────────────────────────────────
    if ($SkipRefresh) {
        Write-Host "`n[SKIP] Data pipeline skipped (-SkipRefresh flag set)." -ForegroundColor Yellow
    } else {
        Write-Host "`n[1/3] Running data pipeline (Kaggle → preprocess → FastText → DB)..." -ForegroundColor Cyan
        python -m backend.data_pipeline.run_pipeline --force
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Data pipeline failed. Check the output above." -ForegroundColor Red
            exit 1
        }
        Write-Host "Data pipeline complete." -ForegroundColor Green
    }

    # ──────────────────────────────────────────────
    # STEP 2: Run first-stage retrieval evaluation
    # No container needed — dotenv loads .env and sys.path is set inside the script.
    # ──────────────────────────────────────────────
    Write-Host "`n[2/3] Running first-stage retrieval evaluation..." -ForegroundColor Cyan
    python -u test/pipeline/evaluate_first_stage.py --data test/data/anime_results.jsonl --iteration 'iteration_2_enriched'
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Evaluation failed. Check the output above." -ForegroundColor Red
        exit 1
    }

    # ──────────────────────────────────────────────
    # STEP 3: Generate markdown report
    # ──────────────────────────────────────────────
    Write-Host "`n[3/3] Generating evaluation report..." -ForegroundColor Cyan
    python test/pipeline/generate_report.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Report generation failed. Check the output above." -ForegroundColor Red
        exit 1
    }

    Write-Host "`nDone! Check test/data/evaluation_report_v2.md for the results." -ForegroundColor Green
} finally {
    Pop-Location
}
