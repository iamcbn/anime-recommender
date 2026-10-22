# Codebase Tidy Findings Ledger

Shared ledger tracking all findings across discovery, challenge, execution, and verification.

## Ledger Schema
- **ID:** Unique finding identifier (`D-xxx` for dead code, `S-xxx` for supersessions/duplicates, `C-xxx` for config/dependencies, `O-xxx` for orphan assets/docs).
- **Category:** `dead_code`, `duplicate`, `superseded`, `dependency`, `config`, `orphan_asset`, `stale_doc`, `build_artefact`.
- **Path and Symbol:** Absolute or repository-relative file path and symbol (function, class, variable, file).
- **Evidence Standard (Points 1 to 5):**
  1. No static references (import/call/link).
  2. No dynamic references (string reflection, config, routes, CI, framework convention).
  3. Not an entry point.
  4. Git history shows no active branch/issue dependence.
  5. Baseline tests, build, typecheck, lint pass without it.
- **Confidence:** `high` (all 5 hold), `medium` (1 uncertain, flag for user decision), `low` (leave alone).
- **Proposed Action:** `delete`, `consolidate`, `repoint`, `flag`.
- **Owner Agent:** Agent that proposed the finding.
- **Status:** `proposed`, `challenged`, `approved`, `applied`, `verified`, `rejected`.

---

## 1. Dead Code Findings (Hunter 2)

### D-001
- **Category:** `dead_code`
- **Path and Symbol:** `frontend/src/components/common/Toast.tsx` (`Toast`, `ToastProps`)
- **Evidence:**
  1. *Static references:* Zero imports in `frontend/src/` or any test suite.
  2. *Dynamic references:* Zero string matches or dynamic component lookups.
  3. *Entry point check:* UI component, not an entry point (`index.html`, `main.tsx`, `App.tsx`).
  4. *Git history:* Scaffolding component; notifications are handled via inline banners in `ChatPage.tsx` and custom modals.
  5. *Test baseline:* `tsc -b && vite build` and Pytest baseline pass cleanly without this file.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-002
- **Category:** `dead_code`
- **Path and Symbol:** `frontend/src/lib/userPreferences.ts` (All 249 lines, all exports)
- **Evidence:**
  1. *Static references:* Zero imports repository-wide (only mentioned in `logs/codebase-map.md`).
  2. *Dynamic references:* Zero references to key `ar_user_preferences_v1` or event `ar:preferences-changed`. All UI state uses `frontend/src/hooks/useUserPreferences.ts`.
  3. *Entry point check:* Utility library module, not an entry point.
  4. *Git history:* Abandoned prototype created concurrently with `useUserPreferences.ts` in commit `f0f9387`.
  5. *Test baseline:* All tests and frontend build pass without this file.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-003
- **Category:** `dead_code`
- **Path and Symbol:** `frontend/src/types/apiKeys.ts:39` (`KeyStatus`)
- **Evidence:**
  1. *Static references:* Zero imports across components, hooks, routes, or tests.
  2. *Dynamic references:* Zero dynamic references. Key status is evaluated inline via `revoked_at` and `expires_at`.
  3. *Entry point check:* Type alias in TypeScript declaration file.
  4. *Git history:* Unused type alias from initial API key feature implementation.
  5. *Test baseline:* Frontend compilation passes cleanly without this type.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-004
