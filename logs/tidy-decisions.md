# Tidy Decisions Log

Record of all code removals, consolidations, repointings, and dependency changes.

## Sprint 0: Baseline and Architecture Mapping
- Established `logs/codebase-map.md` with complete dependency and import topology.
- Verified local startup of primary API (`backend/main.py`) via ASGI test client.
- Verified local build and TypeScript verification of frontend application (`tsc -b && vite build`).
- Established Pytest baseline (419 tests collected, 336 passed, 5 skipped, 9 failed, 69 database-dependent errors).
- Created findings ledger and progress tracking infrastructure.

## Sprint 1: Discovery (Multi-Agent Parallel Sweep)
- Deployed four read-only hunter subagents across backend, frontend, scripts, test, and documentation directories:
  - Hunter 2 (Dead code): Discovered 24 candidate findings (`D-001` through `D-024`).
  - Hunter 3 (Duplicate & supersession): Discovered 13 candidate findings (`S-001` through `S-013`).
  - Hunter 4 (Dependency & configuration): Discovered 13 candidate findings (`C-001` through `C-013`).
  - Hunter 5 (Orphan assets & documentation): Discovered 11 candidate findings (`O-001` through `O-011`).
- Consolidated all 61 findings into `logs/tidy-ledger.md` with 5-point evidence verification.
- Validated gate condition: 100% of top-level directories covered with zero source modifications.

## Sprint 2: Challenge and Triage (Adversarial Audit)
- Deployed adversarial Challenger subagent to independently probe and challenge all 61 findings.
- **Approved 39 findings:**
  - 23 dead code items (`D-001` through `D-023`).
  - 4 duplicate/superseded items (`S-001`, `S-002`, `S-003`, `S-007`).
  - 8 dependency & config items (`C-001`..`C-006`, `C-009`, `C-012`).
  - 4 orphan assets & build artefact items (`O-001`, `O-005`, `O-006`, `O-007`).
- **Flagged 13 findings for user decision (untouched):**
  - Model benchmarks: `S-008` (`test/benchmarks/SBERT_TEST.py`, `.xlsx`).
  - Cross-container helper: `S-011` (`preprocess.py` `parse_json`).
  - Scratchpads: `S-013` & `O-010` (`misc/`).
  - Secrets: `C-007` (`.env` `DATABASE_URL`).
  - Dev convenience: `C-010` (`frontend/package.json` `scripts.preview`).
  - Env template: `C-011` (`.env.example` creation).
  - Dev dependencies: `C-013` (`requirements.txt` `pyarrow`, `supabase`).
  - Untracked archive plans: `O-002`, `O-003`, `O-004` (`archive/`).
  - Policy protected dirs/notes: `O-008` (`models/`), `O-009` (`DEPLOYMENT_TODO.md`).
- **Rejected 9 findings:**
  - `D-024`, `S-004`, `S-005`: Protected dual entrypoint policy (`backend/main.py`, `backend/rag_pipeline/main.py`).
  - `S-006`, `C-008`: Docker container build isolation breaks weekly CI if `data_pipeline` imports from `rag_pipeline`.
  - `S-009`: Documented active CLI entrypoint (`python test/pipeline/evaluate_pipeline.py`).
  - `S-010`: Active runtime method and CI pipeline dependency populating Modal model volume.
  - `S-012`: `evaluation_report_v2.md` is active canonical evaluation output, not an obsolete duplicate.
  - `O-011`: Hand-maintained documentation protection policy (`NOTE_NON_IMPACTING_FILES.md`).
- Exit gate passed: 100% of candidate findings categorized and recorded in `logs/tidy-report.md` and `logs/tidy-ledger.md`.


