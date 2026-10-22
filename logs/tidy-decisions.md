# Tidy Decisions Log

Record of all code removals, consolidations, repointings, and dependency changes.

## Sprint 0: Baseline and Architecture Mapping
- Established `logs/codebase-map.md` with complete dependency and import topology.
- Verified local startup of primary API (`backend/main.py`) via ASGI test client.
- Verified local build and TypeScript verification of frontend application (`tsc -b && vite build`).
- Established Pytest baseline (419 tests collected, 336 passed, 5 skipped, 9 failed, 69 database-dependent errors).
- Created findings ledger and progress tracking infrastructure.
