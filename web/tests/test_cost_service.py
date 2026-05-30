"""Tests for cost_service: calculation correctness, cap enforcement, monthly increment."""
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from .conftest import make_db_chain, make_multi_table_db


def _make_monthly_row(total: float):
    return [{"id": "row-1", "total_cost_usd": str(total)}]


# ── _compute_cost ─────────────────────────────────────────────────────────────

def test_compute_cost_correctness():
    from web.services.cost_service import _compute_cost
    # 1M of each token type
    cost = _compute_cost(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_write_tokens=1_000_000,
    )
    expected = 3.00 + 15.00 + 0.30 + 3.75  # = 22.05
    assert abs(cost - expected) < 1e-9


def test_compute_cost_zero_tokens():
    from web.services.cost_service import _compute_cost
    assert _compute_cost(0, 0, 0, 0) == 0.0


def test_compute_cost_cache_read_cheaper_than_input():
    from web.services.cost_service import _compute_cost
    input_cost = _compute_cost(1_000_000, 0, 0, 0)
    cache_read_cost = _compute_cost(0, 0, 1_000_000, 0)
    assert cache_read_cost < input_cost


# ── check_cost_cap ────────────────────────────────────────────────────────────

async def test_cost_cap_passes_when_under_limit():
    client, _ = make_db_chain(data=[{"total_cost_usd": "5.00"}])
    with patch("web.services.cost_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.cost_service import check_cost_cap
        await check_cost_cap("user-1")  # should not raise


async def test_cost_cap_raises_429_when_at_limit():
    client, _ = make_db_chain(data=[{"total_cost_usd": "8.00"}])
    with patch("web.services.cost_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.cost_service import check_cost_cap
        with pytest.raises(HTTPException) as exc_info:
            await check_cost_cap("user-1")
        assert exc_info.value.status_code == 429
        assert "limit" in exc_info.value.detail.lower()


async def test_cost_cap_passes_when_no_usage_row():
    client, _ = make_db_chain(data=[])  # no row yet = $0 spent
    with patch("web.services.cost_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.cost_service import check_cost_cap
        await check_cost_cap("user-1")  # should not raise


# ── log_usage: monthly increment ─────────────────────────────────────────────

async def test_log_usage_increments_existing_total():
    """Second call should add to the existing total, not overwrite it."""
    existing_total = 3.00

    # Use per-table chains so ai_usage_log.insert and user_monthly_costs.update
    # can be tracked independently.
    client, chains = make_multi_table_db({
        "ai_usage_log": {"data": []},
        "user_monthly_costs": {"data": _make_monthly_row(existing_total)},
    })
    with patch("web.services.cost_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.cost_service import log_usage
        new_total = await log_usage("user-1",
                                    input_tokens=100_000, output_tokens=0,
                                    cache_read_tokens=0, cache_write_tokens=0)

    expected = existing_total + (100_000 * 3.00 / 1_000_000)  # 3.30
    assert abs(new_total - expected) < 1e-6
    chains["user_monthly_costs"].update.assert_called_once()
    chains["user_monthly_costs"].insert.assert_not_called()
    chains["ai_usage_log"].insert.assert_called_once()


async def test_log_usage_inserts_when_no_existing_row():
    """First message of the month — should insert, not update, for user_monthly_costs."""
    client, chains = make_multi_table_db({
        "ai_usage_log": {"data": []},
        "user_monthly_costs": {"data": []},  # no row yet
    })
    with patch("web.services.cost_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.cost_service import log_usage
        total = await log_usage("user-1",
                                input_tokens=1_000_000, output_tokens=0,
                                cache_read_tokens=0, cache_write_tokens=0)

    assert abs(total - 3.00) < 1e-9
    chains["user_monthly_costs"].insert.assert_called_once()
    chains["user_monthly_costs"].update.assert_not_called()
