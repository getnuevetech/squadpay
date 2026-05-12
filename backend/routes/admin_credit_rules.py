"""
Credit Rules Engine (Batch June 2025).

Admin-defined rules that grant credits to qualifying users at contribute
time. Credits start `pending`, become `active` once the source squad is
settled off the card, are auto-consumed on the user's next contribution
(via the existing `_consume_user_credits` flow in core.py), and are
forfeited on refund.

This module owns:
  - Rule CRUD (`/admin/credit-rules/*`)
  - Rule evaluator (`evaluate_and_award`) — called from contribute_routes
  - Lifecycle helpers — called from settle / refund handlers
  - User credit balance summary (`/users/{uid}/credits-summary`)

The underlying credit documents live in the existing `db.credits`
collection (extended with rule metadata + pending status).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _now_dt() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------- Schemas ----------

class CriteriaIn(BaseModel):
    """
    Eligibility criteria — exactly one type per rule.
      first_time         → user's 1st-ever successful contribution
      nth_contribution   → user's Nth contribution (N >= 1)
      date               → contribution falls in [date_from, date_to]
      nth_of_period      → Nth distinct user contributing within day/month
      specific_names     → user's display name matches one of `names` (CI)
      specific_users     → user_id ∈ `user_ids`
      specific_groups    → group_id ∈ `group_ids`
    """
    type: str
    n: Optional[int] = None
    period: Optional[str] = None        # "day" | "month"
    date_from: Optional[str] = None     # iso date
    date_to: Optional[str] = None       # iso date
    names: Optional[List[str]] = None
    user_ids: Optional[List[str]] = None
    group_ids: Optional[List[str]] = None


class RewardIn(BaseModel):
    """
    type:
      fixed              → flat amount in USD
      pct_user_no_fees   → percentage of user's contribution (excluding fees)
      pct_group_no_fees  → percentage of squad's collected contributions (excl fees)
    value:  number (dollars when fixed; percentage 0–100 when pct_*)
    cap:    optional max payout per single award (USD)
    """
    type: str
    value: float
    cap: Optional[float] = None


class RuleIn(BaseModel):
    name: str
    active: bool = True
    message: str
    criteria: CriteriaIn
    reward: RewardIn
    expiry_days: Optional[int] = None      # null = never expires
    stackable_with: List[str] = Field(default_factory=list)


class RulePatchIn(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None
    message: Optional[str] = None
    criteria: Optional[CriteriaIn] = None
    reward: Optional[RewardIn] = None
    expiry_days: Optional[int] = None
    stackable_with: Optional[List[str]] = None


# ---------- Public helpers (called from other routes) ----------

async def evaluate_and_award(
    db,
    *,
    user: dict,
    group: dict,
    contribution: dict,
    net_contribution_amount: float,
    net_group_total: float,
) -> List[dict]:
    """
    Evaluate every active rule against this contribution.

    Returns the list of newly-awarded credit docs (status="pending") so the
    caller can echo them in the API response for the success screen / SMS.

    The caller is responsible for sending SMS/inbox notifications (we just
    return the data so the contribute endpoint can compose the response).
    """
    rules = await db.credit_rules.find({"active": True}, {"_id": 0}).to_list(length=None)
    if not rules:
        return []

    user_id = user.get("id")
    group_id = group.get("id")
    awarded: List[dict] = []
    awarded_rule_ids: List[str] = []

    # Sort by created_at so the order is stable (and so a rule earlier in
    # the table can disqualify later ones via the stacking check).
    rules.sort(key=lambda r: r.get("created_at") or "")

    for rule in rules:
        if not await _matches_criteria(db, rule, user=user, group=group,
                                       contribution=contribution):
            continue

        # Stacking guard — a rule joins the awards only if every rule
        # already awarded in this evaluation lists THIS rule in its
        # `stackable_with`, AND vice versa.
        if awarded_rule_ids:
            this_stack = set(rule.get("stackable_with") or [])
            ok = True
            for prev_id in awarded_rule_ids:
                if prev_id not in this_stack:
                    ok = False
                    break
                prev = next((r for r in rules if r.get("id") == prev_id), None)
                prev_stack = set((prev or {}).get("stackable_with") or [])
                if rule["id"] not in prev_stack:
                    ok = False
                    break
            if not ok:
                continue

        amount = _compute_reward(
            rule=rule,
            net_contribution_amount=net_contribution_amount,
            net_group_total=net_group_total,
        )
        if amount <= 0:
            continue

        expires_at = None
        exp_days = rule.get("expiry_days")
        if exp_days and int(exp_days) > 0:
            expires_at = (_now_dt() + dt.timedelta(days=int(exp_days))).isoformat()

        credit_id = f"cr_{uuid.uuid4().hex[:10]}"
        credit_doc = {
            "id": credit_id,
            "user_id": user_id,
            "amount": round(amount, 2),
            "consumed_amount": 0.0,
            "status": "pending",           # → "active" on settle, → "consumed"|"expired"|"forfeited"
            "created_at": _now(),
            "rule_id": rule["id"],
            "rule_name": rule.get("name") or "Credit",
            "rule_message": rule.get("message") or "",
            "source_group_id": group_id,
            "source_contribution_id": contribution.get("id"),
            "expires_at": expires_at,
            "consumption_events": [],
        }
        await db.credits.insert_one(credit_doc)
        # SMS + in-app inbox dispatch. Best-effort — failure must NOT block
        # the contribute flow. Both channels carry the exact same body so
        # the user gets one consistent message. We append the "Terms &
        # Conditions Applied" tag + a deep link to the credits clause.
        try:
            phone = (user.get("phone") or "").strip()
            sms_body = _compose_credit_message(credit_doc, group_id)
            if phone:
                import sms_providers
                try:
                    await sms_providers.send_sms(db, phone, sms_body)
                except Exception:
                    pass
            inbox_id = f"inb_{uuid.uuid4().hex[:10]}"
            await db.user_inbox.insert_one({
                "id": inbox_id,
                "user_id": user_id,
                "broadcast_id": f"credit:{rule['id']}",
                "message": sms_body,
                "image_url": None,
                "link_url": "/legal/terms?section=credits",
                "read_at": None,
                "created_at": _now(),
            })
        except Exception as e:
            logger.warning(f"[credit-rules] notify failed for {user_id}: {e}")
        awarded.append({
            "id": credit_id,
            "amount": credit_doc["amount"],
            "rule_id": rule["id"],
            "rule_name": credit_doc["rule_name"],
            "message": credit_doc["rule_message"],
            "expires_at": expires_at,
        })
        awarded_rule_ids.append(rule["id"])

        # Update aggregate counters on the rule for the admin dashboard.
        await db.credit_rules.update_one(
            {"id": rule["id"]},
            {"$inc": {"match_count": 1, "total_paid_out": credit_doc["amount"]}},
        )

    return awarded


async def mark_credits_available(db, group_id: str) -> int:
    """When a squad is settled (paid off the card), promote any pending
    credits earned FROM that squad to status `active` so they can be
    consumed on the next contribution. Returns the count promoted."""
    res = await db.credits.update_many(
        {"source_group_id": group_id, "status": "pending"},
        {"$set": {"status": "active", "activated_at": _now()}},
    )
    return res.modified_count


async def forfeit_credits_on_refund(db, group_id: str, user_id: str) -> int:
    """Refund forfeit rule (from product spec): credit is removed when the
    refunded transaction had ANY portion paid via credit. We're slightly
    stricter: we forfeit
      (a) any UNUSED credit earned FROM the refunded squad, and
      (b) any credit that was CONSUMED on a contribution to the refunded
          squad (it's already spent so the dollars are gone — we just
          flag it as forfeited so the ledger reflects the loss).

    Returns the count of credit docs touched.
    """
    touched = 0
    # (a) Unused credits sourced from the refunded squad.
    res_a = await db.credits.update_many(
        {
            "source_group_id": group_id,
            "user_id": user_id,
            "status": {"$in": ["pending", "active"]},
        },
        {"$set": {"status": "forfeited", "forfeited_at": _now(),
                  "forfeit_reason": "refund_on_source_squad"}},
    )
    touched += res_a.modified_count

    # (b) Credits that were partially or fully consumed against the
    # refunded squad. We mark them as forfeited so reconciliation knows
    # the cash never settled.
    cursor = db.credits.find(
        {"user_id": user_id, "consumption_events.group_id": group_id},
    )
    async for c in cursor:
        if c.get("status") == "forfeited":
            continue
        await db.credits.update_one(
            {"id": c["id"]},
            {"$set": {"status": "forfeited", "forfeited_at": _now(),
                      "forfeit_reason": "refund_consumed_credit"}},
        )
        touched += 1
    return touched


# ---------- Internals ----------

async def _matches_criteria(db, rule: dict, *, user: dict, group: dict,
                            contribution: dict) -> bool:
    c = rule.get("criteria") or {}
    t = (c.get("type") or "").lower()

    if t == "first_time":
        prior = await db.groups.count_documents({
            "contributions.user_id": user["id"],
        })
        # contribution was just inserted so "first" means prior count == 1.
        return prior <= 1

    if t == "nth_contribution":
        target = int(c.get("n") or 0)
        if target < 1:
            return False
        cnt = await db.groups.count_documents({
            "contributions.user_id": user["id"],
        })
        return cnt == target

    if t == "date":
        df = c.get("date_from")
        dT = c.get("date_to") or df
        now_iso = _now()
        return (not df or df <= now_iso) and (not dT or now_iso <= dT + "T23:59:59Z")

    if t == "nth_of_period":
        target = int(c.get("n") or 0)
        period = (c.get("period") or "day").lower()
        if target < 1:
            return False
        start = _now_dt().replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "month":
            start = start.replace(day=1)
        # Count distinct users who contributed within this window so far,
        # INCLUDING this one. The current user qualifies if they push the
        # window count to `target`.
        pipeline = [
            {"$match": {"contributions.created_at": {"$gte": start.isoformat()}}},
            {"$unwind": "$contributions"},
            {"$match": {"contributions.created_at": {"$gte": start.isoformat()}}},
            {"$group": {"_id": "$contributions.user_id",
                        "first_at": {"$min": "$contributions.created_at"}}},
            {"$sort": {"first_at": 1}},
        ]
        rows = await db.groups.aggregate(pipeline).to_list(length=None)
        try:
            pos = next(i for i, r in enumerate(rows) if r["_id"] == user["id"]) + 1
        except StopIteration:
            return False
        return pos == target

    if t == "specific_names":
        names = [n.strip().lower() for n in (c.get("names") or []) if n]
        return (user.get("name") or "").strip().lower() in names

    if t == "specific_users":
        return user["id"] in (c.get("user_ids") or [])

    if t == "specific_groups":
        return group["id"] in (c.get("group_ids") or [])

    return False


def _compute_reward(*, rule: dict, net_contribution_amount: float,
                    net_group_total: float) -> float:
    r = rule.get("reward") or {}
    t = (r.get("type") or "").lower()
    v = float(r.get("value") or 0)
    cap = r.get("cap")
    cap = float(cap) if cap is not None else None

    if t == "fixed":
        amt = v
    elif t == "pct_user_no_fees":
        amt = (v / 100.0) * max(0.0, net_contribution_amount)
    elif t == "pct_group_no_fees":
        amt = (v / 100.0) * max(0.0, net_group_total)
    else:
        return 0.0
    if cap is not None and amt > cap:
        amt = cap
    return max(0.0, round(amt, 2))


def _compose_credit_message(credit_doc: dict, group_id: str) -> str:
    """Single source of truth for the in-app + SMS credit-earned message.
    Per product spec we always append "Terms & Conditions Applied" + a
    link to the credits clause."""
    import os
    rule_msg = credit_doc.get("rule_message") or "You earned a SquadPay credit"
    amount = credit_doc.get("amount") or 0
    base_url = os.environ.get("PUBLIC_APP_URL") or ""
    tc_url = (base_url.rstrip("/") + "/legal/terms?section=credits") if base_url else "/legal/terms?section=credits"
    parts = [
        rule_msg,
        f"Credit: ${float(amount):.2f}",
        f"Terms & Conditions Applied — {tc_url}",
    ]
    return "\n".join(parts)


# ---------- Routes ----------

def attach_credit_rules_routes(api_router: APIRouter, db, get_current_admin):
    admin_r = APIRouter()

    @admin_r.get("/admin/credit-rules")
    async def list_rules(admin=Depends(get_current_admin), page: int = 1, page_size: int = 50):
        page = max(1, int(page or 1))
        page_size = max(1, min(200, int(page_size or 50)))
        skip = (page - 1) * page_size
        total = await db.credit_rules.count_documents({})
        cursor = (
            db.credit_rules.find({}, {"_id": 0})
            .sort("created_at", -1)
            .skip(skip)
            .limit(page_size)
        )
        items = [d async for d in cursor]
        return {"items": items, "page": page, "page_size": page_size, "total": total,
                "has_more": (skip + len(items)) < total}

    @admin_r.post("/admin/credit-rules")
    async def create_rule(body: RuleIn, admin=Depends(get_current_admin)):
        if not (body.name or "").strip():
            raise HTTPException(400, "Name is required.")
        if not (body.message or "").strip():
            raise HTTPException(400, "Message is required.")
        _validate_criteria(body.criteria)
        _validate_reward(body.reward)
        rid = f"cr_rule_{uuid.uuid4().hex[:8]}"
        doc = {
            "id": rid,
            "name": body.name.strip(),
            "active": bool(body.active),
            "message": body.message.strip(),
            "criteria": body.criteria.dict(),
            "reward": body.reward.dict(),
            "expiry_days": body.expiry_days,
            "stackable_with": body.stackable_with or [],
            "created_at": _now(),
            "match_count": 0,
            "total_paid_out": 0.0,
            "created_by": {"admin_id": admin.get("id"), "email": admin.get("email")},
        }
        await db.credit_rules.insert_one(doc)
        return doc

    @admin_r.patch("/admin/credit-rules/{rule_id}")
    async def patch_rule(rule_id: str, body: RulePatchIn, admin=Depends(get_current_admin)):
        rule = await db.credit_rules.find_one({"id": rule_id}, {"_id": 0})
        if not rule:
            raise HTTPException(404, "Rule not found.")
        update: Dict[str, Any] = {}
        if body.name is not None:
            update["name"] = body.name.strip()
        if body.active is not None:
            update["active"] = bool(body.active)
        if body.message is not None:
            update["message"] = body.message.strip()
        if body.criteria is not None:
            _validate_criteria(body.criteria)
            update["criteria"] = body.criteria.dict()
        if body.reward is not None:
            _validate_reward(body.reward)
            update["reward"] = body.reward.dict()
        if body.expiry_days is not None:
            update["expiry_days"] = body.expiry_days
        if body.stackable_with is not None:
            update["stackable_with"] = body.stackable_with
        if update:
            update["updated_at"] = _now()
            await db.credit_rules.update_one({"id": rule_id}, {"$set": update})
        return await db.credit_rules.find_one({"id": rule_id}, {"_id": 0})

    @admin_r.delete("/admin/credit-rules/{rule_id}")
    async def delete_rule(rule_id: str, admin=Depends(get_current_admin)):
        res = await db.credit_rules.delete_one({"id": rule_id})
        if not res.deleted_count:
            raise HTTPException(404, "Rule not found.")
        return {"ok": True}

    api_router.include_router(admin_r)

    # ---------- User-facing inbox / balance ----------
    user_r = APIRouter()

    @user_r.get("/users/{user_id}/credits-summary")
    async def credits_summary(user_id: str):
        """Returns pending + available balances + recent ledger so the
        user-side Credits screen can render in one round-trip."""
        rows = await db.credits.find(
            {"user_id": user_id}, {"_id": 0},
        ).sort("created_at", -1).to_list(length=200)
        pending = round(sum(float(r.get("amount") or 0) for r in rows
                            if r.get("status") == "pending"), 2)
        available = round(sum(
            (float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0))
            for r in rows if r.get("status") == "active"
        ), 2)
        consumed = round(sum(float(r.get("consumed_amount") or 0) for r in rows), 2)
        return {
            "pending": pending,
            "available": available,
            "consumed_lifetime": consumed,
            "items": rows[:50],
        }

    api_router.include_router(user_r)


def _validate_criteria(c: CriteriaIn) -> None:
    t = (c.type or "").lower()
    if t not in {"first_time", "nth_contribution", "date", "nth_of_period",
                 "specific_names", "specific_users", "specific_groups"}:
        raise HTTPException(400, f"Unknown criteria type: {c.type}")
    if t == "nth_contribution" and (not c.n or c.n < 1):
        raise HTTPException(400, "nth_contribution requires n >= 1.")
    if t == "nth_of_period":
        if not c.n or c.n < 1:
            raise HTTPException(400, "nth_of_period requires n >= 1.")
        if (c.period or "").lower() not in {"day", "month"}:
            raise HTTPException(400, "nth_of_period.period must be 'day' or 'month'.")
    if t == "date" and not c.date_from:
        raise HTTPException(400, "date criteria requires date_from (YYYY-MM-DD).")
    if t == "specific_names" and not c.names:
        raise HTTPException(400, "specific_names requires at least one name.")
    if t == "specific_users" and not c.user_ids:
        raise HTTPException(400, "specific_users requires at least one user_id.")
    if t == "specific_groups" and not c.group_ids:
        raise HTTPException(400, "specific_groups requires at least one group_id.")


def _validate_reward(r: RewardIn) -> None:
    t = (r.type or "").lower()
    if t not in {"fixed", "pct_user_no_fees", "pct_group_no_fees"}:
        raise HTTPException(400, f"Unknown reward type: {r.type}")
    if r.value is None or r.value <= 0:
        raise HTTPException(400, "Reward value must be > 0.")
    if t.startswith("pct_") and r.value > 100:
        raise HTTPException(400, "Percentage rewards cannot exceed 100.")
    if r.cap is not None and r.cap < 0:
        raise HTTPException(400, "Reward cap cannot be negative.")
