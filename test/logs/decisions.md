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

### Sprint 2: Prune
- Implemented global environment safety guard in `test/conftest.py` preventing test execution against remote Supabase hosts or non-local base URLs.
- Deleted `test/test_sprint9_frontend_chat.py` (27 static string search tests).
- Deleted `test/test_sprint10_presentation.py` (20 static string search tests).
- Deleted static classes `TestFrontendStaticAndContract` (5 tests) and `TestDocumentationAndCodeSamplesContract` (8 tests) from `test/test_sprint6_frontend_and_admin_portal.py`.
- Deleted static class `TestFrontendSprint11Architecture` (5 tests) from `test/pipeline/test_sprint11_admin_usage.py`.
- Deleted 3 duplicate tests from `test/pipeline/test_sprint2_async_concurrency.py`.
- Deleted 3 duplicate/subsumed tests from `test/pipeline/test_sprint3_guardrails_sse.py`.
- Deleted 2 duplicate tests from `test/pipeline/test_sprint4_state_and_web_chat.py`.
- Deleted dead benchmark `test/benchmarks/SBERT_TEST.py` and static spreadsheet `test/benchmarks/sberts_performance.xlsx`.
- Preserved `TestOrchestratorSprint8Integration` and `test_sprint9_chat_tier.py` to prevent coverage regression on orchestrator, NLI, and chat endpoints.
- Total automated tests pruned: 73 items (from 419 to 346).
- Post-prune verification: All 346 tests passed (100% pass rate). Total statement coverage increased from 47% to 66% (missed statements decreased from 2,731 to 1,770).
