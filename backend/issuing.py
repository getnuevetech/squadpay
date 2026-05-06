"""Stripe Issuing helpers (Phase F1).

Exports:
- get_issuing_settings(db)         -> dict
- get_or_create_business_cardholder(db) -> str (cardholder_id)
- issue_group_card(db, group)      -> dict (card payload stored on group)
- disable_group_card(db, group_id, by="system", reason="auto-settled") -> dict
- maybe_auto_disable_after_settlement(db, group_id) -> bool
- get_card_balance_summary(db, card_id) -> dict
"""
from __future__ import annotations
import datetime as dt
import logging
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_BUSINESS_NAME = "KWIKPAY"
SETTINGS_KEY = "integrations"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _stripe_client():
    """Return the stripe SDK module with api_key set from env."""
    import stripe as _stripe
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=True)
    _stripe.api_key = os.environ.get("STRIPE_API_KEY")
    return _stripe


async def get_issuing_settings(db) -> Dict[str, Any]:
    """Get the issuing config block from app_settings.integrations.

    Default shape:
    {
      "enabled": bool,
      "cardholder_id": str | None,
      "cardholder_name": "KWIKPAY",
      "card_disable_mode": "auto" | "manual",
    }
    """
    rec = await db.app_settings.find_one({"key": SETTINGS_KEY}, {"_id": 0}) or {}
    issuing = dict(rec.get("issuing") or {})
    issuing.setdefault("enabled", True)
    issuing.setdefault("cardholder_id", None)
    issuing.setdefault("cardholder_name", DEFAULT_BUSINESS_NAME)
    issuing.setdefault("card_disable_mode", "auto")  # auto | manual
    return issuing