- **Category:** `dead_code`
- **Path and Symbol:** `frontend/src/types/auth.ts:22` (`AuthMode`)
- **Evidence:**
  1. *Static references:* Zero imports across codebase.
  2. *Dynamic references:* Authentication flows are divided across dedicated pages (`LoginPage.tsx`, `SignUpPage.tsx`).
  3. *Entry point check:* Type definition.
  4. *Git history:* Unused modal mode type from early auth scaffolding.
  5. *Test baseline:* `tsc -b` and test suite pass without this type.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-005
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/orchestrator.py:61` (`RetrievalResult`)
- **Evidence:**
  1. *Static references:* Exactly 1 reference repository-wide (its own definition). Never instantiated or referenced.
  2. *Dynamic references:* Zero reflection, dictionary mapping, or serialisation references.
  3. *Entry point check:* Internal dataclass.
  4. *Git history:* Scaffolding dataclass from Sprint 4; pipeline adopted tuples and dictionaries instead.
  5. *Test baseline:* All Pytest tests pass cleanly without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-006
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/helper/guardrails.py:462` (`DomainGuardrails.is_valid_query`)
- **Evidence:**
  1. *Static references:* Exactly 1 reference repository-wide (its own definition).
  2. *Dynamic references:* Zero dynamic calls. Callers consistently use `DomainGuardrails.validate_intent(query)`.
  3. *Entry point check:* Class method on helper class.
  4. *Git history:* Speculative boolean helper from Sprint 3 that was never adopted.
  5. *Test baseline:* All guardrail unit and integration tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-007
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/helper/budget_guard.py:289` (`BudgetGuard.is_hard_limit_exceeded`)
- **Evidence:**
  1. *Static references:* Exactly 1 occurrence (its own definition).
  2. *Dynamic references:* Callers use `check_budget_status()` or `is_budget_exceeded()`.
  3. *Entry point check:* Method on singleton class.
  4. *Git history:* Redundant alias to `is_budget_exceeded` added during Sprint 11.
  5. *Test baseline:* `test_sprint11_budget_guard.py` passes without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-008
- **Category:** `dead_code`
- **Path and Symbol:** `scripts/verify_storage_bucket.py:38` (`inspect_bucket_via_sql`)
- **Evidence:**
  1. *Static references:* Exactly 1 occurrence repository-wide (its own definition). `main()` calls `verify_or_create_bucket_via_sdk()`.
  2. *Dynamic references:* Zero references in CI, scripts, or documentation.
  3. *Entry point check:* Helper inside a CLI maintenance script.
  4. *Git history:* Direct SQL probe written before Supabase SDK was integrated; never wired up.
  5. *Test baseline:* Verification script operates cleanly using SDK; no automated tests import this helper.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-009
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/orchestrator.py:33,36` (`validate_and_sanitize_citations`, `NLIOutput`)
- **Evidence:**
  1. *Static references:* Neither symbol is referenced within `orchestrator.py` outside import statements.
  2. *Dynamic references:* Neither symbol is listed in `__all__` or imported from `orchestrator.py` by external modules.
  3. *Entry point check:* Header import statements.
  4. *Git history:* Leftover imports from Sprint 8 and Sprint 10 development.
  5. *Test baseline:* Pytest tests pass without these imports.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-010
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/rag_pipeline.py:1,3,7` (`Embedder`, `Ranker`, `Set`)
- **Evidence:**
  1. *Static references:* Not used in `rag_pipeline.py`. Inference is managed via `inference_client = get_inference_client()`.
  2. *Dynamic references:* External callers import `Embedder` and `Ranker` from `helper.service_embedding` and `helper.ranking`.
  3. *Entry point check:* Header import statements.
  4. *Git history:* Relic of pre-Sprint 2 direct instantiation prior to `InferenceClient` abstraction.
  5. *Test baseline:* Pytest tests pass cleanly without these imports.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-011
- **Category:** `dead_code`
- **Path and Symbol:** `backend/auth/keys.py:13` (`import uuid`)
- **Evidence:**
  1. *Static references:* Occurs only once on line 13. Token generation uses `secrets.token_urlsafe()`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module import statement.
  4. *Git history:* Residual import from initial schema drafting.
  5. *Test baseline:* Auth tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-012
- **Category:** `dead_code`
- **Path and Symbol:** `backend/auth/supabase_jwt.py:18,24` (`urljoin`, `TTLCache`)
- **Evidence:**
  1. *Static references:* Neither is used in the module; JWKS caching is handled by `PyJWKClient(cache_jwk_set=True)`.
  2. *Dynamic references:* Zero dynamic references or exports.
  3. *Entry point check:* Module import statements.
  4. *Git history:* Relics from an early JWKS client draft.
  5. *Test baseline:* JWT verification tests pass cleanly without them.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-013
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/helper/ranking.py:3` (`SentenceTransformer`)
- **Evidence:**
  1. *Static references:* Occurs only on line 3. `Ranker` uses `CrossEncoder`; embeddings are in `service_embedding.py`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module import statement.
  4. *Git history:* Leftover from when ranking and embedding resided in the same file.
  5. *Test baseline:* Ranking tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-014
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/helper/service_embedding.py:4` (`pandas as pd`)
- **Evidence:**
  1. *Static references:* `pd` appears only once on line 4. `Embedder` operates on lists and numpy arrays.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module import statement.
  4. *Git history:* Leftover from data pipeline embedding exploration.
  5. *Test baseline:* Embedding tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-015
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/helper/retrieval.py:1` (`connect`)
- **Evidence:**
  1. *Static references:* `connect` appears only on line 1. `DatabaseManager` exclusively uses `ThreadedConnectionPool`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module import statement.
  4. *Git history:* Leftover from unpooled prototype.
  5. *Test baseline:* Retrieval tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-016
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/helper/synthesizer.py:30` (`OpenAIError`)
- **Evidence:**
  1. *Static references:* `OpenAIError` appears only on line 30. Specific error subclasses are handled explicitly.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module import statement.
  4. *Git history:* Residual import from initial catch-all block.
  5. *Test baseline:* Synthesizer tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-017
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/helper/nli_parser.py:14,19,20` (`os`, `httpx`, `Dict`, `Any`, `Union`)
- **Evidence:**
  1. *Static references:* None of `os`, `httpx`, `Dict`, `Any`, `Union` are referenced within the file body.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module import statements.
  4. *Git history:* Residual imports from prototype preceding `llm_clients.py` refactoring.
  5. *Test baseline:* NLI parser tests pass without them.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-018
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/helper/query_generator.py:1,5` (`os`, `Any`)
- **Evidence:**
  1. *Static references:* Neither `os` nor `Any` is used in `query_generator.py`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module import statements.
  4. *Git history:* Residual imports from before client abstraction.
  5. *Test baseline:* Query generator tests pass without them.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-019
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/helper/guardrails.py:12` (`Union`)
- **Evidence:**
  1. *Static references:* `Union` occurs only once on line 12.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module import statement.
  4. *Git history:* Leftover from type annotations.
  5. *Test baseline:* Guardrails tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-020
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/helper/budget_guard.py:19` (`Union`)
- **Evidence:**
  1. *Static references:* `Union` occurs only once on line 19.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module import statement.
  4. *Git history:* Leftover from initial schema drafting.
  5. *Test baseline:* Budget guard tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-021
- **Category:** `dead_code`
- **Path and Symbol:** `backend/rag_pipeline/inference_client.py:12` (`import sys`)
- **Evidence:**
  1. *Static references:* `sys` occurs only on line 12.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module import statement.
  4. *Git history:* Leftover from path debugging.
  5. *Test baseline:* Inference client tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-022
- **Category:** `dead_code`
- **Path and Symbol:** `backend/routers/admin_usage.py:23,29,30` (`timezone`, `DevUserContext`, `ApiKeyContext`)
- **Evidence:**
  1. *Static references:* None of the three symbols are used in the router body.
  2. *Dynamic references:* Zero dynamic references or exports.
  3. *Entry point check:* Router header imports.
  4. *Git history:* Residual imports from Sprint 11 Task 11.2 auth setup.
  5. *Test baseline:* Admin usage tests pass without them.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-023
- **Category:** `dead_code`
- **Path and Symbol:** `backend/telemetry/archiver.py:67` (`from psycopg2 import extras`)
- **Evidence:**
  1. *Static references:* `extras` occurs only on line 67. Archiver uses cursor fetch and pyarrow directly.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* CLI module header import.
  4. *Git history:* Leftover from initial connection prototyping.
  5. *Test baseline:* Archiver tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 2
- **Status:** `verified`

### D-024
- **Category:** `dead_code`
- **Path and Symbol:** `backend/main.py:8,9,10,12,31` (`Union`, `defaultdict`, `timedelta`, `Security`, `Response`, `DistributedRateLimiter`, `RateLimiter`)
- **Evidence:**
  1. *Static references:* Unused in `backend/main.py` (rate limiting uses singleton `rate_limiter`).
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Violates ground rule: `backend/main.py` is a protected dual-entrypoint.
  4. *Git history:* Residual imports from previous sprints.
  5. *Test baseline:* Tests pass.
- **Confidence:** `medium`
- **Proposed Action:** `flag` (Protected file policy takes precedence; do not edit without explicit instruction)
- **Owner Agent:** Hunter 2
- **Status:** `rejected`

---

## 2. Duplicate & Supersession Findings (Hunter 3)

### S-001
- **Category:** `config` / `duplicate`
- **Path and Symbol:** `frontend/vite.config.js` and `frontend/vite.config.d.ts`
- **Canonical Path and Symbol:** `frontend/vite.config.ts`
- **Evidence:**
  1. *Static references:* No file imports either transpiled file.
  2. *Dynamic references:* Vite resolves `vite.config.ts`; `frontend/.gitignore` explicitly ignores `.js` and `.d.ts`.
  3. *Entry point check:* Transpiled build output left in source directory.
  4. *Git history:* Untracked build artefacts.
  5. *Test baseline:* `tsc -b && vite build` runs cleanly using only `vite.config.ts`.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 3
- **Status:** `verified`

### S-002
- **Category:** `superseded` / `duplicate`
- **Path and Symbol:** `frontend/src/lib/userPreferences.ts`
- **Canonical Path and Symbol:** `frontend/src/hooks/useUserPreferences.ts`
- **Evidence:**
  1. *Static references:* Zero imports in repository.
  2. *Dynamic references:* Zero references to key `ar_user_preferences_v1`.
  3. *Entry point check:* Utility library.
  4. *Git history:* Parallel implementation abandoned since commit `f0f9387`.
  5. *Test baseline:* `test_sprint9_frontend_chat.py` only tests `useUserPreferences.ts`.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 3
- **Status:** `verified`

### S-003
- **Category:** `superseded`
- **Path and Symbol:** `backend/data_pipeline/helper/database.py:178` (`DatabaseManager._adapt_value_old`)
- **Canonical Path and Symbol:** `backend/data_pipeline/helper/database.py:199` (`DatabaseManager._adapt_value`)
- **Evidence:**
  1. *Static references:* Zero calls to `_adapt_value_old`.
  2. *Dynamic references:* `insert_temp_data` exclusively uses `_adapt_value`.
  3. *Entry point check:* Internal class method.
  4. *Git history:* Explicitly retained backup function superseded when numpy array handling was rewritten.
  5. *Test baseline:* Data pipeline tests pass without this dead function.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 3
- **Status:** `approved`

### S-004
- **Category:** `duplicate` / `superseded`
- **Path and Symbol:** `backend/rag_pipeline/main.py:23` (`class RateLimiter`)
- **Canonical Path and Symbol:** `backend/rag_pipeline/helper/rate_limiter.py:488` (`rate_limiter`)
- **Evidence:**
  1. *Static references:* No external module imports this class.
  2. *Dynamic references:* Local in-file in-memory rate limiter.
  3. *Entry point check:* Internal class in protected container entrypoint.
  4. *Git history:* Prototype limiter superseded in Sprint 2 by Redis-backed `DistributedRateLimiter`.
  5. *Test baseline:* Repointing `backend/rag_pipeline/main.py` to import `rate_limiter` maintains identical interface.
- **Confidence:** `high`
- **Proposed Action:** `consolidate`
- **Owner Agent:** Hunter 3
- **Status:** `rejected`

### S-005
- **Category:** `duplicate`
- **Path and Symbol:** `backend/main.py:111-113` (`BEARER_REDACT_REGEX`, `KEY_REDACT_REGEX`, `OPENAI_KEY_REDACT_REGEX`)
- **Canonical Path and Symbol:** `backend/telemetry/logger.py:56-58` (`_BEARER_REDACT_RE`, `_KEY_REDACT_RE`, `OPENAI_KEY_REDACT_REGEX`)
- **Evidence:**
  1. *Static references:* `backend/main.py` already imports `OPENAI_KEY_REDACT_REGEX` at line 48, then re-declares it at line 113.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Module-level regex constants.
  4. *Git history:* Re-compiled in Sprint 11 instead of importing existing compiled regexes from `telemetry/logger.py`.
  5. *Test baseline:* Re-exporting from `telemetry.logger` passes `test_sprint11_smoke.py`.
- **Confidence:** `high`
- **Proposed Action:** `consolidate`
- **Owner Agent:** Hunter 3
- **Status:** `rejected`

### S-006
- **Category:** `superseded`
- **Path and Symbol:** `backend/data_pipeline/config.py` (`config()`)
- **Canonical Path and Symbol:** `backend/rag_pipeline/config.py` (`config()`)
- **Evidence:**
  1. *Static references:* Only imported by `backend/data_pipeline/run_pipeline.py`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Utility module.
  4. *Git history:* Unmaintained fork lacking Supabase pooler detection (port 6543), SSL enforcement, and timeout guard.
  5. *Test baseline:* Repointing `run_pipeline.py` to canonical `backend.rag_pipeline.config` passes all tests.
- **Confidence:** `high`
- **Proposed Action:** `consolidate`
- **Owner Agent:** Hunter 3
- **Status:** `rejected`

### S-007
- **Category:** `superseded` / `duplicate`
- **Path and Symbol:** `backend/data_pipeline/Dockerfile.gpu`
- **Canonical Path and Symbol:** `backend/data_pipeline/Dockerfile`
- **Evidence:**
  1. *Static references:* Zero references in `docker-compose.yaml` or `.github/workflows/update_data.yaml`.
  2. *Dynamic references:* Data pipeline was explicitly pinned to CPU.
  3. *Entry point check:* Dockerfile, but never built by any pipeline.
  4. *Git history:* Added in commit `084decf`, but superseded by CPU Dockerfile.
  5. *Test baseline:* Builds and CI workflows pass without this file.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 3
- **Status:** `approved`

### S-008
- **Category:** `superseded` / `orphan_asset`
- **Path and Symbol:** `test/benchmarks/SBERT_TEST.py`, `test/benchmarks/sberts_performance.xlsx`
- **Canonical Path and Symbol:** `test/pipeline/evaluate_first_stage.py`, `test/experiments/compare_embeddings.py`
- **Evidence:**
  1. *Static references:* Zero code references or imports.
  2. *Dynamic references:* References obsolete non-existent path `pipeline/artifacts/v1/...`.
  3. *Entry point check:* Historical research script and binary spreadsheet.
  4. *Git history:* Moved to `test/benchmarks/` in commit `084decf` and never run since.
  5. *Test baseline:* Ignored by pytest; test baseline passes without it.
- **Confidence:** `high`
- **Proposed Action:** `delete` (or retain spreadsheet if user desires research archive)
- **Owner Agent:** Hunter 3
- **Status:** `flagged`

### S-009
- **Category:** `superseded`
- **Path and Symbol:** `test/pipeline/evaluate_pipeline.py`
- **Canonical Path and Symbol:** `test/pipeline/evaluate_first_stage.py` + `test/pipeline/generate_report.py`
- **Evidence:**
  1. *Static references:* Not invoked by `run_eval.ps1` or CI.
  2. *Dynamic references:* Evaluates obsolete `cosine_similarity` metric only.
  3. *Entry point check:* Test script.
  4. *Git history:* Early prototype evaluation script before hybrid RRF pipeline was implemented.
  5. *Test baseline:* `run_eval.ps1` runs `evaluate_first_stage.py` and `generate_report.py`.
- **Confidence:** `high`
- **Proposed Action:** `consolidate`
- **Owner Agent:** Hunter 3
- **Status:** `rejected`

### S-010
- **Category:** `superseded` / `duplicate`
- **Path and Symbol:** `backend/data_pipeline/helper/embedding.py` (`Embedder.load_cross_encoder`)
- **Canonical Path and Symbol:** `backend/rag_pipeline/helper/ranking.py` (`Ranker.load_cross_encoder`)
- **Evidence:**
  1. *Static references:* `self.cross_encoder` is never used or called in `backend/data_pipeline`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Method in offline pipeline embedder.
  4. *Git history:* Cross-encoder inference was decoupled into online `Ranker` in `rag_pipeline`.
  5. *Test baseline:* Data pipeline tests pass without cross-encoder loading.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 3
- **Status:** `rejected`

### S-011
- **Category:** `duplicate`
- **Path and Symbol:** `backend/data_pipeline/helper/preprocess.py:118` (`parse_json`)
- **Canonical Path and Symbol:** `backend/rag_pipeline/helper/ranking.py:283` (`parse_json`)
- **Evidence:**
  1. *Static references:* Independent static helpers performing identical task.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Class static methods.
  4. *Git history:* Implemented independently in data preprocessing and ranking.
  5. *Test baseline:* Tests pass.
- **Confidence:** `medium`
- **Proposed Action:** `consolidate` (centralise or preserve module encapsulation)
- **Owner Agent:** Hunter 3
- **Status:** `flagged`

### S-012
- **Category:** `superseded`
- **Path and Symbol:** `test/data/evaluation_report_v2.md`
- **Canonical Path and Symbol:** `test/data/evaluation_report.md`
- **Evidence:**
  1. *Static references:* Generated by `generate_report.py:12` and referenced by `run_eval.ps1:50`.
  2. *Dynamic references:* None.
  3. *Entry point check:* Output report document.
  4. *Git history:* Versioned filename introduced in commit `084decf`.
  5. *Test baseline:* Standardising target path eliminates leftover versioned naming.
- **Confidence:** `medium`
- **Proposed Action:** `consolidate`
- **Owner Agent:** Hunter 3
- **Status:** `rejected`

### S-013
- **Category:** `orphan_asset` / `superseded`
- **Path and Symbol:** `misc/` (`README_v1.md` through `v6.md`, `data copy.csv`, `old gemini code.py`, `*.ipynb`)
- **Canonical Path and Symbol:** Root `README.md`, `ARCHITECTURE.md`, production codebase
- **Evidence:**
  1. *Static references:* Zero production code or test references.
  2. *Dynamic references:* Completely ignored by `.gitignore`.
  3. *Entry point check:* Untracked developer scratchpad.
  4. *Git history:* Not tracked in git. Protected under `NOTE_NON_IMPACTING_FILES.md` line 16.
  5. *Test baseline:* Tests pass without `misc/`.
- **Confidence:** `medium`
- **Proposed Action:** `flag` (Flagged for user decision per ground rules)
- **Owner Agent:** Hunter 3
- **Status:** `flagged`

---

## 3. Dependency & Configuration Findings (Hunter 4)

### C-001
- **Category:** `dependency`
- **Path and Symbol:** `backend/rag_pipeline/requirements.txt`: `scikit_learn==1.8.0`
- **Evidence:**
  1. *Static references:* AST analysis of `backend/rag_pipeline/` found 0 imports of `sklearn`.
  2. *Dynamic references:* Zero dynamic imports or reflection.
  3. *Entry point check:* Requirements line item.
  4. *Git history:* Benchmark dependency moved to `test/benchmarks/`.
  5. *Test baseline:* Container builds and tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 4
- **Status:** `approved`

### C-002
- **Category:** `dependency`
- **Path and Symbol:** `backend/rag_pipeline/requirements.txt`: `Requests==2.32.5`
- **Evidence:**
  1. *Static references:* AST analysis of `backend/rag_pipeline/` found 0 imports of `requests`.
  2. *Dynamic references:* Production HTTP communication uses `httpx` and `urllib`.
  3. *Entry point check:* Requirements line item.
  4. *Git history:* Leftover from early synchronous prototyping.
  5. *Test baseline:* Tests pass without `requests`.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 4
- **Status:** `approved`

### C-003
- **Category:** `dependency`
- **Path and Symbol:** `backend/data_pipeline/requirements.txt`: `scikit_learn==1.8.0`
- **Evidence:**
  1. *Static references:* Scan of `backend/data_pipeline/` confirms 0 imports of `sklearn`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Requirements line item.
  4. *Git history:* Relic from when `SBERT_TEST.py` was inside data pipeline.
  5. *Test baseline:* Data pipeline Docker image builds cleanly without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 4
- **Status:** `approved`

### C-004
- **Category:** `dependency`
- **Path and Symbol:** `requirements.txt`: `scikit_learn==1.8.0`
- **Evidence:**
  1. *Static references:* Zero imports in `backend/` or `modal_deploy.py`. Only used in `test/benchmarks/SBERT_TEST.py`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Requirements line item in prod Modal manifest.
  4. *Git history:* Benchmark dependency included in root requirements.
  5. *Test baseline:* Modal container builds faster and lighter without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 4
- **Status:** `approved`

### C-005
- **Category:** `dependency`
- **Path and Symbol:** `requirements.txt`: `google-genai==2.16.0`
- **Evidence:**
  1. *Static references:* Zero imports in `backend/` or `modal_deploy.py`. Only used in `test/hourly_run.py`.
  2. *Dynamic references:* Production endpoints use OpenAI and local PyTorch models.
  3. *Entry point check:* Manifest line item.
  4. *Git history:* Workflow `hourly-recommendation.yaml` explicitly installs `google-genai` separately.
  5. *Test baseline:* Modal deployment does not require `google-genai`.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 4
- **Status:** `approved`

### C-006
- **Category:** `dependency`
- **Path and Symbol:** `requirements.txt`: `kaggle==2.2.4`
- **Evidence:**
  1. *Static references:* Zero imports in `backend/main.py`, `rag_pipeline/`, or `modal_deploy.py`.
  2. *Dynamic references:* Data pipeline runs in its own Docker container with `kaggle==1.8.3`.
  3. *Entry point check:* Manifest line item creating a conflicting duplicate.
  4. *Git history:* Root requirements pinned conflicting version `2.2.4` vs `1.8.3`.
  5. *Test baseline:* Modal deployment passes without `kaggle`.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 4
- **Status:** `approved`

### C-007
- **Category:** `config`
- **Path and Symbol:** `.env`: `DATABASE_URL`
- **Evidence:**
  1. *Static references:* Zero Python files call `os.getenv("DATABASE_URL")`.
  2. *Dynamic references:* All database connections use discrete `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
  3. *Entry point check:* Environment variable in `.env`.
  4. *Git history:* Stale connection string from early template setup.
  5. *Test baseline:* All tests and containers pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 4
