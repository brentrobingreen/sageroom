import logging
import os

import stripe
from fastapi import APIRouter, HTTPException, Request

from ..services.billing_service import (
    handle_checkout_complete,
    handle_payment_failed,
    handle_subscription_deleted,
    handle_subscription_updated,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict:
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=body,
            sig_header=sig,
            secret=os.environ["STRIPE_WEBHOOK_SECRET"],
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")
    except Exception as e:
        logger.error("Webhook parse error: %s", e)
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")

    event_type = event["type"]
    data = event["data"]["object"]

    try:
        if event_type == "checkout.session.completed":
            await handle_checkout_complete(data)
        elif event_type == "customer.subscription.updated":
            await handle_subscription_updated(data)
        elif event_type == "customer.subscription.deleted":
            await handle_subscription_deleted(data)
        elif event_type == "invoice.payment_failed":
            await handle_payment_failed(data)
        else:
            logger.debug("Unhandled Stripe event: %s", event_type)
    except Exception as e:
        logger.error("Webhook handler error for %s: %s", event_type, e)
        raise HTTPException(status_code=500, detail="Webhook processing failed.")

    return {"received": True}
