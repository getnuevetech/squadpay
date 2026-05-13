"""Stripe Checkout integration (Phase E + Phase 3 ledger refactor).

Server is the source of truth for amounts — frontend only sends origin URL.

Phase 3 (June 2025) — Immutable Ledger + 2-way idempotency
──────────────────────────────────────────────────────────
For every charge we now:
  1. Generate a server-side ``txn_id = tx_charge_<ulid>`` BEFORE talking to
     Stripe and stash it on the ``payment_transactions`` row.
  2. Pass that ``txn_id`` as Stripe's ``idempotency_key`` so a network
     retry / app crash doesn't double-charge — Stripe returns the original
     Session for the second call.
  3. On finalization (status poll OR webhook), call
     ``ledger.record_charge_event(txn_id=...)`` which is itself idempotent
     (it no-ops if rows for the txn already exist).
"""
from __future__ import annotations
import datetime as dt
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from adapters.registry import get_charge_adapter

from ledger import make_txn_id, record_charge_event, to_cents

logger = logging.getLogger(__name__)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class CreateCheckoutIn(BaseModel):
    origin_url: str  # frontend host (window.location.origin), used to build success/cancel URLs
    app_return_url: Optional[str] = None  # native deep link (Phase F1.1)


def attach_payment_routes(api_router: APIRouter, db):

    def _stripe_api_key() -> str:
        return os.environ.get("STRIPE_API_KEY") or "sk_test_emergent"

    async def _post_charge_ledger(tx: dict) -> bool:
        """Idempotently write the charge ledger event for this payment_transactions row.

        Returns True if rows were posted (or already present); False on failure.
        """
        txn_id = tx.get("txn_id")
        if not txn_id:
            # Pre-Phase-3 row (no txn_id stored). Skip rather than fail.
            logger.warning(f"[ledger] skipping charge ledger — missing txn_id on tx={tx.get('id')}")
            return False
        try:
            await record_charge_event(
                db,
                txn_id=txn_id,
                bill_id=tx.get("group_id"),
                user_id=tx.get("user_id") or tx.get("lead_id"),
                gross_cents=to_cents(tx.get("amount") or 0),
                currency=tx.get("currency") or "usd",
                reference={
                    "stripe_session_id": tx.get("session_id"),
                    "kind": (tx.get("metadata") or {}).get("kind"),
                    "payment_transaction_id": tx.get("id"),
                },
                kind=(tx.get("metadata") or {}).get("kind") or "group_lead_pay",
            )
            await db.payment_transactions.update_one(
                {"id": tx["id"]},
                {"$set": {"ledger_posted": True, "ledger_posted_at": _now()}},
            )
            return True
        except Exception as e:
            logger.exception(f"[ledger] post-charge write failed for txn={txn_id}: {e}")
            return False

    @api_router.post("/groups/{group_id}/checkout-session")
    async def create_checkout(group_id: str, body: CreateCheckoutIn, http_request: Request):
        """Lead initiates a real Stripe payment for the merchant total of this group.

        Amount is taken from the group document (server-side; never trust client).
        Uses a pre-generated ``txn_id`` as Stripe idempotency_key so retries are safe.
        """
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Squad not found")
        if group.get("is_blocked"):
            raise HTTPException(403, "This squad has been blocked by an administrator.")
        if group.get("status") != "open":
            raise HTTPException(400, "Bill already paid")
        amount = float(group.get("total_amount") or 0)
        if amount <= 0:
            raise HTTPException(400, "Squad total must be > 0")

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

        # Phase 3 — pre-generate the canonical txn_id BEFORE talking to Stripe.
        txn_id = make_txn_id("charge")

        # Phase 4 — resolve the active charge adapter (currently Stripe).
        adapter = await get_charge_adapter(db)
        try:
            sess = await adapter.create_checkout_session(
                amount_cents=int(round(amount * 100)),
                currency="usd",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "group_id": group_id,
                    "lead_id": str(group.get("lead_id") or ""),
                    "kind": "group_lead_pay",
                    "txn_id": txn_id,
                },
                idempotency_key=txn_id,
                product_name=f"SquadPay merchant payment — {group.get('title') or 'Group Bill'}",
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"[{adapter.slug}] create_checkout_session failed: {e}")
            raise HTTPException(502, f"Charge gateway error: {e}")

        # Mandatory payment_transactions ledger row (status=initiated)
        tx = {
            "id": f"px_{sess.session_id[:14]}",
            "session_id": sess.session_id,
            "txn_id": txn_id,
            "gateway_slug": adapter.slug,
            "group_id": group_id,
            "lead_id": group.get("lead_id"),
            "amount": round(amount, 2),
            "currency": "usd",
            "status": "initiated",  # initiated|complete|expired|failed
            "payment_status": "pending",  # mirrors gateway's payment_status
            "metadata": {"kind": "group_lead_pay", "txn_id": txn_id, "gateway": adapter.slug},
            "applied": False,  # idempotency: True after group marked paid
            "ledger_posted": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.payment_transactions.insert_one(tx.copy())
        return {"url": sess.url, "session_id": sess.session_id, "amount": tx["amount"], "txn_id": txn_id}

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

        try:
            adapter = await get_charge_adapter(db)
            ss = await adapter.retrieve_session(session_id)
            from types import SimpleNamespace
            status = SimpleNamespace(
                status=ss.status,
                payment_status=ss.payment_status,
                amount_total=ss.amount_total_cents,
                currency=ss.currency,
                metadata=ss.metadata,
            )
        except Exception as e:
            logger.exception(f"[charge-adapter] get_checkout_status failed: {e}")
            raise HTTPException(502, f"Charge gateway error: {e}")

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
            # Phase 3 — write immutable ledger event (idempotent inside helper)
            await _post_charge_ledger({**tx, **update})
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
        adapter = await get_charge_adapter(db)
        # Set webhook URL on adapter (Stripe uses it to construct the verifier)
        host_url = str(request.base_url).rstrip("/")
        try:
            adapter.webhook_url = f"{host_url}/api/webhook/stripe"  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            evt = await adapter.verify_webhook(body, sig)
        except Exception as e:
            logger.exception(f"[charge-webhook] verify failed: {e}")
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
                    # Phase 3 — write immutable ledger event (idempotent)
                    await _post_charge_ledger({**tx, "applied": True})
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