- **Status:** `flagged`

### C-008
- **Category:** `config`
- **Path and Symbol:** `backend/data_pipeline/config.py`
- **Evidence:**
  1. *Static references:* Only imported by `run_pipeline.py`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Configuration module.
  4. *Git history:* Inferior copy lacking SSL, timeout, and pooler port detection.
  5. *Test baseline:* Repointing `run_pipeline.py` to `backend.rag_pipeline.config` passes tests.
- **Confidence:** `high`
- **Proposed Action:** `consolidate`
- **Owner Agent:** Hunter 4
- **Status:** `rejected`

### C-009
- **Category:** `config`
- **Path and Symbol:** `backend/rag_pipeline/helper/service_embedding.py` (`SBERT_NAME`, `FASTTEXT_FILE`) and `ranking.py` (`CROSS_ENCODER_NAME`)
- **Evidence:**
  1. *Static references:* Never accessed; classes derive paths directly from directory constants.
  2. *Dynamic references:* Zero dynamic lookups.
  3. *Entry point check:* Class-level constant attributes.
  4. *Git history:* Leftover constants from early refactoring.
  5. *Test baseline:* Tests pass without them.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 4
- **Status:** `approved`

### C-010
- **Category:** `stale_script`
- **Path and Symbol:** `frontend/package.json` (`scripts.preview`)
- **Evidence:**
  1. *Static references:* Not referenced in CI, Dockerfiles, or other scripts.
  2. *Dynamic references:* Zero dynamic invocations.
  3. *Entry point check:* Standard Vite boilerplate script.
  4. *Git history:* Present since Vite initialisation; never invoked in automation.
  5. *Test baseline:* Frontend build unaffected by removal.
