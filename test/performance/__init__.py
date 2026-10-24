"""
test/performance/__init__.py

Performance and latency benchmark suite for the anime recommender service.
Provides configurable performance thresholds loaded from environment variables
with sensible default values conforming to SLA requirements.
"""

import os
from dataclasses import dataclass


def _parse_float_env(var_name: str, fallback: float) -> float:
    """
    Safely parses a floating point environment variable with a resilient fallback.
    Returns the fallback if the variable is unset, empty, or non-numeric.
    """
    raw = os.getenv(var_name)
    if raw is None:
        return fallback
    try:
        parsed = float(raw.strip())
        return parsed if parsed > 0.0 else fallback
    except (ValueError, TypeError):
        return fallback


def _parse_int_env(var_name: str, fallback: int) -> int:
    """
    Safely parses an integer environment variable with a resilient fallback.
    Returns the fallback if the variable is unset, empty, or non-numeric.
    """
    raw = os.getenv(var_name)
    if raw is None:
        return fallback
    try:
        parsed = int(raw.strip())
        return parsed if parsed > 0 else fallback
    except (ValueError, TypeError):
        return fallback


@dataclass(frozen=True)
class PerformanceThresholds:
    """
    Configurable latency, throughput, and bundle budgets for performance testing.
    All thresholds default to agreed local baselines unless overridden in the environment.
    """
    recommend_p95_ms: float
    chat_ttft_ms: float
    load_concurrency: int
    dev_keys_p95_ms: float
    frontend_nav_ms: float
    frontend_bundle_kb: float

    @classmethod
    def load(cls) -> "PerformanceThresholds":
        """
        Constructs threshold configuration by reading active environment variables
        with strict type validation and fallbacks.
        """
        return cls(
            recommend_p95_ms=_parse_float_env("PERF_RECOMMEND_P95_MS", 1000.0),
            chat_ttft_ms=_parse_float_env("PERF_CHAT_TTFT_MS", 1500.0),
            load_concurrency=_parse_int_env("PERF_LOAD_CONCURRENCY", 10),
            dev_keys_p95_ms=_parse_float_env("PERF_DEV_KEYS_P95_MS", 200.0),
            frontend_nav_ms=_parse_float_env("PERF_FRONTEND_NAV_MS", 3000.0),
            frontend_bundle_kb=_parse_float_env("PERF_FRONTEND_BUNDLE_KB", 650.0),
        )


def get_performance_config() -> PerformanceThresholds:
    """
    Helper function returning current performance thresholds from the environment.
    """
    return PerformanceThresholds.load()


__all__ = [
    "PerformanceThresholds",
    "get_performance_config",
]
