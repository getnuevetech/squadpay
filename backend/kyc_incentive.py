"""KYC incentive (June 2025) — short rotating messages + a one-time
reward applied to the lead's NEXT squad bill after they complete Stripe
Connect KYC for payouts.

Why this exists
---------------
Anyone can Venmo / Zelle a lead directly — so KYC has to feel worth it.
We give a tangible reward and rotate through a handful of short, warm
messages so different leads see different angles. Both the reward AND
the message pool are admin-configurable so we can A/B-test copy
without shipping app updates.

Compliance note
---------------
SquadPay does NOT hold member funds. We are a payment channel/aggregator
only. The KYC reward is NOT a stored-value wallet credit — it is a
one-shot DISCOUNT that auto-applies to the lead's next squad. This
keeps SquadPay clear of money-transmitter / stored-value licensing.

Two reward modes (admin picks one):
  • "credit_off_next_bill"        — flat dollar discount off the lead's
                                    own share on the next squad they lead
                                    (default $10).
  • "waive_platform_fees_next_bill"
                                  — SquadPay's platform fee is set to $0
                                    for the lead on their next squad.

Storage
-------
Config (`app_config`, _id="kyc_incentive"):
    {
        "enabled": True,
        "reward_mode": "credit_off_next_bill" | "waive_platform_fees_next_bill",
        "credit_amount": 10.00,   # only used for credit_off_next_bill mode
        "messages": [ ... 1-10 short strings ... ],
        "updated_at": ISO,
        "updated_by": "admin@email",
    }

Per-user stamp (on `users` doc):
    {
        "kyc_completed_at": ISO,
        "kyc_pending_reward": {
            "mode": "credit_off_next_bill" | "waive_platform_fees_next_bill",
            "amount": float,            # 0 for fee-waiver mode
            "granted_at": ISO,
            "used_on_group_id": null,   # set when applied to a squad
            "used_at": null,             # set when applied
        }
    }

We grant ONCE per user (idempotent via `kyc_completed_at`). When the
lead next creates a squad, the pending reward is stamped onto that
squad's `lead_reward` field and consumed.
"""
from __future__ import annotations

import logging
from typing import Any

from core import now_iso

logger = logging.getLogger("kyc_incentive")


DEFAULT_MESSAGES: list[str] = [
    "Stripe handles it — SquadPay just makes sure your money gets back to you.",
    "Verify once. Forever-fast payouts after.",
    "One quick check. We make sure only YOU can pull your Squad's funds.",
    "Stripe verifies it's you. We make sure your Squad pays you, every time.",
    "Lock in your Squad's funds. Only you can withdraw them.",
]

# June 2025 — Non-lead (covering member) incentive uses smaller default
# amount and member-tailored messaging. Admin can fully override.
DEFAULT_MESSAGES_MEMBER: list[str] = [
    "Verify once — get your loan repayments deposited fast.",
    "Stripe checks it's you. Then your covered $$ comes home.",
    "Quick check, then your repayment pulls straight to your bank.",
]

DEFAULT_CREDIT_AMOUNT_USD = 10.00
DEFAULT_CREDIT_AMOUNT_MEMBER_USD = 5.00
DEFAULT_REWARD_MODE = "credit_off_next_bill"

VALID_REWARD_MODES = {"credit_off_next_bill", "waive_platform_fees_next_bill"}
VALID_ROLES = {"lead", "member"}


def _config_id_for_role(role: str) -> str:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
    return "kyc_incentive" if role == "lead" else "kyc_incentive_member"


def _defaults_for_role(role: str) -> dict:
    if role == "member":
        return {
            "credit_amount": DEFAULT_CREDIT_AMOUNT_MEMBER_USD,
            "messages": DEFAULT_MESSAGES_MEMBER,
        }
    return {
        "credit_amount": DEFAULT_CREDIT_AMOUNT_USD,
        "messages": DEFAULT_MESSAGES,
    }


async def get_kyc_incentive(db: Any, role: str = "lead") -> dict:
    """Returns the public-facing KYC incentive config for the given role.

    role="lead"   → reads `app_config._id == 'kyc_incentive'` (default $10)
    role="member" → reads `app_config._id == 'kyc_incentive_member'` (default $5)
    """
    cfg_id = _config_id_for_role(role)
    defaults = _defaults_for_role(role)
    doc = await db.app_config.find_one({"_id": cfg_id}) or {}
    return {
        "role": role,
        "enabled": bool(doc.get("enabled", True)),
        "reward_mode": doc.get("reward_mode", DEFAULT_REWARD_MODE),
        "credit_amount": float(doc.get("credit_amount", defaults["credit_amount"])),
        "messages": list(doc.get("messages") or defaults["messages"]),
    }


