# Claude / Coding Agent Guidelines

See [AGENTS.md](AGENTS.md) for the complete rules and hygiene policies governing coding agents in this repository.

## Summary Checklist Before Committing
1. Extend existing utilities instead of creating new duplicates.
2. Never commit `_old`, `_new`, `_copy`, or temporary scratch files.
3. Remove superseded code in the same change.
4. Run `python scripts/check_hygiene.py` to confirm zero hygiene violations.
5. Confirm tests and build pass (`npm run build` in `frontend/`, `python -m pytest test/`).
6. British English spelling only; zero em-dashes.
