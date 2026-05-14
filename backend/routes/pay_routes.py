"""Pay merchant + repay loan + user/groups list (Batch B refactor)."""
import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException

from core import (
    PayIn, RepayIn,
    new_id, now_iso,
    _load_group_enriched, _recompute_group,
)

logger = logging.getLogger(__name__)


async def _dispatch_sms_to_user(db, user_id: str, body: str, event_key: str | None = None) -> str:
    """Best-effort SMS dispatch to a user, honoring admin Notification Config.

    Returns delivery_via tag for the notification record:
        - "sms_<provider>" on real send
        - "sms_mock" in dev/mock mode
        - "sms_no_phone" if user has no phone
        - "sms_failed" on any error
        - "sms_disabled_by_admin" if the event_key is set to "off" or "push"
    """
    try:
        # Best-effort push dispatch (parallel; never blocks SMS).
        # Admin-config honored inside push_provider.send_push_to_user().
        if event_key:
            try:
                from push_provider import send_push_to_user
                await send_push_to_user(
                    db, user_id, title="SquadPay", body=body[:240], event_key=event_key,
                )
            except Exception as e:
                logger.warning("[push] dispatch alongside SMS failed: %s", e)

        # Respect admin Notification Config: skip SMS if event is disabled.
        if event_key:
            try:
                from notification_config import should_send_sms
                if not await should_send_sms(db, event_key):
                    return "sms_disabled_by_admin"
            except Exception:
                pass  # On config failure, fall through to legacy default-on.
        u = await db.users.find_one({"id": user_id}, {"_id": 0, "phone": 1})
        phone = (u or {}).get("phone")
        if not phone:
            return "sms_no_phone"
        from sms_providers import send_sms
        sent_real, info, provider = await send_sms(db, phone, body)
        if sent_real:
            return f"sms_{provider or 'live'}"
        if provider == "mock":
            return "sms_mock"
        return "sms_failed"
    except Exception as e:
        logger.warning("[shortfall-sms] dispatch failed for %s: %s", user_id, e)
        return "sms_failed"


