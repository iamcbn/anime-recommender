# test/unit/test_jwt_unit.py
"""
Unit tests for Supabase JWT verification, claim extraction, role validation, and freshness barriers.

Conforms to Sprint 3 Unit Testing standards:
- Fast, hermetic, isolated execution with zero database and network dependencies.
- Strict British English documentation without em-dashes.
- Marked with @pytest.mark.unit.
"""

import time
from unittest.mock import MagicMock
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.auth.supabase_jwt import (
    SupabaseJWKSService,
    set_jwks_service,
    get_current_dev,
    get_fresh_current_dev,
)


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generates an in-memory 2048-bit RSA keypair for hermetic JWT signing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def mock_jwks_service(rsa_keypair):
    """
    Creates a hermetic SupabaseJWKSService with an in-memory mock PyJWKClient
    that serves the RSA public key without network access.
    """
    _, public_key = rsa_keypair
    service = SupabaseJWKSService(
        supabase_url="https://xyzcompany.supabase.co",
        jwks_url="https://xyzcompany.supabase.co/auth/v1/.well-known/jwks.json",
    )

    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    service._jwks_client = mock_client
    set_jwks_service(service)
    return service


def create_token(
    private_key,
    payload_overrides=None,
    headers_overrides=None,
    algorithm="RS256",
):
    """Helper to generate RS256/custom JWTs for unit testing."""
    now = int(time.time())
    payload = {
        "sub": "00000000-0000-0000-0000-000000000001",
        "email": "developer@example.com",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": "https://xyzcompany.supabase.co/auth/v1",
        "iat": now,
        "exp": now + 3600,
        "app_metadata": {"role": "developer"},
        "user_metadata": {"role": "user"},
    }
    if payload_overrides:
        payload.update(payload_overrides)

    headers = {"kid": "mock-test-key-id"}
    if headers_overrides:
        headers.update(headers_overrides)

    return jwt.encode(payload, private_key, algorithm=algorithm, headers=headers)


@pytest.mark.unit
def test_rs256_signature_verification_and_claim_extraction(rsa_keypair, mock_jwks_service):
    """
    Verifies that SupabaseJWKSService verifies an RS256 token against the resolved public key,
    successfully extracting user identifier, email, issued-at timestamp, and app metadata.
    """
    private_key, _ = rsa_keypair
    token = create_token(
        private_key,
        payload_overrides={
            "sub": "user-uuid-1234",
            "email": "dev@recommender.co.uk",
            "app_metadata": {"role": "developer", "provider": "email"},
        },
    )

    ctx = mock_jwks_service.verify_token(token)

    assert ctx.user_id == "user-uuid-1234"
    assert ctx.email == "dev@recommender.co.uk"
    assert ctx.role == "developer"
    assert ctx.app_metadata.get("provider") == "email"
    assert ctx.iat > 0


@pytest.mark.unit
def test_role_validation_strictly_from_app_metadata(rsa_keypair, mock_jwks_service):
    """
    Verifies that user role authorization claims are drawn exclusively from app_metadata.role
    and that spoofed role attributes injected into user_metadata are strictly ignored.
    """
    private_key, _ = rsa_keypair

    # Scenario A: Legitimate admin with role in app_metadata
    admin_token = create_token(
        private_key,
        payload_overrides={
            "app_metadata": {"role": "admin"},
            "user_metadata": {"role": "user"},
        },
    )
    admin_ctx = mock_jwks_service.verify_token(admin_token)
    assert admin_ctx.role == "admin"

    # Scenario B: Spoofed admin in user_metadata with non-admin app_metadata
    spoofed_token = create_token(
        private_key,
        payload_overrides={
            "app_metadata": {"role": "user"},
            "user_metadata": {"role": "admin"},
        },
    )
    spoofed_ctx = mock_jwks_service.verify_token(spoofed_token)
    assert spoofed_ctx.role == "user"


@pytest.mark.unit
def test_top_level_role_assertion(rsa_keypair, mock_jwks_service):
    """
    Verifies that tokens possessing a top-level role other than 'authenticated'
    (such as anonymous visitor tokens with role='anon') are rejected.
    """
    private_key, _ = rsa_keypair
    anon_token = create_token(
        private_key,
        payload_overrides={"role": "anon"},
    )

    with pytest.raises(ValueError, match="Forbidden token role: 'anon'"):
        mock_jwks_service.verify_token(anon_token)


