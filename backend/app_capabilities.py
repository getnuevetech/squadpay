"""Capability Registry (June 2025).

A capability is a *user-facing* feature that can be turned on/off from the
admin UI. Distinct from the Module Registry (which gates *admin* pages).

Examples:
  • virtual_card_issuing     — Issuing virtual cards (Stripe Issuing).
                                Currently OFF — we don't yet meet Stripe's
                                Issuing financial requirements.
  • lead_debit_card_payout   — Push contribution funds to the Lead's debit
                                card via Group B provider (Astra etc).
                                Currently ON — replaces virtual cards.
  • tap_to_pay_charge        — Stripe Terminal Tap to Pay for member
                                contributions (NFC on phone).
                                Default OFF — flip on once SDK ships.
  • member_refund_to_card    — Push refund balance to member's debit card.
                                Same Group B plumbing as lead payout.
  • multi_provider_charge    — Allow admin to switch Group A active provider.
                                On = framework live; Off = Stripe-only legacy.

Resolution:
  • Backend: `require_capability("key")` 503s with friendly message if off.
  • Frontend: `/api/me/capabilities` returns the boolean map; UI hides
    relevant buttons/screens when off.

Data model:
  db.app_capabilities:
    { key, label, description, group, enabled, sensitive, settings? }
"""
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Static capability catalog. Seeded into db.app_capabilities on startup.
# Editing this list = code release. Per-row enabled flag = admin-config only.
# ---------------------------------------------------------------------------
CAPABILITIES: List[Dict] = [
    # --- Payments
    {
        "key": "lead_debit_card_payout",
        "label": "Lead Debit-Card Payout",
        "description": "When a squad's contributions complete, the Lead can withdraw the pool to their own debit card via the Group B payment gateway.",
        "group": "Payments",
        "enabled_default": True,
        "sensitive": True,
    },
    {
        "key": "member_refund_to_card",
        "label": "Member Refund-to-Card",
        "description": "Member with refund balance can withdraw to their own debit card via the Group B payment gateway. Reuses the same iframe flow as Lead payout.",
        "group": "Payments",
        "enabled_default": True,
        "sensitive": True,
    },
    {
        "key": "virtual_card_issuing",
        "label": "Virtual Card Issuing",
        "description": "Stripe Issuing — generate a single-use virtual card pre-loaded with the squad's pooled funds. Currently OFF until SquadPay meets Stripe Issuing financial requirements.",
        "group": "Payments",
        "enabled_default": False,
        "sensitive": True,
    },
    {
        "key": "tap_to_pay_charge",
        "label": "Tap to Pay (Member Contribution)",
        "description": "Stripe Terminal Tap to Pay — member taps their own physical card on their phone instead of typing card details in the iframe. Requires native SDK; flip on once the next mobile build ships.",
        "group": "Payments",
        "enabled_default": False,
        "sensitive": True,
    },

    # --- Marketing / engagement
    {
        "key": "referrals",
        "label": "Referral Program",
        "description": "Existing user-invite-user referral credits.",
        "group": "Engagement",
        "enabled_default": True,
        "sensitive": False,
    },
    {
        "key": "credit_rewards",
        "label": "Credit Rewards Engine",
        "description": "Admin-defined contribution-driven credit rewards.",
        "group": "Engagement",
        "enabled_default": True,
        "sensitive": False,
    },

    # --- Communications
    {
        "key": "bulk_sms",
        "label": "Bulk SMS",
        "description": "Admin Bulk SMS marketing.",
        "group": "Communications",
        "enabled_default": True,
        "sensitive": False,
    },
    {
        "key": "in_app_notifications",
        "label": "In-App Notifications",
        "description": "Admin-pushed in-app notification center.",
        "group": "Communications",
        "enabled_default": True,
        "sensitive": False,
    },
]

VALID_KEYS = {c["key"] for c in CAPABILITIES}
GROUP_ORDER = ["Payments", "Engagement", "Communications"]

