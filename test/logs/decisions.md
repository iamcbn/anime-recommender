# Test Architecture and Classification Decisions

This document records the architectural decisions, classifications (keep, merge, delete), and rationales for test suite modifications across all rebuild sprints.

## Decision Log

### Sprint 0: Baseline and Discovery
- Initialised sprint tracker, test logs, and report directories.
- Established baseline test count: 419 collected pytest tests across root and pipeline test directories.

### Sprint 1: Review and Redundancy Analysis
- Reviewed all 426 items across 30 files in `test/` (419 automated pytest items and 7 standalone scripts/benchmarks).
- Classified 277 items as KEEP (unique branches, security checks, and domain logic).
- Classified 5 items as KEEP (FLAGGED) due to tracer timing sensitivity (`test_ac2_2_event_loop_lag_remains_under_15ms`) or environment requirements.
- Classified 60 items as MERGE (exact duplicates, near duplicates, and narrow variants to be consolidated into parameterised tests or shared fixtures in `conftest.py`).
- Classified 84 items as DELETE:
  - 63 static Python regex string checks on TypeScript / TSX files (`test_sprint9_frontend_chat.py`, `test_sprint10_presentation.py`, `test_sprint6_frontend_and_admin_portal.py`, `test_sprint11_admin_usage.py`) to be deleted from the Python suite and replaced by native Vitest tests.
  - 14 duplicate or subsumed Python test methods.
  - 7 non-automated scripts, broken benchmarks, and offline evaluation runners (`hourly_run.py`, `SBERT_TEST.py`, `sberts_performance.xlsx`, `compare_embeddings.py`, `experiment_k.py`, `evaluate_first_stage.py`, `evaluate_pipeline.py`, `generate_report.py`).
