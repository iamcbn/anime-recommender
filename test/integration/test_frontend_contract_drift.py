"""
test/integration/test_frontend_contract_drift.py

Anti-drift contract test suite verifying alignment between backend Pydantic models
and canonical frontend TypeScript mock fixtures in frontend/src/test/contractMocks.ts:
1. Validates PublicRecommendResponse against mockRecommendResponse.
2. Validates KeyListResponse and KeyItem against mockDevKeysListResponse.
3. Validates CreateKeyResponse against mockDevKeyCreateResponse.
4. Validates LayerBudgetStatus against mockCurrentBudgetResponse.
5. Validates DailyUsageItem against mockDailyUsageResponse.
6. Validates RecommendationLog telemetry schema against mockTelemetryLogsResponse.
7. Validates that backend field modifications without updating frontend mocks trigger contract failures.

Conforms strictly to British English documentation standards without em-dashes.
"""

import os
import sys
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

# Ensure Windows standard stream encoding safely supports unicode logging
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.main import PublicRecommendResponse
from backend.routers.dev_keys import KeyListResponse, KeyItem, CreateKeyResponse
from backend.routers.admin_usage import DailyUsageItem
from backend.rag_pipeline.helper.budget_guard import LayerBudgetStatus


# ---------------------------------------------------------------------------
# CONTRACT FIXTURE EXTRACTOR
# ---------------------------------------------------------------------------

CONTRACT_MOCKS_PATH = ROOT_DIR / "frontend" / "src" / "test" / "contractMocks.ts"


def load_frontend_contract_mock(variable_name: str) -> Any:
    """
    Reads frontend/src/test/contractMocks.ts and parses the specified exported constant.
    The mock definitions are authored as valid JSON object or array literals.
    """
    if not CONTRACT_MOCKS_PATH.is_file():
        raise FileNotFoundError(f"Contract mocks file missing at: {CONTRACT_MOCKS_PATH}")

    content = CONTRACT_MOCKS_PATH.read_text(encoding="utf-8")
    pattern = rf"export\s+const\s+{re.escape(variable_name)}\s*:\s*[^=]+=\s*([\[{{].*?\n\s*[\]}}]);"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        raise ValueError(f"Could not extract exported mock '{variable_name}' from {CONTRACT_MOCKS_PATH}")

    json_text = match.group(1)
    return json.loads(json_text)


# ---------------------------------------------------------------------------
# ANTI-DRIFT CONTRACT TESTS
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.fullstack
def test_recommend_response_contract_matches_frontend_mock() -> None:
    """
    Verifies that mockRecommendResponse in contractMocks.ts adheres strictly to the backend
    PublicRecommendResponse schema including query, count, allowed_adult, and results array.

    This behaviour protects API contract fidelity between the recommendation engine and frontend
    chat components, preventing runtime rendering failures caused by backend field renames.
    """
    mock_data = load_frontend_contract_mock("mockRecommendResponse")

    # Validate against backend Pydantic model
    validated = PublicRecommendResponse.model_validate(mock_data)
    assert validated.query == mock_data["query"]
    assert validated.count == mock_data["count"]
    assert validated.allowed_adult == mock_data["allowed_adult"]
    assert len(validated.results) == len(mock_data["results"])

    # Verify exact field name alignment
    expected_fields = set(PublicRecommendResponse.model_fields.keys())
    actual_fields = set(mock_data.keys())
    assert actual_fields == expected_fields, (
        f"Contract drift detected in recommend response. Model fields: {expected_fields}, "
        f"Mock fields: {actual_fields}"
    )

    # Anti-drift guard: missing required field must fail validation
    tampered_data = dict(mock_data)
    del tampered_data["query"]
    with pytest.raises(ValidationError):
        PublicRecommendResponse.model_validate(tampered_data)


@pytest.mark.integration
@pytest.mark.fullstack
def test_dev_keys_list_contract_matches_frontend_mock() -> None:
    """
    Verifies that mockDevKeysListResponse adheres strictly to KeyListResponse and KeyItem models,
    guaranteeing that key identifier, prefix, lifecycle timestamps, and revocation state match.

    This behaviour protects the developer portal table from contract regressions when key metadata
    fields or date serialisation formats are updated in the backend.
    """
    mock_data = load_frontend_contract_mock("mockDevKeysListResponse")

    validated = KeyListResponse.model_validate(mock_data)
    assert len(validated.keys) == len(mock_data["keys"])

    # Verify KeyItem field names
    expected_item_fields = set(KeyItem.model_fields.keys())
    first_mock_item = mock_data["keys"][0]
    actual_item_fields = set(first_mock_item.keys())
    assert actual_item_fields == expected_item_fields, (
        f"Contract drift detected in KeyItem schema. Expected: {expected_item_fields}, "
        f"Found: {actual_item_fields}"
    )

    # Verify date parsing succeeds for ISO 8601 strings
    assert validated.keys[0].name == "Production Web App"
    assert validated.keys[0].prefix == "ar_live_a1b2c3d4"
    assert validated.keys[0].created_at is not None

    # Anti-drift guard: corrupting key type must fail validation
    tampered_data = {"keys": [{"id": "123", "name": "bad"}]}
    with pytest.raises(ValidationError):
        KeyListResponse.model_validate(tampered_data)


