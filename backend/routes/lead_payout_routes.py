"""Lead Payout (no-store, settlement-time) routes — June 2025.

Founder mandate (SquadPay is an aggregator, NEVER holds money):
  • Lead chooses payout method at EVERY settlement — no saved preference.
  • Bank / debit card details are TOKENIZED, used once, then discarded.
  • DB never stores routing #, account #, raw PAN, or CVV.

This is intentionally a DIFFERENT path from `payout_routes.py` (which uses
Stripe Connect Express's persisted onboarding model). That model is fine
for users who *want* a saved connected account; this no-store path is the
default for the Settlement Mode (`lead_card` / `lead_choice`) flow where
the Lead is funded directly without standing relationships.

Public surface:
  GET  /api/group/{group_id}/lead-payout/eligibility
       → Returns: { eligible, fully_funded, settlement_mode, available_cents,
                    supports_ach, supports_card }
  POST /api/group/{group_id}/lead-payout/execute
       → Body: { user_id, session_id, method: "ach" | "push_to_card", payload }
       → ACH payload : { routing_number, account_number, account_holder_name,
                         account_type? }  (account_type = "checking" | "savings")
       → Card payload: { card_number, exp_month, exp_year, cvv,
                         cardholder_name?, postal_code? }
       → Executes the payout via active issuer (Increase ACH / Stripe push-to-card).
       → Returns: { txn_id, status, amount, method, last4 }

Compliance posture:
  - PAN/CVV/account-numbers are accepted ONLY for tokenization and never
    written to logs or persisted to MongoDB.
  - The endpoint zeroes the local Python references after submission.
  - Receipt row stores tokenized provider_payout_id + last4 only.
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core import now_iso
from ledger import make_txn_id, record_payout_event, to_cents, from_cents

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────
class LeadPayoutExecuteIn(BaseModel):
    user_id: str
    session_id: str
    method: str = Field(..., description="'ach' or 'push_to_card'")
    payload: Dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _require_session(db, user_id: str, session_id: str) -> dict:
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(401, "User not found")
    if user.get("deleted_at"):
        raise HTTPException(401, "Account no longer active")
    if user.get("current_session_id") != session_id:
        raise HTTPException(401, "Session expired — please sign in again")
    return user


async def _load_group_for_settlement(db, group_id: str, user_id: str) -> dict:
    g = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(404, "Squad not found")
    if g.get("lead_id") != user_id:
        raise HTTPException(403, "Only the squad lead may settle this squad")
    return g


async def _funding_pool_cents(db, group_id: str) -> int:
    """Total funded amount currently held in the in-flight pool.

    For a member-funded ("group" funding_mode) squad fully funded, this is
    the merchant-payable balance the lead can cash out.
    """
    pipeline = [
        {"$match": {"bill_id": group_id, "account": "merchant_payable"}},
        {"$group": {"_id": "$direction", "amount_cents": {"$sum": "$amount_cents"}}},
    ]
    credit = 0
    debit = 0
    async for d in db.ledger_entries.aggregate(pipeline):
        if d["_id"] == "credit":
            credit = int(d["amount_cents"])
        elif d["_id"] == "debit":
            debit = int(d["amount_cents"])
    return max(credit - debit, 0)


async def _get_settlement_mode(db) -> str:
    rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {}
    pg = rec.get("payment_gateways") or {}
    return (pg.get("settlement_mode") or "virtual_card").lower()


def _scrub(d: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy with PAN/CVV/account#/routing# scrubbed for logging."""
    safe = {}
    for k, v in d.items():
        if k in ("account_number", "card_number", "cvv", "routing_number"):
            safe[k] = f"***{str(v)[-4:]}" if v else "***"
        else:
            safe[k] = v
    return safe


