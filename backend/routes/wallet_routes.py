"""
Wallet provisioning routes — scaffolding for Apple Pay / Google Pay push
provisioning of the SquadPay virtual card into the Lead's native wallet.

⚠️ STATUS: SCAFFOLDED, NOT YET ENABLED.

Both Apple Pay (`PKPushProvisioningContext`) and Google Pay (Tap-to-Pay
`PushTokenizeRequest`) require:
  1. A **Card Network → PNO partnership** (Visa Direct / Mastercard MDES).
  2. A **PSP integration** (Stripe Issuing supports push provisioning for
     enrolled accounts only — requires bank/PNO sign-off).
  3. Native iOS / Android entitlements granted by Apple / Google after the
     PNO confirms our identity.

Until those approvals land, this endpoint returns a 202 with
`status: "pending_psp_approval"` so the frontend can render a graceful
"Coming Soon" CTA instead of breaking.

When approvals land, replace the stub body with real Stripe calls:
    payload = stripe.issuing.Card.create_push_provisioning_data(
        card=card_id, platform=platform, certificates=[...], nonce=..., nonce_signature=...,
    )
…and return the encoded payload to the native side which feeds it into
`PKAddPaymentPassRequest` (iOS) or `PushTokenizeRequest` (Android).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

router = APIRouter(prefix="/api", tags=["wallet"])


class ProvisionRequest(BaseModel):
    user_id: str
    platform: Literal["apple", "google"]
    # iOS provides these in PKAddPaymentPassRequestConfiguration.
    # Android sends a wallet account id + stable hardware id.
    nonce: Optional[str] = None
    nonce_signature: Optional[str] = None
    certificates: Optional[list[str]] = None
    wallet_account_id: Optional[str] = None
    stable_hardware_id: Optional[str] = None


class ProvisionResponse(BaseModel):
    ok: bool
    status: Literal[
        "pending_psp_approval",
        "ready",
        "card_not_issued",
        "not_lead",
        "unsupported_platform",
    ]
    # When status == "ready", the platform-specific payload the native SDK feeds
    # into the wallet activation request. Today this is always None.
    payload: Optional[dict] = None
    message: Optional[str] = None


@router.post("/cards/{group_id}/provision", response_model=ProvisionResponse)
async def provision_card_to_wallet(group_id: str, body: ProvisionRequest):
    """
    Scaffold for push-provisioning the SquadPay virtual card into Apple/Google
    Wallet. Returns 202 with `status: "pending_psp_approval"` until the
    Card Network / PNO / PSP approvals are in place.
    """
    # Local import to avoid pulling Mongo into the module import graph at
    # service start — keeps cold starts fast for endpoints that don't need DB.
    from server import db  # type: ignore

    group = await db.groups.find_one({"id": group_id})
    if not group:
        raise HTTPException(404, "group_not_found")

    # Only the lead's card can be provisioned — enforced server-side so a
    # member can't request someone else's wallet activation.
    if group.get("lead_id") != body.user_id:
        return ProvisionResponse(
            ok=False,
            status="not_lead",
            message="Only the bill lead can add the SquadPay card to a wallet.",
        )

    if not (group.get("virtual_card") or {}).get("stripe_card_id"):
        return ProvisionResponse(
            ok=False,
            status="card_not_issued",
            message="The virtual card hasn't been issued yet. Fully fund the bill first.",
        )

    if body.platform not in ("apple", "google"):
        return ProvisionResponse(
            ok=False,
            status="unsupported_platform",
            message=f"Platform '{body.platform}' is not supported.",
        )

    # ── ADMIN GATE ─────────────────────────────────────────────────────
    # The admin controls wallet enablement via /admin/app-config:
    #   wallet.enabled         = master switch (off until Stripe approves)
    #   wallet.apple_enabled   = per-platform staged-rollout toggle
    #   wallet.google_enabled  = per-platform staged-rollout toggle
    # If the master switch is off OR the per-platform sub-toggle is off,
    # we return `pending_psp_approval` so the frontend shows the polished
    # "coming soon" toast instead of a broken-feeling error.
    try:
        from routes.admin_app_config import get_app_config_cache  # type: ignore
        cfg = get_app_config_cache()
        wallet_cfg = (cfg or {}).get("wallet") or {}
        master_on = bool(wallet_cfg.get("enabled"))
        platform_on = bool(
            wallet_cfg.get("apple_enabled") if body.platform == "apple"
            else wallet_cfg.get("google_enabled")
        )
        if not (master_on and platform_on):
            return ProvisionResponse(
                ok=True,
                status="pending_psp_approval",
                payload=None,
                message=(
                    "Apple/Google Wallet provisioning is pending bank-network approval. "
                    "You'll be able to add the SquadPay card to your wallet as soon as it's enabled."
                ),
            )
    except Exception:
        # Cache not loaded yet (very early in startup) — fail safe to "pending".
        return ProvisionResponse(
            ok=True,
            status="pending_psp_approval",
            payload=None,
            message="Wallet provisioning is initialising — please try again shortly.",
        )

    # ── STUB BRANCH ─────────────────────────────────────────────────────
    # When PSP approvals land, this block becomes a real Stripe Issuing call
    # that returns the platform-specific encrypted provisioning data.
    # Today even with admin toggles ON we still return the stub — flip the
    # implementation here in lockstep with the real Stripe Issuing call.
    return ProvisionResponse(
        ok=True,
        status="pending_psp_approval",
        payload=None,
        message=(
            "Apple/Google Wallet provisioning is pending bank-network approval. "
            "You'll be able to add the SquadPay card to your wallet as soon as it's enabled."
        ),
    )
