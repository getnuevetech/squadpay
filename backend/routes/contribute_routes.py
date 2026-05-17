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
from ledger import make_txn_id, record_charge_event, to_cents
from adapters.registry import get_charge_adapter

logger = logging.getLogger(__name__)


def attach_contribute_routes(router: APIRouter, db):

    @router.post("/groups/{group_id}/contribute")
    async def contribute(group_id: str, body: ContributeIn, request: Request):
        """Member (or lead) pays their share via real Stripe Checkout (Phase F1).

        June 2025 — Also handles OWING-MEMBER repayments for covered shortfalls.
        When a Squad is already at status="paid" or "lead_paid" but the
        caller has a shortfall_owed obligation (loan from a covering
        member), this endpoint routes their payment through Stripe Checkout
        and the repayment is distributed proportionally to covering members.
        """
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Squad not found")

        # Pre-fetch caller's shortfall obligation (if any) to allow repayment
        # on paid/lead_paid squads without breaking the original
        # status-gate for normal contributions.
        _enriched_for_check = await _recompute_group(group)
        _per_check = next((p for p in _enriched_for_check["per_user"] if p["user_id"] == body.user_id), None)
        _has_shortfall = bool(_per_check and float(_per_check.get("shortfall_owed") or 0) > 0.01 and float(_per_check.get("outstanding") or 0) > 0.01)
        _allowed_statuses = {"open"} | ({"paid", "lead_paid"} if _has_shortfall else set())
        if group.get("status") not in _allowed_statuses:
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
        # A squad is by definition multi-person — a single member cannot
        # contribute toward a "squad" bill until at least one other person
        # joins. This prevents the app being used as a solo wallet.
        if len(group.get("members") or []) < 2:
            raise HTTPException(
                400,
                "A squad needs at least 2 members before anyone can contribute. Invite someone first.",
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
            # STRICT funding check (June 2025 — penny-shortfall bug fix).
            # Previously used `total_contributed + 0.01 >= total_amount` which
            # silently flipped the group to "paid" when $0.01 short. Mirror
            # the integer-cent check used in core._recompute_group.
            _total_cents = int(round(float(group.get("total_amount") or 0) * 100))
            _tc_cents = int(round(float(total_contributed) * 100))
            if _total_cents > 0 and _tc_cents >= _total_cents:
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
            # Credit-rules engine — evaluate post-insert. Awarded credits
            # start `pending` and are surfaced to the client so the
            # success page can show a celebratory badge.
            awarded_credits: list = []
            try:
                from routes.admin_credit_rules import evaluate_and_award
                net_user = round(amount, 2)
                net_group = sum(float(c.get("amount") or 0) for c in contributions)
                fresh = await db.groups.find_one({"id": group_id}, {"_id": 0})
                fresh_user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
                awarded_credits = await evaluate_and_award(
                    db,
                    user=fresh_user or user,
                    group=fresh or group,
                    contribution=contributions[-1],
                    net_contribution_amount=net_user,
                    net_group_total=net_group,
                )
                # If the bill just settled, promote any pending credits now.
                if update_doc.get("status") == "paid":
                    from routes.admin_credit_rules import mark_credits_available
                    await mark_credits_available(db, group_id)
            except Exception as e:
                logger.warning(f"[contribute.credits] evaluator failed for {group_id}: {e}")
            result = await _load_group_enriched(db, group_id)
            return {"checkout_required": False, "credit_only": True, "amount": round(amount, 2),
                    "credit_applied": round(float(credit_applied), 2),
                    "awarded_credits": awarded_credits, "group": result}

        # ---- Path B: Cash needed
        origin = (body.origin_url or "").rstrip("/") if hasattr(body, "origin_url") else ""
        if not origin or not origin.startswith("http"):
            raise HTTPException(400, "origin_url (http(s)://...) is required when cash payment is needed")

        import stripe as _stripe_sdk
        _stripe_sdk.api_key = os.environ.get("STRIPE_API_KEY")

        # Phase 3 — pre-generate canonical txn_id BEFORE talking to gateway.
        txn_id = make_txn_id("charge")

        # Phase 4 — resolve active charge adapter.
        adapter = await get_charge_adapter(db)

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
            sess = await adapter.create_checkout_session(
                amount_cents=int(round(cash_owed * 100)),
                currency="usd",
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
                    "txn_id": txn_id,
                },
                idempotency_key=txn_id,
                product_name=f"SquadPay contribution — {group.get('title') or 'Squad Bill'}",
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"[{adapter.slug}] member contribute checkout failed: {e}")
            raise HTTPException(502, f"Charge gateway error: {e}")

        tx = {
            "id": f"px_{sess.session_id[:14]}",
            "session_id": sess.session_id,
            "txn_id": txn_id,
            "gateway_slug": adapter.slug,
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
                "txn_id": txn_id,
                "gateway": adapter.slug,
            },
            "applied": False,
            "ledger_posted": False,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.payment_transactions.insert_one(tx.copy())
        return {
            "checkout_required": True,
            "url": sess.url,
            "session_id": sess.session_id,
            "amount": round(amount, 2),
            "cash_owed": cash_owed,
            "credit_planned": credit_planned,
            "txn_id": txn_id,
        }

    @router.get("/contribute/status/{session_id}")
    async def get_contribute_status(session_id: str):
        """Poll/finalize a member-contribution checkout session (provider-agnostic)."""
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

        adapter = await get_charge_adapter(db)
        try:
            ss = await adapter.retrieve_session(session_id)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"[{adapter.slug}] contribute.status retrieve failed: {e}")
            raise HTTPException(502, f"Charge gateway error: {e}")

        payment_status = ss.payment_status
        sess_status = ss.status
        update: dict = {"status": sess_status, "payment_status": payment_status, "updated_at": now_iso()}

        if payment_status == "paid" and not tx.get("applied"):
            meta = tx.get("metadata") or {}
            group_id = tx["group_id"]
            user_id = tx["user_id"]
            cash_owed = float(meta.get("cash_owed") or tx.get("amount") or 0)
            credit_planned = float(meta.get("credit_planned") or 0)

            group = await db.groups.find_one({"id": group_id}, {"_id": 0})
            # June 2025 — owing-member repayment branch. When the Squad is
            # already funded (status=paid/lead_paid) and the caller has an
            # outstanding shortfall_owed, treat their Stripe charge as a
            # REPAYMENT (settles their obligation; covering members get
            # notified for back-collection / non-lead pay-out).
            if group and group.get("status") in ("paid", "lead_paid"):
                enriched_chk = await _recompute_group(group)
                per_chk = next((p for p in enriched_chk["per_user"] if p["user_id"] == user_id), None)
                owed = float((per_chk or {}).get("shortfall_owed") or 0)
                outstanding = float((per_chk or {}).get("outstanding") or 0)
                if owed > 0.01 and outstanding > 0.01:
                    repayments = list(group.get("repayments") or [])
                    repay_id = new_id("r_")
                    actual_amount = round(cash_owed, 2)
                    repayments.append({
                        "id": repay_id,
                        "user_id": user_id,
                        "amount": actual_amount,
                        "via": "stripe",
                        "stripe_session_id": session_id,
                        "at": now_iso(),
                    })
                    await db.groups.update_one(
                        {"id": group_id}, {"$set": {"repayments": repayments}}
                    )
                    # Distribute notification SMS to covering parties
                    # proportional to their cover amount. Find who covered
                    # for this owing user: contributions marked is_shortfall
                    # with covers=this_user (lead-covered case) OR
                    # shortfall_obligations.covers=this_user (member-covered).
                    covering_contribs = [
                        c for c in (group.get("contributions") or [])
                        if c.get("is_shortfall") and user_id in (c.get("covers") or [])
                    ]
                    covering_obligations = [
                        o for o in (group.get("shortfall_obligations") or [])
                        if user_id in (o.get("covers") or []) and o.get("user_id") != user_id
                    ]
                    cover_total = sum(float(c.get("amount") or 0) for c in covering_contribs) + \
                                  sum(float(o.get("amount") or 0) for o in covering_obligations)
                    covering_users: list[tuple[str, float]] = []
                    if cover_total > 0:
                        for c in covering_contribs:
                            covering_users.append((c.get("user_id"), float(c.get("amount") or 0)))
                        for o in covering_obligations:
                            covering_users.append((o.get("user_id"), float(o.get("amount") or 0)))
                    # Send SMS to each covering user with their proportional
                    # share of the repayment that just landed.
                    notifs = list(group.get("notifications") or [])
                    try:
                        from sms_providers import send_sms
                        repayer_user = await db.users.find_one({"id": user_id}, {"_id": 0, "name": 1}) or {}
                        repayer_name = repayer_user.get("name") or "A squad member"
                        for cov_uid, cov_amt in covering_users:
                            share = round((cov_amt / cover_total) * actual_amount, 2) if cover_total else actual_amount
                            msg = (
                                f"{repayer_name} just repaid ${share:.2f} toward the ${cov_amt:.2f} "
                                f"you covered. Open SquadPay to cash it out."
                            )
                            via = "sms_failed"
                            try:
                                u = await db.users.find_one({"id": cov_uid}, {"_id": 0, "phone": 1}) or {}
                                if u.get("phone"):
                                    sent_real, _info, prov = await send_sms(db, u["phone"], msg)
                                    via = f"sms_{prov or 'live'}" if sent_real else ("sms_mock" if prov == "mock" else "sms_failed")
                                else:
                                    via = "sms_no_phone"
                            except Exception:
                                via = "sms_failed"
                            notifs.append({
                                "id": new_id("n_"),
                                "user_id": cov_uid,
                                "kind": "shortfall_repaid",
                                "amount": share,
                                "message": msg,
                                "at": now_iso(),
                                "delivered_via": via,
                            })
                        if covering_users:
                            await db.groups.update_one(
                                {"id": group_id}, {"$set": {"notifications": notifs}}
                            )
                    except Exception as e:
                        logger.warning("[repay-webhook] cover-member notify failed: %s", e)

                    logger.info(
                        "[repay-webhook] %s repaid $%.2f → %d covering parties notified (cover_total=$%.2f)",
                        user_id, actual_amount, len(covering_users), cover_total,
                    )

            elif group and group.get("status") == "open":
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
                # STRICT funding check (June 2025 — penny-shortfall bug fix).
                _total_cents = int(round(float(group.get("total_amount") or 0) * 100))
                _tc_cents = int(round(float(total_contributed) * 100))
                if _total_cents > 0 and _tc_cents >= _total_cents:
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

                # Credit-rules engine — same hook as the credit-only path
                # above. Awarded credits flow back to the client via the
                # payment_transactions doc so the success screen can read
                # them on resume.
                awarded_credits: list = []
                try:
                    from routes.admin_credit_rules import evaluate_and_award, mark_credits_available
                    net_user = round(actual_amount, 2)
                    net_group = sum(float(c.get("amount") or 0) for c in contributions)
                    fresh = await db.groups.find_one({"id": group_id}, {"_id": 0})
                    fresh_user = await db.users.find_one({"id": user_id}, {"_id": 0})
                    if fresh_user and fresh:
                        awarded_credits = await evaluate_and_award(
                            db,
                            user=fresh_user,
                            group=fresh,
                            contribution=contributions[-1],
                            net_contribution_amount=net_user,
                            net_group_total=net_group,
                        )
                    if update_doc.get("status") == "paid":
                        await mark_credits_available(db, group_id)
                except Exception as e:
                    logger.warning(f"[contribute.status.credits] eval failed for {group_id}: {e}")
                # Persist awarded credits on the payment_transactions doc so
                # subsequent /status calls (on success page mount) return
                # them.
                update["awarded_credits"] = awarded_credits

            update["applied"] = True

            # Phase 3 — write immutable ledger event for the cash portion
            # (credit-only paths don't create a Stripe charge, so the ledger
            # entry uses cash_owed only).
            try:
                _txn = tx.get("txn_id") or (tx.get("metadata") or {}).get("txn_id")
                if _txn and cash_owed > 0:
                    await record_charge_event(
                        db,
                        txn_id=_txn,
                        bill_id=tx.get("group_id"),
                        user_id=tx.get("user_id"),
                        gross_cents=to_cents(cash_owed),
                        currency=tx.get("currency") or "usd",
                        reference={
                            "stripe_session_id": session_id,
                            "kind": "group_member_contribute",
                            "payment_transaction_id": tx.get("id"),
                            "credit_applied_usd": float(meta.get("credit_planned") or 0),
                        },
                        kind="group_member_contribute",
                    )
                    update["ledger_posted"] = True
                    update["ledger_posted_at"] = now_iso()
            except Exception as e:
                logger.exception(f"[ledger] contribute charge ledger write failed: {e}")

        await db.payment_transactions.update_one({"session_id": session_id}, {"$set": update})
        # Re-read the tx so a polling client can still see awarded_credits
        # after the row is marked `applied`.
        tx_after = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0}) or {}
        return {
            "session_id": session_id,
            "status": sess_status,
            "payment_status": payment_status,
            "amount_total": ss.amount_total_cents,
            "currency": ss.currency,
            "applied": bool(update.get("applied") or tx.get("applied")),
            "group_id": tx.get("group_id"),
            "awarded_credits": tx_after.get("awarded_credits") or [],
        }