- **Confidence:** `medium`
- **Proposed Action:** `flag` (Standard script commonly retained for developer convenience)
- **Owner Agent:** Hunter 4
- **Status:** `flagged`

### C-011
- **Category:** `config`
- **Path and Symbol:** Root repository missing `.env.example`
- **Evidence:**
  1. *Static references:* `frontend/.env.example` exists, but root lacks a template.
  2. *Dynamic references:* Redis, Pepper, JWKS, and LLM keys are undocumented in a template.
  3. *Entry point check:* Configuration template asset.
  4. *Git history:* Missing since repository inception.
  5. *Test baseline:* Creating a clean `.env.example` template prevents configuration drift.
- **Confidence:** `high`
- **Proposed Action:** `flag`
- **Owner Agent:** Hunter 4
- **Status:** `flagged`

### C-012
- **Category:** `config`
- **Path and Symbol:** `frontend/src/lib/chatStream.ts:60` (`VITE_API_KEY`)
- **Evidence:**
  1. *Static references:* `chatStream.ts` calls `import.meta.env.VITE_API_KEY`.
  2. *Dynamic references:* Not validated or exported in `frontend/src/config/env.ts`.
  3. *Entry point check:* Environment variable access point.
  4. *Git history:* Fallback added in Sprint 9.
  5. *Test baseline:* Consolidating into `env.ts` standardises environment access.
