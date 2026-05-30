"""Shared fixtures and environment setup for all tests."""
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set env vars before any web module is imported
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_testfake")
os.environ.setdefault("STRIPE_PRICE_ID", "price_testfake")
os.environ.setdefault("ALLOWED_ORIGIN", "http://localhost:8000")
os.environ.setdefault("ADMIN_EMAILS", "admin@test.com")
os.environ.setdefault("MAX_MONTHLY_AI_COST_USD", "8.00")
os.environ.setdefault("MAX_DAILY_GROUP_SESSIONS", "2")
os.environ.setdefault("FREE_TIER_MESSAGE_LIMIT", "10")


def make_db_chain(data=None, count=0):
    """
    Returns (client, chain) satisfying the Supabase fluent builder pattern:
      db.table("x").select().eq().execute()

    table/select/eq etc. are synchronous builder methods — only execute() is async.
    client must be a plain MagicMock so that client.table(...) returns the chain
    directly (not a coroutine). get_supabase() is the async boundary.
    """
    result = MagicMock()
    result.data = data if data is not None else []
    result.count = count

    chain = MagicMock()
    chain.execute = AsyncMock(return_value=result)
    for method in ("select", "insert", "update", "delete", "upsert",
                   "eq", "neq", "gte", "lte", "order", "limit", "single"):
        getattr(chain, method).return_value = chain

    # MagicMock (not AsyncMock) — table() is synchronous
    client = MagicMock()
    client.table.return_value = chain
    return client, chain


def make_multi_table_db(table_data: dict):
    """
    Returns a client where each table name returns its own independent chain.
    table_data: {'table_name': {'data': [...], 'count': N}, ...}
    """
    chains = {}
    for name, cfg in table_data.items():
        _, chain = make_db_chain(**cfg)
        chains[name] = chain

    default_chain = make_db_chain()[1]
    client = MagicMock()
    client.table.side_effect = lambda name: chains.get(name, default_chain)
    return client, chains


@pytest.fixture
def db_chain():
    """Factory for configuring per-test Supabase mock responses."""
    return make_db_chain


@pytest.fixture
def mock_db():
    client, _ = make_db_chain()
    return client


@pytest.fixture
def test_brain():
    from web.brain_registry import Brain
    return Brain(
        slug="tony_robbins",
        system_prompt="You are Tony Robbins. Apply his frameworks.",
        brain_content="# Tony Robbins Brain\n\nKey frameworks: State management, Six human needs.",
    )
