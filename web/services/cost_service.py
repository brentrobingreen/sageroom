import os
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException

from ..db import get_supabase

# Claude Sonnet 4.6 pricing — USD per million tokens
# Verify against https://www.anthropic.com/pricing before launch (task 7.3)
MODEL = "claude-sonnet-4-6"
INPUT_COST_PER_M = 3.00
OUTPUT_COST_PER_M = 15.00
CACHE_WRITE_COST_PER_M = 3.75
CACHE_READ_COST_PER_M = 0.30


def _compute_cost(input_tokens: int, output_tokens: int, cache_read_tokens: int, cache_write_tokens: int) -> float:
    return (
        input_tokens * INPUT_COST_PER_M / 1_000_000
        + output_tokens * OUTPUT_COST_PER_M / 1_000_000
        + cache_read_tokens * CACHE_READ_COST_PER_M / 1_000_000
        + cache_write_tokens * CACHE_WRITE_COST_PER_M / 1_000_000
    )


async def log_usage(
    user_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    brain_slug: str | None = None,
    conversation_id: str | None = None,
    group_session_id: str | None = None,
) -> float:
    cost = _compute_cost(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
    month_year = datetime.now(timezone.utc).strftime("%Y-%m")
    db = await get_supabase()

    await db.table("ai_usage_log").insert({
        "user_id": user_id,
        "conversation_id": conversation_id,
        "group_session_id": group_session_id,
        "brain_slug": brain_slug,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cost_usd": round(cost, 6),
    }).execute()

    await db.table("user_monthly_costs").upsert({
        "user_id": user_id,
        "month_year": month_year,
        "total_cost_usd": cost,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="user_id,month_year", count="exact").execute()

    # Re-fetch to get the true running total after upsert
    result = await db.table("user_monthly_costs").select("total_cost_usd").eq("user_id", user_id).eq("month_year", month_year).single().execute()
    return float(result.data["total_cost_usd"]) if result.data else cost


async def check_cost_cap(user_id: str) -> None:
    cap = float(os.environ.get("MAX_MONTHLY_AI_COST_USD", "8.00"))
    month_year = datetime.now(timezone.utc).strftime("%Y-%m")
    db = await get_supabase()

    result = await db.table("user_monthly_costs").select("total_cost_usd").eq("user_id", user_id).eq("month_year", month_year).execute()

    if result.data:
        current = float(result.data[0]["total_cost_usd"])
        if current >= cap:
            next_month = datetime.now(timezone.utc).replace(day=1).strftime("%B 1")
            raise HTTPException(
                status_code=429,
                detail=f"You've reached your AI usage limit for this month (${cap:.2f}). It resets on {next_month}.",
            )


async def get_monthly_cost(user_id: str, month_year: str) -> float:
    db = await get_supabase()
    result = await db.table("user_monthly_costs").select("total_cost_usd").eq("user_id", user_id).eq("month_year", month_year).execute()
    if result.data:
        return float(result.data[0]["total_cost_usd"])
    return 0.0
