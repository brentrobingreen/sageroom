import os

from fastapi import APIRouter, Depends, HTTPException, Request

from ..db import get_supabase
from ..limiter import limiter
from .auth import get_current_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    allowed = [e.strip() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()]
    if current_user["email"] not in allowed:
        raise HTTPException(status_code=403, detail="Access denied.")
    return current_user


@router.get("/costs")
@limiter.limit("30/minute")
async def admin_costs(request: Request, _: dict = Depends(get_admin_user)) -> list[dict]:
    db = await get_supabase()
    result = await db.table("user_monthly_costs").select("user_id,month_year,total_cost_usd").order("total_cost_usd", desc=True).execute()
    return result.data


@router.get("/usage")
@limiter.limit("30/minute")
async def admin_usage(request: Request, _: dict = Depends(get_admin_user)) -> dict:
    db = await get_supabase()
    result = await db.table("ai_usage_log").select("brain_slug").execute()
    counts: dict[str, int] = {}
    for row in result.data:
        slug = row.get("brain_slug")
        if slug:
            counts[slug] = counts.get(slug, 0) + 1
    return counts


@router.get("/subscribers")
@limiter.limit("30/minute")
async def admin_subscribers(request: Request, _: dict = Depends(get_admin_user)) -> dict:
    db = await get_supabase()
    result = await db.table("user_subscriptions").select("id", count="exact").eq("status", "active").execute()
    return {"active_subscribers": result.count or 0}