- **Confidence:** `high`
- **Proposed Action:** `consolidate`
- **Owner Agent:** Hunter 4
- **Status:** `approved`

### C-013
- **Category:** `dependency`
- **Path and Symbol:** `requirements.txt`: `pyarrow>=19.0.0` and `supabase>=2.13.0`
- **Evidence:**
  1. *Static references:* In `backend/`, only used in `telemetry/archiver.py` and `scripts/verify_storage_bucket.py`.
  2. *Dynamic references:* Dual entrypoints do not import either package.
  3. *Entry point check:* Manifest line items.
  4. *Git history:* `requirements-archive.txt` was created specifically for the archiver to keep CI lean.
  5. *Test baseline:* Modal deployment passes without them.
- **Confidence:** `medium`
- **Proposed Action:** `flag` (Flagged for decision whether root requirements should keep them for local execution)
- **Owner Agent:** Hunter 4
- **Status:** `flagged`

---

## 4. Orphan Asset & Documentation Findings (Hunter 5)

### O-001
- **Category:** `orphan_asset`
- **Path and Symbol:** `frontend/index.html` (line 5: `<link rel="icon" type="image/svg+xml" href="/vite.svg" />`)
- **Evidence:**
  1. *Static references:* Links to `/vite.svg`; no file named `vite.svg` exists in repository, nor does `frontend/public/` exist.
  2. *Dynamic references:* Zero dynamic injection; causes 404 on browser page load.
  3. *Entry point check:* Link tag inside entry point.
  4. *Git history:* Leftover from default Vite template.
  5. *Test baseline:* Removing or repointing eliminates 404 without breaking build.
