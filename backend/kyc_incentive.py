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

DEFAULT_CREDIT_AMOUNT_USD = 10.00
DEFAULT_REWARD_MODE = "credit_off_next_bill"

VALID_REWARD_MODES = {"credit_off_next_bill", "waive_platform_fees_next_bill"}


async def get_kyc_incentive(db: Any) -> dict:
    """Returns the public-facing KYC incentive config."""
    doc = await db.app_config.find_one({"_id": "kyc_incentive"}) or {}
    return {
        "enabled": bool(doc.get("enabled", True)),
        "reward_mode": doc.get("reward_mode", DEFAULT_REWARD_MODE),
        "credit_amount": float(doc.get("credit_amount", DEFAULT_CREDIT_AMOUNT_USD)),
        "messages": list(doc.get("messages") or DEFAULT_MESSAGES),
    }


async def set_kyc_incentive(
    db: Any,
    *,
    enabled: bool,
    reward_mode: str,
    credit_amount: float,
    messages: list[str],
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
    await db.app_config.update_one(
        {"_id": "kyc_incentive"},
        {"$set": {
            "enabled": bool(enabled),
            "reward_mode": reward_mode,
            "credit_amount": round(float(credit_amount), 2),
            "messages": cleaned or DEFAULT_MESSAGES,
            "updated_at": now_iso(),
            "updated_by": admin_email,
        }},
        upsert=True,
    )
    return await get_kyc_incentive(db)


async def maybe_grant_kyc_reward(db: Any, *, user_id: str, source: str = "stripe_connect") -> dict | None:
    """Grants the configured KYC reward to `user_id` IF:
      • incentive is enabled
      • user has not previously received a KYC reward
    Returns the reward dict that was stamped, or None if nothing happened.

    Idempotent via `kyc_completed_at` on the user doc. Crucially, this
    does NOT touch any stored balance — we just stamp a pending reward
    that will auto-apply to their next squad (see `apply_lead_reward`).
    """
    cfg = await get_kyc_incentive(db)
    if not cfg["enabled"]:
        return None

    user = await db.users.find_one({"id": user_id}, {"_id": 0, "kyc_completed_at": 1})
    if not user:
        return None
    if user.get("kyc_completed_at"):
        return None  # idempotent

    now = now_iso()
    reward = {
        "mode": cfg["reward_mode"],
        "amount": (
            round(float(cfg["credit_amount"]), 2)
            if cfg["reward_mode"] == "credit_off_next_bill" else 0.0
        ),
        "granted_at": now,
        "used_on_group_id": None,
        "used_at": None,
        "source": source,
    }

    # Conditional update so two concurrent syncs can't double-stamp.
    res = await db.users.update_one(
        {"id": user_id, "kyc_completed_at": {"$exists": False}},
        {"$set": {
            "kyc_completed_at": now,
            "kyc_pending_reward": reward,
        }},
    )
    if res.modified_count == 0:
        return None

    # Audit/ledger trail (informational only — no value movement).
    try:
        await db.kyc_reward_ledger.insert_one({
            "user_id": user_id,
            "mode": reward["mode"],
            "amount": reward["amount"],
            "source": source,
            "memo": "KYC verification — pending reward stamped",
            "event": "granted",
            "created_at": now,
        })
    except Exception as e:
        logger.warning("[kyc_incentive] ledger insert failed for %s: %s", user_id, e)

    logger.info(
        "[kyc_incentive] stamped pending reward for %s (mode=%s amount=%.2f source=%s)",
        user_id, reward["mode"], reward["amount"], source,
    )
    return reward


async def attach_pending_reward_to_group(db: Any, *, lead_user_id: str, group_id: str) -> dict | None:
    """Called from the group-create endpoint. If the lead has a pending
    KYC reward, attach it to the new squad and mark the reward as
    consumed. Returns the reward dict that was attached, or None.

    Idempotency: once `used_on_group_id` is set on the user, this
    function no-ops on subsequent calls. The reward auto-applies
    inside _compute_per_user (see core.py) every time the group's
    payload is recomputed."""
    user = await db.users.find_one(
        {"id": lead_user_id},
        {"_id": 0, "kyc_pending_reward": 1},
    )
    if not user:
        return None
    reward = user.get("kyc_pending_reward") or {}
    if not reward or reward.get("used_on_group_id"):
        return None

    now = now_iso()
    # Mark the reward as consumed on the user side first (conditional
    # so a race can't double-attach).
    res = await db.users.update_one(
        {"id": lead_user_id, "kyc_pending_reward.used_on_group_id": None},
        {"$set": {
            "kyc_pending_reward.used_on_group_id": group_id,
            "kyc_pending_reward.used_at": now,
        }},
    )
    if res.modified_count == 0:
        return None

    attached = {
        "mode": reward["mode"],
        "amount": float(reward.get("amount") or 0.0),
        "source": reward.get("source") or "stripe_connect",
        "granted_at": reward.get("granted_at"),
        "attached_at": now,
    }
    await db.groups.update_one(
        {"id": group_id},
        {"$set": {"lead_reward": attached}},
    )
    try:
        await db.kyc_reward_ledger.insert_one({
            "user_id": lead_user_id,
            "group_id": group_id,
            "mode": attached["mode"],
            "amount": attached["amount"],
            "event": "attached",
            "created_at": now,
        })
    except Exception:
        pass
    logger.info(
        "[kyc_incentive] attached reward %s ($%.2f) to %s for lead %s",
        attached["mode"], attached["amount"], group_id, lead_user_id,
    )
    return attached
