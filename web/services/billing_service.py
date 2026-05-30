import os
from datetime import datetime, timezone

import stripe

from ..db import get_supabase
from ..models import SubscriptionStatusOut

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")


async def _get_or_create_subscription_row(user_id: str) -> dict:
    db = await get_supabase()
    result = await db.table("user_subscriptions").select("*").eq("user_id", user_id).execute()
    if result.data:
        return result.data[0]
    # Create a blank row for new users
    insert = await db.table("user_subscriptions").insert({"user_id": user_id}).execute()
    return insert.data[0]


async def create_checkout_session(user_id: str, email: str) -> str:
    row = await _get_or_create_subscription_row(user_id)
    if row.get("status") == "active":
        raise ValueError("already_subscribed")

    customer_id = row.get("stripe_customer_id")

    session = stripe.checkout.Session.create(
        customer=customer_id or None,
        customer_email=None if customer_id else email,
        mode="subscription",
        line_items=[{"price": os.environ["STRIPE_PRICE_ID"], "quantity": 1}],
        success_url=f"{os.environ['ALLOWED_ORIGIN']}/account.html?payment=success",
        cancel_url=f"{os.environ['ALLOWED_ORIGIN']}/account.html",
        metadata={"user_id": user_id},
    )
    return session.url


async def create_portal_session(user_id: str) -> str:
    row = await _get_or_create_subscription_row(user_id)
    customer_id = row.get("stripe_customer_id")
    if not customer_id:
        raise ValueError("no_customer")

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{os.environ['ALLOWED_ORIGIN']}/account.html",
    )
    return session.url


async def get_subscription_status(user_id: str) -> SubscriptionStatusOut:
    from .cost_service import get_monthly_cost
    from datetime import datetime, timezone

    row = await _get_or_create_subscription_row(user_id)
    month_year = datetime.now(timezone.utc).strftime("%Y-%m")
    monthly_cost = await get_monthly_cost(user_id, month_year)

    period_end = None
    if row.get("current_period_end"):
        period_end = datetime.fromisoformat(row["current_period_end"])

    return SubscriptionStatusOut(
        status=row.get("status", "inactive"),
        current_period_end=period_end,
        free_messages_used=row.get("free_messages_used", 0),
        monthly_cost_usd=monthly_cost,
    )


async def is_subscriber(user_id: str) -> bool:
    db = await get_supabase()
    result = await db.table("user_subscriptions").select("status").eq("user_id", user_id).execute()
    if result.data:
        return result.data[0].get("status") == "active"
    return False


async def can_use_free_tier(user_id: str) -> bool:
    limit = int(os.environ.get("FREE_TIER_MESSAGE_LIMIT", "10"))
    db = await get_supabase()
    result = await db.table("user_subscriptions").select("free_messages_used").eq("user_id", user_id).execute()
    if result.data:
        return result.data[0].get("free_messages_used", 0) < limit
    return True


async def increment_free_messages(user_id: str) -> None:
    row = await _get_or_create_subscription_row(user_id)
    used = row.get("free_messages_used", 0)
    db = await get_supabase()
    await db.table("user_subscriptions").update({"free_messages_used": used + 1}).eq("user_id", user_id).execute()


# ── Stripe webhook handlers ──────────────────────────────────────────────────

async def handle_checkout_complete(session: dict) -> None:
    user_id = session["metadata"].get("user_id")
    if not user_id:
        return
    db = await get_supabase()
    update_data = {
        "stripe_customer_id": session.get("customer"),
        "stripe_subscription_id": session.get("subscription"),
        "status": "active",
    }
    existing = await db.table("user_subscriptions").select("id").eq("user_id", user_id).execute()
    if existing.data:
        await db.table("user_subscriptions").update(update_data).eq("user_id", user_id).execute()
    else:
        await db.table("user_subscriptions").insert({"user_id": user_id, **update_data}).execute()


async def handle_subscription_updated(sub: dict) -> None:
    db = await get_supabase()
    period_end = datetime.fromtimestamp(sub["current_period_end"], tz=timezone.utc).isoformat()
    await db.table("user_subscriptions").update({
        "status": sub["status"],
        "current_period_end": period_end,
    }).eq("stripe_subscription_id", sub["id"]).execute()


async def handle_subscription_deleted(sub: dict) -> None:
    db = await get_supabase()
    await db.table("user_subscriptions").update({
        "status": "cancelled",
        "stripe_subscription_id": None,
        "current_period_end": None,
    }).eq("stripe_subscription_id", sub["id"]).execute()


async def handle_payment_failed(invoice: dict) -> None:
    db = await get_supabase()
    await db.table("user_subscriptions").update({
        "status": "past_due",
    }).eq("stripe_subscription_id", invoice.get("subscription")).execute()