- **Confidence:** `high`
- **Proposed Action:** `repoint`
- **Owner Agent:** Hunter 5
- **Status:** `verified`

### O-002
- **Category:** `stale_doc`
- **Path and Symbol:** `archive/ORCHESTRATION_MITIGATION_PLAN.md`
- **Evidence:**
  1. *Static references:* Zero active links point to `archive/`; `ARCHITECTURE.md` links to `docs/ORCHESTRATION_MITIGATION_PLAN.md`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Standalone document.
  4. *Git history:* Exact 100% duplicate of `docs/ORCHESTRATION_MITIGATION_PLAN.md`.
  5. *Test baseline:* Deletion has zero test impact.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 5
- **Status:** `flagged`

### O-003
- **Category:** `stale_doc`
- **Path and Symbol:** `archive/orchestration_intelligence_layer_report.md`
- **Evidence:**
  1. *Static references:* Only referenced by `archive/ORCHESTRATION_MITIGATION_PLAN.md`.
  2. *Dynamic references:* Zero dynamic references.
  3. *Entry point check:* Planning report.
  4. *Git history:* Actionable items merged into production orchestrator.
  5. *Test baseline:* Tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 5
- **Status:** `flagged`

### O-004
- **Category:** `stale_doc`
- **Path and Symbol:** `archive/telemetry_and_archival_implementation_plan.md`
- **Evidence:**
  1. *Static references:* Mentioned historically in docstrings.
  2. *Dynamic references:* Excluded in `.gitignore`.
  3. *Entry point check:* Planning document.
  4. *Git history:* Historical specification implemented in Sprints 2-4.
  5. *Test baseline:* Tests pass without it.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 5
