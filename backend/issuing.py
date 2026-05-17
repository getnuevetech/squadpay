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

DEFAULT_BUSINESS_NAME = "SquadPay"
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
      "cardholder_name": "SquadPay",
      "card_disable_mode": "auto" | "manual",
      "require_otp_for_card_reveal": bool,
      "reveal_ttl_seconds": int,
    }
    """
    rec = await db.app_settings.find_one({"key": SETTINGS_KEY}, {"_id": 0}) or {}
    issuing = dict(rec.get("issuing") or {})
    issuing.setdefault("enabled", True)
    issuing.setdefault("cardholder_id", None)
    issuing.setdefault("cardholder_name", DEFAULT_BUSINESS_NAME)
    issuing.setdefault("card_disable_mode", "auto")  # auto | manual
    issuing.setdefault("require_otp_for_card_reveal", True)
    issuing.setdefault("reveal_ttl_seconds", 60)
    # Phase G3 — per-lead cardholder mode
    issuing.setdefault("require_lead_kyc", False)
    # Phase G4 — push provisioning enrollment flags (drop-in)
    issuing.setdefault("apple_pay_enrolled", False)
    issuing.setdefault("google_pay_enrolled", False)
    return issuing


async def set_issuing_settings(db, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge updates into app_settings.integrations.issuing.

    Encrypts `webhook_secret` (Stripe Issuing webhook signing secret) at rest.
    Returns the public-safe view (masked secret).
    """
    cur = await get_issuing_settings(db)
    incoming = {k: v for k, v in patch.items() if v is not None}
    # Encrypt webhook_secret at rest
    if "webhook_secret" in incoming:
        plain = (incoming.pop("webhook_secret") or "").strip()
        if plain:
            try:
                from admin import encrypt_secret  # type: ignore
                incoming["webhook_secret_enc"] = encrypt_secret(plain)
                incoming["webhook_secret_masked"] = (
                    plain[:6] + "…" + plain[-4:] if len(plain) > 12 else "configured"
                )
            except Exception as e:
                logger.warning(f"[issuing] encrypt webhook_secret failed: {e}")
    new = {**cur, **incoming, "updated_at": _now()}
    await db.app_settings.update_one(
        {"key": SETTINGS_KEY},
        {"$set": {"issuing": new}},
        upsert=True,
    )
    # Public view: never return raw encrypted blob
    public = dict(new)
    public.pop("webhook_secret_enc", None)
    return public


async def get_or_create_business_cardholder(db) -> str:
    """Return existing SquadPay cardholder id or auto-create a new one.

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
    """Issue a virtual card for the given group via the ACTIVE issuer adapter.

    Provider-agnostic (June 2025 refactor). Routes through the IssuerAdapter
    registry: whichever provider is currently active in the admin
    `Payment Gateways` panel (Stripe / Lithic / Highnote / Unit / Increase)
    handles the actual issuance. Switching providers requires no code change
    \u2014 just toggle in admin.

    Stores the result on the group doc as `virtual_card`. Idempotent: if the
    group already has a virtual_card with status=active, returns it.

    Stripe-specific legacy fields (`stripe_card_id`, `cardholder_id`) are
    preserved on the payload for backwards compatibility with downstream
    code that hasn't yet been migrated. New code should prefer
    `issuer_slug` + `card_id`.
    """
    existing = group.get("virtual_card") or {}
    if existing.get("card_id") and existing.get("status") == "active":
        return existing
    # Legacy: pre-refactor payloads used "stripe_card_id" \u2014 still respect it.
    if existing.get("stripe_card_id") and existing.get("status") == "active":
        return existing

    # Item 6 (June 2025) \u2014 admin master toggle gate. When OFF, we hard-stop
    # all new card issuance globally. Same kill-switch behavior regardless
    # of which issuer is active.
    try:
        wallet_cfg = await db.app_config.find_one({"_id": "wallet"}) or {}
        if wallet_cfg.get("issuing_enabled") is False:
            raise RuntimeError("Squad cards are currently disabled by the administrator.")
    except RuntimeError:
        raise
    except Exception:
        pass

    # Settlement-mode gate (June 2025) \u2014 if admin configured "lead_card" only,
    # NO virtual card should ever be issued. Refuse loudly so the caller
    # routes to the lead-payout flow instead.
    try:
        ints = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {}
        pg = (ints.get("payment_gateways") or {})
        mode = pg.get("settlement_mode") or "virtual_card"
        if mode == "lead_card":
            raise RuntimeError(
                "Settlement mode is 'lead_card' \u2014 virtual card issuance is disabled. "
                "Use the lead-payout flow instead."
            )
    except RuntimeError:
        raise
    except Exception:
        pass

    # Resolve active issuer.
    from adapters.issuer_registry import get_active_issuer, get_active_slug
    active_slug = await get_active_slug(db)
    adapter = await get_active_issuer(db)

    # Spending cap = bill total in cents (rounded up to nearest cent).
    total = float(group.get("total_amount") or 0.0)
    spend_cap_cents = int(round(max(total, 0.0) * 100))
    spend_cap_cents = max(spend_cap_cents, 100)  # min $1.00 sanity floor

    settings = await get_issuing_settings(db)
    business_name = settings.get("cardholder_name") or DEFAULT_BUSINESS_NAME
    nickname = f"{business_name} - {(group.get('title') or 'Group Bill')[:40]}"

    try:
        handle = await adapter.issue_card(
            db,
            squad_id=group["id"],
            spend_limit_cents=spend_cap_cents,
            memo=nickname,
        )
    except NotImplementedError as e:
        # Adapter is integrated but issuance is intentionally blocked (e.g.,
        # Unit.co compliance conflict). Surface with a clean error rather
        # than a 500 \u2014 admin should activate a different provider.
        raise RuntimeError(
            f"Active issuer {active_slug!r} cannot issue cards right now: {e}. "
            f"Activate a different provider in admin / Payment Gateways."
        )
    except Exception as e:
        logger.exception(f"[issuing] {active_slug}.issue_card failed for group {group.get('id')}: {e}")
        raise

    payload = {
        # New provider-agnostic identity fields.
        "issuer_slug": handle.issuer_slug,
        "card_id": handle.card_id,
        # Legacy Stripe-shaped fields preserved for backwards compatibility.
        # `stripe_card_id` is filled ONLY when issuer_slug == 'stripe'; for
        # other issuers it carries the same card_id so consumers that grep
        # for `stripe_card_id` don't crash.
        "stripe_card_id": handle.card_id,
        "cardholder_id": (handle.raw or {}).get("cardholder") or "",
        "nickname": nickname,
        "last4": handle.last4,
        "brand": handle.brand,
        "exp_month": handle.exp_month,
        "exp_year": handle.exp_year,
        "currency": "usd",
        "status": handle.state if handle.state in ("active", "OPEN") else "active",
        "issued_at": _now(),
        "spend_cap": round(total, 2),
        "spent": 0.0,
        "balance": 0.0,  # filled at read-time by group enricher
    }

    await db.groups.update_one(
        {"id": group["id"]},
        {"$set": {"virtual_card": payload}},
    )
    logger.info(f"[issuing] Issued card via {active_slug} id={handle.card_id[:14]}\u2026 last4={handle.last4} for group {group['id']}")
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
