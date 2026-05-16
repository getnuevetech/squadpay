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
#
# June 2025 — Pricing model finalized per user spec:
#   • Platform Fee: {type: "fixed"|"percent", value: N}  — default $0.50 fixed
#   • Extra Fees:   list of {type, value, name, enabled} — admin-managed (unlimited)
#   • Insurance:    always %, layered on top of (Share + Platform + Extras) — default 1%
#   • Transaction:  always %, layered on top of EVERYTHING below — default 3%
#
# Layering order (per user spec):
#   1. Share_or_Value
#   2. + Platform Fee
#   3. + Extra Fees (each)
#   4. + Insurance (% of layers 1-3)
#   5. + Transaction Fee (% of layers 1-4)
DEFAULT_TRANSACTION_FEE_RATE = 0.03  # 3%
DEFAULT_PLATFORM_FEE_TYPE = "fixed"  # "fixed" | "percent"
DEFAULT_PLATFORM_FEE_VALUE = 0.50    # $0.50 fixed per member (user-specified default)
DEFAULT_INSURANCE_RATE = 0.01        # 1% (user-specified default)

# Backwards-compat aliases — other modules historically imported these.
TRANSACTION_FEE_RATE = DEFAULT_TRANSACTION_FEE_RATE
PLATFORM_FEE = DEFAULT_PLATFORM_FEE_VALUE  # kept as float for older importers

# Live overrides set by admin via /api/admin/app-config (or fallback to defaults).
_CORE_FEES_CACHE: Dict[str, Any] = {
    "transaction_fee_rate": DEFAULT_TRANSACTION_FEE_RATE,
    # Platform fee is now an object {type, value} so admin can pick fixed $ or %.
    "platform_fee_type": DEFAULT_PLATFORM_FEE_TYPE,
    "platform_fee_value": DEFAULT_PLATFORM_FEE_VALUE,
    # Insurance: always percent, never fixed.
    "insurance_rate": DEFAULT_INSURANCE_RATE,
    # Legacy single float (sum-fee semantics) — kept for backwards-compat with
    # older callers that imported `platform_fee` directly. Resolved to the
    # *fixed-dollar value* when type is "fixed", else 0.0.
    "platform_fee": (
        DEFAULT_PLATFORM_FEE_VALUE if DEFAULT_PLATFORM_FEE_TYPE == "fixed" else 0.0
    ),
}


def set_core_fees_cache(
    transaction_fee_rate: float,
    platform_fee: float = None,
    *,
    platform_fee_type: str = None,
    platform_fee_value: float = None,
    insurance_rate: float = None,
    transaction_fee_enabled: bool = None,
    platform_fee_enabled: bool = None,
    insurance_enabled: bool = None,
    transaction_fee_cap: float = None,
    platform_fee_cap: float = None,
    insurance_cap: float = None,
) -> None:
    """Called by the admin route on save + at startup to refresh values.

    Backwards-compatible signature: old callers pass `(tx_rate, platform_fee)`
    where `platform_fee` is interpreted as a fixed-dollar amount. New callers
    can pass the keyword args to set type/value explicitly, an insurance
    rate, and per-fee enable/disable toggles. All new fields fall back to
    current cache values or module defaults.
    """
    global _CORE_FEES_CACHE
    # Resolve platform fee — prefer explicit type/value over the legacy float.
    if platform_fee_type is not None or platform_fee_value is not None:
        ptype = platform_fee_type if platform_fee_type in ("fixed", "percent") else DEFAULT_PLATFORM_FEE_TYPE
        pvalue = float(platform_fee_value) if platform_fee_value is not None else _CORE_FEES_CACHE.get("platform_fee_value", DEFAULT_PLATFORM_FEE_VALUE)
    elif platform_fee is not None:
        # Legacy call site — assume fixed dollar amount.
        ptype = "fixed"
        pvalue = float(platform_fee)
    else:
        ptype = _CORE_FEES_CACHE.get("platform_fee_type", DEFAULT_PLATFORM_FEE_TYPE)
        pvalue = _CORE_FEES_CACHE.get("platform_fee_value", DEFAULT_PLATFORM_FEE_VALUE)
    ins_rate = float(insurance_rate) if insurance_rate is not None else _CORE_FEES_CACHE.get("insurance_rate", DEFAULT_INSURANCE_RATE)
    # Per-fee enable/disable toggles. Default ON when not explicitly set
    # (preserves behaviour for older callers / fresh installs).
    tx_enabled = bool(transaction_fee_enabled) if transaction_fee_enabled is not None else _CORE_FEES_CACHE.get("transaction_fee_enabled", True)
    pf_enabled = bool(platform_fee_enabled) if platform_fee_enabled is not None else _CORE_FEES_CACHE.get("platform_fee_enabled", True)
    ins_enabled = bool(insurance_enabled) if insurance_enabled is not None else _CORE_FEES_CACHE.get("insurance_enabled", True)
    # Per-fee caps (max $ per member). 0 = no cap.
    tx_cap = float(transaction_fee_cap) if transaction_fee_cap is not None else float(_CORE_FEES_CACHE.get("transaction_fee_cap", 0.0) or 0.0)
    pf_cap = float(platform_fee_cap) if platform_fee_cap is not None else float(_CORE_FEES_CACHE.get("platform_fee_cap", 0.0) or 0.0)
    ins_cap = float(insurance_cap) if insurance_cap is not None else float(_CORE_FEES_CACHE.get("insurance_cap", 0.0) or 0.0)
    _CORE_FEES_CACHE = {
        "transaction_fee_rate": float(transaction_fee_rate) if transaction_fee_rate is not None else DEFAULT_TRANSACTION_FEE_RATE,
        "platform_fee_type": ptype,
        "platform_fee_value": pvalue,
        "insurance_rate": ins_rate,
        # Per-fee enable toggles — when False the corresponding fee is
        # completely skipped (does not contribute to any layered base).
        "transaction_fee_enabled": tx_enabled,
        "platform_fee_enabled": pf_enabled,
        "insurance_enabled": ins_enabled,
        # Per-fee caps — when >0 the computed fee is min()-clamped to this
        # value (per member). 0 means no cap. Applied AFTER % computation
        # and BEFORE the fee feeds the next layer's base.
        "transaction_fee_cap": tx_cap,
        "platform_fee_cap": pf_cap,
        "insurance_cap": ins_cap,
        # Legacy float — only meaningful when type is fixed.
        "platform_fee": pvalue if ptype == "fixed" else 0.0,
    }


