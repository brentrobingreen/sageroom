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

MAX_CONTEXT_ROUNDS = 2

_CONTEXT_SYSTEM = (
    "You are a facilitator for a council of expert advisors. "
    "Assess whether you have enough specific context to give genuinely useful, tailored advice. "
    "Respond only with valid JSON — no explanation, no markdown."
)

_PERSPECTIVE_ADDENDUM = (
    "\n\n## Council brief\n"
    "The user's full situation is provided. Give your perspective in 3–4 sentences. "
    "Be specific to their situation — not generic advice. Direct and concrete. "
    "No headers, no bullet points. Write as if presenting a brief to a board."
)

_SYNTHESIS_SYSTEM = (
    "You are a neutral facilitator synthesising a council discussion. "
    "Be specific, reference what was actually said, and be genuinely useful. "
    "Use exactly the structure provided — no deviation."
)


async def assess_context(session_id: str) -> dict:
    """Return {ready: bool, question: str|None}. Saves question to DB if not ready."""
    db = await get_supabase()

    session = (await db.table("group_sessions").select("question").eq("id", session_id).execute()).data
    if not session:
        return {"ready": True, "question": None}
    question = session[0]["question"]

    messages = (
        await db.table("group_messages").select("role,brain_slug,content")
        .eq("session_id", session_id).order("created_at").execute()
    ).data

    facilitator_msgs = [m for m in messages if m.get("brain_slug") == "facilitator"]
    if len(facilitator_msgs) >= MAX_CONTEXT_ROUNDS:
        return {"ready": True, "question": None}

    context_lines: list[str] = []
    for m in messages:
        if m.get("brain_slug") == "facilitator":
            context_lines.append(f"Q: {m['content']}")
        elif m["role"] == "user":
            context_lines.append(f"A: {m['content']}")

    prompt = f'User\'s question: "{question}"\n'
    if context_lines:
        prompt += "\nContext gathered so far:\n" + "\n".join(context_lines) + "\n"
    prompt += (
        "\nDo you have enough specific context to give genuinely useful, tailored advice?\n"
        "If yes: {\"ready\": true}\n"
        'If one focused question would meaningfully improve the advice: {"ready": false, "question": "..."}\n\n'
        "Be conservative — vague questions produce generic advice. But if the situation is already specific, return ready."
    )

    resp = await _anthropic.messages.create(
        model=MODEL, max_tokens=80, system=_CONTEXT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        result = json.loads(resp.content[0].text.strip())
    except Exception:
        result = {"ready": True}

    if not result.get("ready", True) and result.get("question"):
        turn = len(facilitator_msgs) + 1
        await db.table("group_messages").insert({
            "session_id": session_id,
            "role": "assistant",
            "brain_slug": "facilitator",
            "turn": turn,
            "content": result["question"],
        }).execute()

    return {"ready": bool(result.get("ready", True)), "question": result.get("question")}


async def save_context_answer(session_id: str, answer: str) -> None:
    db = await get_supabase()
    messages = (
        await db.table("group_messages").select("turn")
        .eq("session_id", session_id).order("created_at", desc=True).limit(1).execute()
    ).data
    turn = messages[0]["turn"] if messages else 1
    await db.table("group_messages").insert({
        "session_id": session_id,
        "role": "user",
        "brain_slug": None,
        "turn": turn,
        "content": answer,
    }).execute()


def _build_full_context(question: str, messages: list[dict], follow_up: str | None) -> str:
    lines = [f"Situation: {question}"]
    for m in messages:
        if m.get("brain_slug") == "facilitator":
            lines.append(f"Clarifying question asked: {m['content']}")
        elif m["role"] == "user":
            lines.append(f"User's answer: {m['content']}")
    if follow_up:
        lines.append(f"Follow-up question: {follow_up}")
    return "\n".join(lines)


async def stream_deliberation(
    session_id: str,
    user_id: str,
    brain_slugs: list[str],
    follow_up: str | None = None,
) -> AsyncGenerator[str, None]:
    brains = [get_brain(slug) for slug in brain_slugs]
    db = await get_supabase()

    session = (await db.table("group_sessions").select("question").eq("id", session_id).execute()).data
    question = session[0]["question"]
    messages = (
        await db.table("group_messages").select("role,brain_slug,content,turn")
        .eq("session_id", session_id).order("created_at").execute()
    ).data

    if follow_up:
        existing_turns = [m for m in messages if m["role"] == "assistant" and m.get("brain_slug") not in (None, "facilitator")]
        turn = (max((m["turn"] for m in existing_turns), default=0)) + 1
        await db.table("group_messages").insert({
            "session_id": session_id, "role": "user",
            "brain_slug": None, "turn": turn, "content": follow_up,
        }).execute()
        messages.append({"role": "user", "brain_slug": None, "turn": turn, "content": follow_up})
    else:
        existing_turns = [m for m in messages if m["role"] == "assistant" and m.get("brain_slug") not in (None, "facilitator")]
        turn = (max((m["turn"] for m in existing_turns), default=0)) + 1

    full_context = _build_full_context(question, messages, None)
    perspectives: dict[str, str] = {}

    # ── Brain perspectives ────────────────────────────────────────────────────
    for brain in brains:
        yield f"data: {json.dumps({'type': 'brain_start', 'brain_slug': brain.slug})}\n\n"

        context_with_others = full_context
        if perspectives:
            others = "\n".join(f"{s.replace('_',' ').title()}: {c}" for s, c in perspectives.items())
            context_with_others += f"\n\nOther council members have already said:\n{others}"

        msgs = [
            {"role": "user", "content": [{"type": "text", "text": brain.brain_content, "cache_control": {"type": "ephemeral"}}]},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": context_with_others},
        ]
        system = brain.system_prompt + _PERSPECTIVE_ADDENDUM

        full: list[str] = []
        in_tok = out_tok = cr_tok = cw_tok = 0
        try:
            async with _anthropic.messages.stream(model=MODEL, max_tokens=200, system=system, messages=msgs) as stream:
                async for text in stream.text_stream:
                    full.append(text)
                    yield f"data: {json.dumps({'type': 'token', 'brain_slug': brain.slug, 'text': text})}\n\n"
                usage = (await stream.get_final_message()).usage
                in_tok, out_tok = usage.input_tokens, usage.output_tokens
                cr_tok = getattr(usage, "cache_read_input_tokens", 0)
                cw_tok = getattr(usage, "cache_creation_input_tokens", 0)
        except Exception as e:
            logger.error("Deliberation error brain=%s: %s", brain.slug, e)
            yield f"data: {json.dumps({'type': 'brain_error', 'brain_slug': brain.slug})}\n\n"
            continue

        content = "".join(full)
        perspectives[brain.slug] = content
        await db.table("group_messages").insert({
            "session_id": session_id, "role": "assistant",
            "brain_slug": brain.slug, "turn": turn, "content": content,
        }).execute()
        cost = await log_usage(user_id=user_id, brain_slug=brain.slug, group_session_id=session_id,
                               input_tokens=in_tok, output_tokens=out_tok,
                               cache_read_tokens=cr_tok, cache_write_tokens=cw_tok)
        logger.info("claude [deliberation] brain=%s turn=%d cost=$%.6f", brain.slug, turn, cost)
        yield f"data: {json.dumps({'type': 'brain_done', 'brain_slug': brain.slug})}\n\n"

    # ── Synthesis ─────────────────────────────────────────────────────────────
    yield f"data: {json.dumps({'type': 'synthesis_start'})}\n\n"

    perspectives_text = "\n\n".join(
        f"{s.replace('_',' ').title()}: {c}" for s, c in perspectives.items()
    )
    synthesis_prompt = (
        f"Full context:\n{full_context}\n\n"
        f"Council perspectives:\n{perspectives_text}\n\n"
        "Write a synthesis document with exactly this structure:\n\n"
        "## Where they agreed\n- [specific point]\n- [specific point]\n\n"
        "## Where they diverged\n- [tension, note who held which position]\n\n"
        "## The core insight\n[1–2 paragraphs: the single most important takeaway]\n\n"
        "## What to do next\n1. [action]\n2. [action]\n3. [action]\n\n"
        "Be specific. Reference what was actually said. No filler."
    )

    synthesis_full: list[str] = []
    s_in = s_out = s_cr = s_cw = 0
    try:
        async with _anthropic.messages.stream(
            model=MODEL, max_tokens=1000, system=_SYNTHESIS_SYSTEM,
            messages=[{"role": "user", "content": synthesis_prompt}],
        ) as stream:
            async for text in stream.text_stream:
                synthesis_full.append(text)
                yield f"data: {json.dumps({'type': 'synthesis_token', 'text': text})}\n\n"
            usage = (await stream.get_final_message()).usage
            s_in, s_out = usage.input_tokens, usage.output_tokens
            s_cr = getattr(usage, "cache_read_input_tokens", 0)
            s_cw = getattr(usage, "cache_creation_input_tokens", 0)
    except Exception as e:
        logger.error("Synthesis stream error: %s", e)
        yield f"data: {json.dumps({'type': 'synthesis_error'})}\n\n"

    synthesis_content = "".join(synthesis_full)
    existing = (await db.table("group_synthesis").select("id").eq("session_id", session_id).execute()).data
    if existing:
        await db.table("group_synthesis").update({"content": synthesis_content}).eq("session_id", session_id).execute()
    else:
        await db.table("group_synthesis").insert({"session_id": session_id, "content": synthesis_content}).execute()

    await db.table("group_sessions").update({
        "status": "synthesized",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", session_id).execute()

    cost = await log_usage(user_id=user_id, group_session_id=session_id,
                           input_tokens=s_in, output_tokens=s_out,
                           cache_read_tokens=s_cr, cache_write_tokens=s_cw)
    logger.info("claude [synthesis] session=%s cost=$%.6f", session_id, cost)

    yield f"data: {json.dumps({'type': 'synthesis_done'})}\n\n"
    yield f"data: {json.dumps({'type': 'all_done'})}\n\n"
