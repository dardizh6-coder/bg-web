from __future__ import annotations

import time
import uuid
from typing import Any

import stripe

from app.config import settings
from app.db import Db


def stripe_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def _init_stripe() -> None:
    stripe.api_key = settings.STRIPE_SECRET_KEY


def create_checkout_session(client_token: str) -> str:
    if not stripe_configured():
        raise RuntimeError("Stripe is not configured")
    if not settings.PUBLIC_BASE_URL:
        raise RuntimeError("PUBLIC_BASE_URL missing")

    _init_stripe()

    success_url = f"{settings.PUBLIC_BASE_URL}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{settings.PUBLIC_BASE_URL}/?checkout=cancel"

    # Prefer a pre-created Price in Stripe, but allow fallback price_data.
    if settings.STRIPE_PRICE_CHF_199:
        line_items: list[dict[str, Any]] = [{"price": settings.STRIPE_PRICE_CHF_199, "quantity": 1}]
    else:
        line_items = [
            {
                "price_data": {
                    "currency": "chf",
                    "product_data": {"name": "Watermark removal (one-time)"},
                    "unit_amount": 199,
                },
                "quantity": 1,
            }
        ]

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=line_items,
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=client_token,
        metadata={"client_token": client_token, "product": "watermark_removal"},
        allow_promotion_codes=False,
    )
    return session.url


def sync_payment_from_session(db: Db, session_id: str) -> dict[str, Any]:
    """
    Confirms payment via Stripe API (used on redirect after checkout).
    Stores payment + marks client as paid in SQLite when paid.
    """
    if not stripe_configured():
        raise RuntimeError("Stripe is not configured")

    _init_stripe()
    sess = stripe.checkout.Session.retrieve(session_id, expand=["payment_intent", "customer_details"])

    client_token = (sess.get("metadata") or {}).get("client_token") or sess.get("client_reference_id")
    if not client_token:
        raise RuntimeError("Missing client token on session")

    payment_status = sess.get("payment_status")
    amount_total = sess.get("amount_total") or 0
    currency = (sess.get("currency") or "chf").lower()

    out = {
        "client_token": client_token,
        "payment_status": payment_status,
        "amount_total": amount_total,
        "currency": currency,
    }

    if payment_status == "paid":
        payment_intent = sess.get("payment_intent") or {}
        pi_id = payment_intent.get("id")
        db.set_paid(client_token, stripe_customer_id=(sess.get("customer") or None))
        with db.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO payments(
                  id, client_token, amount_chf_centimes, currency, status,
                  stripe_session_id, stripe_payment_intent_id, created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),
                    client_token,
                    int(amount_total),
                    currency,
                    "paid",
                    session_id,
                    pi_id,
                    int(time.time()),
                ),
            )
            conn.commit()
        db.log("info", "payment.paid", f"client={client_token} session={session_id} amount_total={amount_total} {currency}")

    return out


def handle_webhook(db: Db, payload: bytes, sig_header: str | None) -> None:
    if not stripe_configured() or not settings.STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("Stripe webhook not configured")

    _init_stripe()

    event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    etype = event.get("type")

    if etype == "checkout.session.completed":
        sess = event["data"]["object"]
        session_id = sess.get("id")
        # Payment status should be paid, but we keep the same logic.
        if session_id:
            try:
                sync_payment_from_session(db, session_id=session_id)
            except Exception as e:
                db.log("error", "payment.webhook_error", f"{e}")
                raise
    else:
        # Ignore other events for this app.
        pass

