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


# ---------------- Pricing constants (admin-overridable) ----------------
# These are the *defaults* used until the admin saves an override on the
# Platform Fees page. The live values are kept in `_CORE_FEES_CACHE` and
# read by `_recompute_group` via the helpers below.
DEFAULT_TRANSACTION_FEE_RATE = 0.03  # 3% per-member surcharge
DEFAULT_PLATFORM_FEE = 0.03          # 3 cents flat per member

# Backwards-compat aliases — other modules historically imported these.
TRANSACTION_FEE_RATE = DEFAULT_TRANSACTION_FEE_RATE
PLATFORM_FEE = DEFAULT_PLATFORM_FEE

# Live overrides set by admin via /api/admin/app-config (or fallback to defaults).
_CORE_FEES_CACHE: Dict[str, float] = {
    "transaction_fee_rate": DEFAULT_TRANSACTION_FEE_RATE,
    "platform_fee": DEFAULT_PLATFORM_FEE,
}


def set_core_fees_cache(transaction_fee_rate: float, platform_fee: float) -> None:
    """Called by the admin route on save + at startup to refresh values."""
    global _CORE_FEES_CACHE
    _CORE_FEES_CACHE = {
        "transaction_fee_rate": float(transaction_fee_rate) if transaction_fee_rate is not None else DEFAULT_TRANSACTION_FEE_RATE,
        "platform_fee": float(platform_fee) if platform_fee is not None else DEFAULT_PLATFORM_FEE,
    }


def get_core_fees_cache() -> Dict[str, float]:
    return dict(_CORE_FEES_CACHE)


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


