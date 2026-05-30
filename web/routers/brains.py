from fastapi import APIRouter, Depends, Request

from ..limiter import limiter
from ..models import BrainOut
from ..services.brain_service import get_all_brains, get_brain_or_404
from .auth import get_current_user

router = APIRouter(prefix="/api/brains", tags=["brains"])


@router.get("", response_model=list[BrainOut])
@limiter.limit("60/minute")
async def list_brains(request: Request, _: dict = Depends(get_current_user)) -> list[BrainOut]:
    return await get_all_brains()


@router.get("/{slug}", response_model=BrainOut)
@limiter.limit("60/minute")
async def get_brain(request: Request, slug: str, _: dict = Depends(get_current_user)) -> BrainOut:
    brains = await get_all_brains()
    match = next((b for b in brains if b.slug == slug), None)
    if not match:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Brain '{slug}' not found.")
    return match
