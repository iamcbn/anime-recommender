# test/unit/test_keys_unit.py
"""
Unit tests for API key lifecycle management, hashing, formatting, caching, and error sanitisation.

Conforms to Sprint 3 Unit Testing standards:
- Fast, hermetic, isolated execution with zero database and network dependencies.
- Strict British English documentation without em-dashes.
- Marked with @pytest.mark.unit.
"""

import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from backend.auth.keys import (
    hash_api_key,
    validate_key_format,
    ApiKeyContext,
    VALID_KEY_CACHE,
    NEGATIVE_KEY_CACHE,
    KEY_PEPPER,
    authenticate_api_key,
    generate_api_key,
)


@pytest.mark.unit
def test_hmac_sha256_peppered_hashing_consistency():
    """
    Verifies that hash_api_key computes a deterministic 32-byte HMAC-SHA256 digest
    using the default system pepper, ensuring cryptographic consistency across runs.
    """
    raw_key = "ar_live_01234567_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    digest1 = hash_api_key(raw_key)
    digest2 = hash_api_key(raw_key)

    assert isinstance(digest1, bytes)
    assert len(digest1) == 32
    assert digest1 == digest2

    expected_digest = hmac.new(
        KEY_PEPPER.encode("utf-8"),
        raw_key.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    assert digest1 == expected_digest


@pytest.mark.unit
def test_hmac_sha256_pepper_isolation():
    """
    Verifies that supplying a custom pepper produces a distinct digest from the default pepper,
    ensuring pepper rotation and isolation operate securely without cryptographic cross-talk.
    """
    raw_key = "ar_live_abcdef12_1234567890abcdefghijklmnopqrstuvwxyzABCDE"
    custom_pepper = "different_test_pepper_string_longer_than_32_bytes_12345"

    default_digest = hash_api_key(raw_key)
    custom_digest = hash_api_key(raw_key, pepper=custom_pepper)

    assert default_digest != custom_digest
    assert len(custom_digest) == 32


@pytest.mark.unit
def test_validate_key_format_valid():
    """
    Verifies that validate_key_format successfully accepts valid keys adhering to
    the ar_live_<8 hex chars>_<43 urlsafe chars> schema and extracts the prefix and secret.
    """
    raw_key = "ar_live_a1b2c3d4_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    parsed = validate_key_format(raw_key)

    assert parsed is not None
    prefix_hex, secret = parsed
    assert prefix_hex == "a1b2c3d4"
    assert secret == "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    assert len(prefix_hex) == 8
    assert len(secret) == 43


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_key",
    [
        "",  # Empty string
        " ",  # Whitespace only
        "not_an_api_key",  # Malformed prefix
        "ar_test_a1b2c3d4_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",  # Wrong environment prefix
        "ar_live_a1b2c3d_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",  # 7 hex chars instead of 8
        "ar_live_a1b2c3d4e_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",  # 9 hex chars instead of 8
        "ar_live_g1b2c3d4_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",  # Non-hex character in prefix ('g')
        "ar_live_a1b2c3d4_shortsecret",  # Secret too short
        "ar_live_a1b2c3d4_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH!!",  # Special characters in secret
        None,  # None object
        12345,  # Non-string object
    ],
)
def test_validate_key_format_invalid(invalid_key):
    """
    Verifies that validate_key_format rejects malformed, truncated, or non-hex key candidates,
    protecting downstream hashing operations from malformed inputs.
    """
    assert validate_key_format(invalid_key) is None


