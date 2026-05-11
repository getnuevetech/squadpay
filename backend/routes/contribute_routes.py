"""Member contributions (Stripe Checkout) + status polling (Batch B refactor)."""
import logging
import os
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Request

from core import (
    ContributeIn,
    new_id, now_iso,
    _consume_user_credits, _load_group_enriched, _recompute_group,
)

logger = logging.getLogger(__name__)


def attach_contribute_routes(router: APIRouter, db):

    @router.post("/groups/{group_id}/contribute")
    async def contribute(group_id: str, body: ContributeIn, request: Request):
        """Member (or lead) pays their share via real Stripe Checkout (Phase F1)."""
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        if group.get("status") != "open":
            raise HTTPException(400, "Bill already paid; use repay instead")
        if group.get("is_blocked"):
            raise HTTPException(403, "This group has been blocked by an administrator.")
        user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        if user.get("is_blocked"):
            raise HTTPException(403, "Your account has been blocked. Please contact support.")
        if not user.get("verified"):
            raise HTTPException(403, "Phone verification required before contributing")
        if not any(m["user_id"] == body.user_id for m in group.get("members", [])):
            raise HTTPException(403, "Not a member of this group")
        # A group is by definition multi-person — a single member cannot
        # contribute toward a "group" bill until at least one other person
        # joins. This prevents the app being used as a solo wallet.
        if len(group.get("members") or []) < 2:
            raise HTTPException(
                400,
                "A group needs at least 2 members before anyone can contribute. Invite someone first.",
            )

        enriched = await _recompute_group(group)
        per = next((p for p in enriched["per_user"] if p["user_id"] == body.user_id), None)
        share = per["total"] if per else 0.0
        already = per["contributed"] if per else 0.0
        shortfall_owed = per.get("shortfall_owed", 0.0) if per else 0.0
        remaining_share = max(0.0, share + shortfall_owed - already)
        amount = float(body.amount) if body.amount is not None else remaining_share
        if amount <= 0:
            raise HTTPException(400, "Nothing left to contribute")

        available_credits = 0.0
        rows = await db.credits.find({"user_id": body.user_id, "status": "active"}, {"_id": 0}).to_list(length=None)
        for r in rows:
            avail = round(float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0), 2)
            if avail > 0:
                available_credits += avail
        available_credits = round(available_credits, 2)
        credit_planned = round(min(available_credits, amount), 2)
        cash_owed = round(max(0.0, amount - credit_planned), 2)

        # ---- Path A: Credits fully cover
        if cash_owed <= 0.01:
            contributions = list(group.get("contributions", []))
            contrib_id = new_id("c_")
            credit_applied, _events = await _consume_user_credits(db, body.user_id, amount, group_id, contrib_id)
            cash_paid = round(float(amount) - float(credit_applied), 2)
            contributions.append({
                "id": contrib_id,
                "user_id": body.user_id,
                "amount": round(amount, 2),
                "cash_paid": cash_paid,
                "credit_applied": round(float(credit_applied), 2),
                "notify_on_settled": bool(body.notify_on_settled),
                "via": "credit_only",
                "at": now_iso(),
            })
            update_doc: Dict[str, Any] = {"contributions": contributions}
            total_contributed = sum(c["amount"] for c in contributions)
            if total_contributed + 0.01 >= group.get("total_amount", 0):
                update_doc.update({
                    "status": "paid",
                    "funding_mode": "group",
                    "lead_paid_at": now_iso(),
                    "lead_shortfall": 0.0,
                })
            await db.groups.update_one({"id": group_id}, {"$set": update_doc})
            if update_doc.get("status") == "paid":
                try:
                    refreshed = await db.groups.find_one({"id": group_id}, {"_id": 0})
                    from issuing import issue_group_card
                    await issue_group_card(db, refreshed)
                except Exception as e:
                    logger.warning(f"[contribute] auto-issue card failed for {group_id}: {e}")
            result = await _load_group_enriched(db, group_id)
            return {"checkout_required": False, "credit_only": True, "amount": round(amount, 2),
                    "credit_applied": round(float(credit_applied), 2), "group": result}

        # ---- Path B: Cash needed
        origin = (body.origin_url or "").rstrip("/") if hasattr(body, "origin_url") else ""
        if not origin or not origin.startswith("http"):
            raise HTTPException(400, "origin_url (http(s)://...) is required when cash payment is needed")

        import stripe as _stripe_sdk
        _stripe_sdk.api_key = os.environ.get("STRIPE_API_KEY")

        app_return = (body.app_return_url or "").strip() if hasattr(body, "app_return_url") else ""
        if app_return:
            from urllib.parse import quote
            bridge_base = origin
            success_url = (
                f"{bridge_base}/api/checkout/native-bridge"
                f"?session_id={{CHECKOUT_SESSION_ID}}"
                f"&dest={quote(app_return, safe='')}"
                f"&kind=contribute"
            )
            cancel_url = (
                f"{bridge_base}/api/checkout/native-bridge"
                f"?session_id={{CHECKOUT_SESSION_ID}}"
                f"&dest={quote(app_return, safe='')}"
                f"&kind=contribute&cancel=1"
            )
        else:
            success_url = f"{origin}/group/{group_id}/pay?contrib_session_id={{CHECKOUT_SESSION_ID}}"
            cancel_url = f"{origin}/group/{group_id}/pay?stripe_cancel=1"

        try:
            session = _stripe_sdk.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": f"SquadPay contribution — {group.get('title') or 'Group Bill'}"},
                        "unit_amount": int(round(cash_owed * 100)),
                    },
                    "quantity": 1,
                }],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "group_id": group_id,
                    "user_id": body.user_id,
                    "kind": "group_member_contribute",
                    "requested_amount": str(round(amount, 2)),
                    "credit_planned": str(credit_planned),
                    "cash_owed": str(cash_owed),
                    "notify_on_settled": "1" if body.notify_on_settled else "0",
                },
            )
        except Exception as e:
            logger.exception(f"[stripe] member contribute checkout failed: {e}")
            raise HTTPException(502, f"Stripe error: {e}")

        tx = {
            "id": f"px_{session.id[:14]}",
            "session_id": session.id,
            "group_id": group_id,
            "user_id": body.user_id,
            "amount": cash_owed,
            "currency": "usd",
            "status": "initiated",
            "payment_status": "pending",
            "metadata": {
                "kind": "group_member_contribute",
                "requested_amount": round(amount, 2),
                "credit_planned": credit_planned,
                "cash_owed": cash_owed,
                "notify_on_settled": bool(body.notify_on_settled),
            },
            "applied": False,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.payment_transactions.insert_one(tx.copy())
        return {
            "checkout_required": True,
            "url": session.url,
            "session_id": session.id,
            "amount": round(amount, 2),
            "cash_owed": cash_owed,
            "credit_planned": credit_planned,
        }

    @router.get("/contribute/status/{session_id}")
    async def get_contribute_status(session_id: str):
        """Poll/finalize a member-contribution Stripe Checkout session."""
        tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        if not tx:
            raise HTTPException(404, "Contribution session not found")
        if (tx.get("metadata") or {}).get("kind") != "group_member_contribute":
            raise HTTPException(400, "Not a member contribution session")
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

        import stripe as _stripe_sdk
        _stripe_sdk.api_key = os.environ.get("STRIPE_API_KEY")
        try:
            s = _stripe_sdk.checkout.Session.retrieve(session_id)
        except Exception as e:
            logger.exception(f"[stripe] contribute.status retrieve failed: {e}")
            raise HTTPException(502, f"Stripe error: {e}")

        payment_status = getattr(s, "payment_status", None)
        sess_status = getattr(s, "status", None)
        update: dict = {"status": sess_status, "payment_status": payment_status, "updated_at": now_iso()}

        if payment_status == "paid" and not tx.get("applied"):
            meta = tx.get("metadata") or {}
            group_id = tx["group_id"]
            user_id = tx["user_id"]
            cash_owed = float(meta.get("cash_owed") or tx.get("amount") or 0)
            credit_planned = float(meta.get("credit_planned") or 0)

            group = await db.groups.find_one({"id": group_id}, {"_id": 0})
            if group and group.get("status") == "open":
                contributions = list(group.get("contributions") or [])
                contrib_id = new_id("c_")
                credit_consumed, _events = await _consume_user_credits(
                    db, user_id, credit_planned, group_id, contrib_id
                ) if credit_planned > 0 else (0.0, [])
                actual_amount = round(cash_owed + float(credit_consumed), 2)
                contributions.append({
                    "id": contrib_id,
                    "user_id": user_id,
                    "amount": actual_amount,
                    "cash_paid": round(cash_owed, 2),
                    "credit_applied": round(float(credit_consumed), 2),
                    "notify_on_settled": bool(meta.get("notify_on_settled")),
                    "via": "stripe",
                    "stripe_session_id": session_id,
                    "at": now_iso(),
                })
                update_doc: Dict[str, Any] = {"contributions": contributions}
                total_contributed = sum(c["amount"] for c in contributions)
                if total_contributed + 0.01 >= float(group.get("total_amount") or 0):
                    update_doc.update({
                        "status": "paid",
                        "funding_mode": "group",
                        "lead_paid_at": now_iso(),
                        "lead_shortfall": 0.0,
                    })
                await db.groups.update_one({"id": group_id}, {"$set": update_doc})

                if update_doc.get("status") == "paid":
                    try:
                        refreshed = await db.groups.find_one({"id": group_id}, {"_id": 0})
                        from issuing import issue_group_card
                        await issue_group_card(db, refreshed)
                    except Exception as e:
                        logger.warning(f"[contribute.status] auto-issue card failed for {group_id}: {e}")

            update["applied"] = True

        await db.payment_transactions.update_one({"session_id": session_id}, {"$set": update})
        return {
            "session_id": session_id,
            "status": sess_status,
            "payment_status": payment_status,
            "amount_total": getattr(s, "amount_total", None),
            "currency": getattr(s, "currency", None),
            "applied": bool(update.get("applied") or tx.get("applied")),
            "group_id": tx.get("group_id"),
        }