- **Status:** `flagged`

### O-005
- **Category:** `build_artefact`
- **Path and Symbol:** `frontend/dist/`
- **Evidence:**
  1. *Static references:* Zero static imports.
  2. *Dynamic references:* Backend does not serve static files; frontend runs Vite dev server in Docker.
  3. *Entry point check:* Generated build distribution.
  4. *Git history:* Untracked build output ignored by `.gitignore`.
  5. *Test baseline:* `npm run build` regenerates on demand.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 5
- **Status:** `verified`

### O-006
- **Category:** `build_artefact`
- **Path and Symbol:** `frontend/tsconfig*.tsbuildinfo`
- **Evidence:**
  1. *Static references:* Zero static references.
  2. *Dynamic references:* Generated automatically by `tsc -b`.
  3. *Entry point check:* Compiler cache files.
  4. *Git history:* Untracked cache ignored by `.gitignore`.
  5. *Test baseline:* `tsc -b` regenerates cleanly.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 5
- **Status:** `verified`

### O-007
- **Category:** `build_artefact`
- **Path and Symbol:** `frontend/vite.config.js`, `frontend/vite.config.d.ts`
- **Evidence:**
  1. *Static references:* Zero imports; Vite uses `vite.config.ts`.
  2. *Dynamic references:* Explicitly ignored in `frontend/.gitignore`.
  3. *Entry point check:* Transpiled build output in source directory.
  4. *Git history:* Untracked in git.
  5. *Test baseline:* Builds pass cleanly without them.
