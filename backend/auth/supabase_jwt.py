# backend/auth/supabase_jwt.py
"""
Supabase Auth JWKS verification service and FastAPI dependencies.

Features:
- Pinned to asymmetric ES256 and RS256 algorithms (strictly rejecting alg=none and HS256).
- Validates exp, iat, sub, aud='authenticated', iss=<SUPABASE_URL>/auth/v1, and role='authenticated'.
- Restricts authorisation claims exclusively to app_metadata (ignoring user_metadata).
- Supports Supabase Anonymous Sign-In JWTs via app_metadata.is_anonymous.
- 10-minute JWKS caching with rate-limited refresh on unknown kid (at most once every 30s).
- Session freshness barrier (<15m) for sensitive credential operations.
"""

import os
import time
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient, PyJWKClientError
from fastapi import Request, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger("anime_recommender.auth.jwt")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://xyzcompany.supabase.co")
DEFAULT_JWKS_URL = f"{SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
DEFAULT_ISSUER = f"{SUPABASE_URL.rstrip('/')}/auth/v1"

# Allowed asymmetric algorithms strictly pinned
ALLOWED_ALGORITHMS = ["ES256", "RS256"]

# Security scheme for FastAPI
http_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class DevUserContext:
    """Authenticated Supabase identity (developer or user)."""
    user_id: str
    email: Optional[str]
    role: str
    iat: int
    app_metadata: Dict[str, Any]
    is_anonymous: bool = False


class SupabaseJWKSService:
    """
    Manages JWKS public key resolution and JWT validation with
    caching and anti-amplification rate-limiting.
    """

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        jwks_url: Optional[str] = None,
        jwks_cache_ttl: int = 600,
        jwks_client: Optional[PyJWKClient] = None
    ):
        self.supabase_url = (supabase_url or SUPABASE_URL).rstrip("/")
        self.jwks_url = jwks_url or f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
        self.issuer = f"{self.supabase_url}/auth/v1"
        self._last_jwks_refresh_ts = 0.0

        if jwks_client is not None:
            self._jwks_client = jwks_client
        else:
            try:
                self._jwks_client = PyJWKClient(self.jwks_url, cache_jwk_set=True, lifespan=jwks_cache_ttl)
            except Exception as e:
                logger.warning(f"[SupabaseJWKSService] Failed to initialise PyJWKClient: {e}")
                self._jwks_client = None

    def get_signing_key_from_jwt(self, token: str):
        """Resolves signing key from token header with rate-limited cache refetch."""
        if not self._jwks_client:
            raise RuntimeError("JWKS client is not initialised.")

        now = time.time()
        try:
            return self._jwks_client.get_signing_key_from_jwt(token)
        except PyJWKClientError:
            # Refresh only if 30s have elapsed since last refresh
            if now - self._last_jwks_refresh_ts > 30:
                self._last_jwks_refresh_ts = now
                self._jwks_client = PyJWKClient(self.jwks_url, cache_jwk_set=True, lifespan=600)
                return self._jwks_client.get_signing_key_from_jwt(token)
            raise

    def verify_token(self, token: str, require_fresh: bool = False) -> DevUserContext:
        """
        Validates token signature and required claims.
        Enforces:
        - alg IN ('ES256', 'RS256')
        - aud == 'authenticated'
        - iss == issuer
        - role == 'authenticated' (not anon)
        - freshness check if require_fresh is True
        """
        if not token:
            raise ValueError("Token missing.")

        # 1. Inspect unverified header for algorithm pinning
        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as e:
            raise ValueError(f"Invalid token header: {e}") from e

        alg = unverified_header.get("alg")
        if alg not in ALLOWED_ALGORITHMS:
            logger.warning(f"[SupabaseJWT] Rejected forbidden token algorithm: {alg}")
            raise ValueError(f"Algorithm '{alg}' is not permitted. Pinned to ES256/RS256.")

        # 2. Resolve signing public key
        try:
            signing_key = self.get_signing_key_from_jwt(token)
            key_data = signing_key.key
        except Exception as e:
            logger.warning(f"[SupabaseJWT] Public signing key resolution failed: {e}")
            raise ValueError("Invalid token signature or unknown key identifier.") from e

        # 3. Decode & Verify Token Claims
        try:
            payload = jwt.decode(
                token,
                key=key_data,
                algorithms=ALLOWED_ALGORITHMS,
                audience="authenticated",
                issuer=self.issuer,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "require": ["exp", "iat", "sub", "aud", "iss"],
                }
            )
        except jwt.ExpiredSignatureError as e:
            raise ValueError("Token has expired.") from e
        except jwt.InvalidAudienceError as e:
            raise ValueError("Invalid audience claim.") from e
        except jwt.InvalidIssuerError as e:
            raise ValueError("Invalid issuer claim.") from e
        except Exception as e:
            raise ValueError(f"JWT verification failed: {e}") from e

        # 4. Strict Role Assertion
        token_role = payload.get("role")
        if token_role != "authenticated":
            raise ValueError(f"Forbidden token role: '{token_role}'. Must be 'authenticated'.")

        # 5. Freshness Barrier Check
        iat = payload.get("iat", 0)
        if require_fresh:
            age_seconds = time.time() - iat
            if age_seconds > 900:  # 15 minutes
                raise ValueError("Session is older than 15 minutes. Re-authentication required.")

        # 6. Extract role strictly from app_metadata (never user_metadata)
        app_meta = payload.get("app_metadata", {})
        user_role = app_meta.get("role", "user")
        is_anon = bool(
            app_meta.get("is_anonymous", False)
            or payload.get("is_anonymous", False)
            or app_meta.get("provider") == "anonymous"
        )

        return DevUserContext(
            user_id=str(payload["sub"]),
            email=payload.get("email"),
            role=user_role,
            iat=iat,
            app_metadata=app_meta,
            is_anonymous=is_anon,
        )


