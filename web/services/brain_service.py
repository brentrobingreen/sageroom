from fastapi import HTTPException

from ..brain_registry import Brain, get_brain
from ..db import get_supabase
from ..models import BrainOut


async def get_all_brains() -> list[BrainOut]:
    db = await get_supabase()
    result = await db.table("brains").select("id,slug,display_name,tagline,category,avatar_url").eq("is_active", True).execute()
    return [BrainOut(**row) for row in result.data]


async def get_brain_or_404(slug: str) -> Brain:
    try:
        return get_brain(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Brain '{slug}' not found.")
