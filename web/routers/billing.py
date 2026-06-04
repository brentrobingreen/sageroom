from fastapi import APIRouter, Depends, HTTPException, Request

from ..limiter import limiter
from ..models import SubscriptionStatusOut
from ..services.billing_service import (
    CREDIT_PACKS,
    create_credit_checkout,
    get_subscription_status,
)
from .auth import get_current_user

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/status", response_model=SubscriptionStatusOut)
@limiter.limit("30/minute")
async def billing_status(request: Request, current_user: dict = Depends(get_current_user)) -> SubscriptionStatusOut:
    return await get_subscription_status(current_user["id"])


@router.get("/packs")
@limiter.limit("60/minute")
async def list_packs(request: Request) -> list[dict]:
    return [
        {"id": k, "name": v["name"], "credits": v["credits"], "price_label": v["price_label"]}
        for k, v in CREDIT_PACKS.items()
    ]


@router.post("/purchase")
@limiter.limit("10/minute")
async def purchase_credits(request: Request, current_user: dict = Depends(get_current_user)) -> dict:
    body = await request.json()
    pack_id = body.get("pack_id", "")
    try:
        url = await create_credit_checkout(current_user["id"], current_user["email"], pack_id)
        return {"url": url}
    except ValueError as e:
        msg = str(e)
        if msg.startswith("unknown_pack"):
            raise HTTPException(status_code=400, detail="Invalid credit pack.")
        raise HTTPException(status_code=500, detail="Billing configuration error.")
