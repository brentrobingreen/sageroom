"""Tests for group_chat_service: parallelism, round 2 context, status transitions."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .conftest import make_db_chain


def _make_brain(slug: str):
    from web.brain_registry import Brain
    return Brain(slug=slug, system_prompt=f"You are {slug}.", brain_content=f"# {slug} content")


def _make_anthropic_response(text: str):
    usage = MagicMock()
    usage.input_tokens = 50
    usage.output_tokens = 30
    usage.cache_read_input_tokens = 0
    usage.cache_creation_input_tokens = 0

    content_item = MagicMock()
    content_item.text = text

    response = MagicMock()
    response.content = [content_item]
    response.usage = usage
    return response


async def test_round1_calls_all_brains_in_parallel():
    """Both brains must be called during Round 1."""
    brain_a = _make_brain("brain_a")
    brain_b = _make_brain("brain_b")
    client, _ = make_db_chain(data=[{"id": "session-1"}])

    call_slugs = []

    async def fake_create(**kwargs):
        system = kwargs.get("system", "")
        call_slugs.append(system)
        return _make_anthropic_response("A response.")

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = fake_create

    with patch("web.services.group_chat_service.get_supabase", AsyncMock(return_value=client)), \
         patch("web.services.group_chat_service._anthropic", mock_anthropic), \
         patch("web.services.group_chat_service.get_brain", side_effect=[brain_a, brain_b]), \
         patch("web.services.group_chat_service.log_usage", AsyncMock(return_value=0.01)):

        from web.services.group_chat_service import run_group_chat
        await run_group_chat("session-1", "user-1", ["brain_a", "brain_b"], "What should I do?")

    # Round 1 (2) + Round 2 (2) + Synthesis (1) = 5 total calls
    assert len(call_slugs) == 5
    # Both brains called in Round 1 — their system prompts appear
    assert any("brain_a" in s for s in call_slugs)
    assert any("brain_b" in s for s in call_slugs)


async def test_round2_prompt_includes_other_brains_response():
    """Each brain's Round 2 prompt must reference what other brains said in Round 1."""
    brain_a = _make_brain("brain_a")
    brain_b = _make_brain("brain_b")
    client, _ = make_db_chain(data=[{"id": "session-1"}])

    round2_messages = []
    call_count = [0]

    async def fake_create(**kwargs):
        call_count[0] += 1
        messages = kwargs.get("messages", [])
        last_user = next(
            (m["content"] for m in reversed(messages)
             if m.get("role") == "user" and isinstance(m.get("content"), str)),
            None,
        )
        # Calls 3 and 4 are Round 2 (after 2 Round 1 calls; call 5 is synthesis)
        if 2 < call_count[0] <= 4 and last_user:
            round2_messages.append(last_user)
        return _make_anthropic_response("A thoughtful response.")

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = fake_create

    with patch("web.services.group_chat_service.get_supabase", AsyncMock(return_value=client)), \
         patch("web.services.group_chat_service._anthropic", mock_anthropic), \
         patch("web.services.group_chat_service.get_brain", side_effect=[brain_a, brain_b]), \
         patch("web.services.group_chat_service.log_usage", AsyncMock(return_value=0.01)):

        from web.services.group_chat_service import run_group_chat
        await run_group_chat("session-1", "user-1", ["brain_a", "brain_b"], "What should I do?")

    assert len(round2_messages) == 2
    for prompt in round2_messages:
        assert "Round 2" in prompt
        assert "said" in prompt.lower()


async def test_session_status_progresses_to_complete():
    """Status must transition through all stages and end at 'complete'."""
    brain_a = _make_brain("brain_a")
    brain_b = _make_brain("brain_b")
    client, chain = make_db_chain(data=[{"id": "session-1"}])

    status_updates = []

    def capture_update(data):
        if "status" in data:
            status_updates.append(data["status"])
        return chain

    chain.update.side_effect = capture_update

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = AsyncMock(return_value=_make_anthropic_response("Response."))

    with patch("web.services.group_chat_service.get_supabase", AsyncMock(return_value=client)), \
         patch("web.services.group_chat_service._anthropic", mock_anthropic), \
         patch("web.services.group_chat_service.get_brain", side_effect=[brain_a, brain_b]), \
         patch("web.services.group_chat_service.log_usage", AsyncMock(return_value=0.01)):

        from web.services.group_chat_service import run_group_chat
        await run_group_chat("session-1", "user-1", ["brain_a", "brain_b"], "What now?")

    assert "round1" in status_updates
    assert "round2" in status_updates
    assert "synthesis" in status_updates
    assert "complete" in status_updates
    assert status_updates[-1] == "complete"