# Cache: key → bool
_CAP_CACHE: Dict[str, bool] = {}


async def load_capabilities_cache(db) -> None:
    """Reload _CAP_CACHE from db.app_capabilities."""
    global _CAP_CACHE
    docs = await db.app_capabilities.find({}, {"_id": 0, "key": 1, "enabled": 1}).to_list(length=None)
    _CAP_CACHE = {d["key"]: bool(d.get("enabled")) for d in docs}


async def seed_capabilities(db) -> None:
    """Idempotent seed of every capability in CAPABILITIES.

    Existing docs in db.app_capabilities keep their `enabled` value (don't reset
    admin choices). Only NEW capabilities introduced in this release get the
    default. Catalog-only fields (label, description, group) are always reset
    to the catalog values so code is the source of truth for them.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    for cap in CAPABILITIES:
        existing = await db.app_capabilities.find_one({"key": cap["key"]}, {"_id": 0})
        if not existing:
            await db.app_capabilities.insert_one({
                "key": cap["key"],
                "label": cap["label"],
                "description": cap["description"],
                "group": cap["group"],
                "enabled": cap["enabled_default"],
                "sensitive": cap.get("sensitive", False),
                "created_at": now,
                "updated_at": now,
            })
        else:
            await db.app_capabilities.update_one(
                {"key": cap["key"]},
                {"$set": {
                    "label": cap["label"],
                    "description": cap["description"],
                    "group": cap["group"],
                    "sensitive": cap.get("sensitive", False),
                    "updated_at": now,
                }},
            )
    await load_capabilities_cache(db)


def is_capability_enabled(key: str) -> bool:
    if key not in VALID_KEYS:
        return False  # defensive
    return _CAP_CACHE.get(key, False)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def require_capability(key: str):
    """503 if the capability is off. Use on payment / payout routes."""
    if key not in VALID_KEYS:
        raise ValueError(f"unknown capability: {key}")

    def _check(request: Request):
        if not is_capability_enabled(key):
            raise HTTPException(
                503,
                f"This feature ({key}) is currently unavailable. Please try again later.",
            )

    return _check


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class CapabilityToggle(BaseModel):
    enabled: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def attach_capability_routes(router: APIRouter, db, get_current_admin):
    from fastapi import Depends as _D
    from admin_modules import require_module

    @router.get("/me/capabilities")
    async def my_capabilities():
        """Public — clients use this on launch to gate UI. No auth needed
        (capability state isn't sensitive). Returns just key → bool."""
        return {"capabilities": dict(_CAP_CACHE)}

    @router.get("/admin/capabilities")
    async def list_capabilities(_=_D(get_current_admin)):
        docs = await db.app_capabilities.find({}, {"_id": 0}).to_list(length=None)
        # Sort by GROUP_ORDER then catalog order.
        order = {c["key"]: i for i, c in enumerate(CAPABILITIES)}
        docs.sort(key=lambda d: order.get(d["key"], 999))
        return {"items": docs, "group_order": GROUP_ORDER}

    @router.put("/admin/capabilities/{key}")
    async def toggle_capability(
        key: str,
        body: CapabilityToggle,
        admin=_D(get_current_admin),
        _check=_D(require_module("integrations")),  # capability mgmt = integrations sensitive module
    ):
        if key not in VALID_KEYS:
            raise HTTPException(404, f"Unknown capability '{key}'")
        from datetime import datetime, timezone
        await db.app_capabilities.update_one(
            {"key": key},
            {"$set": {"enabled": bool(body.enabled), "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=False,
        )
        await load_capabilities_cache(db)
        try:
            from admin import write_audit
            await write_audit(
                db, admin_id=admin["id"], admin_email=admin["email"],
                action="admin.capability_toggled", target_type="capability", target_id=key,
                payload={"enabled": bool(body.enabled)},
            )
        except Exception:
            pass
        updated = await db.app_capabilities.find_one({"key": key}, {"_id": 0})
        return updated