# Singleton instance
_supabase_jwks_service: Optional[SupabaseJWKSService] = None


def get_jwks_service() -> SupabaseJWKSService:
    global _supabase_jwks_service
    if _supabase_jwks_service is None:
        _supabase_jwks_service = SupabaseJWKSService()
    return _supabase_jwks_service


def set_jwks_service(service: SupabaseJWKSService) -> None:
    """Allows test fixtures to inject an in-memory mock JWKS service."""
    global _supabase_jwks_service
    _supabase_jwks_service = service


async def get_current_dev(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(http_bearer)
) -> DevUserContext:
    """
    FastAPI dependency: authenticates developer identity via Supabase JWT.
    Returns DevUserContext or raises uniform 401 HTTPException.
    Rejects anonymous sign-ins with 403 Forbidden.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Missing Bearer authentication token."}},
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials
    jwks = get_jwks_service()
    try:
        user_ctx = jwks.verify_token(token, require_fresh=False)
        if user_ctx.is_anonymous:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "forbidden", "message": "Anonymous users cannot access developer resources."}},
            )
        return user_ctx
    except ValueError as val_err:
        err_msg = str(val_err)
        err_code = "invalid_token"
        if "expired" in err_msg.lower():
            err_code = "token_expired"
        elif "re-authentication required" in err_msg.lower():
            err_code = "stale_token"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": err_code, "message": err_msg}},
            headers={"WWW-Authenticate": "Bearer"}
        )


async def get_fresh_current_dev(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(http_bearer)
) -> DevUserContext:
    """
    FastAPI dependency: enforces that JWT was issued within the last 15 minutes
    for sensitive state mutations (e.g., API key issuance).
    Rejects anonymous sign-ins with 403 Forbidden.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Missing Bearer authentication token."}},
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials
    jwks = get_jwks_service()
    try:
        user_ctx = jwks.verify_token(token, require_fresh=True)
        if user_ctx.is_anonymous:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "forbidden", "message": "Anonymous users cannot manage developer API keys."}},
            )
        return user_ctx
    except ValueError as val_err:
        err_msg = str(val_err)
        err_code = "invalid_token"
        if "expired" in err_msg.lower():
            err_code = "token_expired"
        elif "15 minutes" in err_msg.lower():
            err_code = "stale_token"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": err_code, "message": err_msg}},
            headers={"WWW-Authenticate": "Bearer"}
        )
