# Anime Recommender: Test Suite Runbook (Stage 1 Local and Stage 2 Cloud Readiness)

This runbook documents the architecture, local execution instructions, environment configuration, and cloud test migration guidelines for the unified test suite.

---

## 1. Architectural Overview

The test suite enforces a strict layered structure, ensuring clear separation of concerns, fast execution feedback, and complete isolation:

| Layer | Directory / Path | Markers | Scope | Description |
|---|---|---|---|---|
| **Unit** | `test/unit/`<br>`frontend/src/**/*.test.ts(x)` | `@pytest.mark.unit`<br>(Vitest) | Backend<br>Frontend | Fast, hermetic tests with zero network or database dependencies covering business logic, guardrails, tokens, and UI components. |
| **Integration** | `test/integration/`<br>`frontend/src/test/apiContract.test.ts` | `@pytest.mark.integration`<br>(Vitest) | Backend<br>Fullstack | Live local database interactions (PostgreSQL 16), trigger enforcement, audit logging, telemetry rollups, and UI-backend contract drift prevention. |
| **System** | `test/system/`<br>`frontend/e2e/critical_flows.spec.ts` | `@pytest.mark.system`<br>(Playwright) | Backend<br>Fullstack | Real HTTP API journeys (`/recommend`, `/chat`, `/dev/keys`, `/admin/*`) and fullstack browser automation flows across critical discovery journeys. |
| **Regression** | `test/regression/`<br>`test/smoke/` | `@pytest.mark.regression`<br>`@pytest.mark.smoke` | Backend | Tests protecting past fixed bugs mined from git history, alongside a high-speed critical path smoke set. |
| **Performance** | `test/performance/`<br>`frontend/e2e/performance.spec.ts` | `@pytest.mark.performance`<br>(Playwright) | Backend<br>Fullstack | Configurable latency baselines (P95 < 1000ms), Time-to-First-Token (TTFT < 1500ms), 10-client concurrent load, bundle budgets, and Navigation Timing API metrics. |
| **Non-Functional** | `test/non_functional/`<br>`frontend/e2e/non_functional.spec.ts` | `@pytest.mark.non_functional`<br>(Playwright) | Backend<br>Fullstack | Security matrices, prompt and SQL injection defence, CORS and cache headers, secrets redaction, fault-tolerant degradation, safety guards, and ARIA accessibility. |

---

## 2. Local Setup and Prerequisites

### Prerequisites
1. **Python 3.11+**:
   - Virtual environment located at `./anime` (or system Python 3.11).
   - Dependencies: `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx`, `psycopg2`, `cachetools`.
2. **Node.js v20+ / v24+**:
   - Package manager: `npm` inside `frontend/`.
   - Playwright Chromium installed (`npx playwright install chromium`).
3. **Local PostgreSQL 16**:
   - Host: `localhost:5432`, Database: `anime_db`, User: `postgres`.

### Environment Safety Guard
The root test configuration in `test/conftest.py` contains an automated safety guard. The suite will immediately abort with exit code 3 if `DB_HOST`, `DATABASE_URL`, or `MODAL_API_URL` point to production indicators (`supabase.co`, `pooler.supabase.com`, `aws-1-eu-north-1`, `neon.tech`, `rds.amazonaws.com`).

---

## 3. Test Execution Commands

### A. Unified Single Entry Point
Execute the entire test suite (backend, frontend unit, and browser automation) with a single command:
```bash
python test/run_suite.py
```

### B. Run by Architectural Layer
Run any specific layer across backend and frontend:
```bash
# Unit tests only (Python unit + Vitest)
python test/run_suite.py --layer unit

# Integration & Contract tests
python test/run_suite.py --layer integration

# System tests (HTTP journeys + browser automation)
python test/run_suite.py --layer system

# Regression & Smoke tests
python test/run_suite.py --layer regression

# Performance benchmarks
python test/run_suite.py --layer performance

# Non-functional & Security tests
python test/run_suite.py --layer non_functional
```

### C. Run by Scope
Filter execution by scope:
```bash
# Backend pytest tests only
python test/run_suite.py --scope backend

# Frontend unit and browser tests only
python test/run_suite.py --scope frontend

# Fullstack end-to-end integration only
python test/run_suite.py --scope fullstack
```

### D. Direct Pytest CLI Shortcuts
Alternatively, execute pytest directly using registered markers:
```bash
# Run unit layer
pytest -m unit -v

# Run integration layer
pytest -m integration -v

# Run system layer
pytest -m "system and backend" -v

# Run regression layer
pytest -m regression -v

# Run high-speed smoke set
pytest -m smoke -v

# Run performance benchmarks
pytest -m performance -v

# Run non-functional suite
pytest -m non_functional -v
```

---

## 4. Stage 2 Cloud Test Migration and Environment Profiles

Stage 2 executes the identical test suite in an isolated cloud test environment (e.g. GitHub Actions, ephemeral Docker Compose, or Kubernetes test namespace). No new test code is written for Stage 2; all tests are environment-driven.

### A. Stage 2 Environment Variables
Configure the following environment variables in your cloud test runner:

```bash
# Environment Profile
TEST_ENV="stage2_cloud"

# Target Services
API_BASE_URL="http://test-api:8001"
PLAYWRIGHT_BASE_URL="http://test-frontend:5173"
STAGE2_ALLOWED_HOSTS="test-api,api-test,test-db,test-frontend"

# Database Configuration (Isolated Cloud Test Instance)
DB_HOST="test-db"
DB_PORT="5432"
DB_NAME="anime_test_db"
DB_USER="postgres"
DB_PASSWORD="test_password"
DB_SSLMODE="prefer"

# Credentials & Mock Secrets
ADMIN_API_KEY="ar_live_admin_secret_test_key_1234567890"
MY_API_KEY="ar_live_regular_user_key_1234567890"

# Configurable Performance Thresholds
PERF_RECOMMEND_P95_MS="1200.0"
PERF_CHAT_TTFT_MS="2000.0"
PERF_LOAD_CONCURRENCY="10"
PERF_DEV_KEYS_P95_MS="250.0"
PERF_FRONTEND_NAV_MS="3500.0"
PERF_FRONTEND_BUNDLE_KB="650.0"
```

### B. Stage 2 Docker Compose Profile
To stand up an isolated test stack in CI or cloud environments:

```yaml
version: "3.8"

services:
  test-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: anime_test_db
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: test_password
    ports:
      - "5432:5432"

  test-runner:
    build:
      context: .
      dockerfile: Dockerfile.test
    environment:
      TEST_ENV: "stage2_cloud"
      DB_HOST: "test-db"
      DB_PORT: "5432"
      DB_NAME: "anime_test_db"
      DB_USER: "postgres"
      DB_PASSWORD: "test_password"
      API_BASE_URL: "http://test-api:8001"
      PLAYWRIGHT_BASE_URL: "http://test-frontend:5173"
    depends_on:
      - test-db
    command: ["python", "test/run_suite.py"]
```

### C. CI Workflow Step
In GitHub Actions:
```yaml
- name: Run Unified Test Suite
  env:
    PYTHONIOENCODING: "utf-8"
    TEST_ENV: "ci"
    DB_HOST: "localhost"
    DB_PORT: "5432"
    DB_NAME: "anime_db"
  run: |
    python test/run_suite.py --cov
```

---

## 5. Automated Hygiene and Verification Gate

Before committing any changes to the test directory or application code, execute the repository hygiene audit:
```bash
python scripts/check_hygiene.py
```
This check ensures that no temporary, leftover, or superseded files (such as `_old`, `_new`, `_tmp`, or unused shims) are introduced into the codebase.