## Sprint 3: Dead and Orphaned Code Removal
- Executed removal of 29 verified dead code, unused symbol, and unreferenced asset findings:
  - Deleted dead frontend component `frontend/src/components/common/Toast.tsx` (`D-001`).
  - Deleted superseded preferences module `frontend/src/lib/userPreferences.ts` (`D-002`, `S-002`, 249 lines).
  - Pruned unused `KeyStatus` type from `frontend/src/types/apiKeys.ts` (`D-003`).
  - Pruned unused `AuthMode` type from `frontend/src/types/auth.ts` (`D-004`).
  - Removed unused `RetrievalResult` dataclass from `backend/rag_pipeline/orchestrator.py` (`D-005`).
  - Removed unused `is_valid_query` method from `backend/rag_pipeline/helper/guardrails.py` (`D-006`).
  - Removed unused `is_hard_limit_exceeded` method from `backend/rag_pipeline/helper/budget_guard.py` (`D-007`).
  - Removed unused `inspect_bucket_via_sql` function from `scripts/verify_storage_bucket.py` (`D-008`).
  - Pruned unused imports across 14 backend and router modules (`D-009` through `D-023`).
  - Repointed `frontend/index.html` to eliminate 404 error from missing `/vite.svg` (`O-001`).
  - Cleaned untracked transpiled build artefacts `frontend/vite.config.js` and `frontend/vite.config.d.ts` (`S-001`, `O-007`).
  - Cleaned untracked build artefacts and compilation caches (`O-005`, `O-006`).
- Verified zero behavioural regressions:
  - Pytest baseline: exactly 336 passed, 5 skipped, 9 failed, 69 errors (100% parity with baseline).
  - Frontend build: `tsc -b && vite build` built in 4.58s with zero errors or warnings.
  - App startup: verified `GET /` returns 200 OK with CUDA GPU acceleration.
- Gate status: Sprint 3 exit gate Passed.


## Sprint 4: Consolidation of Duplicates & Supersessions
- Consolidated duplicate and superseded data pipeline components:
  - Pruned dead legacy helper `_adapt_value_old` from `backend/data_pipeline/helper/database.py` (`S-003`).
  - Added single-source-of-truth docstring to surviving canonical `DatabaseManager._adapt_value` method.
  - Verified exactly one definition of `_adapt_value` exists across the data pipeline subsystem.
  - Deleted unreferenced `backend/data_pipeline/Dockerfile.gpu` (`S-007`), establishing `backend/data_pipeline/Dockerfile` as the single canonical CPU Dockerfile matching GitHub Actions CI and docker-compose.
- Verified module loading: `backend.data_pipeline.helper.database.DatabaseManager` loads and imports cleanly.
- Gate status: Sprint 4 exit gate Passed.


## Sprint 5: Dependencies & Configuration Clean-Up
- Pruned redundant and unused dependencies across dependency manifests:
  - Pruned `scikit_learn==1.8.0` from `backend/rag_pipeline/requirements.txt` (`C-001`).
  - Pruned `Requests==2.32.5` from `backend/rag_pipeline/requirements.txt` (`C-002`).
  - Pruned `scikit_learn==1.8.0` from `backend/data_pipeline/requirements.txt` (`C-003`).
  - Pruned `scikit_learn==1.8.0` from root `requirements.txt` (`C-004`).
  - Pruned `google-genai==2.16.0` from root `requirements.txt` (`C-005`).
  - Pruned `kaggle==2.2.4` from root `requirements.txt` (`C-006`).
- Pruned unused model metadata class constants:
  - Pruned `SBERT_NAME` and `FASTTEXT_FILE` from `backend/rag_pipeline/helper/service_embedding.py` (`C-009`).
  - Pruned `CROSS_ENCODER_NAME` from `backend/rag_pipeline/helper/ranking.py` (`C-009`).
- Standardised frontend environment variable configuration:
  - Consolidated direct `import.meta.env.VITE_API_KEY` in `frontend/src/lib/chatStream.ts` into centralized `frontend/src/config/env.ts` (`C-012`).
- Verified zero behavioural regressions:
  - Frontend build: `tsc -b && vite build` built cleanly in 5.71s.
  - App startup: verified `GET /` returns 200 OK with CUDA GPU acceleration.
- Gate status: Sprint 5 exit gate Passed.
