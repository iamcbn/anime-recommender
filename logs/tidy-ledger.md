# Codebase Tidy Findings Ledger

Shared ledger tracking all findings across discovery, challenge, execution, and verification.

## Ledger Schema
- **ID:** Unique finding identifier (`D-xxx` for dead code, `S-xxx` for supersessions/duplicates, `C-xxx` for config/dependencies, `O-xxx` for orphan assets/docs).
- **Category:** `dead_code`, `duplicate`, `superseded`, `dependency`, `config`, `orphan_asset`, `stale_doc`.
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

## Findings

*(Populated during Sprint 1 Discovery)*
