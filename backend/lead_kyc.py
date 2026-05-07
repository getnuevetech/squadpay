"""Per-lead Stripe Issuing cardholder (Phase G3).

When `app_settings.integrations.issuing.require_lead_kyc` is ON:
  - Each lead gets their own Stripe Issuing cardholder (type="individual")
  - The cardholder is created lazily on first card issuance
  - The cardholder's name + phone come from the lead's SquadPay user record
  - In Stripe Test Mode, individual cardholders go straight to status="active"
  - In Live Mode, Stripe will return `requirements.disabled_reason="requirements.past_due"`
    and the operator must run KYC (Stripe Identity or hosted onboarding) before the
    cardholder becomes usable. The lead's KYC status is mirrored from
    cardholder.status (active = passed, inactive = pending KYC).

When OFF (default), all groups share the single business cardholder
(`get_or_create_business_cardholder`), preserving current behavior.

DB schema additions (per-user, in `users` collection):
  stripe_cardholder_id     str | None
  kyc_status               "none" | "pending" | "verified" | "blocked"
  kyc_last_checked_at      iso str
  kyc_disabled_reason      str | None  (e.g. Stripe's requirements.disabled_reason)
"""
from __future__ import annotations
import datetime as dt
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _stripe_client():
    """Return the stripe SDK module with api_key set."""
    import os
    import stripe as _stripe
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=True)
    _stripe.api_key = os.environ.get("STRIPE_API_KEY")
    return _stripe


def _format_e164_or_default(phone: Optional[str]) -> str:
    """Stripe requires E.164. Default to a US sandbox number if missing."""
    if phone and phone.strip().startswith("+") and len(phone.strip()) >= 11:
        return phone.strip()
    return "+15555550100"  # Stripe test number


async def get_or_create_lead_cardholder(db, user: Dict[str, Any]) -> Dict[str, Any]:
    """Return (or create) a Stripe Issuing cardholder for the given lead user.

    Returns a dict: { cardholder_id, status, disabled_reason }
    Raises RuntimeError if Stripe call fails.
    """
    if not user or not user.get("id"):
        raise RuntimeError("Invalid user")

    user_id = user["id"]
    stripe = _stripe_client()
    existing_id = user.get("stripe_cardholder_id")
    existing_status = user.get("kyc_status")

    # 1. If we have an id, fetch its current status from Stripe (single source of truth)
    if existing_id:
        try:
            ch = stripe.issuing.Cardholder.retrieve(existing_id)
            stripe_status = getattr(ch, "status", None) or "inactive"
            requirements = getattr(ch, "requirements", None)
            disabled_reason = (
                getattr(requirements, "disabled_reason", None)
                if requirements else None
            )
            kyc = "verified" if stripe_status == "active" else (
                "blocked" if stripe_status == "blocked" else "pending"
            )
            await db.users.update_one(
                {"id": user_id},
                {"$set": {
                    "kyc_status": kyc,
                    "kyc_last_checked_at": _now(),
                    "kyc_disabled_reason": disabled_reason,
                }},
            )
            return {
                "cardholder_id": existing_id,
                "status": stripe_status,
                "kyc_status": kyc,
                "disabled_reason": disabled_reason,
            }
        except Exception as e:
            logger.warning(f"[lead-kyc] cardholder {existing_id} retrieval failed for {user_id}: {e}")
            # fall through and create a new one

    # 2. Create a new individual cardholder for this lead.
    name = (user.get("name") or "SquadPay Lead").strip()[:60]
    phone = _format_e164_or_default(user.get("phone"))
    email = user.get("email") or f"lead-{user_id}@squadpay.example"

    # Minimal billing address (US default — required by Stripe Issuing).
    billing = {
        "address": {
            "line1": "354 Oyster Point Blvd",
            "city": "South San Francisco",
            "state": "CA",
            "postal_code": "94080",
            "country": "US",
        }
    }

    try:
        ch = stripe.issuing.Cardholder.create(
            type="individual",
            name=name,
            phone_number=phone,
            email=email,
            billing=billing,
            individual={
                "first_name": name.split()[0] if name else "Lead",
                "last_name": (" ".join(name.split()[1:]) or "User") if name else "User",
            },
            metadata={
                "squadpay_user_id": user_id,
                "squadpay_kind": "lead",
            },
        )
    except Exception as e:
        logger.exception(f"[lead-kyc] Cardholder.create failed for {user_id}: {e}")
        raise RuntimeError(f"Stripe Issuing Cardholder.create failed: {e}")

    cid = ch.id
    stripe_status = getattr(ch, "status", None) or "inactive"
    requirements = getattr(ch, "requirements", None)
    disabled_reason = getattr(requirements, "disabled_reason", None) if requirements else None
    kyc = "verified" if stripe_status == "active" else (
        "blocked" if stripe_status == "blocked" else "pending"
    )

    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "stripe_cardholder_id": cid,
            "kyc_status": kyc,
            "kyc_last_checked_at": _now(),
            "kyc_disabled_reason": disabled_reason,
        }},
    )

    logger.info(f"[lead-kyc] Created cardholder {cid} for user {user_id} (status={stripe_status})")
    return {
        "cardholder_id": cid,
        "status": stripe_status,
        "kyc_status": kyc,
        "disabled_reason": disabled_reason,
    }


async def refresh_lead_kyc_status(db, user_id: str) -> Dict[str, Any]:
    """Re-fetch the lead's cardholder status from Stripe and persist on the user."""
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise RuntimeError("User not found")
    if not user.get("stripe_cardholder_id"):
        return {
            "cardholder_id": None,
            "kyc_status": user.get("kyc_status") or "none",
            "disabled_reason": None,
        }
    return await get_or_create_lead_cardholder(db, user)
