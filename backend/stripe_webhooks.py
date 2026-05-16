"""
stripe_webhooks.py — Real-Time Ledger Reconciliation, Phase 2.
==============================================================
Inbound Stripe event listeners that mirror the existing payout-side webhook
infrastructure (which handles `payout.*` events for cash-out) for the
OPPOSITE direction of money flow: contributions (payment_intent.*),
refunds (charge.refunded, refund.*) and Squad-Card spend (issuing_*).

Three independent endpoints — each takes its own webhook secret so an admin
can rotate one credential without touching the others:

  POST /api/webhook/stripe-payments    — payment_intent.* / charge.succeeded
  POST /api/webhook/stripe-refunds     — charge.refunded / refund.*
  POST /api/webhook/stripe-issuing     — issuing_transaction.* / authorization.*

Behaviour notes:
  • Idempotency — every event is keyed by `event.id` in `payment_events`
    collection. Re-deliveries are no-ops (Stripe at-least-once delivery).
  • Drift writes — any event we can't match to an internal record creates
    a row in `reconciliation_drift` (Phase 1 collection). Admin sees these
    surface in the existing /admin/reconciliation-drift screen via new
    drift `kind` values (stripe_orphan_payment, stripe_orphan_refund,
    issuing_spend_drift).
  • Signature verification — uses `stripe.Webhook.construct_event` with
    the webhook secret from `db.integrations` (admin Integrations page).
    Per-endpoint secrets are stored under separate keys so admins rotating
    one (e.g. issuing) don't disrupt the others.
  • Graceful degradation — if no secret is configured the endpoint returns
    501 (Not Implemented) so Stripe will retry once configured.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("stripe_webhooks")

try:
    import stripe as _stripe  # type: ignore
except Exception:
    _stripe = None  # SDK absent → endpoints will fail closed.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "drft_") -> str:
    return f"{prefix}{int(time.time() * 1000):x}"


async def _get_webhook_secret(db, key: str) -> Optional[str]:
    """Pull the named webhook secret from the admin Integrations document.

    Keys we look up:
       webhook_secret              — legacy: shared across all stripe events
                                      (used by existing /webhook/stripe-connect)
       webhook_secret_payments     — Phase 2 inbound payments
       webhook_secret_refunds      — Phase 2 refunds
       webhook_secret_issuing      — Phase 2 issuing

    Storage layout (set by admin via POST /api/admin/integrations/stripe):
       db.app_settings { key: "integrations" }.stripe.<key>_enc  (encrypted)
       db.app_settings { key: "integrations" }.stripe.<key>      (plain, dev/test only)

    Falls back to env `STRIPE_WEBHOOK_SECRET_<KIND>` if not in DB, then to
    `STRIPE_WEBHOOK_SECRET` for compatibility with dev setups.
    """
    # The admin layer persists Stripe config under app_settings, NOT a
    # separate `integrations` collection — see admin_integrations.py.
    doc = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {}
    stripe_cfg = (doc.get("stripe") or {})

    # Prefer the encrypted value if present (admin UI always writes _enc).
    enc_key = f"{key}_enc"
    legacy_enc_key = "webhook_secret_enc"
    plain = stripe_cfg.get(key) or stripe_cfg.get("webhook_secret")  # legacy plain
    if plain:
        return plain
    encoded = stripe_cfg.get(enc_key) or stripe_cfg.get(legacy_enc_key)
    if encoded:
        try:
            from integrations import decrypt_secret
            decoded = decrypt_secret(encoded)
            if decoded:
                return decoded
        except Exception as e:
            logger.warning(f"[stripe-webhook] decrypt {enc_key} failed: {e}")
    return (
        os.environ.get(f"STRIPE_WEBHOOK_SECRET_{key.split('_')[-1].upper()}")
        or os.environ.get("STRIPE_WEBHOOK_SECRET")
    )


async def _record_event(db, event: dict, kind_tag: str) -> bool:
    """Insert the raw event into `payment_events` with id-based idempotency.

    Returns True if NEW (handler should process), False if already seen.
    """
    event_id = event.get("id")
    if not event_id:
        return False
    try:
        await db.payment_events.insert_one({
            "id": event_id,
            "type": event.get("type"),
            "kind_tag": kind_tag,                  # 'payments' | 'refunds' | 'issuing'
            "livemode": bool(event.get("livemode")),
            "created": event.get("created"),
            "received_at": _now_iso(),
            "data": event.get("data") or {},
        })
        return True
    except Exception as e:
        # Duplicate _id (unique index will be added in startup) or any other write
        # error — treat as "already seen" to keep the webhook idempotent.
        msg = str(e).lower()
        if "duplicate" in msg or "e11000" in msg:
            return False
        logger.warning(f"[stripe-webhook] event recording failed: {e}")
        # Fail open: don't reject the event over a logging hiccup.
        return True


async def _write_drift(db, *, kind: str, group_id: Optional[str], expected: float,
                       observed: float, notes: str, event_id: Optional[str] = None,
                       group_title: Optional[str] = None,
                       group_status: Optional[str] = None) -> str:
    """Insert (or refresh) a row in `reconciliation_drift` so the Phase 1
    admin screen surfaces it alongside DB-denorm / settlement-imbalance
    drifts. Compound key (group_id, kind, event_id) prevents duplicate
    rows when Stripe re-delivers the same event.
    """
    filt = {"kind": kind, "resolved": False}
    if group_id:
        filt["group_id"] = group_id
    if event_id:
        filt["event_id"] = event_id

    delta = round(observed - expected, 2)
    existing = await db.reconciliation_drift.find_one(filt)
    if existing:
        await db.reconciliation_drift.update_one(
            {"id": existing["id"]},
            {"$set": {
                "expected": round(expected, 2),
                "observed": round(observed, 2),
                "delta": delta,
                "detected_at": _now_iso(),
            }},
        )
        return existing["id"]
    new_id = _new_id()
    await db.reconciliation_drift.insert_one({
        "id": new_id,
        "group_id": group_id,
        "group_title": group_title or "(unknown squad)",
        "group_status": group_status or "(unknown)",
        "kind": kind,
        "expected": round(expected, 2),
        "observed": round(observed, 2),
        "delta": delta,
        "detected_at": _now_iso(),
        "resolved": False,
        "event_id": event_id,
        "notes": notes,
    })
    return new_id


# ──────────────────────────────────────────────────────────────────────────
# Per-endpoint handlers
# ──────────────────────────────────────────────────────────────────────────

async def _handle_payments_event(db, event: dict):
    """Process payment_intent.succeeded / charge.succeeded — the inbound
    contribution path. Updates `payment_transactions.webhook_verified_at`
    and writes a drift row if the PI isn't recognised.
    """
    evt_type = event.get("type") or ""
    obj = (event.get("data") or {}).get("object") or {}
    pi_id: Optional[str] = None
    amount_received: float = 0.0
    if evt_type.startswith("payment_intent."):
        pi_id = obj.get("id")
        amount_received = round((obj.get("amount_received") or obj.get("amount") or 0) / 100.0, 2)
    elif evt_type.startswith("charge."):
        pi_id = obj.get("payment_intent")
        amount_received = round((obj.get("amount_captured") or obj.get("amount") or 0) / 100.0, 2)
    if not pi_id:
        return {"ok": True, "ignored": "no-pi-id"}

    tx = await db.payment_transactions.find_one({"payment_intent_id": pi_id}, {"_id": 0})
    if not tx:
        # Orphan: Stripe says we received money for a PI we don't track.
        await _write_drift(
            db,
            kind="stripe_orphan_payment",
            group_id=(obj.get("metadata") or {}).get("group_id"),
            expected=0.0,
            observed=amount_received,
            event_id=event.get("id"),
            notes=(
                f"Stripe webhook ({evt_type}) reports {amount_received:.2f} succeeded for "
                f"PaymentIntent {pi_id} but no matching row exists in payment_transactions. "
                "Possible causes: PI was created outside the app, or the create-PI handler "
                "failed to persist before Stripe accepted the payment."
            ),
        )
        return {"ok": True, "drift": "stripe_orphan_payment", "pi_id": pi_id}

    # Stamp the row with webhook verification so admin can audit which
    # contributions were confirmed by Stripe vs. only by the success-redirect.
    await db.payment_transactions.update_one(
        {"payment_intent_id": pi_id},
        {"$set": {
            "webhook_verified_at": _now_iso(),
            "webhook_event_id": event.get("id"),
            "stripe_payment_status": obj.get("status") or "succeeded",
            "stripe_amount_received_cents": int(amount_received * 100),
        }},
    )

    # If we tracked a different amount than Stripe captured, write drift.
    expected = float(tx.get("amount") or 0.0)
    if abs(expected - amount_received) > 0.01:
        await _write_drift(
            db,
            kind="stripe_payment_amount_drift",
            group_id=tx.get("group_id"),
            expected=expected,
            observed=amount_received,
            event_id=event.get("id"),
            notes=(
                f"PI {pi_id} captured {amount_received:.2f} but the contribution row was "
                f"created for {expected:.2f}. Likely cause: partial capture or amount edit."
            ),
        )
    return {"ok": True, "pi_id": pi_id, "verified": True}


async def _handle_refunds_event(db, event: dict):
    """Process charge.refunded / refund.* — auto-mark contributions refunded.

    We don't unwind the contribution from the group's funding aggregate
    here (that's a money-out flow with its own auth path); we just mark
    the payment_transactions row and write a drift if there's no match.
    """
    evt_type = event.get("type") or ""
    obj = (event.get("data") or {}).get("object") or {}
    pi_id: Optional[str] = None
    refunded_amount: float = 0.0
    if evt_type == "charge.refunded":
        pi_id = obj.get("payment_intent")
        refunded_amount = round((obj.get("amount_refunded") or 0) / 100.0, 2)
    elif evt_type.startswith("refund."):
        pi_id = obj.get("payment_intent")
        refunded_amount = round((obj.get("amount") or 0) / 100.0, 2)
    if not pi_id:
        return {"ok": True, "ignored": "no-pi-id"}

    tx = await db.payment_transactions.find_one({"payment_intent_id": pi_id}, {"_id": 0})
    if not tx:
        await _write_drift(
            db,
            kind="stripe_orphan_refund",
            group_id=(obj.get("metadata") or {}).get("group_id"),
            expected=0.0,
            observed=refunded_amount,
            event_id=event.get("id"),
            notes=(
                f"Stripe webhook ({evt_type}) reports {refunded_amount:.2f} refunded for "
                f"PaymentIntent {pi_id} but we have no matching contribution. "
                "Admin should investigate whether this refund was triggered outside SquadPay."
            ),
        )
        return {"ok": True, "drift": "stripe_orphan_refund", "pi_id": pi_id}

    await db.payment_transactions.update_one(
        {"payment_intent_id": pi_id},
        {"$set": {
            "refunded": True,
            "refunded_amount_cents": int(refunded_amount * 100),
            "refunded_at": _now_iso(),
            "refund_webhook_event_id": event.get("id"),
        }},
    )
    return {"ok": True, "pi_id": pi_id, "refunded_amount": refunded_amount}


async def _handle_issuing_event(db, event: dict):
    """Process issuing_transaction.created / issuing_authorization.created —
    the Squad-Card spend path. Updates `groups.virtual_card.spent` and
    writes drift if our total disagrees with Stripe's.
    """
    evt_type = event.get("type") or ""
    obj = (event.get("data") or {}).get("object") or {}
    card_id = obj.get("card") if isinstance(obj.get("card"), str) else (obj.get("card") or {}).get("id")
    if not card_id:
        return {"ok": True, "ignored": "no-card-id"}

    # Locate the squad whose virtual card matches.
    g = await db.groups.find_one(
        {"virtual_card.stripe_card_id": card_id},
        {"_id": 0, "id": 1, "title": 1, "status": 1, "virtual_card": 1},
    )
    if not g:
        # Could be the platform master card — that has its own ledger.
        master = await db.master_card.find_one({"stripe_card_id": card_id}, {"_id": 0})
        if master:
            return {"ok": True, "ignored": "master-card", "card_id": card_id}
        await _write_drift(
            db,
            kind="issuing_orphan_card",
            group_id=None,
            expected=0.0,
            observed=round((obj.get("amount") or 0) / 100.0, 2),
            event_id=event.get("id"),
            notes=(
                f"Stripe Issuing event {evt_type} for card {card_id} but the card isn't "
                "associated with any squad in our DB. May indicate a leaked/orphaned card."
            ),
        )
        return {"ok": True, "drift": "issuing_orphan_card", "card_id": card_id}

    if evt_type.startswith("issuing_transaction."):
        # `issuing_transaction.created` — captured spend; amount is negative for spend.
        spent_delta_cents = abs(int(obj.get("amount") or 0))
        spent_delta = round(spent_delta_cents / 100.0, 2)
        # Append to local transaction history and increment running total.
        await db.groups.update_one(
            {"id": g["id"]},
            {
                "$push": {"virtual_card.transactions": {
                    "stripe_transaction_id": obj.get("id"),
                    "amount": spent_delta,
                    "currency": obj.get("currency") or "usd",
                    "merchant": (obj.get("merchant_data") or {}).get("name"),
                    "merchant_category": (obj.get("merchant_data") or {}).get("category"),
                    "created_at": _now_iso(),
                    "webhook_event_id": event.get("id"),
                }},
                "$inc": {"virtual_card.spent": spent_delta},
                "$set": {"virtual_card.last_webhook_at": _now_iso()},
            },
        )
        return {"ok": True, "group_id": g["id"], "spent_delta": spent_delta}

    if evt_type.startswith("issuing_authorization."):
        # Authorization (pending). Track separately for visibility but
        # don't touch the spent total — only the transaction (captured)
        # increases the spent number. This keeps single-source-of-truth.
        await db.groups.update_one(
            {"id": g["id"]},
            {"$push": {"virtual_card.authorizations": {
                "stripe_authorization_id": obj.get("id"),
                "amount": round((obj.get("amount") or 0) / 100.0, 2),
                "approved": bool(obj.get("approved")),
                "created_at": _now_iso(),
                "webhook_event_id": event.get("id"),
            }}},
        )
        return {"ok": True, "group_id": g["id"], "authorization": obj.get("id")}

    return {"ok": True, "ignored": f"unhandled {evt_type}"}


# ──────────────────────────────────────────────────────────────────────────
# Endpoint mounting
# ──────────────────────────────────────────────────────────────────────────

async def _verify_and_dispatch(db, request: Request, secret_key: str, handler) -> dict:
    body_bytes = await request.body()
    sig = request.headers.get("Stripe-Signature")
    if not _stripe:
        raise HTTPException(501, "Stripe SDK not installed on this backend")
    secret = await _get_webhook_secret(db, secret_key)
    if not secret:
        raise HTTPException(
            501,
            f"Webhook secret '{secret_key}' not configured in Admin → Integrations → Stripe",
        )
    if not sig:
        raise HTTPException(400, "Missing Stripe-Signature header")
    try:
        event = _stripe.Webhook.construct_event(body_bytes, sig, secret)
    except Exception as e:
        logger.exception(f"[stripe-webhook] signature verification failed: {e}")
        raise HTTPException(400, f"Webhook error: {e}")
    event_dict = event if isinstance(event, dict) else event.to_dict_recursive()
    # Idempotency — bail out on re-delivery.
    is_new = await _record_event(db, event_dict, secret_key.split("_")[-1])
    if not is_new:
        return {"ok": True, "duplicate": True, "event_id": event_dict.get("id")}
    return await handler(db, event_dict)


def attach_stripe_webhooks(api_router: APIRouter, db):
    """Mount the three inbound Stripe webhook endpoints + ensure the
    idempotency index on `payment_events.id` (best-effort).
    """
    import asyncio as _asyncio

    async def _ensure_indexes():
        try:
            await db.payment_events.create_index("id", unique=True)
        except Exception as e:
            logger.warning(f"[stripe-webhook] index create failed: {e}")

    try:
        _asyncio.create_task(_ensure_indexes())
    except Exception:
        pass

    @api_router.post("/webhook/stripe-payments")
    async def stripe_payments_webhook(request: Request):
        return await _verify_and_dispatch(db, request, "webhook_secret_payments", _handle_payments_event)

    @api_router.post("/webhook/stripe-refunds")
    async def stripe_refunds_webhook(request: Request):
        return await _verify_and_dispatch(db, request, "webhook_secret_refunds", _handle_refunds_event)

    @api_router.post("/webhook/stripe-issuing")
    async def stripe_issuing_webhook(request: Request):
        return await _verify_and_dispatch(db, request, "webhook_secret_issuing", _handle_issuing_event)
