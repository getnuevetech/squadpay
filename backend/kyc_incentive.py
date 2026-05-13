"""KYC incentive (June 2025) — short rotating messages + a one-time
credit awarded to a lead the first time they complete Stripe Connect
KYC for payouts.

Why this exists
---------------
Anyone can Venmo / Zelle a lead directly — so KYC has to feel worth it.
We give a tangible reward (default $10 SquadPay credit) and rotate
through a handful of short, warm messages so different leads see
different angles. The credit value AND the message pool are both
admin-configurable from the backend so we can A/B-test copy without
shipping app updates.

Storage
-------
Single config doc in `app_config` keyed by `_id="kyc_incentive"`:

    {
        "_id": "kyc_incentive",
        "enabled": True,
        "credit_amount": 10.00,
        "messages": [
            "Stripe handles it — SquadPay just makes sure your money gets back to you.",
            ...
        ],
        "updated_at": ISO,
        "updated_by": "admin@email"
    }

We also stamp `users.kyc_credit_granted_at` so we don't grant twice.
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


async def get_kyc_incentive(db: Any) -> dict:
    """Returns the public-facing KYC incentive config. Falls back to
    sensible defaults if the admin hasn't configured anything yet."""
    doc = await db.app_config.find_one({"_id": "kyc_incentive"}) or {}
    return {
        "enabled": bool(doc.get("enabled", True)),
        "credit_amount": float(doc.get("credit_amount", DEFAULT_CREDIT_AMOUNT_USD)),
        "messages": list(doc.get("messages") or DEFAULT_MESSAGES),
    }


async def set_kyc_incentive(
    db: Any,
    *,
    enabled: bool,
    credit_amount: float,
    messages: list[str],
    admin_email: str | None = None,
) -> dict:
    if credit_amount < 0:
        raise ValueError("credit_amount must be >= 0")
    if not isinstance(messages, list) or any(not isinstance(m, str) for m in messages):
        raise ValueError("messages must be a list of strings")
    # Cap pool size and per-message length so the app doesn't explode if
    # someone pastes Lorem Ipsum in by accident.
    cleaned = [m.strip()[:200] for m in messages if m.strip()][:10]
    await db.app_config.update_one(
        {"_id": "kyc_incentive"},
        {"$set": {
            "enabled": bool(enabled),
            "credit_amount": round(float(credit_amount), 2),
            "messages": cleaned or DEFAULT_MESSAGES,
            "updated_at": now_iso(),
            "updated_by": admin_email,
        }},
        upsert=True,
    )
    return await get_kyc_incentive(db)


async def maybe_grant_kyc_credit(db: Any, *, user_id: str, source: str = "stripe_connect") -> float | None:
    """Grants the configured KYC credit to `user_id` IF:
      - incentive is enabled
      - credit_amount > 0
      - user has not previously received a KYC credit
    Returns the granted amount, or None if nothing was granted (already
    granted, disabled, or zero amount).

    Idempotent via the `kyc_credit_granted_at` stamp on the user doc.
    Also writes a `wallet_credits` ledger entry so it shows up in the
    admin Credits page and the user-facing wallet balance.
    """
    cfg = await get_kyc_incentive(db)
    if not cfg["enabled"] or cfg["credit_amount"] <= 0:
        return None

    user = await db.users.find_one({"id": user_id}, {"_id": 0, "kyc_credit_granted_at": 1})
    if not user:
        return None
    if user.get("kyc_credit_granted_at"):
        return None  # already granted — idempotent

    amount = round(float(cfg["credit_amount"]), 2)
    now = now_iso()

    # Stamp the user FIRST (with a conditional update) so two concurrent
    # syncs can't double-credit. If somebody else already set the stamp
    # in the race window, we no-op.
    res = await db.users.update_one(
        {"id": user_id, "kyc_credit_granted_at": {"$exists": False}},
        {"$set": {
            "kyc_credit_granted_at": now,
            "kyc_credit_amount": amount,
            "kyc_credit_source": source,
        }, "$inc": {"wallet_credits": amount}},
    )
    if res.modified_count == 0:
        return None

    # Audit/ledger trail for the admin Credits page.
    try:
        await db.wallet_credit_ledger.insert_one({
            "user_id": user_id,
            "amount": amount,
            "type": "kyc_incentive",
            "source": source,
            "memo": "KYC verification credit",
            "created_at": now,
        })
    except Exception as e:
        logger.warning("[kyc_incentive] ledger insert failed for %s: %s", user_id, e)

    logger.info("[kyc_incentive] granted $%.2f to %s (source=%s)", amount, user_id, source)
    return amount
