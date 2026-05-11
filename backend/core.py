"""Shared core: helpers, Pydantic models, and DB-dependent service functions.

Extracted from server.py during the Batch B refactor (post-Phase F2.2). These
utilities are imported by the route modules under /app/backend/routes/*.

Purity rule:
  - "Pure" helpers (no DB) are top-level functions.
  - DB-dependent helpers all take `db` as the first argument (no module-level
    state) — this keeps the routes/ modules trivially testable.
"""
from __future__ import annotations
import logging
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------- Pricing constants ----------------
TRANSACTION_FEE_RATE = 0.03  # 3% per-member surcharge
PLATFORM_FEE = 0.03          # 3 cents flat per member

# Admin-configurable extra fees (populated at startup / on admin PUT).
# Each entry: {id, name, type ("percent"|"flat"), value, enabled}.
# Kept as a module-level cache so the sync-ish _recompute_group can read it
# without needing a DB handle.
_EXTRA_FEES_CACHE: List[Dict[str, Any]] = []


def set_extra_fees_cache(fees: List[Dict[str, Any]]) -> None:
    """Called by the admin route + startup hook to refresh the cache."""
    global _EXTRA_FEES_CACHE
    _EXTRA_FEES_CACHE = list(fees or [])


def get_extra_fees_cache() -> List[Dict[str, Any]]:
    return list(_EXTRA_FEES_CACHE)


def _compute_extra_fees_per_member(merchant_subtotal: float, member_count: int) -> List[Dict[str, Any]]:
    """Return a list of {id,name,amount} per-member for each enabled extra
    fee, computed from the cache. `merchant_subtotal` is the items+tax+tip
    pre-fee amount; `member_count` is used to split flat fees evenly.

    • type=percent: amount = (value/100) * merchant_subtotal / member_count
    • type=flat:    amount = value / member_count (split equally)
    """
    out: List[Dict[str, Any]] = []
    if member_count <= 0:
        return out
    for f in _EXTRA_FEES_CACHE:
        if not f.get("enabled"):
            continue
        val = float(f.get("value") or 0)
        if val <= 0:
            continue
        if f.get("type") == "percent":
            amt = (val / 100.0) * merchant_subtotal / member_count
        else:
            amt = val / member_count
        out.append({
            "id": str(f.get("id") or ""),
            "name": str(f.get("name") or "Extra fee"),
            "amount": round(amt, 2),
        })
    return out

# C1: referral code helpers — 6-char uppercase, drop confusing chars (0/O/1/I)
_REFERRAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# ---------------- Pure helpers ----------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def new_short_code(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _gen_referral_code(length: int = 6) -> str:
    return "".join(secrets.choice(_REFERRAL_ALPHABET) for _ in range(length))


def clean_mongo(doc: dict) -> dict:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


def gen_virtual_card() -> Optional[dict]:
    """DEPRECATED: Mock virtual card generator removed in Phase F1.

    Real virtual cards are now issued via Stripe Issuing when a group is fully funded.
    See /app/backend/issuing.py :: issue_group_card().
    """
    return None


def _apply_group_discount(subtotal_with_tax_tip: float, discount: dict | None) -> tuple[float, float]:
    """Return (final_total, discount_amount). discount = {type: 'flat'|'percent', value: number}.

    'flat' = flat $ off, capped at subtotal. 'percent' = percentage off (0–100).
    """
    if not discount:
        return round(subtotal_with_tax_tip, 2), 0.0
    dtype = discount.get("type")
    val = float(discount.get("value") or 0)
    if val <= 0:
        return round(subtotal_with_tax_tip, 2), 0.0
    if dtype == "percent":
        amount = round(subtotal_with_tax_tip * min(val, 100) / 100.0, 2)
    else:
        amount = min(round(val, 2), round(subtotal_with_tax_tip, 2))
    final = max(0.0, round(subtotal_with_tax_tip - amount, 2))
    return final, round(amount, 2)


# ---------------- DB-dependent helpers ----------------

async def generate_unique_referral_code(db) -> str:
    for _ in range(20):
        code = _gen_referral_code()
        exists = await db.users.find_one({"referral_code": code}, {"_id": 0, "id": 1})
        if not exists:
            return code
    return _gen_referral_code(8)


async def _get_referral_settings(db) -> dict:
    """Read referral system settings (created lazily with safe defaults)."""
    rec = await db.app_settings.find_one({"key": "referrals"}, {"_id": 0})
    if not rec:
        rec = {
            "key": "referrals",
            "enabled": False,
            "referrer_credit": 0.0,
            "referee_credit": 0.0,
            "updated_at": now_iso(),
        }
        await db.app_settings.insert_one(rec.copy())
    return rec


