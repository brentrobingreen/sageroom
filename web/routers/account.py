from __future__ import annotations

import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request

from ..db import get_supabase
from ..limiter import limiter
from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["account"])


@router.delete("/account")
@limiter.limit("3/minute")
async def delete_account(request: Request, current_user: dict = Depends(get_current_user)) -> dict:
    """
    Permanently deletes the authenticated user's account.
    1. Cancels active Stripe subscription immediately.
    2. Deletes all user data from every table.
    3. Deletes the Supabase auth user record.
    Required for GDPR / Australian Privacy Act right-to-deletion compliance.
    """
    user_id = current_user["id"]
    db = await get_supabase()

    # 1. Cancel Stripe subscription if one exists
    sub = await db.table("user_subscriptions").select("stripe_subscription_id").eq("user_id", user_id).execute()
    if sub.data:
        sub_id = sub.data[0].get("stripe_subscription_id")
        if sub_id:
            try:
                stripe.Subscription.delete(sub_id)
                logger.info("Cancelled Stripe subscription %s for user %s", sub_id, user_id)
            except stripe.error.StripeError as e:
                # Log but don't block deletion — subscription may already be cancelled
                logger.warning("Stripe cancellation error for user %s: %s", user_id, e)

    # 2. Delete user data in dependency order.
    # messages and group_responses/synthesis cascade via FK ON DELETE CASCADE.
    tables = [
        "conversations",        # messages cascade
        "group_sessions",       # group_responses, group_synthesis cascade
        "ai_usage_log",
        "user_monthly_costs",
        "user_subscriptions",
    ]
    for table in tables:
        await db.table(table).delete().eq("user_id", user_id).execute()
        logger.info("Deleted %s rows for user %s", table, user_id)

    # 3. Delete the Supabase auth user — requires service-role key
    try:
        await db.auth.admin.delete_user(user_id)
        logger.info("Deleted auth user %s", user_id)
    except Exception as e:
        logger.error("Failed to delete auth user %s: %s", user_id, e)
        raise HTTPException(
            status_code=500,
            detail="Account data was deleted but the auth record could not be removed. Contact support@sageroom.com.",
        )

    return {"ok": True}
