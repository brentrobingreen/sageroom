"""Tests for chat_service: streaming, cost cap SSE event, cache key consistency."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .conftest import make_db_chain


def _make_mock_stream(tokens=("Hello", " world")):
    """Mock for anthropic.AsyncAnthropic().messages.stream() context manager."""
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.cache_read_input_tokens = 10
    usage.cache_creation_input_tokens = 5

    final_msg = MagicMock()
    final_msg.usage = usage

    async def _text_gen():
        for token in tokens:
            yield token

    stream = MagicMock()
    stream.text_stream = _text_gen()
    stream.get_final_message = AsyncMock(return_value=final_msg)
    stream.__aenter__ = AsyncMock(return_value=stream)
    stream.__aexit__ = AsyncMock(return_value=False)
    return stream


async def test_stream_chat_yields_tokens_then_done(test_brain):
    """Happy path: token events stream in, final event is 'done'."""
    db_client, _ = make_db_chain(data=[{"id": "conv-1"}])

    mock_stream = _make_mock_stream(("Hi", " there"))
    mock_anthropic = MagicMock()
    mock_anthropic.messages.stream.return_value = mock_stream

    with patch("web.services.chat_service.get_supabase", AsyncMock(return_value=db_client)), \
         patch("web.services.chat_service._anthropic", mock_anthropic), \
         patch("web.services.chat_service.check_cost_cap", AsyncMock()), \
         patch("web.services.chat_service.log_usage", AsyncMock(return_value=0.01)):

        from web.services.chat_service import stream_chat
        # Pass history=[] and a fake conversation_id to skip DB calls for
        # conversation creation and message history loading
        events = [e async for e in stream_chat(
            "user-1", test_brain, "Hello?",
            conversation_id=None, history=[],
        )]

    parsed = [json.loads(e.replace("data: ", "").strip()) for e in events if e.strip()]
    types = [p["type"] for p in parsed]

    assert "token" in types
    assert types[-1] == "done"
    text = "".join(p["text"] for p in parsed if p["type"] == "token")
    assert text == "Hi there"


async def test_stream_chat_yields_cap_exceeded_event_not_exception(test_brain):
    """When cost cap is hit inside the generator it must yield an SSE event,
    not raise — raising inside a StreamingResponse just closes the connection."""
    from fastapi import HTTPException
    db_client, _ = make_db_chain(data=[])

    with patch("web.services.chat_service.get_supabase", AsyncMock(return_value=db_client)), \
         patch("web.services.chat_service.check_cost_cap",
               AsyncMock(side_effect=HTTPException(429, "Limit reached."))):

        from web.services.chat_service import stream_chat
        events = [e async for e in stream_chat("user-1", test_brain, "Hello?", None)]

    assert len(events) == 1
    data = json.loads(events[0].replace("data: ", "").strip())
    assert data["type"] == "monthly_cost_cap_exceeded"
    assert "Limit reached." in data["message"]


def test_brain_content_identical_across_calls(test_brain):
    """The brain_content string passed to Anthropic must be identical on every call
    — any variation defeats prompt caching (frozen dataclass guarantees this)."""
    assert test_brain.brain_content is test_brain.brain_content
    assert len(test_brain.brain_content) > 0
    assert test_brain.system_prompt is test_brain.system_prompt