async def _maybe_grant_referral_rewards(db, user: dict):
    """Grant pending credits to referrer + referee on FIRST verify, idempotent."""
    if not user or not user.get("referred_by_user_id"):
        return
    if user.get("referral_reward_granted"):
        return
    settings = await _get_referral_settings(db)
    if not settings.get("enabled"):
        await db.users.update_one({"id": user["id"]}, {"$set": {"referral_reward_granted": True}})
        return

    referrer_amt = float(settings.get("referrer_credit") or 0)
    referee_amt = float(settings.get("referee_credit") or 0)
    referrer_id = user["referred_by_user_id"]

    rows = []
    if referrer_amt > 0:
        rows.append({
            "id": new_id("cr_"),
            "user_id": referrer_id,
            "amount": round(referrer_amt, 2),
            "kind": "referral_referrer",
            "source_user_id": user["id"],
            "status": "active",
            "note": f"Referral reward: {user.get('name')} signed up with your code.",
            "created_at": now_iso(),
        })
    if referee_amt > 0:
        rows.append({
            "id": new_id("cr_"),
            "user_id": user["id"],
            "amount": round(referee_amt, 2),
            "kind": "referral_referee",
            "source_user_id": referrer_id,
            "status": "active",
            "note": "Welcome bonus for using a referral code.",
            "created_at": now_iso(),
        })
    if rows:
        await db.credits.insert_many([r.copy() for r in rows])
    await db.users.update_one(
        {"id": user["id"]}, {"$set": {"referral_reward_granted": True}}
    )


async def _activate_pending_credits(db):
    """One-shot migration: flip leftover 'pending' credits to 'active'."""
    try:
        await db.credits.update_many(
            {"consumed_amount": {"$exists": False}},
            {"$set": {"consumed_amount": 0}},
        )
        res = await db.credits.update_many(
            {"status": "pending"}, {"$set": {"status": "active"}}
        )
        if res.modified_count:
            logger.info(f"[c2] activated {res.modified_count} pending credits")
    except Exception as e:
        logger.warning(f"[c2] pending->active migration failed: {e}")


async def _user_credit_balance(db, user_id: str) -> float:
    rows = await db.credits.find(
        {"user_id": user_id, "status": "active"},
        {"_id": 0, "amount": 1, "consumed_amount": 1},
    ).to_list(length=None)
    bal = 0.0
    for r in rows:
        bal += float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0)
    return round(max(0.0, bal), 2)


async def _consume_user_credits(db, user_id: str, amount: float, group_id: str, contribution_id: str) -> tuple[float, list]:
    """Consume up to `amount` from user's active credits, FIFO by created_at."""
    if amount <= 0:
        return 0.0, []
    rows = await db.credits.find(
        {"user_id": user_id, "status": "active"}, {"_id": 0}
    ).sort("created_at", 1).to_list(length=None)
    remaining = round(float(amount), 2)
    consumed_total = 0.0
    consumption_log: list = []
    for r in rows:
        if remaining <= 0:
            break
        avail = round(float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0), 2)
        if avail <= 0:
            continue
        take = min(avail, remaining)
        new_consumed = round(float(r.get("consumed_amount") or 0) + take, 2)
        new_status = "consumed" if new_consumed + 0.001 >= float(r["amount"]) else "active"
        await db.credits.update_one(
            {"id": r["id"]},
            {"$set": {
                "consumed_amount": new_consumed,
                "status": new_status,
                "last_consumed_at": now_iso(),
            },
             "$push": {
                "consumption_events": {
                    "amount": round(take, 2),
                    "group_id": group_id,
                    "contribution_id": contribution_id,
                    "at": now_iso(),
                }
            }},
        )
        consumption_log.append({
            "credit_id": r["id"],
            "amount": round(take, 2),
            "group_id": group_id,
            "contribution_id": contribution_id,
            "at": now_iso(),
        })
        remaining = round(remaining - take, 2)
        consumed_total = round(consumed_total + take, 2)
    return consumed_total, consumption_log


