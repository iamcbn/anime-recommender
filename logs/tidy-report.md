# Adversarial Challenge & Triage Report

This report documents the rigorous adversarial challenge of all 61 findings in `logs/tidy-ledger.md`. Every finding was independently tested against dynamic reflection, container build isolation, CI/CD automation, framework conventions, and repository safety policies.

## Executive Summary

- **Total Findings Audited:** 61
- **High-Confidence Approved:** 39 findings (ready for automated execution across Sprints 3, 4, and 5)
- **Medium-Confidence Flagged:** 13 findings (retained untouched pending explicit user decision)
- **Rejected Findings:** 9 findings (disproved through concrete runtime references, container boundaries, or safety ground rules)

---

## 1. High-Confidence Approved Findings (39 Items)

These findings have been proven dead, superseded, or redundant against all 5 evidence standard points:
1. No static references.
2. No dynamic references (reflection, strings, config, CI, framework conventions).
3. Not an entry point.
4. Git history shows no active branch dependence.
5. Baseline build, typecheck, lint, and test suite pass cleanly without them.

### A. Dead Code (Sprint 3 Scope) - 23 Items
- **D-001** (`frontend/src/components/common/Toast.tsx`): Zero imports across frontend source or tests. UI notifications are handled inline in `ChatPage.tsx` and custom modals. Action: delete.
- **D-002** (`frontend/src/lib/userPreferences.ts`): All 249 lines unreferenced. Superseded by `frontend/src/hooks/useUserPreferences.ts`. Action: delete.
- **D-003** (`frontend/src/types/apiKeys.ts:39` - `KeyStatus`): Zero imports. Key status is computed locally in `KeyListTable.tsx` via `getKeyStatus()`. Action: delete.
- **D-004** (`frontend/src/types/auth.ts:22` - `AuthMode`): Zero imports. Auth flows use dedicated routes (`LoginPage.tsx`, `SignUpPage.tsx`). Action: delete.
- **D-005** (`backend/rag_pipeline/orchestrator.py:61` - `RetrievalResult`): Zero non-definition uses. The pipeline adopted standard tuples and dicts. Action: delete.
- **D-006** (`backend/rag_pipeline/helper/guardrails.py:462` - `DomainGuardrails.is_valid_query`): Unused speculative helper. All callers invoke `validate_intent(query)`. Action: delete.
- **D-007** (`backend/rag_pipeline/helper/budget_guard.py:289` - `BudgetGuard.is_hard_limit_exceeded`): Redundant alias. Callers invoke `check_budget_status()` or `is_budget_exceeded()`. Action: delete.
- **D-008** (`scripts/verify_storage_bucket.py:38` - `inspect_bucket_via_sql`): Unused helper in CLI probe script; `main()` exclusively uses `verify_or_create_bucket_via_sdk()`. Action: delete.
- **D-009** (`backend/rag_pipeline/orchestrator.py:33,36` - `validate_and_sanitize_citations`, `NLIOutput`): Unused header imports. Not referenced within file and not re-exported. Action: delete.
- **D-010** (`backend/rag_pipeline/rag_pipeline.py:1,3,7` - `Embedder`, `Ranker`, `Set`): Unused header imports from pre-Sprint 2 direct instantiation; inference is handled via `inference_client`. Action: delete.
- **D-011** (`backend/auth/keys.py:13` - `import uuid`): Unused import. Key generation uses `secrets.token_urlsafe()`. Action: delete.
- **D-012** (`backend/auth/supabase_jwt.py:18,24` - `urljoin`, `TTLCache`): Unused imports. JWKS caching is handled by `PyJWKClient`. Action: delete.
- **D-013** (`backend/rag_pipeline/helper/ranking.py:3` - `SentenceTransformer`): Unused import. `Ranker` uses `CrossEncoder`; embeddings reside in `service_embedding.py`. Action: delete.
- **D-014** (`backend/rag_pipeline/helper/service_embedding.py:4` - `pandas as pd`): Unused import. `Embedder` operates on lists and numpy arrays. Action: delete.
- **D-015** (`backend/rag_pipeline/helper/retrieval.py:1` - `connect`): Unused import. Connection pooling uses `ThreadedConnectionPool`. Action: delete.
- **D-016** (`backend/rag_pipeline/helper/synthesizer.py:30` - `OpenAIError`): Unused import. Specific error subclasses are handled explicitly. Action: delete.
- **D-017** (`backend/rag_pipeline/helper/nli_parser.py:14,19,20` - `os`, `httpx`, `Dict`, `Any`, `Union`): Unused imports left over from earlier prototypes. Action: delete.
- **D-018** (`backend/rag_pipeline/helper/query_generator.py:1,5` - `os`, `Any`): Unused imports left over from earlier prototypes. Action: delete.
- **D-019** (`backend/rag_pipeline/helper/guardrails.py:12` - `Union`): Unused typing import. Action: delete.
- **D-020** (`backend/rag_pipeline/helper/budget_guard.py:19` - `Union`): Unused typing import. Action: delete.
- **D-021** (`backend/rag_pipeline/inference_client.py:12` - `import sys`): Unused import left over from debugging. Action: delete.
- **D-022** (`backend/routers/admin_usage.py:23,29,30` - `timezone`, `DevUserContext`, `ApiKeyContext`): Unused imports. Neither symbol is used in router logic or re-exported. Action: delete.
- **D-023** (`backend/telemetry/archiver.py:67` - `from psycopg2 import extras`): Unused import. Archiver uses cursor iterations and pyarrow tables directly. Action: delete.

