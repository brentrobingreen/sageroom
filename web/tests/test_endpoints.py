"""HTTP-level endpoint tests: auth, subscription gates, input validation, webhook sig."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from .conftest import make_db_chain


@pytest.fixture(scope="module")
def app():
    """FastAPI app with all external deps mocked at module level."""
    with patch("web.brain_registry.load_brains"), \
         patch("web.db.get_supabase", AsyncMock(return_value=make_db_chain()[0])):
        from web.main import app as _app
        from web.brain_registry import BRAIN_REGISTRY, Brain
        BRAIN_REGISTRY["tony_robbins"] = Brain(
            slug="tony_robbins",
            system_prompt="You are Tony.",
            brain_content="Tony brain content.",
        )
        return _app


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def authed(app):
    """Override auth dep to return a valid user for the duration of the test."""
    from web.routers.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1", "email": "u@test.com"}
    yield
    app.dependency_overrides.pop(get_current_user, None)


# ── Auth required (no token) ──────────────────────────────────────────────────

def test_get_brains_requires_auth(client):
    assert client.get("/api/brains").status_code == 401


def test_get_conversations_requires_auth(client):
    assert client.get("/api/conversations").status_code == 401


def test_get_billing_status_requires_auth(client):
    assert client.get("/api/billing/status").status_code == 401


def test_post_chat_stream_requires_auth(client):
    r = client.post("/api/chat/stream", json={"brain_slug": "tony_robbins", "message": "Hi"})
    assert r.status_code == 401


def test_post_group_chat_requires_auth(client):
    r = client.post("/api/group-chat", json={"brain_slugs": ["tony_robbins", "w"], "question": "?"})
    assert r.status_code == 401


# ── Input validation (422) ────────────────────────────────────────────────────

def test_group_chat_rejects_one_brain(client, authed):
    r = client.post("/api/group-chat", json={"brain_slugs": ["tony_robbins"], "question": "What?"})
    assert r.status_code == 422


def test_group_chat_rejects_five_brains(client, authed):
    r = client.post("/api/group-chat", json={"brain_slugs": ["a", "b", "c", "d", "e"], "question": "?"})
    assert r.status_code == 422


def test_chat_rejects_empty_message(client, authed):
    r = client.post("/api/chat/stream", json={"brain_slug": "tony_robbins", "message": "   "})
    assert r.status_code == 422


def test_chat_rejects_message_over_2000_chars(client, authed):
    r = client.post("/api/chat/stream", json={"brain_slug": "tony_robbins", "message": "x" * 2001})
    assert r.status_code == 422


# ── Stripe webhook signature ──────────────────────────────────────────────────

def test_webhook_rejects_missing_signature(client):
    r = client.post("/webhooks/stripe",
                    content=b'{"type":"checkout.session.completed"}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_webhook_rejects_invalid_signature(client):
    import stripe
    with patch.object(stripe.Webhook, "construct_event",
                      side_effect=stripe.error.SignatureVerificationError("bad sig", "sig")):
        r = client.post("/webhooks/stripe",
                        content=b'{"type":"checkout.session.completed"}',
                        headers={"Content-Type": "application/json",
                                 "Stripe-Signature": "t=bad,v1=wrong"})
    assert r.status_code == 400


def test_webhook_accepts_valid_signature(client):
    import stripe
    fake_event = {"type": "checkout.session.completed",
                  "data": {"object": {"metadata": {}}}}
    with patch.object(stripe.Webhook, "construct_event", return_value=fake_event), \
         patch("web.routers.webhooks.handle_checkout_complete", AsyncMock()):
        r = client.post("/webhooks/stripe",
                        content=b'{}',
                        headers={"Content-Type": "application/json",
                                 "Stripe-Signature": "t=1,v1=ok"})
    assert r.status_code == 200


# ── Health check ──────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
