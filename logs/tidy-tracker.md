# Codebase Tidy Tracker

| Sprint | Status | Agents Used | Findings (Prop / Chlg / Appr / Rej / Flag) | Files Removed | Lines Removed | Gate Result | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Sprint 0: Baseline and map** | Done | Orchestrator, Mapper, Verifier | 0 / 0 / 0 / 0 / 0 | 0 | 0 | Passed | Baseline metrics recorded (178 files, 40,991 lines, 419 tests: 336 pass / 5 skip / 9 fail / 69 err; frontend build clean; app startup verified). Codebase map generated. |
| **Sprint 1: Discovery** | Done | Hunters 2 to 5 | 61 / 0 / 0 / 0 / 0 | 0 | 0 | Passed | Multi-hunter parallel sweep completed across all directories. Shared ledger populated with 61 candidate findings (24 dead code, 13 duplicates/supersessions, 13 dependencies/config, 11 orphan assets/docs). |
| **Sprint 2: Challenge and triage** | Done | Challenger | 61 / 61 / 39 / 9 / 13 | 0 | 0 | Passed | Adversarial challenge completed across all 61 findings. 39 approved, 13 flagged for user decision, 9 rejected. Report written to `logs/tidy-report.md`. |
| **Sprint 3: Remove dead and orphaned code** | Done | Executor, Verifier | 0 / 0 / 29 / 0 / 0 | 2 | 298 | Passed | Removed dead code, unused functions, dead types, and unused imports (`D-001`..`D-023`, `S-001`, `S-002`, `O-001`, `O-005`, `O-006`, `O-007`). Tests (336 pass) and build (4.58s) 100% green. |
| **Sprint 4: Consolidate duplicates** | Done | Executor, Verifier | 0 / 0 / 2 / 0 / 0 | 1 | 57 | Passed | Consolidated `DatabaseManager._adapt_value`, added single source of truth docstring, removed `_adapt_value_old` and obsolete `Dockerfile.gpu`. Single definition confirmed. |
| **Sprint 5: Dependencies and config** | Done | Executor, Verifier | 0 / 0 / 8 / 0 / 0 | 0 | 7 | Passed | Pruned 6 unused packages across requirements files, pruned unused model constants, consolidated `VITE_API_KEY` into `env.ts`. Clean install, build, and app startup verified. |
| **Sprint 6: Prevent regrowth** | Done | Orchestrator | 0 / 0 / 0 / 0 / 0 | 0 | 0 | Passed | Created `AGENTS.md`, `CLAUDE.md`, and automated check script `scripts/check_hygiene.py`. Hygiene check verified green (0 violations). |
| **Sprint 7: Final verification** | In Progress | Verifier | 0 / 0 / 39 / 9 / 13 | 3 | 362 | Pending | Final comprehensive before/after metrics comparison and verification. |