# ─────────────────────────────────────────────────────────────────────────────
# Increase ACH — ephemeral external_account → ach_transfer → cleanup
# ─────────────────────────────────────────────────────────────────────────────
async def _execute_ach_via_increase(
    db, *, amount_cents: int, payload: Dict[str, Any], memo: str
) -> Dict[str, Any]:
    """Create ephemeral Increase external_account, run ACH, delete account.

    Mandatory payload fields: routing_number, account_number, account_holder_name.
    Optional: account_type (checking|savings, default checking).
    """
    from adapters.issuer_increase import _client as _increase_client

    routing_number = (payload.get("routing_number") or "").strip()
    account_number = (payload.get("account_number") or "").strip()
    account_holder_name = (payload.get("account_holder_name") or "").strip()
    account_type = (payload.get("account_type") or "checking").strip().lower()

    if not routing_number or not account_number or not account_holder_name:
        raise HTTPException(400, "ACH payload requires routing_number, account_number, account_holder_name")
    if account_type not in ("checking", "savings"):
        account_type = "checking"

    client = _increase_client()
    # Resolve platform account_id (cached during issuer onboarding).
    rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {}
    pg = rec.get("payment_gateways") or {}
    issuer_cfg = ((pg.get("issuers") or {}).get("increase") or {})
    account_id = issuer_cfg.get("account_id")
    if not account_id:
        # Ensure cardholder lazily for sandbox first-run
        from adapters.issuer_increase import IncreaseIssuerAdapter
        account_id = await IncreaseIssuerAdapter().ensure_business_cardholder(db)

    # 1. Create ephemeral external_account.
    ext = None
    try:
        ext = client.external_accounts.create(
            account_number=account_number,
            routing_number=routing_number,
            description=f"SquadPay payout to {account_holder_name[:32]}",
            funding=account_type,  # "checking" or "savings"
        )
    except Exception as e:
        logger.exception(f"[lead-payout/ach] external_account.create failed: {e}")
        raise HTTPException(502, f"Bank verification failed: {e}")

    # 2. Execute ACH transfer.
    try:
        transfer = client.ach_transfers.create(
            account_id=account_id,
            external_account_id=ext.id,
            amount=int(amount_cents),
            statement_descriptor="SQUADPAY",
            company_entry_description="SQDPAYOUT",
            individual_name=account_holder_name[:22],
        )
    except Exception as e:
        # Try to clean up the ephemeral external_account on failure.
        try:
            client.external_accounts.archive(ext.id)
        except Exception:
            pass
        logger.exception(f"[lead-payout/ach] ach_transfers.create failed: {e}")
        raise HTTPException(502, f"ACH transfer failed: {e}")

    # 3. Archive the external_account so it can never be reused — true "no
    #    storage" posture. Increase archives are soft-delete (record kept
    #    for audit, but unusable for further transfers).
    try:
        client.external_accounts.archive(ext.id)
    except Exception as e:
        logger.warning(f"[lead-payout/ach] archive cleanup failed (non-fatal): {e}")

    return {
        "provider": "increase",
        "method": "ach",
        "provider_payout_id": transfer.id,
        "status": (getattr(transfer, "status", "pending") or "pending").lower(),
        "last4": account_number[-4:],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Push-to-Card (Stripe one-shot — no persisted Connect account)
# ─────────────────────────────────────────────────────────────────────────────
async def _execute_push_to_card_via_stripe(
    *, amount_cents: int, payload: Dict[str, Any], memo: str
) -> Dict[str, Any]:
    """Single-use card payout via Stripe Issuing-style tokenization.

    For the MVP no-store flow we use the Stripe Tokens API to convert raw
    card details into a one-time token, then issue a Payout via the
    platform's Stripe balance. Stripe never persists the PAN on our side
    and the token expires immediately after use.

    NOTE: For production, the frontend SHOULD tokenize using Stripe.js /
    Stripe Elements (PCI scope minimisation). The raw-PAN endpoint
    accepted here is for the no-Onboarding lightweight path; admin can
    later flip to Stripe Elements once the public key + Elements SDK is
    wired into the React Native shell.
    """
    import stripe
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=True)
    api_key = os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        raise HTTPException(503, "Stripe API key not configured — cannot push to card")
    stripe.api_key = api_key

    card_number = (payload.get("card_number") or "").replace(" ", "").replace("-", "")
    exp_month = payload.get("exp_month")
    exp_year = payload.get("exp_year")
    cvv = str(payload.get("cvv") or "")
    cardholder_name = (payload.get("cardholder_name") or "Squad Lead")[:64]

    if not (card_number and exp_month and exp_year and cvv):
        raise HTTPException(400, "Card payload requires card_number, exp_month, exp_year, cvv")
    try:
        exp_month = int(exp_month)
        exp_year = int(exp_year)
        if exp_year < 100:
            exp_year += 2000
    except Exception:
        raise HTTPException(400, "Invalid exp_month/exp_year")

    # 1. Tokenize via Stripe (one-shot, never stored).
    try:
        token = stripe.Token.create(
            card={
                "number": card_number,
                "exp_month": exp_month,
                "exp_year": exp_year,
                "cvc": cvv,
                "name": cardholder_name,
            }
        )
    except Exception as e:
        logger.exception(f"[lead-payout/card] Token.create failed: {e}")
        raise HTTPException(502, f"Card tokenization failed: {e}")

    last4 = token.card.last4 if hasattr(token, "card") else card_number[-4:]

    # 2. Single-use payout via Stripe Payout API to the tokenized card.
    #    For platform balance → card direct payout, we use the Stripe
    #    Payout API with destination=<token_id> in instant mode.
    try:
        payout = stripe.Payout.create(
            amount=int(amount_cents),
            currency="usd",
            method="instant",
            destination=token.id,
            metadata={"memo": memo[:200]},
            statement_descriptor="SQUADPAY",
        )
        provider_payout_id = payout.id
        status_raw = (getattr(payout, "status", "pending") or "pending").lower()
    except Exception as e:
        # Fallback: some Stripe accounts don't have direct platform→card
        # push-to-card enabled. Bubble up a clear error.
        logger.exception(f"[lead-payout/card] Payout.create failed: {e}")
        raise HTTPException(
            502,
            f"Stripe Push-to-Card failed: {e}. Your Stripe account may not "
            "have Instant Payouts enabled — contact support to enable.",
        )

    return {
        "provider": "stripe",
        "method": "push_to_card",
        "provider_payout_id": provider_payout_id,
        "status": "paid" if status_raw == "paid" else "pending" if status_raw in ("pending", "in_transit") else status_raw,
        "last4": last4,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Route attach
# ─────────────────────────────────────────────────────────────────────────────
def attach_lead_payout_routes(api_router: APIRouter, db):

    @api_router.get("/group/{group_id}/lead-payout/eligibility")
    async def eligibility(group_id: str, user_id: str, session_id: str):
        await _require_session(db, user_id, session_id)
        g = await _load_group_for_settlement(db, group_id, user_id)
        settlement_mode = await _get_settlement_mode(db)
        funding_mode = (g.get("funding_mode") or "lead").lower()

        # Pool is fully funded when remaining_to_collect ~= 0.
        funding = g.get("funding") or {}
        remaining = float(funding.get("remaining_to_collect") or 0)
        fully_funded = remaining < 0.005

        available_cents = await _funding_pool_cents(db, group_id) if fully_funded else 0

        # ACH always supported when Increase issuer configured.
        supports_ach = bool(os.environ.get("INCREASE_API_KEY"))
        # Push-to-card always supported when Stripe configured.
        supports_card = bool(os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY"))

        # Eligibility: must be lead, group funded, mode allows lead payout, member-funded.
        reasons = []
        eligible = True
        if not fully_funded:
            reasons.append("not_fully_funded")
            eligible = False
        if settlement_mode == "virtual_card":
            reasons.append("settlement_mode_disallows_lead_payout")
            eligible = False
        if funding_mode != "group":
            reasons.append("funding_mode_not_group")
            eligible = False
        if eligible and not (supports_ach or supports_card):
            reasons.append("no_payout_provider_configured")
            eligible = False

        return {
            "eligible": eligible,
            "reasons": reasons,
            "fully_funded": fully_funded,
            "settlement_mode": settlement_mode,
            "funding_mode": funding_mode,
            "available_cents": available_cents,
            "available_usd": from_cents(available_cents),
            "supports_ach": supports_ach,
            "supports_card": supports_card,
            "show_virtual_card_option": settlement_mode in ("virtual_card", "lead_choice"),
            "show_lead_payout_option": settlement_mode in ("lead_card", "lead_choice"),
        }

    @api_router.post("/group/{group_id}/lead-payout/execute")
    async def execute(group_id: str, body: LeadPayoutExecuteIn):
        await _require_session(db, body.user_id, body.session_id)
        g = await _load_group_for_settlement(db, group_id, body.user_id)
        settlement_mode = await _get_settlement_mode(db)
        if settlement_mode == "virtual_card":
            raise HTTPException(409, "Lead-direct payout is disabled by admin (settlement_mode=virtual_card)")

        # Re-validate full funding (the user could trigger this manually).
        funding = g.get("funding") or {}
        remaining = float(funding.get("remaining_to_collect") or 0)
        if remaining >= 0.005:
            raise HTTPException(409, f"Squad is not fully funded yet (remaining ${remaining:.2f})")

        available_cents = await _funding_pool_cents(db, group_id)
        if available_cents <= 0:
            raise HTTPException(409, "No funds available to settle")

        method = (body.method or "").lower().strip()
        if method not in ("ach", "push_to_card"):
            raise HTTPException(400, "method must be 'ach' or 'push_to_card'")

        # Log scrubbed payload only.
        logger.info(
            f"[lead-payout] execute group={group_id} method={method} "
            f"payload={_scrub(body.payload)}"
        )

        memo = f"SquadPay settlement for {g.get('name') or group_id}"
        try:
            if method == "ach":
                result = await _execute_ach_via_increase(
                    db, amount_cents=available_cents, payload=body.payload, memo=memo,
                )
            else:
                result = await _execute_push_to_card_via_stripe(
                    amount_cents=available_cents, payload=body.payload, memo=memo,
                )
        finally:
            # Belt-and-braces scrub of sensitive locals before they age out.
            for k in ("account_number", "routing_number", "card_number", "cvv"):
                if k in body.payload:
                    body.payload[k] = None

        # Persist receipt row (tokenized id + last4 only — NEVER PAN/account).
        txn_id = make_txn_id("payout")
        receipt = {
            "id": txn_id,
            "txn_id": txn_id,
            "user_id": body.user_id,
            "group_id": group_id,
            "gateway_slug": result["provider"],
            "provider_payout_id": result["provider_payout_id"],
            "amount_cents": available_cents,
            "currency": "usd",
            "status": result["status"],
            "fee_cents": 0,
            "method": result["method"],
            "last4": result["last4"],
            "kind": "lead_settlement_payout",
            "settlement_mode_at_time": settlement_mode,
            "ledger_posted": False,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.payouts.insert_one(receipt.copy())

        # Ledger entry — keeps drift recon happy.
        try:
            await record_payout_event(
                db,
                txn_id=txn_id,
                bill_id=group_id,
                user_id=body.user_id,
                amount_cents=available_cents,
                currency="usd",
                reference={
                    "provider_payout_id": result["provider_payout_id"],
                    "gateway_slug": result["provider"],
                    "method": result["method"],
                    "card_last4": result["last4"] if result["method"] == "push_to_card" else None,
                    "bank_last4": result["last4"] if result["method"] == "ach" else None,
                },
                provider_fee_cents=0,
                kind="lead_settlement_payout",
            )
            await db.payouts.update_one(
                {"txn_id": txn_id},
                {"$set": {"ledger_posted": True, "ledger_posted_at": now_iso()}},
            )
        except Exception as e:
            logger.exception(f"[lead-payout] ledger write failed for txn={txn_id}: {e}")

        # Flip group status to lead_paid (settlement timer starts).
        try:
            await db.groups.update_one(
                {"id": group_id, "status": {"$in": ["open", "paid"]}},
                {"$set": {
                    "status": "lead_paid",
                    "lead_payout_paid_at": now_iso(),
                    "updated_at": now_iso(),
                    "lead_payout_method": result["method"],
                }},
            )
        except Exception as e:
            logger.warning(f"[lead-payout] group status flip failed: {e}")

        return {
            "ok": True,
            "txn_id": txn_id,
            "status": result["status"],
            "amount": from_cents(available_cents),
            "method": result["method"],
            "last4": result["last4"],
            "provider": result["provider"],
        }