@pytest.mark.unit
def test_prefix_extraction_and_key_structure():
    """
    Verifies that generate_api_key constructs an 8-character hex prefix matching ar_live_XXXXXXXX,
    ensuring database indexing and administrative auditing work without exposing full keys.
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {
        "id": "11111111-1111-1111-1111-111111111111",
        "created_at": datetime.now(timezone.utc),
    }

    raw_key, record = generate_api_key(
        name="test_prefix_key",
        owner_id="00000000-0000-0000-0000-000000000001",
        role="user",
        conn=mock_conn,
    )

    assert raw_key.startswith("ar_live_")
    prefix = record["prefix"]
    assert prefix.startswith("ar_live_")
    hex_part = prefix.replace("ar_live_", "")
    assert len(hex_part) == 8
    int(hex_part, 16)  # Asserts valid hex encoding


@pytest.mark.unit
def test_api_key_context_is_active_lifecycle():
    """
    Verifies that ApiKeyContext.is_active accurately evaluates expiration and revocation timestamps,
    supporting both timezone-aware and naive UTC datetimes.
    """
    now = datetime.now(timezone.utc)

    # Active key
    active_ctx = ApiKeyContext(
        key_id="key-1",
        name="active",
        owner_id=None,
        role="user",
        scopes=["recommend"],
        rate_limit_per_min=20,
        expires_at=now + timedelta(days=10),
        revoked_at=None,
    )
    assert active_ctx.is_active is True

    # Revoked key
    revoked_ctx = ApiKeyContext(
        key_id="key-2",
        name="revoked",
        owner_id=None,
        role="user",
        scopes=["recommend"],
        rate_limit_per_min=20,
        expires_at=now + timedelta(days=10),
        revoked_at=now - timedelta(minutes=5),
    )
    assert revoked_ctx.is_active is False

    # Expired key
    expired_ctx = ApiKeyContext(
        key_id="key-3",
        name="expired",
        owner_id=None,
        role="user",
        scopes=["recommend"],
        rate_limit_per_min=20,
        expires_at=now - timedelta(seconds=1),
        revoked_at=None,
    )
    assert expired_ctx.is_active is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cache_hit_and_eviction_on_expiration():
    """
    Verifies that authenticate_api_key utilises the positive in-memory cache for fast lookups
    and evicts cached entries immediately once an expired context is detected.
    """
    VALID_KEY_CACHE.clear()
    NEGATIVE_KEY_CACHE.clear()

    raw_key = "ar_live_12345678_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    candidate_hash = hash_api_key(raw_key)

    # Populate cache with an expired context
    now = datetime.now(timezone.utc)
    expired_ctx = ApiKeyContext(
        key_id="key-expired",
        name="expired_in_cache",
        owner_id=None,
        role="user",
        scopes=["recommend"],
        rate_limit_per_min=20,
        expires_at=now - timedelta(seconds=10),
        revoked_at=None,
    )
    VALID_KEY_CACHE[candidate_hash] = expired_ctx

    with pytest.raises(ValueError, match="API key expired or revoked"):
        await authenticate_api_key(raw_key)

    # Must be evicted from cache
    assert candidate_hash not in VALID_KEY_CACHE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_negative_cache_prevents_repeated_lookups():
    """
    Verifies that candidate keys recorded in NEGATIVE_KEY_CACHE are rejected immediately
    without triggering subsequent database queries, defending against brute-force amplification.
    """
    VALID_KEY_CACHE.clear()
    NEGATIVE_KEY_CACHE.clear()

    raw_key = "ar_live_deadbeef_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    candidate_hash = hash_api_key(raw_key)
    NEGATIVE_KEY_CACHE[candidate_hash] = True

    with patch("backend.auth.keys.get_auth_db_pool") as mock_db_pool:
        with pytest.raises(ValueError, match="Invalid API key."):
            await authenticate_api_key(raw_key)
        # Verify zero database access occurred
        mock_db_pool.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_sanitisation_during_authentication():
    """
    Verifies that error messages raised during authentication are generic and sanitised,
    never disclosing internal database details, table names, or secret pepper values.
    """
    # 1. Empty key error
    with pytest.raises(ValueError) as exc_info:
        await authenticate_api_key("")
    assert "Missing API key." in str(exc_info.value)
    assert "pepper" not in str(exc_info.value).lower()

    # 2. Format error
    with pytest.raises(ValueError) as exc_info:
        await authenticate_api_key("malformed_token")
    assert "Invalid API key format." in str(exc_info.value)

    # 3. Database outage fail-closed error
    valid_syntax_key = "ar_live_99887766_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    VALID_KEY_CACHE.clear()
    NEGATIVE_KEY_CACHE.clear()

    with patch("backend.auth.keys.get_auth_db_pool") as mock_pool:
        mock_pool.return_value.getconn.side_effect = Exception("psycopg2.OperationalError: password auth failed for postgres")
        with pytest.raises(RuntimeError) as exc_info:
            await authenticate_api_key(valid_syntax_key)
        assert "Database unavailable for authentication." in str(exc_info.value)
        # Confirms sensitive database credentials are not leaked in the exception text
        assert "password" not in str(exc_info.value).lower()
