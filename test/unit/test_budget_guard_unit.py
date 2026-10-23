# test/unit/test_budget_guard_unit.py
"""
Unit tests for daily token ceiling, budget guard, layer/date isolation, and gpt-5.4-mini cost calculations.

Conforms to Sprint 3 Unit Testing standards:
- Fast, hermetic, isolated execution with zero database and network dependencies.
- Strict British English documentation without em-dashes.
- Marked with @pytest.mark.unit.
"""

import pytest

from backend.rag_pipeline.helper.budget_guard import (
    BudgetGuard,
    InMemoryBudgetStore,
    LayerBudgetStatus,
    get_budget_key,
)
from backend.routers.admin_usage import calculate_llm_cost


@pytest.fixture
def isolated_budget_guard():
    """Provides a fresh hermetic BudgetGuard instance with isolated in-memory storage."""
    limits = {
        "nli": 10000,
        "retrieval": 20000,
        "presentation": 30000,
    }
    guard = BudgetGuard(limits=limits, redis_client=None)
    guard.reset()
    return guard


@pytest.mark.unit
def test_in_memory_budget_store_primitives():
    """
    Verifies that InMemoryBudgetStore reliably performs get, incr, set, and reset
    operations without data corruption or memory leaks.
    """
    store = InMemoryBudgetStore()
    key = "usage:nli:2026-10-23"

    assert store.get(key) == 0

    assert store.incr(key, 500) == 500
    assert store.incr(key, 250) == 750
    assert store.get(key) == 750

    store.set(key, 1200)
    assert store.get(key) == 1200

    store.reset()
    assert store.get(key) == 0