### B. Duplicates & Supersessions (Sprint 4 Scope) - 4 Items
- **S-001** (`frontend/vite.config.js` and `frontend/vite.config.d.ts`): Transpiled build artefacts left in source directory. Canonical file is `frontend/vite.config.ts`. Action: delete.
- **S-002** (`frontend/src/lib/userPreferences.ts`): Superseded duplicate of `frontend/src/hooks/useUserPreferences.ts` (concurs with D-002). Action: delete.
- **S-003** (`backend/data_pipeline/helper/database.py:178` - `DatabaseManager._adapt_value_old`): Dead legacy adaptation helper superseded by `_adapt_value()` on line 199. Action: delete.
- **S-007** (`backend/data_pipeline/Dockerfile.gpu`): Unreferenced Dockerfile. Production data pipeline updates run on CPU (`.github/workflows/update_data.yaml`), and `docker-compose.yaml` references the CPU Dockerfile. Action: delete.

### C. Dependencies & Configuration (Sprint 5 Scope) - 8 Items
- **C-001** (`backend/rag_pipeline/requirements.txt`: `scikit_learn==1.8.0`): Zero imports of `sklearn` across `backend/rag_pipeline/`. Action: delete.
- **C-002** (`backend/rag_pipeline/requirements.txt`: `Requests==2.32.5`): Zero imports across `backend/rag_pipeline/`; HTTP requests use `httpx` and `urllib`. Action: delete.
- **C-003** (`backend/data_pipeline/requirements.txt`: `scikit_learn==1.8.0`): Zero imports across `backend/data_pipeline/`. Action: delete.
- **C-004** (`requirements.txt`: `scikit_learn==1.8.0`): Unused in backend source or Modal deployment manifest (`modal_deploy.py`). Action: delete.
- **C-005** (`requirements.txt`: `google-genai==2.16.0`): Unused by backend and Modal deployment. The only consumer (`test/hourly_run.py`) has its dependency installed directly in GitHub Actions (`.github/workflows/hourly-recommendation.yaml`). Action: delete.
- **C-006** (`requirements.txt`: `kaggle==2.2.4`): Unused by Modal deployment. Data pipeline container pins its own separate version (`kaggle==1.8.3`). Action: delete.
- **C-009** (`backend/rag_pipeline/helper/service_embedding.py` - `SBERT_NAME`, `FASTTEXT_FILE` and `ranking.py` - `CROSS_ENCODER_NAME`): Unused class constants. Serving containers load models directly from disk directory paths. Action: delete.
- **C-012** (`frontend/src/lib/chatStream.ts:60` - `VITE_API_KEY`): Ad-hoc direct `import.meta.env` access. Action: consolidate into `frontend/src/config/env.ts`.

