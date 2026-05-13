"""Stripe charge adapter — production-ready (Phase 4).

Wraps the Stripe Python SDK behind the ChargeAdapter contract.

Key features:
  • idempotency_key plumbed through to Stripe (2-way idempotency with our ledger txn_id)
  • webhook signature verification via emergentintegrations (preserves existing wiring)
  • metadata serialization handled here so callers can pass dicts of any shape
"""
from __future__ import annotations
import logging
import os
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import stripe as _stripe_sdk
from emergentintegrations.payments.stripe.checkout import StripeCheckout

from .base import ChargeAdapter, CheckoutSession, CheckoutStatus, WebhookEvent

logger = logging.getLogger(__name__)


class StripeChargeAdapter(ChargeAdapter):
    slug = "stripe"
    display_name = "Stripe"

    def __init__(self, api_key: Optional[str] = None, webhook_url: Optional[str] = None):
        self.api_key = api_key or os.environ.get("STRIPE_API_KEY") or "sk_test_emergent"
        self.webhook_url = webhook_url or ""
        _stripe_sdk.api_key = self.api_key

    async def create_checkout_session(
        self,
        *,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: Dict[str, str],
        idempotency_key: str,
        line_items: Optional[List[Dict]] = None,
        product_name: Optional[str] = None,
    ) -> CheckoutSession:
        # Stripe wants strings everywhere in metadata
        meta_str = {k: str(v) for k, v in (metadata or {}).items()}

        if not line_items:
            line_items = [{
                "price_data": {
                    "currency": currency,
                    "product_data": {"name": product_name or "SquadPay charge"},
                    "unit_amount": int(amount_cents),
                },
                "quantity": 1,
            }]

        try:
            session = _stripe_sdk.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=line_items,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=meta_str,
                idempotency_key=idempotency_key,
            )
        except Exception as e:
            logger.exception(f"[stripe-adapter] create_checkout_session failed: {e}")
            raise

        return CheckoutSession(
            session_id=session.id,
            url=session.url,
            amount_cents=int(amount_cents),
            currency=currency,
            raw={"id": session.id, "url": session.url, "status": getattr(session, "status", None)},
        )

    async def retrieve_session(self, session_id: str) -> CheckoutStatus:
        try:
            s = _stripe_sdk.checkout.Session.retrieve(session_id)
        except Exception as e:
            logger.exception(f"[stripe-adapter] retrieve_session failed: {e}")
            raise

        _meta = getattr(s, "metadata", None)
        if _meta is None:
            meta_dict = {}
        elif hasattr(_meta, "to_dict"):
            meta_dict = _meta.to_dict()
        else:
            try:
                meta_dict = {k: _meta[k] for k in (list(_meta.keys()) if hasattr(_meta, "keys") else [])}
            except Exception:
                meta_dict = {}

        return CheckoutStatus(
            session_id=session_id,
            status=getattr(s, "status", None),
            payment_status=getattr(s, "payment_status", None),
            amount_total_cents=getattr(s, "amount_total", None),
            currency=getattr(s, "currency", None),
            metadata=meta_dict,
            raw={"id": session_id},
        )

    async def verify_webhook(self, body: bytes, signature: Optional[str]) -> WebhookEvent:
        # Use the existing emergentintegrations wrapper for signature verification.
        checkout = StripeCheckout(api_key=self.api_key, webhook_url=self.webhook_url or "")
        try:
            evt = await checkout.handle_webhook(body, signature)
        except Exception as e:
            logger.exception(f"[stripe-adapter] verify_webhook failed: {e}")
            raise

        return WebhookEvent(
            event_type=getattr(evt, "event_type", "unknown"),
            session_id=getattr(evt, "session_id", None),
            payment_status=getattr(evt, "payment_status", None),
            raw={"event_type": getattr(evt, "event_type", None)},
        )
