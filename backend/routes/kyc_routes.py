"""User-facing KYC endpoints (Phase G3).

When `app_settings.integrations.issuing.require_lead_kyc` is ON, leads must
have an active Stripe Issuing cardholder before a card can be issued for
their group.

These endpoints let the lead app:
  GET  /api/users/{id}/kyc          → current KYC status (refreshed from Stripe)
  POST /api/users/{id}/kyc/start    → kick off cardholder creation (idempotent)

If you wire up Stripe Identity later, add a /verify endpoint that creates a
verification_session and returns the hosted URL. For Test Mode, the cardholder
is auto-active on creation (Stripe doesn't require docs in test mode), so the
"start" call here is enough.
"""
from fastapi import APIRouter, HTTPException

from issuing import get_issuing_settings
from lead_kyc import get_or_create_lead_cardholder, refresh_lead_kyc_status


def _public(user: dict, ch: dict | None = None) -> dict:
    return {
        "user_id": user["id"],
        "stripe_cardholder_id": user.get("stripe_cardholder_id"),
        "kyc_status": user.get("kyc_status") or "none",
        "kyc_disabled_reason": user.get("kyc_disabled_reason"),
        "kyc_last_checked_at": user.get("kyc_last_checked_at"),
        "stripe_status": (ch or {}).get("status") if ch else None,
    }


def attach_kyc_routes(router: APIRouter, db):

    @router.get("/users/{user_id}/kyc")
    async def get_kyc(user_id: str):
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        settings = await get_issuing_settings(db)
        require = bool(settings.get("require_lead_kyc"))
        # If feature off and no existing cardholder, return a simple "not_required" payload
        if not require and not user.get("stripe_cardholder_id"):
            return {**_public(user), "required": False}
        # If we have a cardholder, refresh from Stripe; else just return current cached
        ch = None
        if user.get("stripe_cardholder_id"):
            try:
                ch = await refresh_lead_kyc_status(db, user_id)
                user = await db.users.find_one({"id": user_id}, {"_id": 0})
            except Exception as e:
                # Stripe transient error — return cached
                pass
        return {**_public(user, ch), "required": require}

    @router.post("/users/{user_id}/kyc/start")
    async def start_kyc(user_id: str):
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        if not user.get("verified"):
            raise HTTPException(403, "Phone verification required first")
        if user.get("is_blocked"):
            raise HTTPException(403, "Account blocked")
        settings = await get_issuing_settings(db)
        if not settings.get("require_lead_kyc"):
            return {"required": False, "message": "Lead KYC is not currently required."}
        try:
            ch = await get_or_create_lead_cardholder(db, user)
        except Exception as e:
            raise HTTPException(502, f"Stripe error: {e}")
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        return {
            **_public(user, ch),
            "required": True,
            "next_step": (
                "complete"
                if ch.get("status") == "active"
                else f"Stripe requires further documentation: {ch.get('disabled_reason') or 'pending'}. "
                     f"In production, you would now be redirected to a Stripe Identity hosted page; "
                     f"the operator must integrate Stripe Identity separately for full verification."
            ),
        }
