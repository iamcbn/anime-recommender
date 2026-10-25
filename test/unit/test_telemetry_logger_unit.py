# test/unit/test_telemetry_logger_unit.py
"""
Unit tests for telemetry logging, NumPy scalar conversions, NaN/Inf handling, IP hashing, and payload sanitisation.

Conforms to Sprint 3 Unit Testing standards:
- Fast, hermetic, isolated execution with zero database and network dependencies.
- Strict British English documentation without em-dashes.
- Marked with @pytest.mark.unit.
"""

import math
import numpy as np
import pytest

from backend.telemetry.logger import (
    sanitize_float,
    sanitize_for_json,
    strip_scores,
    extract_candidate_scores,
    hash_client_ip,
    sanitize_client_metadata,
    _sanitize_error_text,
    _normalize_endpoint,
    _normalize_source,
    STRIP_SCORE_FIELDS,
    MAX_USER_AGENT_CHARS,
    MAX_ERROR_CHARS,
)


@pytest.mark.unit
def test_numpy_scalar_and_array_conversions():
    """
    Verifies that sanitize_for_json and sanitize_float convert NumPy numeric scalars,
    boolean types, and ndarrays into standard JSON-compliant Python primitives.
    """
    # NumPy integers and floats
    np_int = np.int64(42)
    np_float = np.float32(3.14159)
    np_bool = np.bool_(True)
    np_arr = np.array([1, 2, 3], dtype=np.int32)

    assert isinstance(sanitize_for_json(np_int), int)
    assert sanitize_for_json(np_int) == 42

    assert isinstance(sanitize_for_json(np_float), float)
    assert pytest.approx(sanitize_for_json(np_float), rel=1e-4) == 3.14159

    assert isinstance(sanitize_for_json(np_bool), bool)
    assert sanitize_for_json(np_bool) is True

    assert sanitize_for_json(np_arr) == [1, 2, 3]

    # Test sanitize_float scalar conversion
    assert isinstance(sanitize_float(np_float), float)
    assert sanitize_float(np_int) == 42.0
    assert sanitize_float(np_bool) is None  # Booleans rejected by float sanitizer


@pytest.mark.unit
def test_nan_and_inf_truncation_to_none():
    """
    Verifies that NaN, positive infinity, and negative infinity values are converted
    to None by both sanitize_float and sanitize_for_json to prevent PostgreSQL JSONB serialization failures.
    """
    nan_val = float("nan")
    inf_val = float("inf")
    neg_inf_val = float("-inf")
    np_nan = np.nan

    assert sanitize_float(nan_val) is None
    assert sanitize_float(inf_val) is None
    assert sanitize_float(neg_inf_val) is None
    assert sanitize_float(np_nan) is None

    # Nested dictionary with NaNs and Infs
    nested = {
        "score": nan_val,
        "upper_bound": inf_val,
        "nested_list": [1.0, neg_inf_val, np_nan, 4.0],
    }
    sanitized = sanitize_for_json(nested)
    assert sanitized["score"] is None
    assert sanitized["upper_bound"] is None
    assert sanitized["nested_list"] == [1.0, None, None, 4.0]


@pytest.mark.unit
def test_privacy_preserving_ip_hashing():
    """
    Verifies that hash_client_ip produces a consistent 16-hex-character HMAC-SHA256
    digest, yields distinct hashes for different IPs, and handles empty or unknown values gracefully.
    """
    ip1 = "192.168.1.100"
    ip2 = "203.0.113.195"

    hash1 = hash_client_ip(ip1)
    hash2 = hash_client_ip(ip2)

    assert isinstance(hash1, str)
    assert len(hash1) == 16
    assert hash1 == hash_client_ip(ip1)  # Deterministic
    assert hash1 != hash2  # Distinct

    # Null, empty, and 'unknown' inputs
    assert hash_client_ip(None) is None
    assert hash_client_ip("") is None
    assert hash_client_ip("   ") is None
    assert hash_client_ip("unknown") is None
    assert hash_client_ip("UNKNOWN") is None


@pytest.mark.unit
def test_strip_scores_non_mutating_behaviour():
    """
    Verifies that strip_scores removes score fields from candidate dictionaries
    without mutating the original input dictionaries or candidate lists in place.
    """
    original_item = {
        "id": 101,
        "title_romaji": "Steins;Gate",
        "cross_encoder_score": 2.45,
        "final_rrf_score": 0.089,
        "retrieval_rrf_score": 0.045,
        "cosine_similarity": 0.88,
    }
    original_list = [dict(original_item)]

    stripped = strip_scores(original_list)

    assert len(stripped) == 1
    cleaned = stripped[0]
    assert "id" in cleaned
    assert "title_romaji" in cleaned

    # All score fields stripped
    for score_field in STRIP_SCORE_FIELDS:
        assert score_field not in cleaned

    # Input dictionary and list remain unmutated
    assert "cross_encoder_score" in original_list[0]
    assert original_list[0]["cross_encoder_score"] == 2.45