@pytest.mark.unit
def test_budget_key_layer_and_date_formatting():
    """
    Verifies that get_budget_key generates canonical Redis keys in the format
    usage:<layer>:<YYYY-MM-DD> and rejects unknown layer identifiers.
    """
    key_nli = get_budget_key("nli", "2026-10-23")
    assert key_nli == "usage:nli:2026-10-23"

    key_retrieval = get_budget_key("RETRIEVAL", "2026-10-23")
    assert key_retrieval == "usage:retrieval:2026-10-23"

    key_presentation = get_budget_key("presentation", "2026-10-24")
    assert key_presentation == "usage:presentation:2026-10-24"

    with pytest.raises(ValueError, match="Invalid layer 'unknown'"):
        get_budget_key("unknown", "2026-10-23")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_per_layer_budget_isolation(isolated_budget_guard):
    """
    Verifies that token consumption in one pipeline layer (e.g. NLI) does not
    pollute or affect token consumption counters in other layers (Retrieval or Presentation).
    """
    date_str = "2026-10-23"

    await isolated_budget_guard.record_usage("nli", 4000, target_date=date_str)

    nli_usage = await isolated_budget_guard.get_usage("nli", target_date=date_str)
    retrieval_usage = await isolated_budget_guard.get_usage("retrieval", target_date=date_str)
    presentation_usage = await isolated_budget_guard.get_usage("presentation", target_date=date_str)

    assert nli_usage == 4000
    assert retrieval_usage == 0
    assert presentation_usage == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_date_budget_isolation(isolated_budget_guard):
    """
    Verifies that token usage recorded for one day does not carry over to subsequent
    days, ensuring daily token quotas reset cleanly across day boundaries.
    """
    layer = "nli"
    day1 = "2026-10-23"
    day2 = "2026-10-24"

    await isolated_budget_guard.record_usage(layer, 8500, target_date=day1)

    usage_day1 = await isolated_budget_guard.get_usage(layer, target_date=day1)
    usage_day2 = await isolated_budget_guard.get_usage(layer, target_date=day2)

    assert usage_day1 == 8500
    assert usage_day2 == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_soft_limit_and_hard_limit_boundaries(isolated_budget_guard):
    """
    Verifies that the soft limit (80%) and hard limit (100%) triggers engage at their
    exact percentage boundaries, transitioning through clean warning and hard exhaustion states.
    """
    layer = "nli"
    date_str = "2026-10-23"
    # Limit for nli is 10000 in isolated_budget_guard fixture
    # Soft limit is 80% = 8000 tokens

    # 1. Below soft limit (7900 tokens = 79%)
    await isolated_budget_guard.record_usage(layer, 7900, target_date=date_str)
    status_below = await isolated_budget_guard.check_budget_status(layer, date_str=date_str)
    assert status_below["current_usage"] == 7900
    assert status_below["soft_limit_hit"] is False
    assert status_below["hard_limit_hit"] is False
    assert status_below["remaining"] == 2100
    assert await isolated_budget_guard.is_soft_limit_exceeded(layer, date_str) is False
    assert await isolated_budget_guard.is_budget_exceeded(layer, date_str) is False

    # 2. At soft limit boundary (8000 tokens = 80%)
    await isolated_budget_guard.record_usage(layer, 100, target_date=date_str)
    status_soft = await isolated_budget_guard.check_budget_status(layer, date_str=date_str)
    assert status_soft["current_usage"] == 8000
    assert status_soft["soft_limit_hit"] is True
    assert status_soft["hard_limit_hit"] is False
    assert await isolated_budget_guard.is_soft_limit_exceeded(layer, date_str) is True
    assert await isolated_budget_guard.is_budget_exceeded(layer, date_str) is False

    # 3. At hard ceiling boundary (10000 tokens = 100%)
    await isolated_budget_guard.record_usage(layer, 2000, target_date=date_str)
    status_hard = await isolated_budget_guard.check_budget_status(layer, date_str=date_str)
    assert status_hard["current_usage"] == 10000
    assert status_hard["soft_limit_hit"] is True
    assert status_hard["hard_limit_hit"] is True
    assert status_hard["remaining"] == 0
    assert await isolated_budget_guard.is_budget_exceeded(layer, date_str) is True

    # 4. Synchronous check adheres to in-memory state
    assert isolated_budget_guard.is_budget_exceeded_sync(layer, date_str) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_layer_budget_status_pydantic_schema(isolated_budget_guard):
    """
    Verifies that get_layer_budget constructs a validated LayerBudgetStatus model
    with mathematically consistent consumption ratios and remaining counts.
    """
    layer = "retrieval"
    date_str = "2026-10-23"
    # retrieval limit: 20000

    await isolated_budget_guard.record_usage(layer, 15000, target_date=date_str)
    model: LayerBudgetStatus = await isolated_budget_guard.get_layer_budget(layer, target_date=date_str)

    assert model.layer == "retrieval"
    assert model.current_usage == 15000
    assert model.limit == 20000
    assert model.remaining == 5000
    assert model.soft_limit_hit is False  # 15000 / 20000 = 75% < 80%
    assert model.hard_limit_hit is False
    assert model.usage_ratio == 0.75


@pytest.mark.unit
def test_gpt_5_4_mini_cost_formula():
    """
    Verifies that calculate_llm_cost calculates accurate USD costs according to
    the standard gpt-5.4-mini pricing ($0.15 / 1M prompt tokens, $0.60 / 1M completion tokens).
    """
    # 1. Zero tokens
    assert calculate_llm_cost(0, 0) == 0.0

    # 2. 1,000,000 prompt tokens and 0 completion tokens = $0.15
    cost_prompt = calculate_llm_cost(1_000_000, 0)
    assert cost_prompt == 0.15

    # 3. 0 prompt tokens and 1,000,000 completion tokens = $0.60
    cost_completion = calculate_llm_cost(0, 1_000_000)
    assert cost_completion == 0.60

    # 4. Realistic request: 1,500 prompt tokens and 350 completion tokens
    # (1500 * 0.15 + 350 * 0.60) / 1,000,000 = (225 + 210) / 1,000,000 = 435 / 1,000,000 = 0.000435
    cost_mixed = calculate_llm_cost(1500, 350)
    assert cost_mixed == 0.000435

    # 5. Negative tokens guarded gracefully
    assert calculate_llm_cost(-100, -50) == 0.0
