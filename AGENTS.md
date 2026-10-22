# Guidelines for Coding Agents (Anti-Regrowth & Clean Code Rules)

This repository enforces strict clean code and hygiene rules to prevent dead code, duplicate implementations, and superseded leftovers from accumulating.

---

## 1. Ground Rules for Code Changes

1. **Extend, Do Not Duplicate:**
   - Before creating any new file, helper, or script, search for an existing module that performs a related job and extend it.
   - Do not create parallel implementations or wrappers around wrappers.

2. **No Scratch or Leftover File Names:**
   - Never create files with suffixes or prefixes such as `_old`, `_new`, `_v2`, `_final`, `_copy`, `_backup`, `_tmp`, or scratch notebooks.
   - Rely strictly on Git for version history.

3. **Atomic Supersession:**
   - When a change supersedes existing code, delete the superseded code in the exact same change or commit.
   - Never leave dead functions, obsolete aliases, or unused shims behind.
   - When consolidating, provide a clear docstring in the surviving canonical symbol explaining what it is the single source of truth for.

4. **One-Off Script Policy:**
   - One-off operational or maintenance scripts must be placed in a clearly named `scripts/oneoff/` directory with a header stating purpose and creation date, or they must not be committed to version control.

5. **Run the Hygiene Check:**
   - Run the automated repository hygiene check before committing:
     ```bash
     python scripts/check_hygiene.py
     ```
   - Commits will be rejected if banned naming patterns or superseded symbols are detected.

---

## 2. Protected Files & Architecture Boundaries

1. **Dual Entrypoints (Strictly Protected):**
   - `backend/main.py` (serves the Modal serverless CPU/GPU deployment and local API).
   - `backend/rag_pipeline/main.py` (serves the standalone RAG microservice).
   - Neither entry point may be modified or restructured without explicit authorization.

2. **Container Isolation (Data Pipeline):**
   - `backend/data_pipeline/Dockerfile` packages `backend/data_pipeline` exclusively into `/app/data_pipeline`.
   - Never import from `backend.rag_pipeline` or root `backend` inside the data pipeline, as this will crash the container build and the weekly GitHub Actions data update workflow.

3. **Frontend Environment Configuration:**
   - All frontend environment variables must be validated and declared in `frontend/src/config/env.ts`.
   - Never access `import.meta.env` directly in application components or libraries.
   - Never prefix backend secrets with `VITE_`.

4. **Language & Documentation Standard:**
   - Use British English in all comments, documentation, and log files.
   - Do not use em-dashes.

5. **Protected Files & Directories:**
   - Database migrations in `backend/migrations/` must never be altered retroactively.
   - Local scratchpad `misc/` and local operational note `DEPLOYMENT_TODO.md` are protected from deletion.
   - Evaluation data files (`test/data/anime_results.jsonl`, `test/data/llm_cache.db`) are protected test assets.