### D. Orphan Assets & Build Artefacts (Sprint 3 Scope) - 4 Items
- **O-001** (`frontend/index.html` - `<link rel="icon" type="image/svg+xml" href="/vite.svg" />`): Links to non-existent `/vite.svg` causing 404 on page load. Action: remove link or replace with static favicon.
- **O-005** (`frontend/dist/`): Generated build directory ignored by `.gitignore`. Re-generated via `npm run build`. Action: delete.
- **O-006** (`frontend/tsconfig*.tsbuildinfo`): Incremental compilation cache ignored by `.gitignore`. Re-generated via `tsc -b`. Action: delete.
- **O-007** (`frontend/vite.config.js`, `frontend/vite.config.d.ts`): Stale transpiled build artefacts (identical to S-001). Action: delete.

---

## 2. Medium-Confidence Flagged Findings (13 Items - Not Touched)

These findings involve genuine uncertainty, architectural trade-offs, developer convenience scripts, or untracked local scratchpads/secrets. In strict compliance with the project ground rules ("Nothing is deleted on suspicion. When unsure, keep it and flag it for me"), these items are preserved untouched pending explicit user decision.

1. **S-008** (`test/benchmarks/SBERT_TEST.py`, `test/benchmarks/sberts_performance.xlsx`): Intentionally migrated and preserved as historical model selection benchmarks per `NOTE_NON_IMPACTING_FILES.md` lines 8 and 27-30.
2. **S-011** (`backend/data_pipeline/helper/preprocess.py:118` - `parse_json`): Deciding whether to create a shared utility breaking Docker container encapsulation or retain duplicated small helpers is an architectural design decision.
3. **S-013** (`misc/` - Versioned READMEs, CSV data, notebooks): Untracked developer scratchpad explicitly protected by `NOTE_NON_IMPACTING_FILES.md` line 16.
4. **C-007** (`.env`: `DATABASE_URL`): Contains active Supabase credentials. Prompt safety rules mandate flagging all `.env` secrets for user confirmation rather than automated deletion.
5. **C-010** (`frontend/package.json` - `scripts.preview`): Standard Vite script commonly retained for developer convenience when previewing production builds locally.
6. **C-011** (Root repository missing `.env.example`): Feature improvement rather than dead code removal. Creating an environment template requires user validation of documented variables.
7. **C-013** (`requirements.txt`: `pyarrow>=19.0.0` and `supabase>=2.13.0`): While omitted from lightweight Modal deployments, root requirements are used for local full-stack development and running maintenance scripts.
8. **O-002** (`archive/ORCHESTRATION_MITIGATION_PLAN.md`): Resides in an untracked directory (`.gitignore` line 31). Untracked deletions are irreversible by git.
9. **O-003** (`archive/orchestration_intelligence_layer_report.md`): Exists only in untracked `archive/`. Deleting it permanently discards historical design documentation.
10. **O-004** (`archive/telemetry_and_archival_implementation_plan.md`): Exists only in untracked `archive/`. Permanent deletion requires user sign-off.
11. **O-008** (`models/` - empty root directory): Explicitly protected by repository policy in `NOTE_NON_IMPACTING_FILES.md` line 17 ("empty root models/: Left untouched as they are not tracked by git").
12. **O-009** (`DEPLOYMENT_TODO.md`): Uncommitted operational checklist excluded via `.git/info/exclude`. Protected developer note.
13. **O-010** (`misc/` - 28 files): Identical to S-013. Untracked exploratory scratchpad protected under `NOTE_NON_IMPACTING_FILES.md` line 16.

---

## 3. Rejected Findings (9 Items)

These findings were disproved during adversarial auditing due to active runtime references, container isolation requirements, or explicit repository safety rules.