@pytest.mark.unit
def test_expired_token_rejection(rsa_keypair, mock_jwks_service):
    """
    Verifies that tokens whose expiration timestamp has passed are rejected
    with a clear ExpiredSignatureError message.
    """
    private_key, _ = rsa_keypair
    now = int(time.time())
    expired_token = create_token(
        private_key,
        payload_overrides={
            "iat": now - 7200,
            "exp": now - 3600,
        },
    )

    with pytest.raises(ValueError, match="Token has expired."):
        mock_jwks_service.verify_token(expired_token)


@pytest.mark.unit
def test_algorithm_confusion_rejection(rsa_keypair, mock_jwks_service):
    """
    Verifies that algorithm confusion attacks (such as alg='none' or symmetric alg='HS256')
    are blocked by strict algorithm pinning prior to verification.
    """
    private_key, _ = rsa_keypair

    # 1. Reject alg=none
    none_token = jwt.encode(
        {"sub": "attacker", "role": "authenticated", "aud": "authenticated", "iss": mock_jwks_service.issuer, "iat": int(time.time()), "exp": int(time.time()) + 3600},
        key="",
        algorithm="none",
    )
    with pytest.raises(ValueError, match="Algorithm 'none' is not permitted"):
        mock_jwks_service.verify_token(none_token)

    # 2. Reject alg=HS256
    hs_token = jwt.encode(
        {"sub": "attacker", "role": "authenticated", "aud": "authenticated", "iss": mock_jwks_service.issuer, "iat": int(time.time()), "exp": int(time.time()) + 3600},
        key="symmetric_secret_key_used_in_confusion_attack",
        algorithm="HS256",
    )
    with pytest.raises(ValueError, match="Algorithm 'HS256' is not permitted"):
        mock_jwks_service.verify_token(hs_token)


@pytest.mark.unit
def test_freshness_barrier_enforcement(rsa_keypair, mock_jwks_service):
    """
    Verifies that get_fresh_current_dev rejects sessions issued more than 15 minutes ago,
    ensuring sensitive operations demand recent user re-authentication.
    """
    private_key, _ = rsa_keypair
    now = int(time.time())

    # Stale token: issued 16 minutes (960s) ago, but still unexpired (exp valid for 1 hour)
    stale_token = create_token(
        private_key,
        payload_overrides={
            "iat": now - 960,
            "exp": now + 2640,
        },
    )

    # Normal verification passes
    ctx = mock_jwks_service.verify_token(stale_token, require_fresh=False)
    assert ctx.user_id is not None

    # Freshness verification fails
    with pytest.raises(ValueError, match="Session is older than 15 minutes"):
        mock_jwks_service.verify_token(stale_token, require_fresh=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fastapi_dependencies_bearer_extraction_and_error_codes(rsa_keypair, mock_jwks_service):
    """
    Verifies that get_current_dev and get_fresh_current_dev extract tokens properly
    and raise uniform HTTP 401 status exceptions with structured error codes.
    """
    private_key, _ = rsa_keypair
    mock_request = MagicMock()

    # 1. Missing credentials
    with pytest.raises(HTTPException) as exc_info:
        await get_current_dev(mock_request, credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "unauthorized"

    # 2. Valid credentials
    valid_token = create_token(private_key)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=valid_token)
    ctx = await get_current_dev(mock_request, credentials=creds)
    assert ctx.user_id == "00000000-0000-0000-0000-000000000001"

    # 3. Expired token raises 401 with token_expired
    now = int(time.time())
    expired_token = create_token(
        private_key,
        payload_overrides={"iat": now - 7200, "exp": now - 3600},
    )
    with pytest.raises(HTTPException) as exc_info:
        await get_current_dev(mock_request, credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired_token))
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "token_expired"

    # 4. Stale token in get_fresh_current_dev raises 401 with stale_token
    stale_token = create_token(
        private_key,
        payload_overrides={"iat": now - 1000, "exp": now + 2600},
    )
    with pytest.raises(HTTPException) as exc_info:
        await get_fresh_current_dev(mock_request, credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=stale_token))
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "stale_token"
