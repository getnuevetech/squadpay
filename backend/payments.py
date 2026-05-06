"""Stripe Checkout integration (Phase E).

Uses the Emergent-managed flow (`emergentintegrations.payments.stripe.checkout`).
Server is the source of truth for amounts — frontend only sends origin URL.
"""
from __future__ import annotations
import datetime as dt
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from emergentintegrations.payments.stripe.checkout import (
    StripeCheckout,
    CheckoutSessionRequest,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class CreateCheckoutIn(BaseModel):
    origin_url: str  # frontend host (window.location.origin), used to build success/cancel URLs
    app_return_url: Optional[str] = None  # native deep link (Phase F1.1)


def attach_payment_routes(api_router: APIRouter, db):

    def _stripe(http_request: Request) -> StripeCheckout:
        api_key = os.environ.get("STRIPE_API_KEY") or "sk_test_emergent"
        host_url = str(http_request.base_url).rstrip("/")
        webhook_url = f"{host_url}/api/webhook/stripe"
        return StripeCheckout(api_key=api_key, webhook_url=webhook_url)

    @api_router.post("/groups/{group_id}/checkout-session")
    async def create_checkout(group_id: str, body: CreateCheckoutIn, http_request: Request):
        """Lead initiates a real Stripe payment for the merchant total of this group.

        Amount is taken from the group document (server-side; never trust client).
        """
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        if group.get("is_blocked"):
            raise HTTPException(403, "This group has been blocked by an administrator.")
        if group.get("status") != "open":
            raise HTTPException(400, "Bill already paid")
        amount = float(group.get("total_amount") or 0)
        if amount <= 0:
            raise HTTPException(400, "Group total must be > 0")

        origin = (body.origin_url or "").rstrip("/")
        if not origin.startswith("http"):
            raise HTTPException(400, "origin_url must include scheme (http(s)://...)")

        # Phase F1.1 native bridge support
        app_return = (body.app_return_url or "").strip()
        if app_return:
            from urllib.parse import quote
            success_url = (
                f"{origin}/api/checkout/native-bridge"
                f"?session_id={{CHECKOUT_SESSION_ID}}"
                f"&dest={quote(app_return, safe='')}"
                f"&kind=lead_pay"
            )
            cancel_url = (
                f"{origin}/api/checkout/native-bridge"
                f"?session_id={{CHECKOUT_SESSION_ID}}"
                f"&dest={quote(app_return, safe='')}"
                f"&kind=lead_pay&cancel=1"
            )
        else:
            success_url = f"{origin}/group/{group_id}/pay?session_id={{CHECKOUT_SESSION_ID}}"
            cancel_url = f"{origin}/group/{group_id}/pay?stripe_cancel=1"

        stripe_checkout = _stripe(http_request)
        try:
            session = await stripe_checkout.create_checkout_session(
                CheckoutSessionRequest(
                    amount=round(amount, 2),
                    currency="usd",
                    success_url=success_url,
                    cancel_url=cancel_url,
                    metadata={
                        "group_id": group_id,
                        "lead_id": str(group.get("lead_id") or ""),
                        "kind": "group_lead_pay",
                    },
                )
            )
        except Exception as e:
            logger.exception(f"[stripe] create_checkout_session failed: {e}")
            raise HTTPException(502, f"Stripe error: {e}")

        # Mandatory payment_transactions ledger row (status=initiated)
        tx = {
            "id": f"px_{session.session_id[:14]}",
            "session_id": session.session_id,
            "group_id": group_id,
            "lead_id": group.get("lead_id"),
            "amount": round(amount, 2),
            "currency": "usd",
            "status": "initiated",  # initiated|complete|expired|failed
            "payment_status": "pending",  # mirrors Stripe's payment_status
            "metadata": {"kind": "group_lead_pay"},
            "applied": False,  # idempotency: True after group marked paid
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.payment_transactions.insert_one(tx.copy())
        return {"url": session.url, "session_id": session.session_id, "amount": tx["amount"]}

    @api_router.get("/checkout/status/{session_id}")
    async def get_checkout_status(session_id: str, http_request: Request):
        tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        if not tx:
            raise HTTPException(404, "Payment session not found")
        if tx.get("applied"):
            return {
                "session_id": session_id,
                "status": tx.get("status"),
                "payment_status": tx.get("payment_status"),
                "amount_total": int(round(float(tx.get("amount") or 0) * 100)),
                "currency": tx.get("currency"),
                "applied": True,
                "group_id": tx.get("group_id"),
            }

        stripe_checkout = _stripe(http_request)
        try:
            # Workaround: emergentintegrations' get_checkout_status fails with Pydantic v2
            # rejecting Stripe's StripeObject metadata. Call Stripe SDK directly.
            import stripe as _stripe_sdk
            from types import SimpleNamespace
            _stripe_sdk.api_key = os.environ.get("STRIPE_API_KEY") or "sk_test_emergent"
            s = _stripe_sdk.checkout.Session.retrieve(session_id)
            # stripe.checkout.Session is a StripeObject; access fields by attribute
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
            status = SimpleNamespace(
                status=getattr(s, "status", None),
                payment_status=getattr(s, "payment_status", None),
                amount_total=getattr(s, "amount_total", None),
                currency=getattr(s, "currency", None),
                metadata=meta_dict,
            )
        except Exception as e:
            logger.exception(f"[stripe] get_checkout_status failed: {e}")
            raise HTTPException(502, f"Stripe error: {e}")

        update: dict = {
            "status": status.status,
            "payment_status": status.payment_status,
            "updated_at": _now(),
        }
        # Stripe returns status='complete' once the session is paid; payment_status='paid' is final.
        if status.payment_status == "paid" and not tx.get("applied"):
            # Mark group as paid (idempotent)
            group = await db.groups.find_one({"id": tx["group_id"]}, {"_id": 0})
            if group and group.get("status") == "open":
                await db.groups.update_one(
                    {"id": tx["group_id"]},
                    {"$set": {
                        "status": "paid",
                        "lead_paid_at": _now(),
                        "funding_mode": group.get("funding_mode") or "lead",
                        "stripe_session_id": session_id,
                    }},
                )
            update["applied"] = True
        await db.payment_transactions.update_one({"session_id": session_id}, {"$set": update})

        return {
            "session_id": session_id,
            "status": status.status,
            "payment_status": status.payment_status,
            "amount_total": status.amount_total,
            "currency": status.currency,
            "applied": bool(update.get("applied") or tx.get("applied")),
            "group_id": tx.get("group_id"),
        }

    @api_router.post("/webhook/stripe")
    async def stripe_webhook(request: Request):
        body = await request.body()
        sig = request.headers.get("Stripe-Signature")
        stripe_checkout = _stripe(request)
        try:
            evt = await stripe_checkout.handle_webhook(body, sig)
        except Exception as e:
            logger.exception(f"[stripe-webhook] failed: {e}")
            raise HTTPException(400, f"Webhook error: {e}")
        # Best-effort sync: if a checkout session became paid, ensure group/contrib state.
        try:
            tx = await db.payment_transactions.find_one(
                {"session_id": evt.session_id}, {"_id": 0}
            )
            if not tx:
                return {"ok": True, "ignored": "no-tx"}
            kind = (tx.get("metadata") or {}).get("kind") or "group_lead_pay"

            if evt.payment_status == "paid" and not tx.get("applied"):
                if kind == "group_lead_pay":
                    # Lead pays merchant directly via Stripe -> mark group paid
                    group = await db.groups.find_one({"id": tx["group_id"]}, {"_id": 0})
                    if group and group.get("status") == "open":
                        await db.groups.update_one(
                            {"id": tx["group_id"]},
                            {"$set": {
                                "status": "paid",
                                "lead_paid_at": _now(),
                                "funding_mode": group.get("funding_mode") or "lead",
                                "stripe_session_id": evt.session_id,
                            }},
                        )
                    await db.payment_transactions.update_one(
                        {"session_id": evt.session_id},
                        {"$set": {"status": "complete", "payment_status": "paid",
                                  "applied": True, "updated_at": _now()}},
                    )
                elif kind == "group_member_contribute":
                    # Finalize member contribution + auto-issue card if fully funded
                    # (Same logic as GET /contribute/status; webhook is idempotent backup.)
                    import requests as _req
                    try:
                        host = str(request.base_url).rstrip("/")
                        _req.get(f"{host}/api/contribute/status/{evt.session_id}", timeout=10)
                    except Exception as e2:
                        logger.warning(f"[stripe-webhook] member finalize self-call failed: {e2}")
        except Exception as e:
            logger.warning(f"[stripe-webhook] post-process failed: {e}")
        return {
            "ok": True,
            "event_type": evt.event_type,
            "session_id": evt.session_id,
            "payment_status": evt.payment_status,
        }
