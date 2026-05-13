"""Notification Config (June 2025).

Centralized admin-controlled dispatch table for all user-facing
notifications in the app. Per event type, admin can choose channels:
    "off"   — do not notify
    "sms"   — SMS only (live in prod, mock in dev)
    "push"  — push only (deferred; expo-notifications integration pending)
    "both"  — SMS + push

Stored in app_config under _id="notification_config":
{
    "events": {
        "shortfall_assigned":   {"channel": "sms"},
        "shortfall_lead_covered":{"channel": "sms"},
        "shortfall_repaid":     {"channel": "sms"},
        "contribution_received":{"channel": "sms"},
        "bill_funded":          {"channel": "sms"},
        "lead_paid":            {"channel": "sms"},
        "bill_settled":         {"channel": "sms"},
        "payout_available":     {"channel": "sms"},
        "owing_reminder":       {"channel": "sms"},
    },
    "push_enabled": false,
    "updated_at": ISO,
    "updated_by": "admin@…"
}

The frontend admin page renders this as a checkbox table.

Notifications themselves are dispatched via `should_send_*` helpers
defined here. Push delivery is wired but no-ops until
expo-notifications is integrated (a separate follow-up workstream).
"""
from __future__ import annotations
from typing import Any, Dict
from core import now_iso

# Canonical list of notification events the app emits. Adding a new event:
# just add it here with a sensible default and the admin UI auto-renders it.
DEFAULT_EVENTS: Dict[str, Dict[str, str]] = {
    "shortfall_assigned":     {"channel": "sms", "description": "Member asked to cover or split a shortfall"},
    "shortfall_lead_covered": {"channel": "sms", "description": "Lead covered shortfall (loan or gift)"},
    "shortfall_repaid":       {"channel": "sms", "description": "Owing member repaid → cover party notified"},
    "contribution_received":  {"channel": "off", "description": "Member's contribution landed"},
    "bill_funded":            {"channel": "sms", "description": "Squad reached 100% (Contributed state)"},
    "lead_paid":              {"channel": "sms", "description": "Stripe Connect transfer to Lead landed"},
    "bill_settled":           {"channel": "sms", "description": "Bill flipped to final Settled state"},
    "payout_available":       {"channel": "sms", "description": "Covering member earned a Pay Out"},
    "owing_reminder":         {"channel": "sms", "description": "Recurring reminder to pay outstanding share"},
}

VALID_CHANNELS = {"off", "sms", "push", "both"}


async def get_notification_config(db: Any) -> dict:
    """Read-merge: returns default events overlaid with admin overrides."""
    doc = await db.app_config.find_one({"_id": "notification_config"}) or {}
    overrides = (doc.get("events") or {})
    merged: Dict[str, Dict[str, str]] = {}
    for key, dflt in DEFAULT_EVENTS.items():
        ov = overrides.get(key) or {}
        ch = ov.get("channel") if ov.get("channel") in VALID_CHANNELS else dflt["channel"]
        merged[key] = {"channel": ch, "description": dflt["description"]}
    return {
        "events": merged,
        "push_enabled": bool(doc.get("push_enabled", False)),
        "push_status": "coming_soon",  # Surface to admin UI until expo-notifications is wired.
        "updated_at": doc.get("updated_at"),
        "updated_by": doc.get("updated_by"),
    }


async def set_notification_config(
    db: Any, *, events: Dict[str, str], push_enabled: bool, admin_email: str | None = None
) -> dict:
    """Persist admin choices. `events` is a flat {event_key: channel} map."""
    sanitized: Dict[str, Dict[str, str]] = {}
    for k, ch in (events or {}).items():
        if k in DEFAULT_EVENTS and ch in VALID_CHANNELS:
            sanitized[k] = {"channel": ch}
    await db.app_config.update_one(
        {"_id": "notification_config"},
        {"$set": {
            "events": sanitized,
            "push_enabled": bool(push_enabled),
            "updated_at": now_iso(),
            "updated_by": admin_email,
        }},
        upsert=True,
    )
    return await get_notification_config(db)


async def should_send_sms(db: Any, event_key: str) -> bool:
    cfg = await get_notification_config(db)
    ch = (cfg["events"].get(event_key) or {}).get("channel", "off")
    return ch in ("sms", "both")


async def should_send_push(db: Any, event_key: str) -> bool:
    cfg = await get_notification_config(db)
    if not cfg.get("push_enabled"):
        return False
    ch = (cfg["events"].get(event_key) or {}).get("channel", "off")
    return ch in ("push", "both")