1. **D-024** (`backend/main.py:8,9,10,12,31` - Unused imports):
   - **Reason for Rejection:** Ground rules explicitly mandate: "Do NOT approve touching database migrations, hand-maintained docs/configs, or dual entry points (`backend/main.py`, `backend/rag_pipeline/main.py`)." `backend/main.py` is a protected dual entrypoint serving Modal serverless GPU hosting and local API serving. Modifying it violates core safety ground rules.
2. **S-004** (`backend/rag_pipeline/main.py:23` - `class RateLimiter`):
   - **Reason for Rejection:** Proposed consolidation directly modifies `backend/rag_pipeline/main.py`, violating the ground rule strictly protecting dual entrypoints ("Dual Entrypoints (DO NOT TOUCH): `backend/main.py` and `backend/rag_pipeline/main.py` are strictly protected and remain untouched").
3. **S-005** (`backend/main.py:111-113` - Redaction regexes):
   - **Reason for Rejection:** Proposed consolidation directly modifies `backend/main.py`, violating the protected dual entrypoint ground rule.
4. **S-006** (`backend/data_pipeline/config.py` - `config()`):
   - **Reason for Rejection:** Container isolation failure. `backend/data_pipeline/Dockerfile` line 36 builds an isolated container using `COPY backend/data_pipeline /app/data_pipeline`. `backend/rag_pipeline` is intentionally NOT copied into the data pipeline container image. Repointing `run_pipeline.py` to `backend.rag_pipeline.config` causes an immediate runtime crash: `ModuleNotFoundError: No module named 'backend'`. This would break the weekly data update workflow in GitHub Actions (`.github/workflows/update_data.yaml` line 89).
5. **S-009** (`test/pipeline/evaluate_pipeline.py`):
   - **Reason for Rejection:** Active documented CLI entrypoint. `test/pipeline/evaluate_pipeline.py` is explicitly documented in `test/README.md` lines 11 and 44 as the official command for running offline MRR and hit-rate analysis: `python test/pipeline/evaluate_pipeline.py`. It is also documented in `NOTE_NON_IMPACTING_FILES.md` line 38. Deleting it breaks documented developer commands.
6. **S-010** (`backend/data_pipeline/helper/embedding.py` - `Embedder.load_cross_encoder`):
   - **Reason for Rejection:** Active runtime invocation and CI dependency. `Embedder.__init__` line 56 explicitly calls `self.cross_encoder = self.load_cross_encoder()`. Deleting this method causes an immediate `AttributeError` on startup. Furthermore, in CI (`.github/workflows/update_data.yaml` lines 71, 88, 114), the data pipeline runs with a volume mounted to `models/`. `load_cross_encoder()` downloads and saves the cross-encoder model to disk. The subsequent CI step ("Upload Models to Modal") uploads all models from this directory to the Modal volume `anime-models-vol`. Deleting `load_cross_encoder` prevents the cross-encoder model from being populated in Modal inference volume.
7. **S-012** (`test/data/evaluation_report_v2.md`):
   - **Reason for Rejection:** `test/data/evaluation_report.md` does not exist. `evaluation_report_v2.md` is the active canonical output generated by `test/pipeline/generate_report.py` line 12 and reported by `test/run_eval.ps1` line 50. It is also documented in `test/README.md` line 25 and `NOTE_NON_IMPACTING_FILES.md` line 49. It is not an unreferenced duplicate.
8. **C-008** (`backend/data_pipeline/config.py`):
   - **Reason for Rejection:** Identical to S-006. Consolidation into `backend/rag_pipeline/config.py` breaks container build isolation in `backend/data_pipeline/Dockerfile` and breaks `.github/workflows/update_data.yaml` with `ModuleNotFoundError`.
9. **O-011** (`NOTE_NON_IMPACTING_FILES.md` line 20 - `scripts/hourly_run.py`):
   - **Reason for Rejection:** Safety rule forbids touching hand-maintained documentation. `NOTE_NON_IMPACTING_FILES.md` is a protected local document recording repository policies.