def get_core_fees_cache() -> Dict[str, Any]:
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
    """[LEGACY — kept for backwards compatibility]

    Older callers may still use this helper. Per the June 2025 pricing
    spec, fixed extra fees are NOT divided by member count (each member
    pays the full $ amount), so this helper is no longer suitable for
    new code paths. Use `_compute_layered_member_fees()` instead.
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


def _compute_layered_member_fees(
    *,
    member_share: float,
    pct_base: float,
) -> Dict[str, Any]:
    """Compute the layered fee stack for a single member (June 2025 spec).

    Layering order (per user-locked formula):
        1. Member's Share or Value (already includes their tax/tip slice)
        2. + Platform Fee     ($F fixed → each pays full; F% → percent of pct_base)
        3. + Each Extra Fee   (same fixed/percent rules as Platform)
        4. + Insurance        (H% × (Share + Platform + Extras)) — never fixed
        5. + Transaction Fee  (B% × (Share + Platform + Extras + Insurance))

    Args:
        member_share: This member's Share (Equal) or Value (Itemized).
                      Already includes their tax+tip portion.
        pct_base:     Base used when Platform/Extras are PERCENTAGE.
                      Equal mode  → same as `member_share` (= Total/N).
                      Itemized    → Total Bill / N (uniform across all members).

    Returns:
        Dict with keys: platform_fee, extra_fees (list of {id,name,type,amount}),
        extra_fees_total, insurance, transaction_fee, fees_total, total.
        `total` is the member's grand-total bill obligation (incl. all fees).
    """
    cache = _CORE_FEES_CACHE
    # ─── Layer 2: Platform fee ──────────────────────────────────────
    # June 2025 — Honor the per-fee enable toggle and cap (max $).
    # When disabled, the fee is COMPLETELY skipped (does not contribute
    # to Insurance/Tx Fee bases either).
    if cache.get("platform_fee_enabled", True):
        p_type = cache.get("platform_fee_type", DEFAULT_PLATFORM_FEE_TYPE)
        p_val = float(cache.get("platform_fee_value", DEFAULT_PLATFORM_FEE_VALUE) or 0)
        if p_type == "percent":
            platform_fee = (p_val / 100.0) * pct_base
        else:
            platform_fee = p_val
        # Apply cap (max $) if configured (>0).
        p_cap = float(cache.get("platform_fee_cap", 0.0) or 0.0)
        if p_cap > 0 and platform_fee > p_cap:
            platform_fee = p_cap
        platform_fee = round(platform_fee, 2)
    else:
        platform_fee = 0.0
    # ─── Layer 3: Extra fees (each one fixed-$ or %) ───────────────
    extra_fees: List[Dict[str, Any]] = []
    for f in _EXTRA_FEES_CACHE:
        if not f.get("enabled"):
            continue
        val = float(f.get("value") or 0)
        if val <= 0:
            continue
        f_type = "percent" if f.get("type") == "percent" else "flat"
        if f_type == "percent":
            amt = (val / 100.0) * pct_base
        else:
            # Per user spec: fixed = each member pays full $ (NOT divided).
            amt = val
        # Apply per-extra cap (max $) if configured.
        f_cap = float(f.get("cap", 0) or 0)
        if f_cap > 0 and amt > f_cap:
            amt = f_cap
        amt = round(amt, 2)
        extra_fees.append({
            "id": str(f.get("id") or ""),
            "name": str(f.get("name") or "Extra fee"),
            "type": f_type,
            "amount": amt,
        })
    extras_total = round(sum(ef["amount"] for ef in extra_fees), 2)
    # ─── Layer 4: Insurance (always %, layered) ────────────────────
    if cache.get("insurance_enabled", True):
        ins_rate = float(cache.get("insurance_rate", DEFAULT_INSURANCE_RATE) or 0)
        insurance_base = member_share + platform_fee + extras_total
        insurance = ins_rate * insurance_base
        ins_cap = float(cache.get("insurance_cap", 0.0) or 0.0)
        if ins_cap > 0 and insurance > ins_cap:
            insurance = ins_cap
        insurance = round(insurance, 2)
    else:
        insurance = 0.0
        insurance_base = member_share + platform_fee + extras_total
    # ─── Layer 5: Transaction fee (always %, on top of EVERYTHING) ──
    if cache.get("transaction_fee_enabled", True):
        tx_rate = float(cache.get("transaction_fee_rate", DEFAULT_TRANSACTION_FEE_RATE) or 0)
        tx_base = insurance_base + insurance
        transaction_fee = tx_rate * tx_base
        tx_cap = float(cache.get("transaction_fee_cap", 0.0) or 0.0)
        if tx_cap > 0 and transaction_fee > tx_cap:
            transaction_fee = tx_cap
        transaction_fee = round(transaction_fee, 2)
    else:
        transaction_fee = 0.0

    fees_total = round(platform_fee + extras_total + insurance + transaction_fee, 2)
    total = round(member_share + fees_total, 2)
    return {
        "platform_fee": platform_fee,
        "extra_fees": extra_fees,
        "extra_fees_total": extras_total,
        "insurance": insurance,
        "transaction_fee": transaction_fee,
        "fees_total": fees_total,
        "total": total,
    }

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
            # Penny-safe equal split (June 2025 — "Lead absorbs residual"
            # per user spec). For $89.21 ÷ 2 the math is $44.605 each, but
            # Stripe charges whole cents only. Rather than show $44.60 each
            # (loses $0.01) or randomly assign the extra cent, we route
            # every leftover cent to the LEAD member. This keeps non-Lead
            # members at an identical base share and concentrates rounding
            # on the dispute / shortfall owner — which is the industry
            # norm (Splitwise behaves the same way).
            #
            # We identify the Lead explicitly via role=="lead" rather than
            # relying on array index, because members may be re-ordered
            # by joins, sorts, or migration scripts. Fallback to index 0
            # if no role is set (legacy groups).
            total_cents = int(round(float(total) * 100))
            n = len(members)
            base_cents = total_cents // n
            extra_cents = total_cents - base_cents * n  # 0 ≤ extra < n

            # Find Lead index. Fallback: members[0].
            lead_idx = next(
                (i for i, m in enumerate(members) if (m.get("role") or "").lower() == "lead"),
                0,
            )
            per_user = []
            for idx, m in enumerate(members):
                # Lead absorbs ALL leftover cents (typically 0 or 1).
                bonus = extra_cents if idx == lead_idx else 0
                share_cents = base_cents + bonus
                share_amt = share_cents / 100.0
                per_user.append({
                    "user_id": m["user_id"],
                    "food": share_amt,
                    "tax_tip": 0.0,
                    "total": share_amt,
                })
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
        # Penny-safe extras (tax + tip) proration (May 2026 fix). Doing
        # `round(share * extras, 2)` per member can drop or duplicate a
        # cent so the per-member totals don't quite add up to extras.
        # We compute everyone's float extras, take the integer-cent
        # floor for each, then distribute the leftover cents to the
        # members with the largest fractional remainder. Lead acts as
        # tie-breaker (members[0] absorbs the first leftover cent).
        per_user = []
        extras_cents_total = int(round(extras * 100))
        # Pre-compute (member, float_extra) so we can index back.
        member_extras_float = []
        if subtotal > 0:
            for m in members:
                food = per_user_food.get(m["user_id"], 0.0)
                share = food / subtotal
                member_extras_float.append((m, food, share * extras))
        else:
            for m in members:
                member_extras_float.append((m, per_user_food.get(m["user_id"], 0.0), 0.0))

        # Floor each to cents, track fractional remainders.
        floored_cents = []
        for _, _, fe in member_extras_float:
            cents = int(fe * 100)  # truncate toward zero (positive amounts only)
            floored_cents.append(cents)
        leftover_cents = max(0, extras_cents_total - sum(floored_cents))
        # "Lead absorbs residual" policy (June 2025) — route every leftover
        # cent to the Lead member, regardless of fractional remainder. This
        # keeps non-Lead members at the cleanly-prorated amount and matches
        # the equal-split branch's behavior. Identify Lead explicitly via
        # role=="lead", fall back to index 0 if not set.
        lead_idx = next(
            (i for i, (m, _, _) in enumerate(member_extras_float)
             if (m.get("role") or "").lower() == "lead"),
            0,
        )
        if leftover_cents > 0 and member_extras_float:
            floored_cents[lead_idx] += leftover_cents

        for i, (m, food, _) in enumerate(member_extras_float):
            extra = floored_cents[i] / 100.0
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
            p["insurance"] = 0.0
            p["extra_fees"] = []
            p["extra_fees_total"] = 0.0
            p["total"] = 0.0
            continue
        # ─────────────────────────────────────────────────────────────
        # June 2025 — Layered Fee Model (per user spec)
        #
        # Per-user breakdown is computed by `_compute_layered_member_fees()`
        # which applies all five layers in the exact order the user
        # specified:
        #     Share/Value → +Platform → +Extras → +Insurance → +Tx Fee
        #
        # Percent-fee base differs by split mode:
        #     • Equal mode    → each member's share == Total/N == pct_base
        #     • Itemized mode → pct_base is Total Bill / N (uniform across
        #                        all members), while their `merchant_share`
        #                        (= Value) varies by item claims.
        # ─────────────────────────────────────────────────────────────
        if split_mode == "fast":
            pct_base = merchant_share
        else:
            # Itemized: percentage Platform/Extras use the uniform per-bill
            # base so every member sees the same Platform $ regardless of
            # how many items they claimed.
            pct_base = (total / max(1, len(members))) if total else 0.0
        layered = _compute_layered_member_fees(
            member_share=merchant_share,
            pct_base=pct_base,
        )
        p["transaction_fee"] = layered["transaction_fee"]
        p["platform_fee"] = layered["platform_fee"]
        p["insurance"] = layered["insurance"]
        p["extra_fees"] = layered["extra_fees"]
        p["extra_fees_total"] = layered["extra_fees_total"]
        p["total"] = layered["total"]

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
            # SYMMETRIC FORMULA (June 2025 — final, per user spec):
            # `remaining_to_collect` = sum of EVERY member's own bill gap
            # (`total − contributed − repaid`), INCLUDING the lead.
            #
            # Per the user's clear mental model:
            #   "If lead is part of the unpaid Squad, then we add lead's
            #    total share to the pool of shortfall."
            #
            # Lead is treated identically to every other Squad member —
            # no special exclusion. The frontend exposes two CTAs:
            #   1. "Contribute Your Share"  — pays only lead's own gap
            #   2. "Cover Shortfall"        — pays this whole sum
            #
            # NOTE: With the per-bill fee divider (above) and the
            # equal-split formula, every member's `total` is identical
            # in fast/equal mode. No "residual gap" can arise from
            # asymmetric fee calculation any more.
            "remaining_to_collect": round(
                sum(
                    max(
                        0.0,
                        float(p.get("total", 0.0))
                        - float(p.get("contributed", 0.0))
                        - float(p.get("repaid", 0.0)),
                    )
                    for p in per_user
                ),
                2,
            ),
            # Merchant-only shortfall is still exposed for any caller
            # that needs the raw merchant gap (e.g. accounting).
            #
            # NOTE: `merchant_remaining` is NOT guaranteed to be ≤
            # `remaining_to_collect`. Before the lead contributes their
            # own share, `sum(per_user.outstanding)` excludes the lead's
            # own row (lead has no shortfall_owed against themselves),
            # so the merchant gap can be larger than the fees-inclusive
            # sum. Once the lead has contributed, the relationship
            # reverses and `remaining_to_collect ≥ merchant_remaining`
            # by the amount of uncollected non-lead fees.
            "merchant_remaining": round(max(0.0, total_amount - total_contributed), 2),
            "fees_total": round(sum(p["transaction_fee"] + p["platform_fee"] + p.get("insurance", 0) + p.get("extra_fees_total", 0) for p in per_user), 2),
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