- **Confidence:** `high`
- **Proposed Action:** `delete`
- **Owner Agent:** Hunter 5
- **Status:** `verified`

### O-008
- **Category:** `empty_directory`
- **Path and Symbol:** `models/` (root workspace directory)
- **Evidence:**
  1. *Static references:* Model loading references `backend/models` or HuggingFace Hub.
  2. *Dynamic references:* Docker Compose volume `models:` is a named Docker volume, not root `./models/`.
  3. *Entry point check:* Empty directory containing 0 files.
  4. *Git history:* Untracked; noted in `NOTE_NON_IMPACTING_FILES.md` line 17.
  5. *Test baseline:* Tests pass without it.
- **Confidence:** `medium`
- **Proposed Action:** `flag`
- **Owner Agent:** Hunter 5
- **Status:** `flagged`

### O-009
- **Category:** `stale_doc`
- **Path and Symbol:** `DEPLOYMENT_TODO.md`
- **Evidence:**
  1. *Static references:* Zero imports or links.
  2. *Dynamic references:* Excluded via `.git/info/exclude`.
  3. *Entry point check:* Local checklist.
  4. *Git history:* Uncommitted operational deployment notes.
  5. *Test baseline:* Tests pass without it.
- **Confidence:** `medium`
- **Proposed Action:** `flag` (Retain as local developer note)
- **Owner Agent:** Hunter 5
- **Status:** `flagged`

### O-010
- **Category:** `unreferenced_data` / `stale_doc`
- **Path and Symbol:** `misc/` (28 files: versioned READMEs, exploratory notebooks, legacy data)
- **Evidence:**
  1. *Static references:* Zero references from active codebase.
  2. *Dynamic references:* Ignored by `.gitignore`.
  3. *Entry point check:* Untracked scratchpad.
  4. *Git history:* Untracked; protected under `NOTE_NON_IMPACTING_FILES.md` policy.
  5. *Test baseline:* Tests pass without it.
- **Confidence:** `medium`
- **Proposed Action:** `flag` (Flagged for user decision per ground rules)
- **Owner Agent:** Hunter 5
- **Status:** `flagged`

### O-011
- **Category:** `stale_doc`
- **Path and Symbol:** `NOTE_NON_IMPACTING_FILES.md` (line 20: `scripts/hourly_run.py`)
- **Evidence:**
  1. *Static references:* Refers to `scripts/hourly_run.py`, which was moved to `test/hourly_run.py`.
  2. *Dynamic references:* CI invokes `python test/hourly_run.py`.
  3. *Entry point check:* Documentation reference discrepancy.
  4. *Git history:* `test/hourly_run.py` is the tracked file.
  5. *Test baseline:* Updating documentation line has zero runtime impact.
- **Confidence:** `high`
- **Proposed Action:** `repoint`
- **Owner Agent:** Hunter 5
- **Status:** `rejected`