def attach_pay_routes(router: APIRouter, db):

    @router.post("/groups/{group_id}/pay")
    async def pay_group(group_id: str, body: PayIn):
        """Lead settles the bill with the merchant."""
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Squad not found")
        if group["lead_id"] != body.user_id:
            raise HTTPException(403, "Only lead can pay the merchant")
        if group.get("status") != "open":
            raise HTTPException(400, "Bill already paid")
        if group.get("is_blocked"):
            raise HTTPException(403, "This squad has been blocked by an administrator.")
        # A squad is by definition multi-person — the lead can't settle the
        # merchant until at least one other member has joined. This blocks
        # using the app as a solo wallet.
        if len(group.get("members") or []) < 2:
            raise HTTPException(
                400,
                "A squad needs at least 2 members before the bill can be paid. Invite someone first.",
            )
        user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if not user or not user.get("verified"):
            raise HTTPException(403, "Lead must verify phone before paying")
        if user.get("is_blocked"):
            raise HTTPException(403, "Your account has been blocked. Please contact support.")

        enriched = await _recompute_group(group)
        lead_per = next((p for p in enriched["per_user"] if p["user_id"] == body.user_id), None)
        if lead_per and lead_per["contributed"] + 0.01 < lead_per["total"]:
            raise HTTPException(
                400,
                f"Please contribute your own share first (${lead_per['total'] - lead_per['contributed']:.2f}).",
            )

        contributions = list(group.get("contributions", []))
        obligations = [
            o for o in (group.get("shortfall_obligations") or [])
            if o.get("kind") not in ("shortfall_member", "shortfall_split")
        ]
        notifications = [
            n for n in (group.get("notifications") or [])
            if n.get("kind") not in ("shortfall_assigned", "shortfall_lead_covered")
        ]
        total_contributed = sum(float(c["amount"]) for c in contributions)  # noqa: F841 — kept for backwards-compatible accounting hooks
        total = float(group.get("total_amount") or 0.0)  # noqa: F841 — kept for backwards-compatible accounting hooks
        # CRITICAL (June 2025 bug fix v2): The shortfall the lead is
        # covering = sum of each OTHER member's own bill gap
        # (total − contributed − repaid). We MUST NOT sum
        # `p.outstanding` because that field also includes
        # `shortfall_owed` — which is itself derived from absent
        # members' debt. Summing outstandings would double-count the
        # same dollars (once on the absent member's row, once on each
        # remaining member's row in `shortfall_split` mode), causing
        # the lead to be charged 2× or 3× the actual gap.
        shortfall = round(
            sum(
                max(
                    0.0,
                    float(p.get("total", 0.0) or 0.0)
                    - float(p.get("contributed", 0.0) or 0.0)
                    - float(p.get("repaid", 0.0) or 0.0),
                )
                for p in enriched.get("per_user", [])
                if p.get("user_id") != body.user_id
            ),
            2,
        )

        settlement: Optional[dict] = None
        awaiting_obligations = False
        if shortfall > 0.01:
            mode = body.shortfall_mode
            if not mode:
                raise HTTPException(
                    400,
                    f"Bill is short ${shortfall:.2f}. Choose how to settle the shortfall.",
                )
            is_loan = bool(body.is_loan) if body.is_loan is not None else True
            beneficiaries = [
                p["user_id"] for p in enriched["per_user"]
                if p["outstanding"] > 0.01 and p["user_id"] != group["lead_id"]
            ]

            if mode == "lead":
                funder_id = group["lead_id"]
                contributions.append({
                    "id": new_id("c_"),
                    "user_id": funder_id,
                    "amount": shortfall,
                    "is_shortfall": True,
                    "is_loan": is_loan,
                    "covers": beneficiaries,
                    "at": now_iso(),
                })
                for bid in beneficiaries:
                    msg = (
                        f"Lead covered ${shortfall:.2f} shortfall on your behalf — please repay."
                        if is_loan
                        else f"Lead covered the ${shortfall:.2f} shortfall as a gift — no repayment needed."
                    )
                    via = await _dispatch_sms_to_user(db, bid, msg, event_key="shortfall_lead_covered")
                    notifications.append({
                        "id": new_id("n_"),
                        "user_id": bid,
                        "kind": "shortfall_lead_covered",
                        "amount": shortfall,
                        "message": msg,
                        "at": now_iso(),
                        "delivered_via": via,
                    })
            elif mode == "member":
                if not body.funder_member_id:
                    raise HTTPException(400, "funder_member_id required for member mode")
                funder_id = body.funder_member_id
                if not any(m["user_id"] == funder_id for m in group.get("members", [])):
                    raise HTTPException(400, "Funder is not a member")
                obligations.append({
                    "id": new_id("o_"),
                    "user_id": funder_id,
                    "amount": shortfall,
                    "kind": "shortfall_member",
                    "covers": [b for b in beneficiaries if b != funder_id],
                    "at": now_iso(),
                })
                msg = f"You've been asked to cover a ${shortfall:.2f} shortfall on the bill. Open SquadPay to pay your share."
                via = await _dispatch_sms_to_user(db, funder_id, msg, event_key="shortfall_assigned")
                notifications.append({
                    "id": new_id("n_"),
                    "user_id": funder_id,
                    "kind": "shortfall_assigned",
                    "amount": shortfall,
                    "message": msg,
                    "at": now_iso(),
                    "delivered_via": via,
                })
                awaiting_obligations = True
            elif mode == "split_equal":
                split_targets = [m["user_id"] for m in group.get("members", [])]
                if not split_targets:
                    raise HTTPException(400, "No members to split shortfall across")
                per_share = round(shortfall / len(split_targets), 2)
                assigned = 0.0
                for idx, uid in enumerate(split_targets):
                    amt = per_share if idx < len(split_targets) - 1 else round(shortfall - assigned, 2)
                    assigned += amt
                    obligations.append({
                        "id": new_id("o_"),
                        "user_id": uid,
                        "amount": amt,
                        "kind": "shortfall_split",
                        "covers": beneficiaries,
                        "at": now_iso(),
                    })
                    msg = f"Bill is short — your share of the shortfall is ${amt:.2f}. Open SquadPay to pay."
                    via = await _dispatch_sms_to_user(db, uid, msg, event_key="shortfall_assigned")
                    notifications.append({
                        "id": new_id("n_"),
                        "user_id": uid,
                        "kind": "shortfall_assigned",
                        "amount": amt,
                        "message": msg,
                        "at": now_iso(),
                        "delivered_via": via,
                    })
                is_loan = True
                awaiting_obligations = True
            else:
                raise HTTPException(400, "Invalid shortfall_mode")

            settlement = {
                "mode": mode,
                "is_loan": is_loan,
                "amount": shortfall,
                "beneficiaries": beneficiaries,
                "at": now_iso(),
            }
            if mode in ("lead", "member"):
                settlement["funder_id"] = funder_id

        if awaiting_obligations:
            update_doc = {
                "shortfall_obligations": obligations,
                "notifications": notifications,
                "shortfall_settlement": settlement,
            }
            await db.groups.update_one({"id": group_id}, {"$set": update_doc})
            return await _load_group_enriched(db, group_id)

        others_contributed = any(c["user_id"] != group["lead_id"] for c in group.get("contributions", []))
        if shortfall <= 0.01:
            funding_mode = "group"
        elif others_contributed:
            funding_mode = "shortfall"
        else:
            funding_mode = "lead"

        update_doc = {
            "status": "paid",
            "funding_mode": funding_mode,
            "lead_paid_at": now_iso(),
            "lead_shortfall": shortfall,
            "contributions": contributions,
            "shortfall_obligations": obligations,
            "notifications": notifications,
        }
        if settlement:
            update_doc["shortfall_settlement"] = settlement

        await db.groups.update_one({"id": group_id}, {"$set": update_doc})

        if settlement and not settlement["is_loan"]:
            await db.groups.update_one({"id": group_id}, {"$set": {"status": "closed"}})

        return await _load_group_enriched(db, group_id)

    # ===== Issue Virtual Card on demand (lead-only) =====
    # Stripe Issuing card creation can fail silently from the contribute path
    # (network glitch, transient Stripe error, missing config). This endpoint
    # lets the Lead Dashboard / Card page lazily provision the card once the
    # bill is fully funded but no card has been minted yet.
    from pydantic import BaseModel as _BM
    class _IssueCardIn(_BM):
        user_id: str

    @router.post("/groups/{group_id}/issue-card")
    async def issue_card_now(group_id: str, body: _IssueCardIn):
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Squad not found")
        if group["lead_id"] != body.user_id:
            raise HTTPException(403, "Only the lead can issue the virtual card")
        # Already issued? Just return the current card
        existing = group.get("virtual_card") or {}
        if existing.get("stripe_card_id"):
            return {"ok": True, "already_issued": True, "virtual_card": existing}
        # Must be fully funded (within $0.01)
        total_contributed = float((group.get("funding") or {}).get("total_contributed") or 0)
        if not total_contributed:
            # try recomputing from contributions
            total_contributed = sum(
                float(c.get("amount") or 0) for c in (group.get("contributions") or [])
            )
        if total_contributed + 0.01 < float(group.get("total") or group.get("total_amount") or 0):
            raise HTTPException(
                400,
                f"Bill is not fully funded yet (${total_contributed:.2f} of "
                f"${float(group.get('total') or 0):.2f} collected). Card will be auto-issued "
                f"the moment funding completes.",
            )
        # Mark group as paid+group-funded if not already, then issue
        if group.get("status") == "open":
            await db.groups.update_one(
                {"id": group_id},
                {"$set": {
                    "status": "paid",
                    "funding_mode": group.get("funding_mode") or "group",
                    "lead_paid_at": now_iso(),
                    "lead_shortfall": 0.0,
                }},
            )
        # Now issue
        try:
            from issuing import issue_group_card
            refreshed = await db.groups.find_one({"id": group_id}, {"_id": 0})
            new_vc = await issue_group_card(db, refreshed)
        except Exception as e:
            logger.warning(f"[issue-card] failed for {group_id}: {e}")
            raise HTTPException(502, f"Could not provision virtual card: {e}")
        return {"ok": True, "virtual_card": new_vc, "group": await _load_group_enriched(db, group_id)}

    @router.post("/groups/{group_id}/repay")
    async def repay(group_id: str, body: RepayIn):
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Squad not found")
        if group.get("status") == "open":
            raise HTTPException(400, "Bill not yet settled with merchant; use contribute instead")
        user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        if not user.get("verified"):
            raise HTTPException(403, "Phone verification required before payment")

        enriched = await _recompute_group(group)
        per = next((p for p in enriched["per_user"] if p["user_id"] == body.user_id), None)
        if not per:
            raise HTTPException(403, "Not a member of this squad")
        if per["outstanding"] <= 0.01:
            raise HTTPException(400, "Nothing to repay")
        if body.amount > per["outstanding"] + 0.01:
            raise HTTPException(400, f"Amount exceeds outstanding ${per['outstanding']:.2f}")

        repayments = group.get("repayments", [])
        repayments.append({"id": new_id("r_"), "user_id": body.user_id, "amount": round(body.amount, 2), "at": now_iso()})
        await db.groups.update_one({"id": group_id}, {"$set": {"repayments": repayments}})

        enriched = await _load_group_enriched(db, group_id)
        all_settled = all(p["outstanding"] <= 0.01 for p in enriched["per_user"] if p["user_id"] != group["lead_id"])
        if all_settled:
            await db.groups.update_one({"id": group_id}, {"$set": {"status": "closed"}})
            enriched = await _load_group_enriched(db, group_id)
        return enriched

    @router.get("/users/{user_id}/groups")
    async def get_user_groups(user_id: str):
        groups = await db.groups.find(
            {"members.user_id": user_id}, {"_id": 0}
        ).sort("created_at", -1).to_list(100)

        # Resolve all member names in one round-trip so we can render avatar
        # stacks on the home screen without N+1 queries.
        all_member_ids = list({m.get("user_id") for g in groups for m in (g.get("members") or []) if m.get("user_id")})
        users = await db.users.find(
            {"id": {"$in": all_member_ids}}, {"_id": 0, "id": 1, "name": 1}
        ).to_list(length=None) if all_member_ids else []
        name_map = {u["id"]: u.get("name") or "" for u in users}

        enriched = []
        for g in groups:
            e = await _recompute_group(g)
            members = g.get("members", []) or []
            ordered = sorted(
                members,
                key=lambda m: (0 if m.get("user_id") == g.get("lead_id") else 1, m.get("joined_at") or ""),
            )
            preview = [
                {"user_id": m.get("user_id"), "name": name_map.get(m.get("user_id"), "")}
                for m in ordered[:4]
            ]
            # Phase J2 — surface this user's per-group totals so the home
            # FeaturedBillCard can show their expected contribution alongside
            # the group total without a second roundtrip.
            per = next((p for p in (e.get("per_user") or []) if p.get("user_id") == user_id), None)
            user_share = float(per.get("total")) if per else 0.0
            user_contributed = float(per.get("contributed")) if per else 0.0
            user_outstanding = float(per.get("outstanding")) if per else 0.0

            # Phase L+3 — surface paid_count (# members fully covered) and
            # contributed_total (sum collected so far) so the home featured
            # card "X of N paid · $A of $B" line is real, not mock.
            per_users = e.get("per_user") or []
            non_lead = [p for p in per_users if p.get("user_id") != g.get("lead_id")]
            # Count members who have actually put money toward the bill —
            # any contribution or repayment > 0 counts as "paid". Before
            # anyone contributes the count is 0, so a brand-new bill with
            # $0 collected will correctly show "0 of N paid".
            paid_count = sum(
                1 for p in per_users
                if float(p.get("contributed") or 0) > 0.01
                or float(p.get("repaid") or 0) > 0.01
            )
            funding = e.get("funding") or {}
            contributed_total_raw = float(
                funding.get("total_contributed") or funding.get("contributed_total") or 0
            )
            total_repaid = float(funding.get("total_repaid") or 0)
            # Cap displayed "collected" at the bill total so a lead pre-funding
            # the whole bill (lead-funded mode) can't show "$105 of $58 collected".
            bill_total = float(e.get("total") or 0)
            contributed_total_display = min(contributed_total_raw + total_repaid, bill_total) if bill_total > 0 else contributed_total_raw

            enriched.append({
                "id": g["id"],
                "title": g["title"],
                "total": e["total"],
                "status": g["status"],
                "derived_status": e["derived_status"],
                "lead_id": g["lead_id"],
                "created_at": g["created_at"],
                "member_count": len(members),
                "members_preview": preview,
                # Per-user fields
                "user_share": round(user_share, 2),
                "user_contributed": round(user_contributed, 2),
                "user_outstanding": round(user_outstanding, 2),
                # Group-level progress (used by FeaturedBillCard)
                "paid_count": paid_count,
                # member_count includes the lead; the "X of N" tile excludes
                # the lead, so expose the non-lead count too for accurate UX.
                "member_count_non_lead": len(non_lead),
                "funding": {
                    "total_contributed": round(contributed_total_display, 2),
                    "total_repaid": round(total_repaid, 2),
                    "contributed_total": round(contributed_total_display, 2),  # legacy alias
                    "total_contributed_raw": round(contributed_total_raw, 2),
                },
            })
        return enriched
