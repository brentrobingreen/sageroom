from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import anthropic

from ..brain_registry import Brain, get_brain
from ..db import get_supabase
from .cost_service import MODEL, log_usage

logger = logging.getLogger(__name__)

_anthropic = anthropic.AsyncAnthropic()

_LEAD_ADDENDUM = (
    "\n\n## Group chat mode — you speak first this turn\n\n"
    "This is a casual group chat, not a consultation. Think WhatsApp with smart friends.\n\n"
    "RULES:\n"
    "- 1–3 short sentences MAXIMUM. If you write more, you've failed.\n"
    "- Use 1–2 emojis naturally — not forced, just how you'd text a friend.\n"
    "- THERAPIST RULE: Until you have real context about this person's specific situation, "
    "ask questions — don't give advice. A good therapist spends several rounds understanding "
    "before they prescribe anything. You do not have enough context yet unless the conversation "
    "is already several turns deep with real specifics.\n"
    "- End with ONE question that goes one level deeper into their actual situation.\n"
    "- No frameworks, no headers, no plans unless they've explicitly asked for one.\n"
    "- Be warm and direct. Sound like a human being, not a self-help book."
)

_REACTOR_ADDENDUM = (
    "\n\n## Group chat mode — reacting to what's already been said\n\n"
    "Someone else has just spoken. You're reacting in a group chat.\n\n"
    "RULES:\n"
    "- 1 sentence ONLY. Seriously, one sentence.\n"
    "- Use 1 emoji.\n"
    "- Either: add a different angle to the question already asked, "
    "or push back on one specific word or assumption.\n"
    "- Do NOT ask a new question — one has been asked already.\n"
    "- Do NOT give advice or a plan.\n"
    "- Do NOT repeat or summarise what was just said.\n"
    "- Sound like a real person reacting in a group chat, not giving a speech."
)


def _build_messages(brain: Brain, user_message: str, history: list[dict], current_turn_others: dict[str, str]) -> list[dict]:
    """Build the Anthropic messages array for one brain's response."""
    msgs: list[dict] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": brain.brain_content, "cache_control": {"type": "ephemeral"}}],
        },
        {"role": "assistant", "content": "Understood. I'll engage through the lens of these frameworks."},
    ]

    # Replay conversation history, grouping by turn
    turns: dict[int, dict] = {}
    for msg in history:
        t = msg["turn"]
        if t not in turns:
            turns[t] = {"user": None, "brains": {}}
        if msg["role"] == "user":
            turns[t]["user"] = msg["content"]
        else:
            turns[t]["brains"][msg["brain_slug"]] = msg["content"]

    for turn_num in sorted(turns.keys()):
        td = turns[turn_num]
        user_text = td["user"] or ""
        others = {s: c for s, c in td["brains"].items() if s != brain.slug}
        if others:
            ctx = "\n\n".join(f"**{s}:** {c}" for s, c in others.items())
            user_text = f"{user_text}\n\n[Other thinkers said:\n{ctx}]"
        msgs.append({"role": "user", "content": user_text})
        own = td["brains"].get(brain.slug)
        msgs.append({"role": "assistant", "content": own or "[acknowledged]"})

    # Current user message + any brains that have already responded this turn
    cur_text = user_message
    if current_turn_others:
        ctx = "\n\n".join(f"**{s}:** {c}" for s, c in current_turn_others.items())
        cur_text = f"{user_message}\n\n[Others have just responded:\n{ctx}]"
    msgs.append({"role": "user", "content": cur_text})
    return msgs


