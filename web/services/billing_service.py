import os
from datetime import datetime, timezone

import stripe
from fastapi import HTTPException

from ..db import get_supabase
from ..models import SubscriptionStatusOut

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

# Credit pack definitions — single source of truth for backend + frontend
CREDIT_PACKS = {
    "starter":  {"name": "Starter",  "credits": 50,  "amount_aud_cents": 500,  "price_label": "$5"},
    "standard": {"name": "Standard", "credits": 150, "amount_aud_cents": 1500, "price_label": "$15"},
    "pro":      {"name": "Pro",      "credits": 350, "amount_aud_cents": 3000, "price_label": "$30"},
}


def _stripe_price_id(pack_id: str) -> str:
    key = f"STRIPE_CREDITS_{pack_id.upper()}_PRICE_ID"
    return os.environ.get(key, "")


async def _get_or_create_subscription_row(user_id: str) -> dict:
    db = await get_supabase()
    result = await db.table("user_subscriptions").select("*").eq("user_id", user_id).execute()
    if result.data:
        return result.data[0]
    insert = await db.table("user_subscriptions").insert({"user_id": user_id}).execute()
    return insert.data[0]


async def check_and_deduct_access(user_id: str) -> None:
    """
    Allows the request if user has free messages remaining or credits.
    Deducts one free message or one credit. Raises 402 otherwise.
    """
    free_limit = int(os.environ.get("FREE_TIER_MESSAGE_LIMIT", "10"))
    db = await get_supabase()
    result = await db.table("user_subscriptions").select(
        "id,free_messages_used,credits_balance"
    ).eq("user_id", user_id).execute()

    if not result.data:
        # First message — create row and allow on free tier
        await db.table("user_subscriptions").insert({
            "user_id": user_id, "free_messages_used": 1,
        }).execute()
        return

    row = result.data[0]
    used = row.get("free_messages_used", 0)
    credits = row.get("credits_balance", 0)

    if used < free_limit:
        await db.table("user_subscriptions").update({
            "free_messages_used": used + 1
        }).eq("user_id", user_id).execute()
        return

    if credits > 0:
        await db.table("user_subscriptions").update({
            "credits_balance": credits - 1
        }).eq("user_id", user_id).execute()
        return

    raise HTTPException(
        status_code=402,
        detail="You've used your 10 free messages. Top up your credits to keep chatting.",
    )


async def create_credit_checkout(user_id: str, email: str, pack_id: str) -> str:
    if pack_id not in CREDIT_PACKS:
        raise ValueError(f"unknown_pack:{pack_id}")

    price_id = _stripe_price_id(pack_id)
    if not price_id:
        raise ValueError("price_not_configured")

    pack = CREDIT_PACKS[pack_id]
    row = await _get_or_create_subscription_row(user_id)
    customer_id = row.get("stripe_customer_id")

    session = stripe.checkout.Session.create(
        customer=customer_id or None,
        customer_email=None if customer_id else email,
        mode="payment",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{os.environ['ALLOWED_ORIGIN']}/account.html?credits=success&pack={pack_id}",
        cancel_url=f"{os.environ['ALLOWED_ORIGIN']}/account.html",
        metadata={"user_id": user_id, "pack_id": pack_id, "credits": pack["credits"]},
    )
    return session.url


async def get_subscription_status(user_id: str) -> SubscriptionStatusOut:
    from .cost_service import get_monthly_cost

    row = await _get_or_create_subscription_row(user_id)
    month_year = datetime.now(timezone.utc).strftime("%Y-%m")
    monthly_cost = await get_monthly_cost(user_id, month_year)

    return SubscriptionStatusOut(
        status=row.get("status", "free"),
        credits_balance=row.get("credits_balance", 0),
        free_messages_used=row.get("free_messages_used", 0),
        monthly_cost_usd=monthly_cost,
    )


async def handle_credit_purchase(session: dict) -> None:
    user_id = session["metadata"].get("user_id")
    pack_id = session["metadata"].get("pack_id")
    credits = int(session["metadata"].get("credits", 0))
    if not user_id or not credits:
        return

    db = await get_supabase()
    row = await _get_or_create_subscription_row(user_id)
    current = row.get("credits_balance", 0)

    pack = CREDIT_PACKS.get(pack_id, {})
    await db.table("user_subscriptions").update({
        "credits_balance": current + credits,
        "stripe_customer_id": session.get("customer") or row.get("stripe_customer_id"),
    }).eq("user_id", user_id).execute()

    await db.table("credit_purchases").insert({
        "user_id": user_id,
        "stripe_payment_intent_id": session.get("payment_intent"),
        "pack_id": pack_id,
        "credits": credits,
        "amount_aud_cents": pack.get("amount_aud_cents", 0),
    }).execute()


# ── Legacy subscription handlers (kept for webhook routing) ──────────────────

async def handle_checkout_complete(session: dict) -> None:
    """Route to credit purchase or legacy subscription handler."""
    if session.get("mode") == "payment":
        await handle_credit_purchase(session)


async def handle_subscription_updated(sub: dict) -> None:
    pass  # Subscriptions removed — no-op


async def handle_subscription_deleted(sub: dict) -> None:
    pass


async def handle_payment_failed(invoice: dict) -> None:
    pass