async def set_issuing_settings(db, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge updates into app_settings.integrations.issuing."""
    cur = await get_issuing_settings(db)
    new = {**cur, **{k: v for k, v in patch.items() if v is not None}, "updated_at": _now()}
    await db.app_settings.update_one(
        {"key": SETTINGS_KEY},
        {"$set": {"issuing": new}},
        upsert=True,
    )
    return new


async def get_or_create_business_cardholder(db) -> str:
    """Return existing KWIKPAY cardholder id or auto-create a new one.

    For test mode, we attempt to reuse the most-recent active cardholder if
    the persisted ID is missing/invalid.
    """
    settings = await get_issuing_settings(db)
    cardholder_id = settings.get("cardholder_id")

    stripe = _stripe_client()
    if cardholder_id:
        try:
            ch = stripe.issuing.Cardholder.retrieve(cardholder_id)
            if ch and getattr(ch, "status", None) == "active":
                return ch.id
        except Exception as e:
            logger.warning(f"[issuing] persisted cardholder invalid ({cardholder_id}): {e}")

    # Try reuse most recent active cardholder if any
    try:
        chs = stripe.issuing.Cardholder.list(limit=10)
        for c in chs.data:
            if getattr(c, "status", None) == "active":
                await set_issuing_settings(db, {"cardholder_id": c.id, "cardholder_name": getattr(c, "name", None) or DEFAULT_BUSINESS_NAME})
                return c.id
    except Exception as e:
        logger.warning(f"[issuing] list cardholders failed: {e}")

    raise RuntimeError(
        "No active Stripe Issuing cardholder found. Please create one via the Stripe dashboard "
        "(https://dashboard.stripe.com/test/issuing/cardholders) and re-run."
    )


async def issue_group_card(db, group: Dict[str, Any]) -> Dict[str, Any]:
    """Issue a real Stripe virtual card for the given group.

    Stores the result on the group doc as `virtual_card`. Idempotent: if the
    group already has a virtual_card with status=active, returns it.
    """
    existing = group.get("virtual_card") or {}
    if existing.get("stripe_card_id") and existing.get("status") == "active":
        return existing

    settings = await get_issuing_settings(db)
    if not settings.get("enabled", True):
        raise RuntimeError("Stripe Issuing is disabled in admin settings.")

    cardholder_id = await get_or_create_business_cardholder(db)
    stripe = _stripe_client()
    business_name = settings.get("cardholder_name") or DEFAULT_BUSINESS_NAME
    nickname = f"{business_name} - {(group.get('title') or 'Group Bill')[:40]}"

    # Spending controls: cap total spend at the group's total_amount (rounded up).
    total = float(group.get("total_amount") or 0.0)
    spend_cap_cents = int(round(max(total, 0.0) * 100))

    spending_controls: Dict[str, Any] = {
        "spending_limits": [
            {
                "amount": max(spend_cap_cents, 100),  # min $1.00 to avoid 0
                "interval": "all_time",
            }
        ],
        "allowed_categories": [],  # empty = allow all
    }

    try:
        card = stripe.issuing.Card.create(
            cardholder=cardholder_id,
            currency="usd",
            type="virtual",
            status="active",
            metadata={
                "group_id": group["id"],
                "group_title": (group.get("title") or "")[:80],
                "lead_id": str(group.get("lead_id") or ""),
                "kwikpay_kind": "group_card",
            },
            spending_controls=spending_controls,
        )
    except Exception as e:
        logger.exception(f"[issuing] Card.create failed for group {group.get('id')}: {e}")
        raise

    payload = {
        "stripe_card_id": card.id,
        "cardholder_id": cardholder_id,
        "nickname": nickname,
        "last4": getattr(card, "last4", None),
        "brand": getattr(card, "brand", None),
        "exp_month": getattr(card, "exp_month", None),
        "exp_year": getattr(card, "exp_year", None),
        "currency": getattr(card, "currency", "usd") or "usd",
        "status": getattr(card, "status", "active") or "active",
        "issued_at": _now(),
        "spend_cap": round(total, 2),
        "spent": 0.0,
        "balance": 0.0,  # filled at read-time by group enricher
    }

    await db.groups.update_one(
        {"id": group["id"]},
        {"$set": {"virtual_card": payload}},
    )
    logger.info(f"[issuing] Issued card {card.id} ({getattr(card, 'last4', None)}) for group {group['id']}")
    return payload


async def disable_group_card(db, group_id: str, by: str = "system", reason: str = "auto-settled") -> Dict[str, Any]:
    """Set the group's Stripe Issuing card status=inactive (disabled but not deleted)."""
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise RuntimeError("Group not found")
    vc = group.get("virtual_card") or {}
    card_id = vc.get("stripe_card_id")
    if not card_id:
        raise RuntimeError("Group has no issued Stripe card")
    if vc.get("status") == "inactive":
        return vc  # already

    stripe = _stripe_client()
    try:
        stripe.issuing.Card.modify(card_id, status="inactive")
    except Exception as e:
        logger.exception(f"[issuing] disable card {card_id} failed: {e}")
        raise

    new_vc = {
        **vc,
        "status": "inactive",
        "disabled_at": _now(),
        "disabled_by": by,
        "disabled_reason": reason,
    }
    await db.groups.update_one(
        {"id": group_id},
        {"$set": {"virtual_card": new_vc}},
    )
    logger.info(f"[issuing] Disabled card {card_id} for group {group_id} (by={by}, reason={reason})")
    return new_vc


async def maybe_auto_disable_after_settlement(db, group_id: str) -> bool:
    """If admin's `card_disable_mode` is `auto` and group has been settled (charged),
    disable the card. Returns True if it was disabled, False otherwise.
    """
    settings = await get_issuing_settings(db)
    if (settings.get("card_disable_mode") or "auto") != "auto":
        return False

    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        return False
    vc = group.get("virtual_card") or {}
    if not vc.get("stripe_card_id") or vc.get("status") == "inactive":
        return False
    # Auto-disable trigger: group has spent_at set OR a settlement transaction recorded.
    spent = float(vc.get("spent") or 0.0)
    cap = float(vc.get("spend_cap") or 0.0)
    if spent + 0.01 >= cap and cap > 0:
        try:
            await disable_group_card(db, group_id, by="system", reason="auto-disabled after merchant settlement")
            return True
        except Exception as e:
            logger.warning(f"[issuing] auto-disable failed for {group_id}: {e}")
    return False


async def record_issuing_transaction(db, group_id: str, txn_payload: Dict[str, Any]) -> None:
    """Append a transaction summary to the group's virtual_card.transactions list and bump `spent`."""
    amount = float(txn_payload.get("amount") or 0.0)
    merchant = txn_payload.get("merchant") or {}
    entry = {
        "id": txn_payload.get("id"),
        "type": txn_payload.get("type", "capture"),  # authorization | capture | refund
        "amount": round(amount, 2),
        "currency": txn_payload.get("currency", "usd"),
        "merchant_name": merchant.get("name"),
        "merchant_category": merchant.get("category"),
        "merchant_city": merchant.get("city"),
        "created_at": txn_payload.get("created_at") or _now(),
    }
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        return
    vc = group.get("virtual_card") or {}
    txns = list(vc.get("transactions") or [])
    txns.append(entry)
    new_spent = round(float(vc.get("spent") or 0.0) + amount, 2)
    new_vc = {**vc, "transactions": txns, "spent": new_spent}
    await db.groups.update_one({"id": group_id}, {"$set": {"virtual_card": new_vc}})
