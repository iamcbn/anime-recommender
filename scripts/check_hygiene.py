#!/usr/bin/env python3
"""
scripts/check_hygiene.py

Automated repository hygiene check preventing dead code, duplicate patterns,
and leftover scratch files from being introduced by coding agents.

Run locally:
    python scripts/check_hygiene.py

Exit code:
    0 if clean, 1 if hygiene violations are detected.
"""

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 1. Banned leftover and scratch naming patterns
LEFTOVER_PATTERNS = [
    re.compile(r".*(_old|_new|_copy|_backup|_tmp|_final)\.[^.]+$", re.IGNORECASE),
    re.compile(r".*(_v\d+)\.(py|ts|tsx|js|json)$", re.IGNORECASE),
]

# Explicitly exempt historical or canonical files
EXEMPT_FILES = {
    "evaluation_report_v2.md",  # Canonical evaluation output
    "test_sprint1_migration.py",
}

# Directories ignored by hygiene check
IGNORE_DIRS = {
    ".git",
    "node_modules",
    "anime",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".continue",
    ".claude",
    "dist",
    "build",
    "logs",
    "misc",
}

# 2. Banned function / symbol naming patterns in tracked python files
BANNED_SYMBOL_PATTERNS = [
    re.compile(r"^\s*def\s+([a-zA-Z0-9_]+_(?:old|backup|tmp|copy|new))\s*\(", re.MULTILINE),
]


def check_file_names() -> list[str]:
    """Checks for leftover, temporary, or scratch files in tracked directories."""
    violations = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            if f in EXEMPT_FILES:
                continue
            for pattern in LEFTOVER_PATTERNS:
                if pattern.match(f):
                    rel_path = os.path.relpath(os.path.join(root, f), REPO_ROOT)
                    violations.append(f"Leftover file pattern: {rel_path}")
    return violations


def check_banned_symbols() -> list[str]:
    """Checks for superseded or backup functions left in Python files."""
    violations = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as fp:
                        content = fp.read()
                    for pattern in BANNED_SYMBOL_PATTERNS:
                        for match in pattern.finditer(content):
                            rel_path = os.path.relpath(path, REPO_ROOT)
                            violations.append(
                                f"Superseded symbol '{match.group(1)}' defined in {rel_path}"
                            )
                except Exception as e:
                    violations.append(f"Could not read {path}: {e}")
    return violations


import subprocess


def check_stray_build_artefacts() -> list[str]:
    """Ensures transpiled build outputs are not committed or tracked in git."""
    violations = []
    frontend_dir = REPO_ROOT / "frontend"
    stray_files = [
        frontend_dir / "vite.config.js",
        frontend_dir / "vite.config.d.ts",
    ]
    for p in stray_files:
        rel_path = os.path.relpath(p, REPO_ROOT).replace("\\", "/")
        try:
            res = subprocess.run(
                ["git", "ls-files", rel_path],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            if res.stdout.strip():
                violations.append(f"Stray build artefact tracked in git: {rel_path}")
        except Exception:
            pass
    return violations


def main() -> int:
    print("=" * 60)
    print("Running Repository Hygiene and Anti-Regrowth Audit")
    print("=" * 60)

    violations = []
    violations.extend(check_file_names())
    violations.extend(check_banned_symbols())
    violations.extend(check_stray_build_artefacts())

    if violations:
        print(f"\nFAILED: {len(violations)} hygiene violation(s) detected:\n")
        for v in violations:
            print(f"  - {v}")
        print("\nPlease resolve these issues before committing.\n")
        return 1

    print("\nPASSED: Zero hygiene violations detected across repository.")
    print("Codebase is clean of dead-code leftovers, scratch files, and stray artefacts.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