@pytest.mark.integration
@pytest.mark.fullstack
def test_dev_key_create_contract_matches_frontend_mock() -> None:
    """
    Verifies that mockDevKeyCreateResponse adheres strictly to backend CreateKeyResponse schema,
    guaranteeing that id, name, plaintext key, prefix, and created_at fields are aligned.

    This behaviour protects credential provisioning workflows, ensuring that one-time key revelation
    modals in the frontend accurately receive and display the newly generated secret.
    """
    mock_data = load_frontend_contract_mock("mockDevKeyCreateResponse")

    validated = CreateKeyResponse.model_validate(mock_data)
    assert validated.name == "Mobile Client Key"
    assert validated.key.startswith("ar_live_")
    assert validated.prefix == "ar_live_12345678"

    # Verify exact field name alignment
    expected_fields = set(CreateKeyResponse.model_fields.keys())
    actual_fields = set(mock_data.keys())
    assert actual_fields == expected_fields, (
        f"Contract drift detected in CreateKeyResponse. Expected: {expected_fields}, Found: {actual_fields}"
    )

    # Anti-drift guard: missing one-time key field must fail validation
    tampered_data = dict(mock_data)
    del tampered_data["key"]
    with pytest.raises(ValidationError):
        CreateKeyResponse.model_validate(tampered_data)


@pytest.mark.integration
@pytest.mark.fullstack
def test_current_budget_contract_matches_frontend_mock() -> None:
    """
    Verifies that mockCurrentBudgetResponse adheres strictly to the LayerBudgetStatus schema
    across all three pipeline layers (nli, retrieval, presentation).

    This behaviour protects administrative budget gauge visualisation, ensuring that threshold
    flags (soft_limit_hit, hard_limit_hit) and usage ratios are reliably transmitted without drift.
    """
    mock_data = load_frontend_contract_mock("mockCurrentBudgetResponse")

    expected_layers = {"nli", "retrieval", "presentation"}
    assert set(mock_data.keys()) == expected_layers, (
        f"Contract drift in budget layers. Expected: {expected_layers}, Found: {set(mock_data.keys())}"
    )

    for layer_name, layer_status in mock_data.items():
        validated_layer = LayerBudgetStatus.model_validate(layer_status)
        assert validated_layer.layer == layer_name
        assert validated_layer.limit > 0
        assert validated_layer.remaining >= 0
        assert isinstance(validated_layer.soft_limit_hit, bool)
        assert isinstance(validated_layer.hard_limit_hit, bool)
        assert 0.0 <= validated_layer.usage_ratio <= 1.0

        expected_fields = set(LayerBudgetStatus.model_fields.keys())
        actual_fields = set(layer_status.keys())
        assert actual_fields == expected_fields, (
            f"Contract drift in LayerBudgetStatus for layer '{layer_name}'. "
            f"Expected: {expected_fields}, Found: {actual_fields}"
        )

    # Anti-drift guard: missing soft_limit_hit must fail validation
    tampered_layer = dict(mock_data["nli"])
    del tampered_layer["soft_limit_hit"]
    with pytest.raises(ValidationError):
        LayerBudgetStatus.model_validate(tampered_layer)


@pytest.mark.integration
@pytest.mark.fullstack
def test_daily_usage_contract_matches_frontend_mock() -> None:
    """
    Verifies that mockDailyUsageResponse adheres strictly to backend DailyUsageItem schema,
    guaranteeing date format, layer identifiers, token metrics, cache counts, and estimated cost.

    This behaviour protects telemetry accounting and daily LLM usage reports from silent contract
    breakages when metric aggregations are expanded in backend routers.
    """
    mock_data = load_frontend_contract_mock("mockDailyUsageResponse")
    assert isinstance(mock_data, list)
    assert len(mock_data) >= 1

    expected_fields = set(DailyUsageItem.model_fields.keys())

    for item in mock_data:
        validated_item = DailyUsageItem.model_validate(item)
        assert validated_item.request_count >= 0
        assert validated_item.total_tokens >= (validated_item.prompt_tokens + validated_item.completion_tokens)
        assert validated_item.estimated_cost_usd >= 0.0

        actual_fields = set(item.keys())
        assert actual_fields == expected_fields, (
            f"Contract drift detected in DailyUsageItem. Expected: {expected_fields}, Found: {actual_fields}"
        )

    # Anti-drift guard: missing total_tokens must fail validation
    tampered_item = dict(mock_data[0])
    del tampered_item["total_tokens"]
    with pytest.raises(ValidationError):
        DailyUsageItem.model_validate(tampered_item)


@pytest.mark.integration
@pytest.mark.fullstack
def test_telemetry_logs_contract_matches_frontend_mock() -> None:
    """
    Verifies that mockTelemetryLogsResponse conforms to the canonical telemetry schema,
    containing required columns: request_id, endpoint, source, status, status_code, timings,
    candidate_scores, and client_metadata.

    This behaviour protects administrator telemetry inspection modals from undefined field access
    and ensures complete audit visibility across production queries.
    """
    mock_data = load_frontend_contract_mock("mockTelemetryLogsResponse")
    assert isinstance(mock_data, list)
    assert len(mock_data) >= 1

    required_columns = {
        "id",
        "request_id",
        "created_at",
        "endpoint",
        "source",
        "api_key_id",
        "session_id",
        "query",
        "top_k",
        "allow_adult",
        "results_count",
        "status",
        "status_code",
        "error",
        "total_ms",
        "timings",
        "candidate_scores",
        "client_metadata",
    }

    for log_record in mock_data:
        record_keys = set(log_record.keys())
        missing = required_columns - record_keys
        assert not missing, f"Contract drift detected: telemetry log missing canonical columns: {missing}"
        assert log_record["endpoint"] in {"recommend", "chat", "admin_recommend"}
        assert log_record["source"] in {"user", "admin_eval"}
        assert isinstance(log_record["status_code"], int) or log_record["status_code"] is None
        assert isinstance(log_record["results_count"], int)