def new_short_code(length: int = 8, charset: str = "alphanumeric") -> str:
    """Generate a random short code for squad join codes.

    `charset` controls the alphabet:
      - "numeric"      → digits only (0-9)            — most user-friendly
      - "alpha"        → uppercase A-Z only
      - "alphanumeric" → A-Z + 0-9 (default, legacy)

    Admins can set the active charset + length via app_config._id=join_code.
    """
    if charset == "numeric":
        alphabet = string.digits
    elif charset == "alpha":
        alphabet = string.ascii_uppercase
    else:
        # Legacy default — uppercase + digits (excludes ambiguous chars later
        # if we want to harden, but keep simple for now).
        alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def get_join_code_config(db) -> Dict[str, Any]:
    """Read admin-configured join-code format + length, with safe defaults.

    Defaults to 6-digit numeric (per user spec — easiest to share verbally
    and type into the join field). Admin can override via the
    /admin/join-code-config endpoint.
    """
    cfg = await db.app_config.find_one({"_id": "join_code"}) or {}
    return {
        "charset": cfg.get("charset") or "numeric",
        "length": int(cfg.get("length") or 6),
    }


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
    # June 2025 — legacy "smart" mode was a UX option that fell through to
    # the itemized branch but never had per-item claims attached, so users
    # saw "$0 share" until they manually claimed. We now treat "smart" as
    # equal-split ("fast") so existing data renders correctly.
    if split_mode == "smart":
        split_mode = "fast"
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

    # Item 8 (June 2025) — Member with NO items claimed in itemized mode
    # should see $0 contribution (no fees either). Previously we tacked
    # transaction_fee + platform_fee + extras onto every member regardless
    # of whether they actually owed anything, which produced confusing
    # "$0.75 owed" lines for brand-new joiners and leads who hadn't
    # claimed yet. In FAST/equal mode we keep the old behavior since the
    # split is defined as "everyone pays an equal share" by design.
    no_food_users: set = set()
    if split_mode != "fast":
        no_food_users = {p["user_id"] for p in per_user if p.get("food", 0.0) <= 0.001}

    for p in per_user:
        merchant_share = round(p["total"], 2)
        p["merchant_share"] = merchant_share
        if p["user_id"] in no_food_users:
            # Zero out the entire breakdown — they have nothing to contribute
            # until an item is claimed for them.
            p["transaction_fee"] = 0.0
            p["platform_fee"] = 0.0
            p["extra_fees"] = []
            p["extra_fees_total"] = 0.0
            p["total"] = 0.0
            continue
        p["transaction_fee"] = round(merchant_share * _CORE_FEES_CACHE["transaction_fee_rate"], 2)
        p["platform_fee"] = round(_CORE_FEES_CACHE["platform_fee"], 2)
        # Admin-configurable extra fees (split equally across members WITH
        # items claimed — empty-handed members are excluded from the divisor).
        active_count = max(1, len(per_user) - len(no_food_users))
        extra_fees = _compute_extra_fees_per_member(merchant_share, active_count)
        p["extra_fees"] = extra_fees
        extras_sum = round(sum(ef["amount"] for ef in extra_fees), 2)
        p["extra_fees_total"] = extras_sum
        p["total"] = round(
            merchant_share + p["transaction_fee"] + p["platform_fee"] + extras_sum,
            2,
        )

    # Generalized reward application (June 2025) — `group.lead_rewards`
    # is an ARRAY of pending rewards (KYC, marketing, referral, etc.)
    # that were attached when the squad was created. We apply each in
    # order to the LEAD's per-user row, bounded by what they owe so we
    # never go negative or refund cash. Each reward exposes its `kind`
    # ("kyc" / "marketing" / …) so the FE can render distinct line
    # items. Back-compat: also reads the legacy singular
    # `group.lead_reward` for any pre-array groups.
    lead_rewards = list(group.get("lead_rewards") or [])
    legacy_reward = group.get("lead_reward") or None
    if legacy_reward and not any(r.get("id") == legacy_reward.get("id") for r in lead_rewards):
        lead_rewards.append({
            "kind": legacy_reward.get("kind") or "kyc",
            "mode": legacy_reward.get("mode"),
            "amount": float(legacy_reward.get("amount") or 0.0),
            "source": legacy_reward.get("source"),
        })

    if lead_rewards:
        lead_id = group.get("lead_id")
        for p in per_user:
            if p["user_id"] != lead_id:
                continue
            if p.get("total", 0) <= 0:
                # Lead hasn't claimed any items — no charge to discount.
                # Rewards stay attached on the group; they'll apply once
                # the lead claims something on a subsequent recompute.
                break
            applied: list[dict] = []
            for reward in lead_rewards:
                mode = reward.get("mode")
                if p["total"] <= 0:
                    break
                if mode == "credit_off_next_bill":
                    requested = float(reward.get("amount") or 0)
                    amt = round(min(requested, p["total"]), 2)
                    if amt > 0:
                        applied.append({
                            "kind": reward.get("kind") or "reward",
                            "mode": mode,
                            "amount": amt,
                            "source": reward.get("source"),
                        })
                        p["total"] = round(p["total"] - amt, 2)
                elif mode == "waive_platform_fees_next_bill":
                    waived = round(float(p.get("platform_fee") or 0), 2)
                    if waived > 0:
                        applied.append({
                            "kind": reward.get("kind") or "reward",
                            "mode": mode,
                            "amount": waived,
                            "source": reward.get("source"),
                        })
                        p["total"] = round(p["total"] - waived, 2)
                        p["platform_fee"] = 0.0
            if applied:
                # Expose what was applied so the FE can render a clean
                # line per reward (e.g. "−$10 KYC reward" then
                # "−$1.50 Holiday promo"). Also keep the legacy single-
                # reward field populated for any FE code still reading
                # `lead_reward`.
                p["lead_rewards"] = applied
                p["lead_reward"] = applied[0]
            break

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

    # June 2025 — Cover tracking for non-lead Pay Out eligibility.
    # Compute per-user `cover_amount` (how much THIS user covered for OTHERS)
    # and `cover_repaid` (how much of that has been repaid by owing members
    # so far). The FE uses (cover_amount - cover_repaid) to surface a Pay
    # Out CTA on covering members' dashboards.
    cover_by_user: Dict[str, float] = {}
    # 1. Lead-cover contributions (is_shortfall=True with covers list)
    for c in contributions:
        if c.get("is_shortfall") and c.get("covers"):
            cov_uid = c.get("user_id")
            cover_by_user[cov_uid] = cover_by_user.get(cov_uid, 0.0) + float(c.get("amount", 0))
    # 2. Member-cover obligations (assigned to a member to fund the shortfall)
    for o in obligations:
        if o.get("kind") in ("shortfall_member", "shortfall_split") and o.get("covers"):
            cov_uid = o.get("user_id")
            cover_by_user[cov_uid] = cover_by_user.get(cov_uid, 0.0) + float(o.get("amount", 0))
    # Cover repaid = sum of repayments from owing users whose `covers` list
    # included the covering user — distributed proportionally by cover share.
    # (Approximation: total repayments × this_user_cover / total_cover.)
    total_cover = round(sum(cover_by_user.values()), 2)
    total_owed_repayments = round(sum(
        float(r.get("amount") or 0)
        for r in repayments
        # Only repayments from members who had obligations (not lead) count
        if any(o.get("user_id") == r.get("user_id") for o in obligations)
    ), 2)
    for p in per_user:
        cov = round(cover_by_user.get(p["user_id"], 0.0), 2)
        p["cover_amount"] = cov
        if total_cover > 0:
            cov_repaid = round((cov / total_cover) * total_owed_repayments, 2)
        else:
            cov_repaid = 0.0
        p["cover_repaid"] = cov_repaid
        p["cover_outstanding"] = round(max(0.0, cov - cov_repaid), 2)

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
    # ─── 5-State Squad Lifecycle (June 2025 spec) ────────────────────────────
    #  Open         → freshly created, lead only, no items/contributions
    #  Contributing → items added OR members added, still collecting
    #  Contributed  → value coverage == 100% (incl. lead/member covers).
    #                 Lead Pay Out becomes available here.
    #                 NOTE: owing-member back-collection happens in parallel;
    #                 it does NOT block Lead Pay Out per product spec.
    #  Lead Paid    → Stripe Connect `payout.paid` webhook fired for lead.
    #                 (raw status = "lead_paid" in DB)
    #  Bill Settled → admin-configured delay (default 20min) after Lead Paid.
    #                 (raw status = "closed" in DB)
    #
    # Legacy raw status `paid` from pre-June-2025 data is treated as
    # `Bill Settled` (most existing rows are settled merchants).
    items_count = len(group.get("items") or [])
    members_count = len(group.get("members") or [])
    contribs_count = len(group.get("contributions") or [])
    # "Value coverage" = total money in the squad (real contributions + active
    # covers that fill the gap). Lead/member covers count toward funding.
    cover_amount = 0.0
    if settlement:
        # Settlement records who's covering — when a cover is in place we
        # consider its amount as "money in" toward the grand total, since
        # the covering party has committed to fund the merchant.
        # The actual repayment from owing members is tracked separately
        # via shortfall_obligations + repayments.
        cover_amount = float(settlement.get("amount") or 0.0)
    value_covered = total_contributed + cover_amount
    funding_complete = (value_covered + 0.01) >= total_amount and total_amount > 0

    if raw_status == "closed":
        derived_status = "bill_settled"
    elif raw_status == "lead_paid":
        derived_status = "lead_paid"
    elif raw_status == "paid":
        # `paid` now means "funding complete, awaiting lead pay-out".
        # Legacy rows already past Stripe transfer carry lead_payout_paid_at;
        # we surface those as bill_settled for back-compat.
        if group.get("lead_payout_paid_at"):
            derived_status = "bill_settled"
        else:
            derived_status = "contributed"
    elif raw_status == "open":
        if items_count == 0 and members_count <= 1 and contribs_count == 0:
            derived_status = "open"
        elif funding_complete and not has_outstanding:
            derived_status = "contributed"
        elif funding_complete and has_outstanding:
            derived_status = "contributed"
        else:
            derived_status = "contributing"
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
        raise HTTPException(404, "Squad not found")
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
    # How the member joined this group. Logged on the member record for
    # backend analytics + audit. Frontend should send one of:
    #   "code"   — typed the 8-char invite code
    #   "qr"     — scanned a QR code (in-app camera scanner)
    #   "link"   — opened a Universal Link / deep link
    #   "invite" — tapped an SMS / push invite
    #   "manual" — joined via /admin (rare)
    # Accepts free-form strings to keep the schema flexible; the join route
    # normalises to lowercase and falls back to "unknown".
    joined_via: Optional[str] = None


class SetSplitModeIn(BaseModel):
    """Lead changes the bill's split mode mid-flight. See
    `set_split_mode` in routes/groups_routes.py for the validation rules.
    """
    user_id: str
    split_mode: str  # "fast" or "itemized"


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
