#!/usr/bin/env python3
"""
test/run_suite.py

Unified Test Runner and Stage 2 Execution Entry Point.
Provides a single interface to execute tests across all architectural layers
(unit, integration, system, regression, performance, non_functional)
and scopes (backend, frontend, fullstack).

Conforms strictly to British English documentation standards without em-dashes.

Usage:
    # Run the full test suite (backend, frontend unit, and browser E2E)
    python test/run_suite.py

    # Run specific layer
    python test/run_suite.py --layer unit
    python test/run_suite.py --layer integration
    python test/run_suite.py --layer system
    python test/run_suite.py --layer regression
    python test/run_suite.py --layer performance
    python test/run_suite.py --layer non_functional

    # Run specific scope
    python test/run_suite.py --scope backend
    python test/run_suite.py --scope frontend
    python test/run_suite.py --scope fullstack

    # Run flakiness audit (rerun N times)
    python test/run_suite.py --repeat 3
"""

import os
import sys
import time
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent


def find_python_executable() -> str:
    """Resolves virtual environment Python executable or system Python."""
    venv_python = REPO_ROOT / "anime" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    posix_venv = REPO_ROOT / "anime" / "bin" / "python"
    if posix_venv.exists():
        return str(posix_venv)
    return sys.executable


def get_node_env() -> Dict[str, str]:
    """Prepares process environment with Node.js in PATH."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    node_path = r"C:\Program Files\nodejs"
    if os.path.exists(node_path) and node_path not in env.get("PATH", ""):
        env["PATH"] = f"{node_path};{env.get('PATH', '')}"
    return env


def run_command(cmd: List[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None) -> int:
    """Executes a command synchronously, streaming output."""
    working_dir = str(cwd or REPO_ROOT)
    proc_env = env or get_node_env()
    print(f"\n[EXEC] {' '.join(cmd)} (cwd: {working_dir})")
    start_time = time.perf_counter()
    res = subprocess.run(cmd, cwd=working_dir, env=proc_env)
    elapsed = time.perf_counter() - start_time
    status = "SUCCESS" if res.returncode == 0 else f"FAILED (code {res.returncode})"
    print(f"[DONE] Completed in {elapsed:.2f}s with status: {status}\n")
    return res.returncode


def validate_stage2_environment() -> None:
    """Validates configuration parameters for Stage 2 isolated test environment."""
    test_env = os.environ.get("TEST_ENV", "local").strip().lower()
    print(f"[Stage 2 Profile] Active TEST_ENV: {test_env}")

    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "anime_db")
    api_url = os.environ.get("API_BASE_URL", "http://localhost:8001")
    web_url = os.environ.get("PLAYWRIGHT_BASE_URL", "http://localhost:5173")

    print(f"  - Database Target:    {db_host}:{db_port}/{db_name}")
    print(f"  - Backend API URL:    {api_url}")
    print(f"  - Frontend URL:       {web_url}")

    if test_env == "stage2_cloud":
        required_keys = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]
        missing = [k for k in required_keys if not os.environ.get(k)]
        if missing:
            print(f"[WARNING] Missing Stage 2 environment variables: {', '.join(missing)}")
            print("Ensure variables are injected via container environment or CI secret manager.")


def run_backend_tests(layer: str = "all", with_cov: bool = False) -> int:
    """Runs backend pytest tests matching layer markers."""
    python_bin = find_python_executable()
    cmd = [python_bin, "-m", "pytest"]

    # Layer mapping to pytest markers and directories
    layer_markers = {
        "unit": "unit",
        "integration": "integration",
        "system": "system and backend",
        "regression": "regression",
        "smoke": "smoke",
        "performance": "performance",
        "non_functional": "non_functional",
    }

    if layer in layer_markers:
        cmd.extend(["-m", layer_markers[layer]])
    elif layer != "all":
        cmd.extend(["-m", layer])

    if with_cov:
        reports_dir = REPO_ROOT / "test" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        cmd.extend([
            "--junitxml=test/reports/junit.xml",
            "--cov=backend",
            "--cov-report=xml:test/reports/coverage.xml",
            "--cov-report=term-missing",
        ])

    cmd.append("-v")
    return run_command(cmd)


def run_frontend_unit_tests() -> int:
    """Runs frontend Vitest tests."""
    frontend_dir = REPO_ROOT / "frontend"
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    cmd = [npm_cmd, "test"]
    return run_command(cmd, cwd=frontend_dir)


def run_frontend_e2e_tests(layer: str = "all") -> int:
    """Runs Playwright browser automation tests."""
    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"

    e2e_files = {
        "system": "frontend/e2e/critical_flows.spec.ts",
        "performance": "frontend/e2e/performance.spec.ts",
        "non_functional": "frontend/e2e/non_functional.spec.ts",
    }

    target_file = e2e_files.get(layer)
    if target_file:
        cmd = [npx_cmd, "--prefix", "frontend", "playwright", "test", target_file]
    else:
        cmd = [npx_cmd, "--prefix", "frontend", "playwright", "test"]

    return run_command(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified test suite runner for local and Stage 2 environments."
    )
    parser.add_argument(
        "--layer",
        choices=["all", "unit", "integration", "system", "regression", "smoke", "performance", "non_functional"],
        default="all",
        help="Target test layer to execute (default: all)",
    )
    parser.add_argument(
        "--scope",
        choices=["all", "backend", "frontend", "fullstack"],
        default="all",
        help="Target scope to execute (default: all)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of iterations to rerun suite for flakiness auditing (default: 1)",
    )
    parser.add_argument(
        "--cov",
        action="store_true",
        default=True,
        help="Enable coverage recording and XML report generation (default: True)",
    )
    parser.add_argument(
        "--no-cov",
        action="store_false",
        dest="cov",
        help="Disable coverage reporting",
    )
    parser.add_argument(
        "--stage2",
        action="store_true",
        help="Validate Stage 2 cloud test environment profile before running",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("ANIME RECOMMENDER: UNIFIED TEST SUITE RUNNER")
    print(f"Layer: {args.layer} | Scope: {args.scope} | Iterations: {args.repeat}")
    print("=" * 70)

    if args.stage2:
        validate_stage2_environment()

    total_runs = args.repeat
    for iteration in range(1, total_runs + 1):
        if total_runs > 1:
            print(f"\n>>> AUDIT ITERATION {iteration} of {total_runs} <<<\n")

        # 1. Backend tests
        if args.scope in ("all", "backend", "fullstack"):
            code = run_backend_tests(layer=args.layer, with_cov=(args.cov and args.layer == "all"))
            if code != 0:
                print(f"[FAIL] Backend tests failed during iteration {iteration}.")
                return code

        # 2. Frontend unit/contract tests
        if args.scope in ("all", "frontend", "fullstack"):
            if args.layer in ("all", "unit", "integration"):
                code = run_frontend_unit_tests()
                if code != 0:
                    print(f"[FAIL] Frontend unit tests failed during iteration {iteration}.")
                    return code

        # 3. Frontend browser automation E2E tests
        if args.scope in ("all", "frontend", "fullstack"):
            if args.layer in ("all", "system", "performance", "non_functional"):
                code = run_frontend_e2e_tests(layer=args.layer)
                if code != 0:
                    print(f"[FAIL] Frontend browser tests failed during iteration {iteration}.")
                    return code

    print("\n" + "=" * 70)
    print("PASSED: All targeted test layers and scopes completed successfully.")
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
