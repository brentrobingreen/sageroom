from fastapi import APIRouter, Depends, HTTPException, Request

from ..limiter import limiter
from ..models import SubscriptionStatusOut
from ..services.billing_service import (
    create_checkout_session,
    create_portal_session,
    get_subscription_status,
)
from .auth import get_current_user

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/status", response_model=SubscriptionStatusOut)
@limiter.limit("30/minute")
async def billing_status(request: Request, current_user: dict = Depends(get_current_user)) -> SubscriptionStatusOut:
    return await get_subscription_status(current_user["id"])


@router.post("/checkout")
@limiter.limit("10/minute")
async def checkout(request: Request, current_user: dict = Depends(get_current_user)) -> dict:
    try:
        url = await create_checkout_session(current_user["id"], current_user["email"])
        return {"url": url}
    except ValueError as e:
        if str(e) == "already_subscribed":
            raise HTTPException(status_code=400, detail="You already have an active subscription.")
        raise


@router.post("/portal")
@limiter.limit("10/minute")
async def portal(request: Request, current_user: dict = Depends(get_current_user)) -> dict:
    try:
        url = await create_portal_session(current_user["id"])
        return {"url": url}
    except ValueError as e:
        if str(e) == "no_customer":
            raise HTTPException(status_code=400, detail="No billing account found. Please subscribe first.")
        raise