async def _recompute_group(group: dict) -> dict:
    """Compute per-user breakdown and totals. Mutates nothing in DB; returns enriched dict."""
    items = group.get("items", [])
    assignments = group.get("assignments", [])
    members = group.get("members", [])
    split_mode = group.get("split_mode", "itemized")
    subtotal = sum(i["price"] * i["quantity"] for i in items)
    tax = group.get("tax", 0.0)
    tip = group.get("tip", 0.0)
    total = group.get("total_amount") or (subtotal + tax + tip)

    per_user_food: Dict[str, float] = {m["user_id"]: 0.0 for m in members}
    unclaimed_items: List[Dict[str, Any]] = []

    if split_mode == "fast":
        if members:
            equal = total / len(members)
            per_user = [
                {"user_id": m["user_id"], "food": round(equal, 2), "tax_tip": 0.0, "total": round(equal, 2)}
                for m in members
            ]
        else:
            per_user = []
    else:
        for item in items:
            item_id = item["id"]
            claimed_qty = sum(a["quantity"] for a in assignments if a["item_id"] == item_id)
            remaining = item["quantity"] - claimed_qty
            if remaining > 0:
                unclaimed_items.append({"item_id": item_id, "name": item["name"], "remaining": remaining, "price": item["price"]})
            for a in assignments:
                if a["item_id"] == item_id and a["user_id"] in per_user_food:
                    per_user_food[a["user_id"]] += a["quantity"] * item["price"]
        extras = tax + tip
        per_user = []
        for m in members:
            food = per_user_food.get(m["user_id"], 0.0)
            share = (food / subtotal) if subtotal > 0 else 0.0
            extra = round(share * extras, 2)
            per_user.append({
                "user_id": m["user_id"],
                "food": round(food, 2),
                "tax_tip": extra,
                "total": round(food + extra, 2),
            })

    fully_claimed = (split_mode == "fast") or (len(unclaimed_items) == 0 and subtotal > 0)

    for p in per_user:
        merchant_share = round(p["total"], 2)
        p["merchant_share"] = merchant_share
        p["transaction_fee"] = round(merchant_share * TRANSACTION_FEE_RATE, 2)
        p["platform_fee"] = round(PLATFORM_FEE, 2)
        # Admin-configurable extra fees (split equally across members).
        extra_fees = _compute_extra_fees_per_member(merchant_share, len(per_user))
        p["extra_fees"] = extra_fees
        extras_sum = round(sum(ef["amount"] for ef in extra_fees), 2)
        p["extra_fees_total"] = extras_sum
        p["total"] = round(
            merchant_share + p["transaction_fee"] + p["platform_fee"] + extras_sum,
            2,
        )

    contributions = group.get("contributions", [])
    repayments = group.get("repayments", [])
    contrib_by_user: Dict[str, float] = {}
    for c in contributions:
        contrib_by_user[c["user_id"]] = contrib_by_user.get(c["user_id"], 0.0) + float(c["amount"])
    repaid_by_user: Dict[str, float] = {}
    for r in repayments:
        repaid_by_user[r["user_id"]] = repaid_by_user.get(r["user_id"], 0.0) + float(r["amount"])

    lead_id = group.get("lead_id")
    settlement = group.get("shortfall_settlement") or {}
    gift_active = bool(settlement) and not settlement.get("is_loan", True)
    beneficiaries = set(settlement.get("beneficiaries") or [])

    obligations = group.get("shortfall_obligations", []) or []
    obligation_by_user: Dict[str, float] = {}
    for o in obligations:
        obligation_by_user[o["user_id"]] = obligation_by_user.get(o["user_id"], 0.0) + float(o.get("amount", 0))

    for p in per_user:
        uid = p["user_id"]
        p["contributed"] = round(contrib_by_user.get(uid, 0.0), 2)
        p["repaid"] = round(repaid_by_user.get(uid, 0.0), 2)
        p["shortfall_owed"] = round(obligation_by_user.get(uid, 0.0), 2)
        if uid == lead_id:
            p["outstanding"] = round(max(0.0, p["shortfall_owed"] - p["repaid"]), 2)
        elif gift_active and uid in beneficiaries:
            p["outstanding"] = 0.0
        else:
            total_owed = p["total"] + p["shortfall_owed"]
            p["outstanding"] = round(max(0.0, total_owed - p["contributed"] - p["repaid"]), 2)
        # Phase H7 — Overpayment tracking. When the group expands or a member
        # paid more than their fair share (e.g. lead paid full bill before adding
        # members, then equal-split halves their share), surface the difference
        # so the user can request a refund.
        owed_for_overpaid_calc = p["total"] + p["shortfall_owed"]
        already_paid = p["contributed"] + p["repaid"]
        p["overpaid"] = round(max(0.0, already_paid - owed_for_overpaid_calc), 2)

    total_contributed = round(sum(contrib_by_user.values()), 2)
    total_repaid = round(sum(repaid_by_user.values()), 2)
    total_amount = group.get("total_amount") or round(total, 2)
    lead_shortfall = group.get("lead_shortfall")
    if lead_shortfall is None:
        lead_shortfall = round(max(0.0, total_amount - total_contributed), 2)

    virtual_card = group.get("virtual_card")
    if virtual_card:
        virtual_card = {**virtual_card, "balance": total_contributed}

    raw_status = group.get("status", "open")
    settlement = group.get("shortfall_settlement") or {}
    has_outstanding = any(p["outstanding"] > 0.01 for p in per_user)
    lead_loaned = (
        settlement.get("mode") == "lead"
        and settlement.get("is_loan", False)
        and any(
            p["outstanding"] > 0.01
            for p in per_user
            if p["user_id"] in (settlement.get("beneficiaries") or [])
        )
    )
    vc = group.get("virtual_card") or {}
    card_spent = float(vc.get("spent") or 0.0)
    card_status = vc.get("status")
    card_swiped = card_spent > 0.005 or (card_status == "inactive" and bool(vc.get("transactions")))

    if raw_status == "open":
        if not group.get("contributions"):
            derived_status = "bill_created"
        elif total_contributed + 0.01 >= total_amount and not has_outstanding:
            derived_status = "contributed"
        else:
            derived_status = "contributing"
    elif raw_status == "paid":
        if card_swiped:
            derived_status = "settled_with_debt" if (lead_loaned or has_outstanding) else "bill_settled"
        else:
            derived_status = "settled_with_debt" if (lead_loaned or has_outstanding) else "contributed"
    else:
        derived_status = "bill_settled"

    return {
        **group,
        "virtual_card": virtual_card,
        "subtotal": round(subtotal, 2),
        "total": round(total, 2),
        "per_user": per_user,
        "unclaimed": unclaimed_items,
        "fully_claimed": fully_claimed,
        "derived_status": derived_status,
        "funding": {
            "total_contributed": total_contributed,
            "total_repaid": total_repaid,
            "lead_shortfall": round(lead_shortfall, 2),
            "remaining_to_collect": round(max(0.0, total_amount - total_contributed), 2),
            "fees_total": round(sum(p["transaction_fee"] + p["platform_fee"] for p in per_user), 2),
        },
    }


