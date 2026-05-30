"""Tests for billing_service: subscription status, checkout, webhook handlers."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .conftest import make_db_chain


# ── is_subscriber ─────────────────────────────────────────────────────────────

async def test_is_subscriber_returns_true_when_active():
    client, _ = make_db_chain(data=[{"status": "active"}])
    with patch("web.services.billing_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.billing_service import is_subscriber
        assert await is_subscriber("user-1") is True


async def test_is_subscriber_returns_false_when_inactive():
    client, _ = make_db_chain(data=[{"status": "inactive"}])
    with patch("web.services.billing_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.billing_service import is_subscriber
        assert await is_subscriber("user-1") is False


async def test_is_subscriber_returns_false_when_cancelled():
    client, _ = make_db_chain(data=[{"status": "cancelled"}])
    with patch("web.services.billing_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.billing_service import is_subscriber
        assert await is_subscriber("user-1") is False


async def test_is_subscriber_returns_false_when_no_row():
    client, _ = make_db_chain(data=[])
    with patch("web.services.billing_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.billing_service import is_subscriber
        assert await is_subscriber("user-1") is False


# ── handle_checkout_complete ─────────────────────────────────────────────────

async def test_checkout_complete_updates_existing_row():
    """When a subscription row exists, it should be updated not inserted."""
    client, chain = make_db_chain(data=[{"id": "row-1"}])
    with patch("web.services.billing_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.billing_service import handle_checkout_complete
        await handle_checkout_complete({
            "metadata": {"user_id": "user-1"},
            "customer": "cus_123",
            "subscription": "sub_456",
        })
    chain.update.assert_called_once()
    chain.insert.assert_not_called()


async def test_checkout_complete_inserts_when_no_row():
    """First-ever subscription — no row exists yet, should insert."""
    client, chain = make_db_chain(data=[])
    with patch("web.services.billing_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.billing_service import handle_checkout_complete
        await handle_checkout_complete({
            "metadata": {"user_id": "user-1"},
            "customer": "cus_123",
            "subscription": "sub_456",
        })
    chain.insert.assert_called_once()
    chain.update.assert_not_called()


async def test_checkout_complete_skips_when_no_user_id():
    """Webhook without user_id metadata should be a no-op, not crash."""
    client, chain = make_db_chain()
    with patch("web.services.billing_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.billing_service import handle_checkout_complete
        await handle_checkout_complete({"metadata": {}, "customer": "cus_x", "subscription": "sub_x"})
    chain.table.assert_not_called() if hasattr(client, "table") else None


# ── subscription status transitions ──────────────────────────────────────────

async def test_handle_subscription_deleted_sets_cancelled():
    client, chain = make_db_chain()
    with patch("web.services.billing_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.billing_service import handle_subscription_deleted
        await handle_subscription_deleted({"id": "sub_456"})

    call_kwargs = chain.update.call_args[0][0]
    assert call_kwargs["status"] == "cancelled"


async def test_handle_payment_failed_sets_past_due():
    client, chain = make_db_chain()
    with patch("web.services.billing_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.billing_service import handle_payment_failed
        await handle_payment_failed({"subscription": "sub_456"})

    call_kwargs = chain.update.call_args[0][0]
    assert call_kwargs["status"] == "past_due"


# ── checkout idempotency ──────────────────────────────────────────────────────

async def test_create_checkout_raises_if_already_subscribed():
    """Should raise ValueError('already_subscribed') for active users."""
    client, _ = make_db_chain(data=[{"status": "active", "stripe_customer_id": "cus_x",
                                      "stripe_subscription_id": "sub_x",
                                      "free_messages_used": 0, "current_period_end": None}])
    with patch("web.services.billing_service.get_supabase", AsyncMock(return_value=client)):
        from web.services.billing_service import create_checkout_session
        with pytest.raises(ValueError, match="already_subscribed"):
            await create_checkout_session("user-1", "user@test.com")