async def set_kyc_incentive(
    db: Any,
    *,
    enabled: bool,
    reward_mode: str,
    credit_amount: float,
    messages: list[str],
    role: str = "lead",
    admin_email: str | None = None,
) -> dict:
    if reward_mode not in VALID_REWARD_MODES:
        raise ValueError(
            f"reward_mode must be one of {sorted(VALID_REWARD_MODES)}"
        )
    if credit_amount < 0:
        raise ValueError("credit_amount must be >= 0")
    if not isinstance(messages, list) or any(not isinstance(m, str) for m in messages):
        raise ValueError("messages must be a list of strings")
    cleaned = [m.strip()[:200] for m in messages if m.strip()][:10]
    defaults = _defaults_for_role(role)
    cfg_id = _config_id_for_role(role)
    await db.app_config.update_one(
        {"_id": cfg_id},
        {"$set": {
            "enabled": bool(enabled),
            "reward_mode": reward_mode,
            "credit_amount": round(float(credit_amount), 2),
            "messages": cleaned or defaults["messages"],
            "updated_at": now_iso(),
            "updated_by": admin_email,
            "role": role,
        }},
        upsert=True,
    )
    return await get_kyc_incentive(db, role=role)


async def maybe_grant_kyc_reward(db: Any, *, user_id: str, source: str = "stripe_connect", role: str = "lead") -> dict | None:
    """Grants the configured KYC reward to `user_id` IF eligible.

    role="lead"   → consumes/awards from the lead KYC config
    role="member" → consumes/awards from the member KYC config
    Idempotent: kyc_completed_at_<role> is the dedupe stamp.
    """
    cfg = await get_kyc_incentive(db, role=role)
    if not cfg["enabled"]:
        return None

    stamp_field = "kyc_completed_at" if role == "lead" else "kyc_completed_at_member"
    user = await db.users.find_one({"id": user_id}, {"_id": 0, stamp_field: 1})
    if not user:
        return None
    if user.get(stamp_field):
        return None  # idempotent

    now = now_iso()
    reward = {
        "id": f"rwd_kyc_{role}_{user_id}_{int(__import__('time').time())}",
        "kind": f"kyc_{role}",
        "source": source,
        "mode": cfg["reward_mode"],
        "amount": (
            round(float(cfg["credit_amount"]), 2)
            if cfg["reward_mode"] == "credit_off_next_bill" else 0.0
        ),
        "granted_at": now,
        "used_on_group_id": None,
        "used_at": None,
    }

    # Conditional update so two concurrent syncs can't double-stamp.
    res = await db.users.update_one(
        {"id": user_id, stamp_field: {"$exists": False}},
        {
            "$set": {stamp_field: now},
            "$push": {"pending_rewards": reward},
        },
    )
    if res.modified_count == 0:
        return None

    try:
        await db.kyc_reward_ledger.insert_one({
            "user_id": user_id,
            "reward_id": reward["id"],
            "kind": reward["kind"],
            "mode": reward["mode"],
            "amount": reward["amount"],
            "source": source,
            "memo": "KYC verification — pending reward queued",
            "event": "granted",
            "created_at": now,
        })
    except Exception as e:
        logger.warning("[kyc_incentive] ledger insert failed for %s: %s", user_id, e)

    logger.info(
        "[kyc_incentive] queued KYC reward for %s (mode=%s amount=%.2f)",
        user_id, reward["mode"], reward["amount"],
    )
    return reward


