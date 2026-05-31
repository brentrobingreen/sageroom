import asyncio
import json
import logging
from datetime import datetime, timezone

import anthropic

from ..brain_registry import Brain, get_brain
from ..db import get_supabase
from .cost_service import MODEL, log_usage

logger = logging.getLogger(__name__)

_anthropic = anthropic.AsyncAnthropic()


async def _call_brain(brain: Brain, system_override: str, user_message: str, user_id: str, session_id: str) -> tuple[str, dict]:
    messages = [
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
            "content": "Understood. I'll engage through the lens of these frameworks.",
        },
        {"role": "user", "content": user_message},
    ]

    response = await _anthropic.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_override or brain.system_prompt,
        messages=messages,
    )

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
        "cache_write_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
    }

    return response.content[0].text, usage


async def _update_session_status(session_id: str, status: str) -> None:
    db = await get_supabase()
    update = {"status": status}
    if status == "complete":
        update["completed_at"] = datetime.now(timezone.utc).isoformat()
    await db.table("group_sessions").update(update).eq("id", session_id).execute()


async def _save_response(session_id: str, brain_slug: str, round_num: int, content: str) -> None:
    db = await get_supabase()
    await db.table("group_responses").insert({
        "session_id": session_id,
        "brain_slug": brain_slug,
        "round": round_num,
        "content": content,
    }).execute()


async def run_group_chat(session_id: str, user_id: str, brain_slugs: list[str], question: str) -> None:
    brains = [get_brain(slug) for slug in brain_slugs]

    # ── Round 1: all brains answer the question in parallel ─────────────────
    await _update_session_status(session_id, "round1")

    round1_tasks = [
        _call_brain(brain, brain.system_prompt, question, user_id, session_id)
        for brain in brains
    ]
    round1_results = await asyncio.gather(*round1_tasks, return_exceptions=True)

    round1_responses: dict[str, str] = {}
    for brain, result in zip(brains, round1_results):
        if isinstance(result, Exception):
            logger.error("Round 1 error for %s in session %s: %s", brain.slug, session_id, result)
            await _update_session_status(session_id, "failed")
            return
        content, usage = result
        round1_responses[brain.slug] = content
        await _save_response(session_id, brain.slug, 1, content)
        cost = await log_usage(
            user_id=user_id,
            brain_slug=brain.slug,
            group_session_id=session_id,
            **usage,
        )
        logger.info(
            "claude call [group/r1] brain=%s in=%d out=%d cost=$%.6f",
            brain.slug, usage["input_tokens"], usage["output_tokens"], cost,
        )

    # ── Round 2: each brain responds knowing what others said ────────────────
    await _update_session_status(session_id, "round2")

    def _round2_prompt(brain: Brain) -> str:
        others = "\n\n".join(
            f"**{slug}** said:\n{resp}"
            for slug, resp in round1_responses.items()
            if slug != brain.slug
        )
        return (
            f"The original question was: {question}\n\n"
            f"Your initial response was:\n{round1_responses[brain.slug]}\n\n"
            f"Here is what the other thinkers said:\n\n{others}\n\n"
            "Now give your Round 2 response: refine your thinking, acknowledge where you agree or disagree with the others, and add any new insights."
        )

    round2_tasks = [
        _call_brain(brain, brain.system_prompt, _round2_prompt(brain), user_id, session_id)
        for brain in brains
    ]
    round2_results = await asyncio.gather(*round2_tasks, return_exceptions=True)

    round2_responses: dict[str, str] = {}
    for brain, result in zip(brains, round2_results):
        if isinstance(result, Exception):
            logger.error("Round 2 error for %s in session %s: %s", brain.slug, session_id, result)
            await _update_session_status(session_id, "failed")
            return
        content, usage = result
        round2_responses[brain.slug] = content
        await _save_response(session_id, brain.slug, 2, content)
        cost = await log_usage(
            user_id=user_id,
            brain_slug=brain.slug,
            group_session_id=session_id,
            **usage,
        )
        logger.info(
            "claude call [group/r2] brain=%s in=%d out=%d cost=$%.6f",
            brain.slug, usage["input_tokens"], usage["output_tokens"], cost,
        )

    # ── Synthesis: neutral facilitator weaves everything together ────────────
    await _update_session_status(session_id, "synthesis")

    all_responses = "\n\n".join(
        f"**{slug} (Round 1):**\n{round1_responses[slug]}\n\n**{slug} (Round 2):**\n{round2_responses[slug]}"
        for slug in brain_slugs
    )
    synthesis_prompt = (
        f"The group was asked: {question}\n\n"
        f"Here are all responses from both rounds:\n\n{all_responses}\n\n"
        "As a neutral facilitator, write a clear synthesis that:\n"
        "1. Identifies the key themes where the thinkers agree\n"
        "2. Highlights meaningful points of disagreement or tension\n"
        "3. Surfaces the most actionable insight from the discussion\n"
        "Write in plain prose, 3–5 paragraphs."
    )

    synthesis_response = await _anthropic.messages.create(
        model=MODEL,
        max_tokens=1024,
        system="You are a neutral facilitator synthesising a multi-perspective discussion.",
        messages=[{"role": "user", "content": synthesis_prompt}],
    )

    synthesis_content = synthesis_response.content[0].text
    synthesis_usage = {
        "input_tokens": synthesis_response.usage.input_tokens,
        "output_tokens": synthesis_response.usage.output_tokens,
        "cache_read_tokens": getattr(synthesis_response.usage, "cache_read_input_tokens", 0),
        "cache_write_tokens": getattr(synthesis_response.usage, "cache_creation_input_tokens", 0),
    }

    db = await get_supabase()
    await db.table("group_synthesis").insert({
        "session_id": session_id,
        "content": synthesis_content,
    }).execute()

    synthesis_cost = await log_usage(
        user_id=user_id,
        group_session_id=session_id,
        **synthesis_usage,
    )
    logger.info(
        "claude call [group/synthesis] session=%s in=%d out=%d cost=$%.6f",
        session_id, synthesis_usage["input_tokens"], synthesis_usage["output_tokens"], synthesis_cost,
    )

    await _update_session_status(session_id, "complete")
