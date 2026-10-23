"""
test/conftest.py

Root pytest configuration, environment safety guards, and shared fixtures
for the anime recommender test suite.
"""

import os
import pytest
from urllib.parse import urlparse


def pytest_configure(config):
    """
    Safety Guard: refuse test execution if the configured database or base URL
    does not look like an isolated local test target.
    """
    # 1. Database Host and URL Validation
    db_host = os.environ.get("DB_HOST", "localhost").strip()
    db_name = os.environ.get("DB_NAME", "anime_db").strip()
    db_url = os.environ.get("DATABASE_URL", "").strip()
    archiver_host = os.environ.get("ARCHIVER_DB_HOST", db_host).strip()

    # Forbidden production indicators
    forbidden_host_patterns = [
        "supabase.co",
        "pooler.supabase.com",
        "aws-1-eu-north-1",
        "neon.tech",
        "rds.amazonaws.com",
    ]

    for pattern in forbidden_host_patterns:
        if pattern in db_host.lower():
            pytest.exit(
                f"SAFETY GUARD REFUSAL: Configured DB_HOST ({db_host}) matches forbidden production "
                f"pattern '{pattern}'. Tests must target an isolated local test database.",
                returncode=3,
            )
        if pattern in archiver_host.lower():
            pytest.exit(
                f"SAFETY GUARD REFUSAL: Configured ARCHIVER_DB_HOST ({archiver_host}) matches forbidden "
                f"production pattern '{pattern}'. Tests must target an isolated local test database.",
                returncode=3,
            )
        if db_url and pattern in db_url.lower():
            pytest.exit(
                f"SAFETY GUARD REFUSAL: Configured DATABASE_URL matches forbidden production pattern "
                f"'{pattern}'. Tests must target an isolated local test database.",
                returncode=3,
            )

    # 2. Base URL Validation
    modal_api_url = os.environ.get("MODAL_API_URL", "").strip()
    api_base_url = os.environ.get("API_BASE_URL", "").strip()

    for url_val, var_name in [(modal_api_url, "MODAL_API_URL"), (api_base_url, "API_BASE_URL")]:
        if url_val:
            parsed = urlparse(url_val)
            hostname = (parsed.hostname or "").lower()
            allowed_hosts = {"localhost", "127.0.0.1", "testserver"}
            if hostname and hostname not in allowed_hosts:
                pytest.exit(
                    f"SAFETY GUARD REFUSAL: Configured {var_name} ({url_val}) targets remote host "
                    f"'{hostname}'. Tests must target local services (localhost, 127.0.0.1, or testserver).",
                    returncode=3,
                )
