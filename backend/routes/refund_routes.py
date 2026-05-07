"""Refund / overpayment routes — Phase H7.

When a member's contributions exceed their fair share (e.g. lead paid full
bill before adding members, then equal-split halves their target share), the
projected `per_user[*].overpaid` field becomes positive. This module exposes:

  POST /api/groups/{id}/refund-overpayment
    body: { user_id, amount? }
    behavior: refunds up to `min(overpaid, amount or overpaid)` to the user.
    Strategy:
      1) Walk the user's contributions newest-first.
      2) For each contribution backed by a Stripe PaymentIntent (cash_paid > 0),
         issue a stripe.Refund up to the lesser of (cash_paid - already_refunded)
         and the remaining target.
      3) Decrement the contribution's `amount` (effectively removing it from
         total_contributed) and stamp `refunded_amount`, `refunded_at` so
         subsequent calls are idempotent.
      4) If amount remains and the contribution was credit-funded (no PI),
         return the credit back to the user's wallet via /api/users/.../credits.

The endpoint logs an audit entry and returns a summary:
  { refunded: float, breakdown: [...], remaining_overpaid: float, info: str }
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core import (
    _recompute_group as apply_calculations,
    new_id,
    now_iso,
)

logger = logging.getLogger(__name__)


class RefundOverpaymentIn(BaseModel):
    user_id: str
    amount: Optional[float] = Field(default=None, description="Cap; defaults to full overpaid balance")


def make_refund_router(db) -> APIRouter:
    router = APIRouter()

    @router.post("/groups/{group_id}/refund-overpayment")
    async def refund_overpayment(group_id: str, body: RefundOverpaymentIn):
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        if body.user_id not in [m["user_id"] for m in (group.get("members") or [])]:
            raise HTTPException(403, "User is not a member of this group")

        # Compute current overpaid amount from the projection helper.
        projected = await apply_calculations(group)
        per_user = projected.get("per_user") or []
        me = next((p for p in per_user if p["user_id"] == body.user_id), None)
        if not me:
            raise HTTPException(404, "User not in per_user")
        overpaid = float(me.get("overpaid") or 0.0)
        if overpaid <= 0.005:
            raise HTTPException(400, f"No overpayment to refund (overpaid=${overpaid:.2f})")

        target = min(overpaid, float(body.amount)) if body.amount and body.amount > 0 else overpaid
        target = round(target, 2)
        if target <= 0.005:
            raise HTTPException(400, "Refund amount must be > 0")

        contributions = list(group.get("contributions") or [])
        # User's contribs newest-first
        my_contribs = [
            (idx, c) for idx, c in enumerate(contributions)
            if c.get("user_id") == body.user_id
        ]
        my_contribs.sort(key=lambda t: t[1].get("at") or "", reverse=True)

        remaining = target
        breakdown = []
        info_msgs = []

        # Lazily init Stripe SDK
        import stripe as _stripe
        _stripe.api_key = os.environ.get("STRIPE_API_KEY")

        for idx, c in my_contribs:
            if remaining <= 0.005:
                break
            already_refunded = float(c.get("refunded_amount") or 0.0)
            cash_remaining = max(0.0, float(c.get("cash_paid") or 0.0) - already_refunded)
            credit_remaining = max(
                0.0,
                float(c.get("credit_applied") or 0.0)
                - float(c.get("credit_refunded") or 0.0),
            )

            # --- 1) Cash via Stripe refund ---
            if cash_remaining > 0.005:
                refund_amt = round(min(cash_remaining, remaining), 2)
                refunded_via = "stripe"
                stripe_refund_id = None
                error = None
                try:
                    session_id = c.get("stripe_session_id")
                    if not session_id:
                        raise RuntimeError("missing stripe_session_id")
                    sess = _stripe.checkout.Session.retrieve(session_id)
                    pi = getattr(sess, "payment_intent", None)
                    if not pi:
                        raise RuntimeError("session has no payment_intent")
                    r = _stripe.Refund.create(
                        payment_intent=pi if isinstance(pi, str) else pi.id,
                        amount=int(round(refund_amt * 100)),
                        reason="requested_by_customer",
                        metadata={
                            "kind": "overpayment_refund",
                            "group_id": group_id,
                            "user_id": body.user_id,
                            "contribution_id": c.get("id") or "",
                        },
                    )
                    stripe_refund_id = getattr(r, "id", None)
                except Exception as e:
                    logger.warning(f"[refund] stripe refund failed for contrib {c.get('id')}: {e}")
                    refunded_via = "stripe_failed"
                    error = str(e)[:200]
                    info_msgs.append(f"Stripe refund failed: {error}")

                if refunded_via == "stripe":
                    contributions[idx]["refunded_amount"] = round(already_refunded + refund_amt, 2)
                    contributions[idx]["amount"] = round(float(c.get("amount") or 0.0) - refund_amt, 2)
                    contributions[idx]["last_refund_at"] = now_iso()
                    breakdown.append({
                        "contribution_id": c.get("id"),
                        "via": "stripe",
                        "amount": refund_amt,
                        "stripe_refund_id": stripe_refund_id,
                    })
                    remaining = round(remaining - refund_amt, 2)
                    continue  # next contribution

            # --- 2) Credit back to wallet (for credit-funded portions / Stripe failures) ---
            if credit_remaining > 0.005 or (cash_remaining <= 0.005 and remaining > 0.005):
                # Restore as wallet credit. If cash was supposed to refund but
                # Stripe failed, we DO NOT silently turn it into wallet credit
                # (that could be surprising) — we just stop with a partial result.
                refund_amt = round(min(credit_remaining, remaining), 2)
                if refund_amt < 0.005:
                    continue
                doc = {
                    "id": new_id("cr_"),
                    "user_id": body.user_id,
                    "amount": refund_amt,
                    "consumed_amount": 0.0,
                    "kind": "refund_overpayment",
                    "status": "active",
                    "note": f"Refund of overpayment on group {group.get('title') or group_id}",
                    "created_at": now_iso(),
                    "last_consumed_at": None,
                    "source_group_id": group_id,
                    "source_contribution_id": c.get("id"),
                }
                await db.user_credits.insert_one(doc)
                contributions[idx]["credit_refunded"] = round(
                    float(c.get("credit_refunded") or 0.0) + refund_amt, 2
                )
                contributions[idx]["amount"] = round(float(c.get("amount") or 0.0) - refund_amt, 2)
                contributions[idx]["last_refund_at"] = now_iso()
                breakdown.append({
                    "contribution_id": c.get("id"),
                    "via": "wallet_credit",
                    "amount": refund_amt,
                    "credit_id": doc["id"],
                })
                remaining = round(remaining - refund_amt, 2)

        actually_refunded = round(target - remaining, 2)
        if actually_refunded <= 0.005:
            raise HTTPException(
                502,
                detail="Could not process refund. " + (info_msgs[0] if info_msgs else "Please try again."),
            )

        # Persist updated contributions
        await db.groups.update_one(
            {"id": group_id},
            {"$set": {"contributions": contributions, "updated_at": now_iso()}},
        )

        # Audit
        try:
            await db.audit_log.insert_one({
                "id": new_id("au_"),
                "actor_id": body.user_id,
                "action": "user.refund_overpayment",
                "target_type": "group",
                "target_id": group_id,
                "payload": {
                    "amount_target": target,
                    "amount_refunded": actually_refunded,
                    "breakdown": breakdown,
                },
                "at": now_iso(),
            })
        except Exception as e:
            logger.warning(f"[refund] audit insert failed: {e}")

        # Refresh + return new state
        refreshed = await db.groups.find_one({"id": group_id}, {"_id": 0})
        projected_after = await apply_calculations(refreshed)

        return {
            "ok": True,
            "refunded": actually_refunded,
            "breakdown": breakdown,
            "remaining_overpaid": round(max(0.0, overpaid - actually_refunded), 2),
            "group": projected_after,
            "info": "; ".join(info_msgs) if info_msgs else "",
        }

    return router
