# backend/rag_pipeline/helper/llm_clients.py
"""
Centralized LLM Client Factory with Per-Layer Key Isolation (Sprint 7).

Provides independent AsyncOpenAI clients for each pipeline layer:
1. "nli"          -> OPENAI_API_KEY_NLI
2. "retrieval"    -> OPENAI_API_KEY_RETRIEVAL (HyDE expansion)
3. "presentation" -> OPENAI_API_KEY_PRESENTATION (Taste concierge pitch)

If a layer-specific key is missing, falls back cleanly to OPENAI_API_KEY
with a startup warning log to maintain 100% backward compatibility.
"""

import os
import logging
from typing import Literal, Optional, Dict
import httpx
from openai import OpenAI, AsyncOpenAI

logger = logging.getLogger("anime_recommender.llm_clients")

LayerName = Literal["nli", "retrieval", "presentation"]

LAYER_ENV_VARS: Dict[LayerName, str] = {
    "nli": "OPENAI_API_KEY_NLI",
    "retrieval": "OPENAI_API_KEY_RETRIEVAL",
    "presentation": "OPENAI_API_KEY_PRESENTATION",
}

# Module-level cached clients and connection pools
_async_http_client: Optional[httpx.AsyncClient] = None
_sync_http_client: Optional[httpx.Client] = None


def get_shared_async_http_client() -> httpx.AsyncClient:
    """Returns a shared, bounded async HTTP client to avoid socket leaks."""
    global _async_http_client
    if _async_http_client is None or _async_http_client.is_closed:
        _async_http_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            timeout=httpx.Timeout(15.0, connect=3.0),
        )
    return _async_http_client


def get_shared_sync_http_client() -> httpx.Client:
    """Returns a shared, bounded synchronous HTTP client."""
    global _sync_http_client
    if _sync_http_client is None or _sync_http_client.is_closed:
        _sync_http_client = httpx.Client(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=httpx.Timeout(10.0, connect=3.0),
        )
    return _sync_http_client


def resolve_layer_api_key(layer: LayerName, override_key: Optional[str] = None) -> Optional[str]:
    """
    Resolves the OpenAI API key for a specific layer.
    Precedence:
    1. override_key (if passed explicitly)
    2. OPENAI_API_KEY_<LAYER> (dedicated key for the layer)
    3. OPENAI_API_KEY (global fallback)
    """
    if override_key:
        return override_key.strip()

    env_var_name = LAYER_ENV_VARS.get(layer)
    if env_var_name:
        key = os.getenv(env_var_name)
        if key and key.strip():
            return key.strip()

    # Fallback to shared OPENAI_API_KEY
    shared_key = os.getenv("OPENAI_API_KEY")
    if shared_key and shared_key.strip():
        logger.warning(
            f"Layer '{layer}' specific key ({env_var_name}) not found. "
            f"Falling back to shared OPENAI_API_KEY."
        )
        return shared_key.strip()

    return None


def get_layer_client(
    layer: LayerName,
    override_key: Optional[str] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Optional[AsyncOpenAI]:
    """
    Factory creating an AsyncOpenAI client bound to the specific layer's API key.
    Returns None if no API key is configured.
    """
    api_key = resolve_layer_api_key(layer, override_key)
    if not api_key:
        return None

    client_http = http_client or get_shared_async_http_client()
    return AsyncOpenAI(api_key=api_key, http_client=client_http)


def get_sync_layer_client(
    layer: LayerName,
    override_key: Optional[str] = None,
    http_client: Optional[httpx.Client] = None,
) -> Optional[OpenAI]:
    """
    Factory creating a synchronous OpenAI client bound to the specific layer's API key.
    Returns None if no API key is configured.
    """
    api_key = resolve_layer_api_key(layer, override_key)
    if not api_key:
        return None

    client_http = http_client or get_shared_sync_http_client()
    return OpenAI(api_key=api_key, http_client=client_http)