async def _load_group_enriched(db, group_id: str) -> dict:
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    user_ids = [m["user_id"] for m in group.get("members", [])]
    users = await db.users.find({"id": {"$in": user_ids}}, {"_id": 0}).to_list(1000)
    user_map = {u["id"]: u for u in users}
    for m in group.get("members", []):
        u = user_map.get(m["user_id"], {})
        m["name"] = u.get("name", "Unknown")
        m["phone"] = u.get("phone")
        m["verified"] = u.get("verified", False)
    enriched = await _recompute_group(group)
    return enriched


# ---------------- Pydantic models ----------------

class RegisterIn(BaseModel):
    name: str
    referral_code: Optional[str] = None


class UserOut(BaseModel):
    id: str
    name: str
    phone: Optional[str] = None
    verified: bool = False
    created_at: str
    referral_code: Optional[str] = None
    referred_by_user_id: Optional[str] = None
    terms_accepted_at: Optional[str] = None  # ISO timestamp of T&C acceptance, or None


class SendOtpIn(BaseModel):
    user_id: str
    phone: str


class VerifyOtpIn(BaseModel):
    user_id: str
    phone: str
    code: str
    # Phase H2: when an account with this phone already exists, the client must
    # explicitly confirm before we merge the placeholder user into the existing one.
    confirm_existing: Optional[bool] = False


class ItemIn(BaseModel):
    name: str
    price: float
    quantity: int = 1


class CreateGroupIn(BaseModel):
    lead_id: str
    title: str
    total_amount: float
    split_mode: str = "itemized"
    tax: float = 0.0
    tip: float = 0.0
    items: List[ItemIn] = []


class JoinGroupIn(BaseModel):
    user_id: str


class RemoveMemberIn(BaseModel):
    """Lead removes a member from the group. Pre-conditions enforced by the
    route: bill must still be open, target must not be the lead, and the
    target must have made no contribution or repayment."""
    user_id: str       # the lead performing the action
    target_id: str     # the member to remove


class UpdateItemsIn(BaseModel):
    items: List[ItemIn]


class AssignIn(BaseModel):
    user_id: str
    item_id: str
    quantity: int


class PayIn(BaseModel):
    user_id: str
    shortfall_mode: Optional[str] = None
    is_loan: Optional[bool] = True
    funder_member_id: Optional[str] = None


class UpdateGroupMetaIn(BaseModel):
    user_id: str
    title: Optional[str] = None
    tax: Optional[float] = None
    tip: Optional[float] = None


class RepayIn(BaseModel):
    user_id: str
    amount: float


class ContributeIn(BaseModel):
    user_id: str
    amount: Optional[float] = None
    notify_on_settled: Optional[bool] = False
    origin_url: Optional[str] = None
    app_return_url: Optional[str] = None


class AppendItemsIn(BaseModel):
    user_id: str
    items: List[ItemIn]


class ItemPatchIn(BaseModel):
    user_id: str
    quantity_delta: int


class ScanReceiptIn(BaseModel):
    image_base64: str