async def grant_pending_reward(
    db: Any,
    *,
    user_id: str,
    kind: str,
    mode: str,
    amount: float,
    dedupe_key: str | None = None,
    note: str | None = None,
) -> dict | None:
    """Generic reward-granting helper for non-KYC sources (marketing,
    referral, support comp, etc.). Stamps a reward onto the user's
    `pending_rewards` array using the same shape KYC uses — so the
    `_compute_per_user` apply path handles everything uniformly.

    Idempotency: if `dedupe_key` is provided, we refuse to grant the
    same `(user_id, dedupe_key)` twice. Marketing campaigns should
    pass `dedupe_key="marketing:<campaign_id>"` or similar.

    Params:
        kind:       free-form tag — e.g. "marketing", "referral", "comp"
        mode:       "credit_off_next_bill" | "waive_platform_fees_next_bill"
        amount:     dollar amount (used only for credit mode)
        dedupe_key: optional idempotency key
        note:       optional auditor-facing memo
    """
    if mode not in VALID_REWARD_MODES:
        raise ValueError(f"mode must be one of {sorted(VALID_REWARD_MODES)}")
    if amount < 0:
        raise ValueError("amount must be >= 0")

    user = await db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "pending_rewards": 1})
    if user is None:
        return None

    if dedupe_key:
        for r in (user.get("pending_rewards") or []):
            if r.get("dedupe_key") == dedupe_key:
                return None  # already granted

    now = now_iso()
    reward = {
        "id": f"rwd_{kind}_{user_id}_{int(__import__('time').time())}",
        "kind": kind,
        "source": kind,
        "mode": mode,
        "amount": round(float(amount), 2) if mode == "credit_off_next_bill" else 0.0,
        "granted_at": now,
        "used_on_group_id": None,
        "used_at": None,
        "dedupe_key": dedupe_key,
        "note": note,
    }
    await db.users.update_one(
        {"id": user_id},
        {"$push": {"pending_rewards": reward}},
    )
    try:
        await db.kyc_reward_ledger.insert_one({
            "user_id": user_id,
            "reward_id": reward["id"],
            "kind": kind,
            "mode": mode,
            "amount": reward["amount"],
            "source": kind,
            "dedupe_key": dedupe_key,
            "memo": note or f"{kind} reward queued",
            "event": "granted",
            "created_at": now,
        })
    except Exception:
        pass
    logger.info("[reward] queued %s reward for %s mode=%s amount=%.2f", kind, user_id, mode, reward["amount"])
    return reward


async def attach_pending_reward_to_group(db: Any, *, lead_user_id: str, group_id: str) -> list[dict]:
    """Called from the group-create endpoint. Drains ALL un-attached
    pending rewards from the lead's `pending_rewards` array and stamps
    them onto the new squad as `group.lead_rewards` (array). Each
    reward is marked consumed on the user side.

    Returns the list of attached rewards (may be empty). Multiple
    rewards stack — e.g. a lead who finished KYC ($10) AND was on a
    marketing campaign (waive fees) will get BOTH applied to their
    next squad. Stacking is bounded by the lead's own share — see
    _compute_per_user — so we never refund cash.
    """
    user = await db.users.find_one(
        {"id": lead_user_id},
        {"_id": 0, "pending_rewards": 1, "kyc_pending_reward": 1},
    )
    if not user:
        return []
    rewards: list[dict] = list(user.get("pending_rewards") or [])

    # Back-compat: migrate legacy singular field if present and unused.
    legacy = user.get("kyc_pending_reward") or None
    if legacy and not legacy.get("used_on_group_id"):
        rewards.insert(0, {
            "id": f"rwd_kyc_legacy_{lead_user_id}",
            "kind": "kyc",
            "source": legacy.get("source") or "stripe_connect",
            "mode": legacy.get("mode") or "credit_off_next_bill",
            "amount": float(legacy.get("amount") or 0.0),
            "granted_at": legacy.get("granted_at"),
            "used_on_group_id": None,
            "used_at": None,
        })

    fresh = [r for r in rewards if not r.get("used_on_group_id")]
    if not fresh:
        return []

    now = now_iso()
    attached: list[dict] = []
    for r in fresh:
        attached.append({
            "id": r.get("id"),
            "kind": r.get("kind") or "unknown",
            "source": r.get("source"),
            "mode": r.get("mode"),
            "amount": float(r.get("amount") or 0.0),
            "granted_at": r.get("granted_at"),
            "attached_at": now,
        })

    # Mark every consumed entry on the user (positional path update by id).
    consumed_ids = {r["id"] for r in fresh}
    new_pending = []
    for r in rewards:
        if r.get("id") in consumed_ids:
            r = {**r, "used_on_group_id": group_id, "used_at": now}
        new_pending.append(r)

    update_doc: dict = {"pending_rewards": new_pending}
    # Sweep the legacy singular field too so admins don't see stale data.
    if legacy and not legacy.get("used_on_group_id"):
        update_doc["kyc_pending_reward"] = {
            **legacy,
            "used_on_group_id": group_id,
            "used_at": now,
        }
    await db.users.update_one({"id": lead_user_id}, {"$set": update_doc})

    await db.groups.update_one(
        {"id": group_id},
        {"$set": {"lead_rewards": attached}},
    )

    try:
        for a in attached:
            await db.kyc_reward_ledger.insert_one({
                "user_id": lead_user_id,
                "group_id": group_id,
                "reward_id": a.get("id"),
                "kind": a["kind"],
                "mode": a["mode"],
                "amount": a["amount"],
                "event": "attached",
                "created_at": now,
            })
    except Exception:
        pass
    logger.info(
        "[reward] attached %d reward(s) to %s for lead %s",
        len(attached), group_id, lead_user_id,
    )
    return attached
