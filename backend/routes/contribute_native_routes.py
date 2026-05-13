"""Native member contribution via Stripe PaymentSheet (Phase 7 — June 2025).

Why this exists
───────────────
The default `/api/groups/{id}/contribute` endpoint hands the user off to
hosted **Stripe Checkout** (web page, opened in a WebView on mobile). That
works but the UX includes a browser-style chrome and one extra tap to reach
Apple Pay / Google Pay.

This endpoint creates a **Stripe PaymentIntent** instead, so the mobile app
can render a native **PaymentSheet** that puts the Apple Pay / Google Pay
buttons front-and-center, fingerprint-confirmable, no browser. Card form
remains available inside the sheet for users without a wallet.

Pre-flight logic is identical to the Checkout path — credits + per-user
share computation are re-used (DRY) via a shared helper.

Flow:
  1. POST  /api/groups/{id}/contribute-payment-intent
       body: {user_id, amount?, notify_on_settled?}
       resp: {client_secret, ephemeral_key, customer_id, publishable_key,
              txn_id, cash_owed, credit_planned, payment_intent_id, ...}
       Side effect: writes a `payment_transactions` row with
                    kind="group_member_contribute_native", status="initiated".

  2. Frontend hands `client_secret` to `PaymentSheet` (or initPaymentSheet)
     and presents it. User completes via Apple Pay / Google Pay / card.

  3. POST /api/groups/{id}/contribute-payment-intent/finalize
       body: {payment_intent_id}
       Looks up the txn, retrieves the PI from Stripe, and on
       status="succeeded":
         - inserts the contribution into db.groups.contributions
         - updates group status / funding_mode
         - writes Phase-3 ledger event (4 rows, idempotent)
         - awards credit-rule bonuses
         - returns the same payload shape as `/contribute/status/{session_id}`

  4. GET /api/stripe/publishable-key
       Tiny helper so the mobile app can fetch the configured publishable
       key. Reads from db.gateway_config first (admin-saved), falls back to
       STRIPE_PUBLISHABLE_KEY in .env. Returns {publishable_key, configured: bool}.
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, Optional

import stripe as _stripe_sdk
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import (
    ContributeIn, new_id, now_iso,
    _consume_user_credits, _recompute_group,
)
from ledger import make_txn_id, record_charge_event, to_cents

logger = logging.getLogger(__name__)


class ContributePIFinalizeIn(BaseModel):
    payment_intent_id: str


async def _resolve_stripe_keys(db) -> Dict[str, Optional[str]]:
    """Pull the live secret + publishable key.

    CRITICAL: returns BOTH keys from the SAME source (gateway_config OR env)
    — never mixed. A mixed-source pair almost always means one key is from
    account A and the other is from account B, which produces Stripe's
    confusing "No such payment_intent" error when the FE PaymentSheet tries
    to confirm a PI that was created on a different account.

    Resolution order:
      1. gateway_config.charge.stripe.credentials_enc — if BOTH secret and
         publishable are present, use them as a pair.
      2. Environment (STRIPE_API_KEY + STRIPE_PUBLISHABLE_KEY) — used only if
         the gateway_config pair is incomplete.

    The returned keys are also fingerprint-checked: Stripe's `_<account_id>_`
    prefix (e.g. `sk_test_51T2maQ…`, `pk_test_51T2maQ…`) must match between
    secret and publishable. If they don't, we log a warning so admins can
    fix the config — but we still return the pair so the caller can decide
    whether to fail loudly or fall through.
    """
    from integrations import decrypt_secret

    cfg = await db.gateway_config.find_one(
        {"group": "charge", "provider_slug": "stripe"}, {"_id": 0}
    )
    creds = (cfg or {}).get("credentials_enc") or {}

    gc_secret: Optional[str] = None
    gc_pub: Optional[str] = creds.get("publishable_key")
    if creds.get("secret_key"):
        try:
            gc_secret = decrypt_secret(creds["secret_key"])
        except Exception:
            gc_secret = None

    env_secret = os.environ.get("STRIPE_API_KEY")
    env_pub = os.environ.get("STRIPE_PUBLISHABLE_KEY")

    # Prefer the gateway_config PAIR when both are present.
    if gc_secret and gc_pub:
        secret, pub, source = gc_secret, gc_pub, "gateway_config"
    elif env_secret and env_pub:
        secret, pub, source = env_secret, env_pub, "env"
    else:
        # Incomplete — fall back to whatever we have. Caller may still work
        # for read-only ops but PaymentSheet will fail.
        secret = gc_secret or env_secret
        pub = gc_pub or env_pub
        source = "mixed/incomplete"

    # Account-id sanity check. Stripe keys are formatted as:
    #   <sk|pk>_<live|test>_<ACCOUNT_PREFIX><RANDOM_KEY_TAIL>
    # NOTE: Stripe does NOT separate the account prefix from the random key
    # tail with an underscore — they're concatenated into one segment.
    # The first ~16 chars of that segment are the account identifier (the
    # same value Stripe uses for `acct_<ACCOUNT_PREFIX>`). The remainder is
    # the per-key random suffix and DIFFERS between sk_ and pk_ even on the
    # same account (which previously produced a false-positive mismatch).
    if secret and pub:
        try:
            s_parts = secret.split("_", 2)  # ['sk', 'test', '<acct><tail>']
            p_parts = pub.split("_", 2)     # ['pk', 'test', '<acct><tail>']
            same_mode = (len(s_parts) >= 2 and len(p_parts) >= 2 and s_parts[1] == p_parts[1])
            # Compare only the account prefix portion of the third segment.
            s_acct = (s_parts[2][:16] if len(s_parts) >= 3 else "")
            p_acct = (p_parts[2][:16] if len(p_parts) >= 3 else "")
            if not same_mode or s_acct != p_acct:
                logger.warning(
                    "[stripe-keys] ACCOUNT MISMATCH source=%s "
                    "secret_acct=%s publishable_acct=%s mode_secret=%s mode_pub=%s — "
                    "PaymentSheet will fail with 'No such payment_intent'. "
                    "Verify both keys belong to the SAME Stripe account in admin Gateway config.",
                    source, s_acct, p_acct,
                    s_parts[1] if len(s_parts) >= 2 else "?",
                    p_parts[1] if len(p_parts) >= 2 else "?",
                )
        except Exception:
            pass

    return {"secret_key": secret, "publishable_key": pub, "source": source}


def _stripe_keys_match(keys: Dict[str, Optional[str]]) -> bool:
    """True iff the secret and publishable keys belong to the same Stripe account+mode.

    Compares the account prefix (first 16 chars of the third underscore-segment),
    not the per-key random tail.
    """
    s = keys.get("secret_key") or ""
    p = keys.get("publishable_key") or ""
    if not s or not p:
        return False
    s_parts = s.split("_", 2)
    p_parts = p.split("_", 2)
    if len(s_parts) < 3 or len(p_parts) < 3:
        return False
    same_mode = s_parts[1] == p_parts[1]
    s_acct = s_parts[2][:16]
    p_acct = p_parts[2][:16]
    return same_mode and s_acct == p_acct


async def _ensure_stripe_customer(db, user_id: str, secret_key: str) -> str:
    """Idempotently create a Stripe Customer for the user (used by PaymentSheet
    for card saving + Apple/Google Pay token reuse). Persists the
    customer_id on db.users.stripe_customer_id."""
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    existing = user.get("stripe_customer_id")
    if existing:
        return existing
    _stripe_sdk.api_key = secret_key
    try:
        cust = _stripe_sdk.Customer.create(
            metadata={"squadpay_user_id": user_id},
            name=user.get("name") or None,
            phone=user.get("phone") or None,
        )
    except Exception as e:
        logger.exception(f"[phase7] Customer.create failed: {e}")
        raise HTTPException(502, f"Stripe error creating Customer: {e}")
    await db.users.update_one(
        {"id": user_id}, {"$set": {"stripe_customer_id": cust.id, "updated_at": now_iso()}}
    )
    return cust.id


def attach_native_contribute_routes(router: APIRouter, db):

    # ── 1. Create PaymentIntent (the meat) ─────────────────────────────
    @router.post("/groups/{group_id}/contribute-payment-intent")
    async def create_contribute_pi(group_id: str, body: ContributeIn):
        # Mirror the eligibility logic of /contribute (DRY would be nicer
        # but Phase 3 already proved the flow is tightly coupled).
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Squad not found")
        if group.get("status") != "open":
            raise HTTPException(400, "Bill already paid; use repay instead")
        if group.get("is_blocked"):
            raise HTTPException(403, "This squad has been blocked by an administrator.")
        user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        if user.get("is_blocked"):
            raise HTTPException(403, "Your account has been blocked. Please contact support.")
        if not user.get("verified"):
            raise HTTPException(403, "Phone verification required before contributing")
        if not any(m["user_id"] == body.user_id for m in group.get("members", [])):
            raise HTTPException(403, "Not a member of this squad")
        if len(group.get("members") or []) < 2:
            raise HTTPException(400, "A squad needs at least 2 members before anyone can contribute. Invite someone first.")

        enriched = await _recompute_group(group)
        per = next((p for p in enriched["per_user"] if p["user_id"] == body.user_id), None)
        share = per["total"] if per else 0.0
        already = per["contributed"] if per else 0.0
        shortfall_owed = per.get("shortfall_owed", 0.0) if per else 0.0
        remaining_share = max(0.0, share + shortfall_owed - already)
        amount = float(body.amount) if body.amount is not None else remaining_share
        if amount <= 0:
            raise HTTPException(400, "Nothing left to contribute")

        # Credit balance
        available_credits = 0.0
        rows = await db.credits.find({"user_id": body.user_id, "status": "active"}, {"_id": 0}).to_list(length=None)
        for r in rows:
            avail = round(float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0), 2)
            if avail > 0:
                available_credits += avail
        available_credits = round(available_credits, 2)
        credit_planned = round(min(available_credits, amount), 2)
        cash_owed = round(max(0.0, amount - credit_planned), 2)

        if cash_owed <= 0.01:
            raise HTTPException(
                400,
                "Your share is fully covered by credits — use the regular /contribute endpoint instead.",
            )

        keys = await _resolve_stripe_keys(db)
        secret = keys["secret_key"]
        publishable = keys["publishable_key"]
        if not secret:
            raise HTTPException(503, "Stripe secret key not configured")

        # Make sure a Stripe Customer exists for PaymentSheet
        customer_id = await _ensure_stripe_customer(db, body.user_id, secret)

        # Mint an EphemeralKey so the mobile SDK can attach a payment method
        _stripe_sdk.api_key = secret
        try:
            eph = _stripe_sdk.EphemeralKey.create(
                customer=customer_id,
                stripe_version="2024-06-20",
            )
        except Exception as e:
            logger.exception(f"[phase7] EphemeralKey.create failed: {e}")
            raise HTTPException(502, f"Stripe error: {e}")

        txn_id = make_txn_id("charge")
        try:
            pi = _stripe_sdk.PaymentIntent.create(
                amount=int(round(cash_owed * 100)),
                currency="usd",
                customer=customer_id,
                automatic_payment_methods={"enabled": True},
                metadata={
                    "group_id": group_id,
                    "user_id": body.user_id,
                    "kind": "group_member_contribute_native",
                    "requested_amount": str(round(amount, 2)),
                    "credit_planned": str(credit_planned),
                    "cash_owed": str(cash_owed),
                    "notify_on_settled": "1" if body.notify_on_settled else "0",
                    "txn_id": txn_id,
                },
                idempotency_key=txn_id,
            )
        except Exception as e:
            logger.exception(f"[phase7] PaymentIntent.create failed: {e}")
            raise HTTPException(502, f"Stripe error: {e}")

        # Persist `payment_transactions` row — same schema as Checkout path,
        # but `session_id` field stores the PaymentIntent id and `kind` is
        # distinguished so finalize logic knows which path to take.
        tx_doc = {
            "id": f"px_{pi.id[:14]}",
            "session_id": pi.id,             # reused field for PI id
            "payment_intent_id": pi.id,
            "txn_id": txn_id,
            "gateway_slug": "stripe",
            "group_id": group_id,
            "user_id": body.user_id,
            "amount": cash_owed,
            "currency": "usd",
            "status": "initiated",
            "payment_status": "requires_payment_method",
            "metadata": {
                "kind": "group_member_contribute_native",
                "requested_amount": round(amount, 2),
                "credit_planned": credit_planned,
                "cash_owed": cash_owed,
                "notify_on_settled": bool(body.notify_on_settled),
                "txn_id": txn_id,
                "gateway": "stripe",
            },
            "applied": False,
            "ledger_posted": False,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.payment_transactions.insert_one(tx_doc.copy())

        return {
            "payment_intent_id": pi.id,
            "client_secret": pi.client_secret,
            "ephemeral_key_secret": eph.secret,
            "customer_id": customer_id,
            "publishable_key": publishable,
            "txn_id": txn_id,
            "cash_owed": cash_owed,
            "credit_planned": credit_planned,
            "requested_amount": round(amount, 2),
            "currency": "usd",
            "merchant_display_name": "SquadPay",
        }

    # ── 2. Finalize after PaymentSheet success ─────────────────────────
    @router.post("/groups/{group_id}/contribute-payment-intent/finalize")
    async def finalize_contribute_pi(group_id: str, body: ContributePIFinalizeIn):
        tx = await db.payment_transactions.find_one(
            {"payment_intent_id": body.payment_intent_id}, {"_id": 0}
        )
        if not tx:
            raise HTTPException(404, "PaymentIntent not found in our records")
        if tx.get("group_id") != group_id:
            raise HTTPException(400, "PaymentIntent does not belong to this squad")
        if tx.get("applied"):
            return {
                "applied": True, "status": tx.get("status"),
                "payment_status": tx.get("payment_status"),
                "group_id": group_id, "amount_total": int(round(float(tx.get("amount") or 0) * 100)),
                "currency": tx.get("currency"),
                "awarded_credits": tx.get("awarded_credits") or [],
            }

        keys = await _resolve_stripe_keys(db)
        if not keys.get("secret_key"):
            raise HTTPException(500, "Stripe is not configured. Ask an admin to set the secret key in Gateway config.")
        # #12 — Refuse to create a PI when the secret + publishable keys
        # belong to different Stripe accounts. PaymentSheet would later fail
        # with the very confusing "No such payment_intent" error. We catch it
        # upfront so the user sees an actionable message.
        if keys.get("publishable_key") and not _stripe_keys_match(keys):
            raise HTTPException(
                500,
                "Stripe key mismatch: the secret key and publishable key belong "
                "to DIFFERENT Stripe accounts. The native Apple/Google Pay sheet "
                "will fail with 'No such payment_intent'. Ask an admin to update "
                "Gateway config so both keys are from the SAME account.",
            )
        _stripe_sdk.api_key = keys["secret_key"]
        try:
            pi = _stripe_sdk.PaymentIntent.retrieve(body.payment_intent_id)
        except Exception as e:
            logger.exception(f"[phase7] PaymentIntent.retrieve failed: {e}")
            raise HTTPException(502, f"Stripe error: {e}")

        payment_status = pi.status
        update: dict = {
            "payment_status": payment_status,
            "status": "complete" if payment_status == "succeeded" else payment_status,
            "updated_at": now_iso(),
        }
        if payment_status != "succeeded":
            await db.payment_transactions.update_one(
                {"payment_intent_id": body.payment_intent_id}, {"$set": update}
            )
            return {
                "applied": False, "payment_status": payment_status, "group_id": group_id,
                "amount_total": pi.amount, "currency": pi.currency,
            }

        # Status is succeeded — apply the contribution + ledger (idempotent guarded by tx.applied)
        meta = tx.get("metadata") or {}
        amount = float(meta.get("requested_amount") or tx.get("amount") or 0)
        credit_planned = float(meta.get("credit_planned") or 0)
        cash_owed = float(meta.get("cash_owed") or tx.get("amount") or 0)
        notify_on_settled = bool(meta.get("notify_on_settled") or False)

        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Squad not found")

        contributions = list(group.get("contributions") or [])
        contrib_id = new_id("c_")

        credit_applied = 0.0
        if credit_planned > 0:
            credit_applied, _events = await _consume_user_credits(
                db, tx["user_id"], credit_planned, group_id, contrib_id
            )
        cash_paid = round(amount - float(credit_applied), 2)
        contributions.append({
            "id": contrib_id, "user_id": tx["user_id"],
            "amount": round(amount, 2),
            "cash_paid": cash_paid,
            "credit_applied": round(float(credit_applied), 2),
            "notify_on_settled": notify_on_settled,
            "via": "stripe_native",  # distinguishes PaymentSheet from Checkout
            "stripe_payment_intent_id": pi.id,
            "at": now_iso(),
        })
        group_update: Dict[str, Any] = {"contributions": contributions}
        total_contributed = sum(c["amount"] for c in contributions)
        if total_contributed + 0.01 >= group.get("total_amount", 0):
            group_update.update({
                "status": "paid", "funding_mode": "group",
                "lead_paid_at": now_iso(), "lead_shortfall": 0.0,
            })
        await db.groups.update_one({"id": group_id}, {"$set": group_update})

        # Auto-issue group card if newly paid
        if group_update.get("status") == "paid":
            try:
                refreshed = await db.groups.find_one({"id": group_id}, {"_id": 0})
                from issuing import issue_group_card
                await issue_group_card(db, refreshed)
            except Exception as e:
                logger.warning(f"[phase7] auto-issue card failed for {group_id}: {e}")

        # Credit-rules engine
        awarded_credits: list = []
        try:
            from routes.admin_credit_rules import evaluate_and_award
            fresh = await db.groups.find_one({"id": group_id}, {"_id": 0})
            fresh_user = await db.users.find_one({"id": tx["user_id"]}, {"_id": 0})
            awarded_credits = await evaluate_and_award(
                db,
                trigger="member_contribute",
                user=fresh_user, group=fresh,
                amount_user=round(amount, 2),
                amount_group=sum(float(c.get("amount") or 0) for c in contributions),
            ) or []
        except Exception as e:
            logger.warning(f"[phase7] credit rules failed: {e}")

        # Phase 3 — write immutable ledger event for the cash portion
        try:
            txn_id = tx.get("txn_id") or meta.get("txn_id")
            if txn_id and cash_owed > 0:
                await record_charge_event(
                    db,
                    txn_id=txn_id, bill_id=group_id, user_id=tx["user_id"],
                    gross_cents=to_cents(cash_owed), currency=tx.get("currency") or "usd",
                    reference={
                        "stripe_payment_intent_id": pi.id,
                        "kind": "group_member_contribute_native",
                        "payment_transaction_id": tx.get("id"),
                        "credit_applied_usd": credit_planned,
                    },
                    kind="group_member_contribute_native",
                )
                update["ledger_posted"] = True
                update["ledger_posted_at"] = now_iso()
        except Exception as e:
            logger.exception(f"[ledger] PI ledger write failed: {e}")

        update["applied"] = True
        update["awarded_credits"] = awarded_credits
        await db.payment_transactions.update_one(
            {"payment_intent_id": body.payment_intent_id}, {"$set": update}
        )

        return {
            "applied": True, "payment_status": payment_status, "status": "complete",
            "group_id": group_id, "amount_total": pi.amount, "currency": pi.currency,
            "awarded_credits": awarded_credits,
        }

    # ── 3. Publishable-key helper for the mobile app ────────────────────
    @router.get("/stripe/publishable-key")
    async def get_publishable_key():
        keys = await _resolve_stripe_keys(db)
        pk = keys["publishable_key"]
        # Pull current wallet enable flags so the FE can hide the native
        # Apple Pay / Google Pay button when admin disables them.
        wallet_cfg = await db.app_config.find_one({"_id": "wallet"}) or {}
        return {
            "publishable_key": pk,
            "configured": bool(pk),
            "merchant_identifier": "merchant.us.squadpay",
            "apple_pay_enabled": wallet_cfg.get("apple_pay_enabled", True),
            "google_pay_enabled": wallet_cfg.get("google_pay_enabled", True),
        }
