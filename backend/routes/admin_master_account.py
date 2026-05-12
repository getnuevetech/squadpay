"""
Admin → Master Account ledger.

Important reality check on Stripe Issuing (which the page UX is built around):

Stripe Issuing cards don't have a "balance" the way a prepaid card does —
they have a SPENDING LIMIT. All issued cards on the same account draw from
the same Stripe Platform Balance. There is no API to "transfer balance"
from one Issuing card to another.

What we actually track here, then:
  • funded   — what members contributed to a bill (lives in Stripe platform balance)
  • spent    — what the bill's virtual card has spent at merchants (POS settlements)
  • residual — funded − spent  (the leftover that "sits" in the platform balance)

Residuals are platform income on top of fees:
  - If members contributed exactly the bill total and the lead spent
    exactly that at the merchant, residual = 0.
  - If the lead spent less than the funded amount (e.g. card had a buffer
    or merchant adjusted the bill downward), the difference is residual
    that the platform retains.
  - If members over-contributed (rare), the excess is also residual.

The MASTER VIRTUAL CARD is a separate Stripe Issuing card the platform
issues for its own use. Because all Stripe Issuing cards on our account
draw against the same Platform Balance, "moving" a group's residual to
the Master Virtual Card is conceptual — the money already sits in the
shared Stripe balance the day the residual is realised. The Master Card
just lets the platform spend that pooled balance.

This module gives admins two endpoints:
  • GET /api/admin/master-account  — full ledger + totals
  • POST /api/admin/master-account/issue-card — provision the Master Virtual Card (idempotent)
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException

MASTER_ACCOUNT_ID = "master_account"


def _safe_iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, str):
        return v
    return None


def _residual_for_group(group: Dict[str, Any]) -> Dict[str, float]:
    """Compute funded/spent/residual for one group.

    `spent` is read from the virtual_card.transactions list when present
    (populated by the Stripe Issuing webhook), otherwise falls back to the
    bill's merchant_subtotal (items + tax + tip) which is what the card
    *would* have spent at the merchant.
    """
    funding = group.get("funding") or {}
    funded = float(funding.get("total_contributed") or 0)

    vc = group.get("virtual_card") or {}
    txs = vc.get("transactions") or []
    if txs:
        spent = sum(float(t.get("amount") or 0) for t in txs)
    else:
        items_total = sum(
            float((it.get("price") or 0)) * float((it.get("quantity") or 1))
            for it in (group.get("items") or [])
        )
        merchant_subtotal = items_total + float(group.get("tax") or 0) + float(group.get("tip") or 0)
        spent = merchant_subtotal if group.get("status") == "paid" else 0.0

    residual = funded - spent
    return {
        "funded": round(funded, 2),
        "spent": round(spent, 2),
        "residual": round(residual, 2),
    }


def attach_master_account_routes(api_router: APIRouter, db, require_admin):
    # NOTE: The /admin/master-account ledger endpoint is owned by the older
    # admin_reconciliation.py module which has a richer master_account_ledger
    # collection model. We deliberately do NOT register a competing GET here.
    # This module ONLY adds the new Master Virtual Card issuance endpoint.

    @api_router.post("/admin/master-card/issue")
    async def issue_master_card(_admin=Depends(require_admin)):
        """Idempotently issue the platform's Master Virtual Card via Stripe Issuing.

        STATUS: stub. Real wiring is one Stripe API call away — see comment.

        When wired:
            card = stripe.issuing.Card.create(
                cardholder=PLATFORM_CARDHOLDER_ID,
                currency="usd",
                type="virtual",
                metadata={"role": "master_account"},
            )
        """
        existing = await db.platform_config.find_one({"_id": MASTER_ACCOUNT_ID}) or {}
        # Idempotency: if ANY master_card record already exists (even a stub
        # with stripe_card_id=None), don't re-create. The previous check
        # gated only on `stripe_card_id` truthiness, which made stub creation
        # repeatable — fixed now.
        if existing.get("master_card") is not None:
            return {"ok": True, "card": existing["master_card"], "created": False}

        # STUB — replace with the Stripe Issuing call once approvals/cardholder are set up.
        stub = {
            "stripe_card_id": None,
            "last4": None,
            "status": "pending_stripe_setup",
            "issued_at": None,
            "note": (
                "Master card issuance is scaffolded. Wire the stripe.issuing.Card.create "
                "call in /app/backend/routes/admin_master_account.py once you have a platform "
                "cardholder configured in Stripe Issuing."
            ),
        }
        await db.platform_config.update_one(
            {"_id": MASTER_ACCOUNT_ID},
            {"$set": {"master_card": stub}},
            upsert=True,
        )
        return {"ok": True, "card": stub, "created": True}

    @api_router.get("/admin/master-card")
    async def get_master_card(_admin=Depends(require_admin)):
        """Return current Master Virtual Card state (null if not yet issued)."""
        doc = await db.platform_config.find_one({"_id": MASTER_ACCOUNT_ID}) or {}
        return {"card": doc.get("master_card")}

    return issue_master_card