@pytest.mark.unit
def test_extract_candidate_scores_structure():
    """
    Verifies that extract_candidate_scores extracts a structured list of score
    dictionaries with Python floats and clean identifiers for telemetry recording.
    """
    results = [
        {
            "id": np.int64(5114),
            "cross_encoder_score": np.float32(3.12),
            "final_rrf_score": np.float64(0.098),
            "retrieval_rrf_score": 0.045,
            "title_romaji": "Fullmetal Alchemist",
        }
    ]

    extracted = extract_candidate_scores(results)
    assert len(extracted) == 1
    score_record = extracted[0]

    assert score_record["id"] == 5114
    assert isinstance(score_record["id"], int)
    assert isinstance(score_record["cross_encoder_score"], float)
    assert pytest.approx(score_record["cross_encoder_score"], rel=1e-3) == 3.12
    assert isinstance(score_record["final_rrf_score"], float)
    assert score_record["retrieval_rrf_score"] == 0.045
    assert "title_romaji" not in score_record


@pytest.mark.unit
def test_sanitize_client_metadata_raw_ip_removal():
    """
    Verifies that sanitize_client_metadata strips raw IP addresses from metadata,
    replaces them with a privacy-safe ip_hash, and truncates excessive user-agent strings.
    """
    meta_input = {
        "client_ip": "198.51.100.4",
        "x_forwarded_for": "198.51.100.4, 10.0.0.1",
        "browser": "Chrome",
        "user_agent": "A" * 500,
    }

    clean_meta = sanitize_client_metadata(meta_input, client_ip="198.51.100.4")

    # Raw IP keys must be eliminated
    assert "client_ip" not in clean_meta
    assert "x_forwarded_for" not in clean_meta
    assert "ip_hash" in clean_meta
    assert len(clean_meta["ip_hash"]) == 16
    assert clean_meta["browser"] == "Chrome"
    assert len(clean_meta["user_agent"]) <= MAX_USER_AGENT_CHARS


@pytest.mark.unit
def test_sanitize_error_text_secrets_redaction():
    """
    Verifies that _sanitize_error_text redacts Bearer tokens, live API keys,
    and OpenAI secret keys from error strings, truncating to 500 characters.
    """
    raw_error = (
        "Authorization failed for Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz.abc "
        "with key ar_live_a1b2c3d4_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG "
        "and OpenAI key sk-proj-1234567890abcdef1234567890"
    )

    sanitized = _sanitize_error_text(raw_error)

    assert "Bearer [REDACTED]" in sanitized
    assert "ar_live_" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
    assert "sk-proj-" not in sanitized
    assert "[REDACTED_OPENAI_KEY]" in sanitized
    assert len(sanitized) <= MAX_ERROR_CHARS


@pytest.mark.unit
def test_endpoint_and_source_normalization():
    """
    Verifies that _normalize_endpoint and _normalize_source conform inputs to
    PostgreSQL table CHECK constraints (endpoint and source allowed values).
    """
    assert _normalize_endpoint("/chat/") == "chat"
    assert _normalize_endpoint("recommend") == "recommend"
    assert _normalize_endpoint("admin/recommend") == "admin_recommend"
    assert _normalize_endpoint(None) == "recommend"

    assert _normalize_source("admin_eval", "admin_recommend") == "admin_eval"
    assert _normalize_source("user", "recommend") == "user"
    assert _normalize_source(None, "admin_recommend") == "admin_eval"
    assert _normalize_source(None, "chat") == "user"


@pytest.mark.unit
def test_decimal_and_float_integer_sanitisation():
    """
    Verifies that sanitize_for_json correctly converts Decimal instances and
    floating point numbers with integer values into Python ints, while preserving
    fractional values and converting NaN/Inf Decimals to None.
    """
    from decimal import Decimal

    assert sanitize_for_json(Decimal("42.0")) == 42
    assert isinstance(sanitize_for_json(Decimal("42.0")), int)

    assert sanitize_for_json(Decimal("42.5")) == 42.5
    assert isinstance(sanitize_for_json(Decimal("42.5")), float)

    assert sanitize_for_json(Decimal("NaN")) is None
    assert sanitize_for_json(Decimal("Infinity")) is None
    assert sanitize_for_json(Decimal("-Infinity")) is None

    # Floats with whole number values converted to int
    assert sanitize_for_json(100.0) == 100
    assert isinstance(sanitize_for_json(100.0), int)

    # Floats with fractional values preserved as float
    assert sanitize_for_json(100.75) == 100.75
    assert isinstance(sanitize_for_json(100.75), float)
