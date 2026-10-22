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
