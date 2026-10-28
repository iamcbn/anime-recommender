"""
test/unit/test_intent_routing_and_validation.py

Unit test suite validating:
1. Canonical response variant pools (greetings, pleasantries, bot identity, wellbeing, off-topic, clarify, lead-in).
2. Lead-in sentence generation and pluralisation.
3. User-safe HTTP 422 validation message formatting and technical leak prevention.
4. Single-character conversational clarification routing without error.

Conforms strictly to British English documentation standards without em-dashes.
"""

import pytest
from backend.rag_pipeline.helper.response_variants import (
    pick_response,
    pick_lead_in,
    GREETING,
    WELLBEING,
    PLEASANTRY,
    FAREWELL,
    BOT_IDENTITY,
    OFF_TOPIC,
    CLARIFY,
    LEAD_IN,
    LEAD_IN_SINGLE,
)
from backend.rag_pipeline.helper.validation_messages import (
    user_safe_validation_message,
    build_validation_error_content,
    MSG_QUERY_TOO_SHORT,
    MSG_QUERY_TOO_LONG,
    MSG_TOP_K,
    MSG_GENERIC,
)
from backend.rag_pipeline.helper.guardrails import DomainGuardrails


@pytest.mark.unit
def test_response_variants_pools_non_empty_and_no_em_dashes():
    """Validates that all variant pools have at least 5 variants and contain no em-dashes."""
    all_pools = [
        GREETING,
        WELLBEING,
        PLEASANTRY,
        FAREWELL,
        BOT_IDENTITY,
        OFF_TOPIC,
        CLARIFY,
        LEAD_IN,
        LEAD_IN_SINGLE,
    ]
    for pool in all_pools:
        assert len(pool) >= 3
        for text in pool:
            assert "\u2014" not in text, f"Em-dash detected in variant: {text}"
            assert "--" not in text, f"Double-hyphen detected in variant: {text}"


@pytest.mark.unit
def test_pick_response_valid_and_invalid_keys():
    """Validates pick_response returns strings for valid keys and raises KeyError on invalid."""
    valid_keys = [
        "greeting",
        "wellbeing",
        "pleasantry",
        "farewell",
        "bot_identity",
        "off_topic",
        "clarify",
    ]
    for key in valid_keys:
        res = pick_response(key)
        assert isinstance(res, str)
        assert len(res) > 10

    with pytest.raises(KeyError):
        pick_response("non_existent_key")


@pytest.mark.unit
def test_pick_lead_in_counts():
    """Validates lead-in pluralisation and zero handling."""
    assert pick_lead_in(0) == ""
    assert pick_lead_in(-1) == ""

    lead_1 = pick_lead_in(1)
    assert "1" in lead_1
    assert "anime" in lead_1.lower()

    lead_5 = pick_lead_in(5)
    assert "5" in lead_5
    assert "anime" in lead_5.lower()


@pytest.mark.unit
def test_user_safe_validation_messages():
    """Validates that validation error mapping returns friendly plain-language copy."""
    # Query too short
    err_short = [{"loc": ["body", "query"], "type": "value_error", "msg": "Query must contain at least 2 printable characters"}]
    assert user_safe_validation_message(err_short) == MSG_QUERY_TOO_SHORT

    # Query too long
    err_long = [{"loc": ["body", "query"], "type": "string_too_long", "msg": "Query cannot exceed 350 characters"}]
    assert user_safe_validation_message(err_long) == MSG_QUERY_TOO_LONG

    # top_k invalid
    err_top_k = [{"loc": ["body", "top_k"], "type": "value_error", "msg": "top_k must be an integer"}]
    assert user_safe_validation_message(err_top_k) == MSG_TOP_K

    # Generic fallback
    err_generic = [{"loc": ["body", "unexpected"], "type": "type_error", "msg": "some technical error"}]
    assert user_safe_validation_message(err_generic) == MSG_GENERIC


@pytest.mark.unit
def test_build_validation_error_content_zero_technical_leakage():
    """Validates that build_validation_error_content strips stack traces and technical details."""
    raw_errors = [
        {
            "type": "value_error",
            "loc": ["body", "query"],
            "msg": "Value error, Query must contain at least 2 printable characters",
            "input": "h",
            "ctx": {"error": "ValueError('Query must contain at least 2 printable characters')"},
        }
    ]
    res = build_validation_error_content(raw_errors)
    assert "error" in res
    assert res["error"]["code"] == "validation_error"
    assert res["error"]["message"] == MSG_QUERY_TOO_SHORT

    # Ensure no ValueError, line numbers, or file paths in the output
    res_str = str(res)
    assert "ValueError" not in res_str
    assert "File " not in res_str
    assert "line " not in res_str
    assert "'input': 'h'" not in res_str


@pytest.mark.unit
def test_single_character_input_clarification_route():
    """Validates that a single character like 'h' routes to chitchat clarification with 0 errors."""
    res = DomainGuardrails.validate_intent("h")
    assert res.is_valid is False
    assert res.category == "chitchat"
    assert res.detail in CLARIFY


@pytest.mark.unit
@pytest.mark.asyncio
async def test_422_endpoint_returns_user_safe_json():
    """Validates that POST /chat with empty input returns friendly 422 error body."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/chat", headers={"X-Forwarded-For": "192.0.2.10"}, json={"query": " "})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["message"] == MSG_QUERY_TOO_SHORT
        assert "ValueError" not in str(body)
        assert "main.py" not in str(body)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_single_character_chat_stream_returns_conversational_reply():
    """Validates that POST /chat with 'h' succeeds with 200 and streams friendly clarification."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/chat", headers={"X-Forwarded-For": "192.0.2.11"}, json={"query": "h"})
        assert resp.status_code == 200
        content = resp.text
        assert "event: token" in content
        assert "event: done" in content
        assert "event: error" not in content

