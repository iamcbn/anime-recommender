"""
backend/rag_pipeline/helper/validation_messages.py

Single source of truth for the public body of HTTP 422 validation errors.
Technical detail (Pydantic messages, input echoes, exception reprs) is logged
server-side only and never returned to clients.
"""

import logging
from typing import Any, Dict, List, Mapping, Sequence

logger = logging.getLogger("anime_recommender.validation")

MSG_QUERY_TOO_SHORT = "Tell me a little more, such as a mood or a title."
MSG_QUERY_TOO_LONG = "That is a bit long. Please keep your request under 350 characters."
MSG_TOP_K = "Please ask for between 1 and 25 recommendations."
MSG_GENERIC = "Something in that request did not look right. Please try again."


def _field(error: Mapping[str, Any]) -> str:
    loc = error.get("loc") or ()
    return str(loc[-1]) if loc else ""


def _message_for(error: Mapping[str, Any]) -> str:
    field = _field(error)
    technical = f"{error.get('type', '')} {error.get('msg', '')}".lower()
    if field == "query":
        if "too_long" in technical or "exceed" in technical or "at most" in technical:
            return MSG_QUERY_TOO_LONG
        return MSG_QUERY_TOO_SHORT
    if field == "top_k":
        return MSG_TOP_K
    return MSG_GENERIC


def user_safe_validation_message(errors: Sequence[Mapping[str, Any]]) -> str:
    """Return one short plain-language message for the first validation error."""
    if not errors:
        return MSG_GENERIC
    return _message_for(errors[0])


def build_validation_error_content(errors: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build the JSON body for a 422 response.

    Keeps the existing envelope shape (`error.code`, `error.message`, `detail`)
    while stripping technical text. `detail` keeps only `loc` and `type` per
    error, so no `ValueError` text, input echo, file path, or line number leaks.
    """
    logger.warning("[Validation] Request rejected: %s", list(errors))
    safe_detail: List[Dict[str, Any]] = [
        {"loc": [str(part) for part in (e.get("loc") or ())], "type": str(e.get("type", "value_error"))}
        for e in errors
    ]
    return {
        "error": {"code": "validation_error", "message": user_safe_validation_message(errors)},
        "detail": safe_detail,
    }