async def stream_group_turn(
    session_id: str,
    user_id: str,
    brain_slugs: list[str],
    user_message: str,
) -> AsyncGenerator[str, None]:
    brains = [get_brain(slug) for slug in brain_slugs]
    db = await get_supabase()

    history = (
        await db.table("group_messages")
        .select("role,brain_slug,content,turn")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    ).data

    turn = (max((m["turn"] for m in history), default=0)) + 1

    # Save user message
    await db.table("group_messages").insert({
        "session_id": session_id,
        "role": "user",
        "brain_slug": None,
        "turn": turn,
        "content": user_message,
    }).execute()

    current_turn_others: dict[str, str] = {}

    for i, brain in enumerate(brains):
        is_lead = i == 0
        yield f"data: {json.dumps({'type': 'brain_start', 'brain_slug': brain.slug})}\n\n"

        msgs = _build_messages(brain, user_message, history, current_turn_others)
        system = brain.system_prompt + (_LEAD_ADDENDUM if is_lead else _REACTOR_ADDENDUM)
        max_tok = 120 if is_lead else 60

        full: list[str] = []
        in_tok = out_tok = cr_tok = cw_tok = 0

        try:
            async with _anthropic.messages.stream(
                model=MODEL,
                max_tokens=max_tok,
                system=system,
                messages=msgs,
            ) as stream:
                async for text in stream.text_stream:
                    full.append(text)
                    yield f"data: {json.dumps({'type': 'token', 'brain_slug': brain.slug, 'text': text})}\n\n"
                usage = (await stream.get_final_message()).usage
                in_tok = usage.input_tokens
                out_tok = usage.output_tokens
                cr_tok = getattr(usage, "cache_read_input_tokens", 0)
                cw_tok = getattr(usage, "cache_creation_input_tokens", 0)
        except Exception as e:
            logger.error("Group stream error brain=%s session=%s: %s", brain.slug, session_id, e)
            yield f"data: {json.dumps({'type': 'brain_error', 'brain_slug': brain.slug})}\n\n"
            continue

        content = "".join(full)
        current_turn_others[brain.slug] = content

        await db.table("group_messages").insert({
            "session_id": session_id,
            "role": "assistant",
            "brain_slug": brain.slug,
            "turn": turn,
            "content": content,
        }).execute()

        cost = await log_usage(
            user_id=user_id, brain_slug=brain.slug, group_session_id=session_id,
            input_tokens=in_tok, output_tokens=out_tok,
            cache_read_tokens=cr_tok, cache_write_tokens=cw_tok,
        )
        logger.info("claude [group/turn] brain=%s turn=%d in=%d out=%d cost=$%.6f",
                    brain.slug, turn, in_tok, out_tok, cost)

        yield f"data: {json.dumps({'type': 'brain_done', 'brain_slug': brain.slug})}\n\n"

    yield f"data: {json.dumps({'type': 'all_done', 'turn': turn})}\n\n"


async def generate_synthesis(session_id: str, user_id: str) -> str:
    db = await get_supabase()
    history = (
        await db.table("group_messages")
        .select("role,brain_slug,content,turn")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    ).data

    lines: list[str] = []
    cur_turn = 0
    for msg in history:
        if msg["turn"] != cur_turn:
            cur_turn = msg["turn"]
            lines.append(f"\n--- Exchange {cur_turn} ---")
        if msg["role"] == "user":
            lines.append(f"User: {msg['content']}")
        else:
            lines.append(f"{msg['brain_slug'].replace('_', ' ').title()}: {msg['content']}")

    synthesis_prompt = (
        "Here is the full group discussion:\n\n"
        + "\n".join(lines)
        + "\n\nWrite a synthesis document using exactly this structure:\n\n"
        "## Where they agreed\n"
        "- [bullet: specific point of convergence]\n"
        "- [bullet: another]\n\n"
        "## Where they diverged\n"
        "- [bullet: tension, note who held which position]\n"
        "- [bullet: another]\n\n"
        "## The core insight\n"
        "[1–2 paragraphs: the single most important takeaway from everything said]\n\n"
        "## What to do next\n"
        "1. [action step directly from the discussion]\n"
        "2. [another]\n"
        "3. [another]\n\n"
        "Be specific. Reference what was actually said. No filler."
    )

    response = await _anthropic.messages.create(
        model=MODEL,
        max_tokens=1200,
        system="You are a neutral facilitator synthesising a group discussion. Be specific, concrete, and genuinely useful.",
        messages=[{"role": "user", "content": synthesis_prompt}],
    )
    content = response.content[0].text

    existing = await db.table("group_synthesis").select("id").eq("session_id", session_id).execute()
    if existing.data:
        await db.table("group_synthesis").update({"content": content}).eq("session_id", session_id).execute()
    else:
        await db.table("group_synthesis").insert({"session_id": session_id, "content": content}).execute()

    await db.table("group_sessions").update({
        "status": "synthesized",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", session_id).execute()

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
        "cache_write_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
    }
    cost = await log_usage(user_id=user_id, group_session_id=session_id, **usage)
    logger.info("claude [group/synthesis] session=%s in=%d out=%d cost=$%.6f",
                session_id, usage["input_tokens"], usage["output_tokens"], cost)

    return content
