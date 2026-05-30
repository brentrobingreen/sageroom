import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from uuid import UUID

import anthropic

from ..brain_registry import Brain
from ..db import get_supabase
from .cost_service import MODEL, check_cost_cap, log_usage

logger = logging.getLogger(__name__)

_anthropic = anthropic.AsyncAnthropic()


async def _get_or_create_conversation(user_id: str, brain_slug: str, conversation_id: UUID | None) -> str:
    db = await get_supabase()
    if conversation_id:
        return str(conversation_id)
    result = await db.table("conversations").insert({
        "user_id": user_id,
        "brain_slug": brain_slug,
        "title": None,
    }).execute()
    return result.data[0]["id"]


async def _load_history(conversation_id: str, limit: int = 20) -> list[dict]:
    db = await get_supabase()
    result = await db.table("messages").select("role,content").eq("conversation_id", conversation_id).order("created_at", desc=False).limit(limit).execute()
    return [{"role": row["role"], "content": row["content"]} for row in result.data]


async def _save_message(conversation_id: str, user_id: str, role: str, content: str) -> None:
    db = await get_supabase()
    await db.table("messages").insert({
        "conversation_id": conversation_id,
        "user_id": user_id,
        "role": role,
        "content": content,
    }).execute()
    await db.table("conversations").update({
        "last_message_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", conversation_id).execute()


async def stream_chat(
    user_id: str,
    brain: Brain,
    message: str,
    conversation_id: UUID | None,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    await check_cost_cap(user_id)

    conv_id = await _get_or_create_conversation(user_id, brain.slug, conversation_id)

    if history is None:
        history = await _load_history(conv_id)

    await _save_message(conv_id, user_id, "user", message)

    messages: list[dict] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": brain.brain_content,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
        {
            "role": "assistant",
            "content": "Understood. I'll engage with you through the lens of these frameworks and experiences.",
        },
        *history,
        {"role": "user", "content": message},
    ]

    full_response = []
    input_tokens = output_tokens = cache_read_tokens = cache_write_tokens = 0

    try:
        async with _anthropic.messages.stream(
            model=MODEL,
            max_tokens=2048,
            system=brain.system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                full_response.append(text)
                yield f"data: {json.dumps({'type': 'token', 'text': text, 'conversation_id': conv_id})}\n\n"

            usage = (await stream.get_final_message()).usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0)
            cache_write_tokens = getattr(usage, "cache_creation_input_tokens", 0)

    except Exception as e:
        logger.error("Stream error for user %s: %s", user_id, e)
        yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong. Please try again.'})}\n\n"
        return

    assistant_content = "".join(full_response)
    await _save_message(conv_id, user_id, "assistant", assistant_content)
    await log_usage(
        user_id=user_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        brain_slug=brain.slug,
        conversation_id=conv_id,
    )

    yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id})}\n\n"
