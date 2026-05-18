"""Home Widgets — admin-configurable widget cards rendered on the user
home screen below the FeaturedBillCard.

Two widget kinds (June 2026):

  1. "What's Next" card — a single dynamic suggestion picked from an
     ordered, admin-editable list of rules. The first rule whose trigger
     condition matches the user's current state wins; if none match, the
     card hides and the gradient simply breathes through.

  2. "Promo Banner" — a single static evergreen card with title/body/icon/
     route, optionally dismissible (× button stores a dismissed-until
     timestamp client-side in AsyncStorage).

All copy, icons, routes, and toggles are admin-editable from
`/admin/home-widgets`. Endpoints:

  GET  /api/runtime/home-widgets               (public — every home load)
  GET  /api/admin/home-widgets                 (admin)
  PUT  /api/admin/home-widgets                 (admin)

Storage: a single document in collection `app_settings` keyed
{"key": "home_widgets"} so the existing observer/CDC machinery can pick
up changes without bespoke plumbing.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core import now_iso

logger = logging.getLogger(__name__)

# Rule keys recognised by the frontend matcher. Adding a new rule here
# requires a corresponding case in HomeWidgets.tsx's `pickWhatsNextRule()`.
KNOWN_RULE_KEYS = {
    "verify_phone",
    "outstanding_owed",
    "no_squads",
    "invite_friends",
}

# Curated lucide-react-native icon allow-list. Frontend has a matching
# map; typos here would render an empty circle so we constrain the set.
ALLOWED_ICONS = [
    "shield-alert", "shield-check", "alert-circle", "alert-triangle",
    "info", "plus-circle", "gift", "camera", "sparkles", "zap",
    "target", "users", "dollar-sign", "credit-card", "bell",
    "heart", "star", "award", "trending-up", "rocket",
    "message-circle", "life-buoy",
]

# Default config — seeded on first read so super_admin sees the widgets
# rendered out of the box with sensible copy.
DEFAULT_CONFIG: Dict[str, Any] = {
    "whats_next_card": {
        "enabled": True,
        "rules": [
            {
                "key": "verify_phone",
                "enabled": True,
                "title": "Verify your phone",
                "subtitle": "Required to get paid faster.",
                "icon": "shield-alert",
                "route": "/auth?mode=verify",
            },
            {
                "key": "outstanding_owed",
                "enabled": True,
                # Template tokens — substituted on the client:
                #   {amount} -> "$24.50"
                #   {count}  -> "2"
                #   {plural} -> "s" (or empty for count==1)
                "title": "${amount} owed across {count} squad{plural}",
                "subtitle": "Tap to settle up.",
                "icon": "alert-circle",
                "route": "/activity",
            },
            {
                "key": "no_squads",
                "enabled": True,
                "title": "Start your first bill",
                "subtitle": "Split anything in 30 seconds.",
                "icon": "plus-circle",
                "route": "/create",
            },
            {
                "key": "invite_friends",
                "enabled": True,
                "title": "Invite friends, earn credits",
                "subtitle": "Both of you get $5.",
                "icon": "gift",
                "route": "/invite",
            },
        ],
    },
    "promo_banner": {
        "enabled": True,
        "title": "Snap-to-split",
        "body": "Scan any receipt, we'll itemize it for you automatically.",
        "icon": "camera",
        "route": "/create",
        "dismissible": True,
        "dismiss_days": 7,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────
class WhatsNextRuleIn(BaseModel):
    key: str
    enabled: bool = True
    title: str = ""
    subtitle: str = ""
    icon: str = "sparkles"
    route: str = "/"


class WhatsNextCardIn(BaseModel):
    enabled: bool = True
    rules: List[WhatsNextRuleIn] = Field(default_factory=list)


class PromoBannerIn(BaseModel):
    enabled: bool = True
    title: str = ""
    body: str = ""
    icon: str = "sparkles"
    route: str = "/"
    dismissible: bool = True
    dismiss_days: int = 7


class HomeWidgetsConfigIn(BaseModel):
    whats_next_card: WhatsNextCardIn
    promo_banner: PromoBannerIn


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _load_or_seed(db) -> Dict[str, Any]:
    """Read the doc, seeding defaults on first run."""
    doc = await db.app_settings.find_one({"key": "home_widgets"}, {"_id": 0})
    if not doc:
        doc = {
            "key": "home_widgets",
            **DEFAULT_CONFIG,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.app_settings.insert_one(doc.copy())
    # Strip storage metadata.
    return {
        "whats_next_card": doc.get("whats_next_card") or DEFAULT_CONFIG["whats_next_card"],
        "promo_banner": doc.get("promo_banner") or DEFAULT_CONFIG["promo_banner"],
        "updated_at": doc.get("updated_at"),
    }


def _sanitise_rule(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Reject rules with unknown keys or icons (silently drops to keep the
    frontend never seeing a broken row). Returns None if invalid."""
    key = (r.get("key") or "").strip()
    if key not in KNOWN_RULE_KEYS:
        logger.warning(f"[home-widgets] dropping unknown rule key={key!r}")
        return None
    icon = (r.get("icon") or "sparkles").strip()
    if icon not in ALLOWED_ICONS:
        icon = "sparkles"
    return {
        "key": key,
        "enabled": bool(r.get("enabled", True)),
        "title": (r.get("title") or "").strip()[:120],
        "subtitle": (r.get("subtitle") or "").strip()[:160],
        "icon": icon,
        "route": (r.get("route") or "/").strip()[:240],
    }


def _sanitise_promo(p: Dict[str, Any]) -> Dict[str, Any]:
    icon = (p.get("icon") or "sparkles").strip()
    if icon not in ALLOWED_ICONS:
        icon = "sparkles"
    return {
        "enabled": bool(p.get("enabled", True)),
        "title": (p.get("title") or "").strip()[:120],
        "body": (p.get("body") or "").strip()[:200],
        "icon": icon,
        "route": (p.get("route") or "/").strip()[:240],
        "dismissible": bool(p.get("dismissible", True)),
        "dismiss_days": max(0, min(int(p.get("dismiss_days") or 0), 365)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Route attach
# ─────────────────────────────────────────────────────────────────────────────
def attach_home_widgets_routes(api_router: APIRouter, db, admin_dep):
    """admin_dep — the FastAPI dependency that enforces a logged-in admin
    session with the `home_widgets` module assigned to their role.
    Caller's responsibility: must validate role.modules contains
    'home_widgets'.
    """

    @api_router.get("/runtime/home-widgets")
    async def runtime_get():
        """Public — the user app reads this on every home page load."""
        cfg = await _load_or_seed(db)
        # Expose only the user-facing surface (no metadata noise).
        return {
            "whats_next_card": cfg["whats_next_card"],
            "promo_banner": cfg["promo_banner"],
            # Cache hint for the client (allow stale-while-revalidate).
            "cache_seconds": 60,
        }

    @api_router.get("/admin/home-widgets")
    async def admin_get(admin=admin_dep):
        cfg = await _load_or_seed(db)
        return {
            "whats_next_card": cfg["whats_next_card"],
            "promo_banner": cfg["promo_banner"],
            "allowed_icons": ALLOWED_ICONS,
            "known_rule_keys": sorted(KNOWN_RULE_KEYS),
            "updated_at": cfg.get("updated_at"),
        }

    @api_router.put("/admin/home-widgets")
    async def admin_put(body: HomeWidgetsConfigIn, admin=admin_dep):
        # Sanitise rules — preserve ordering as submitted.
        sanitised_rules: List[Dict[str, Any]] = []
        seen_keys = set()
        for r in body.whats_next_card.rules:
            s = _sanitise_rule(r.model_dump())
            if s is None:
                continue
            if s["key"] in seen_keys:
                # Dedupe — keep first occurrence.
                continue
            seen_keys.add(s["key"])
            sanitised_rules.append(s)

        update_doc = {
            "key": "home_widgets",
            "whats_next_card": {
                "enabled": bool(body.whats_next_card.enabled),
                "rules": sanitised_rules,
            },
            "promo_banner": _sanitise_promo(body.promo_banner.model_dump()),
            "updated_at": now_iso(),
            "updated_by": (admin.get("email") if isinstance(admin, dict) else None),
        }
        await db.app_settings.update_one(
            {"key": "home_widgets"},
            {"$set": update_doc, "$setOnInsert": {"created_at": now_iso()}},
            upsert=True,
        )
        logger.info(
            f"[home-widgets] admin={update_doc.get('updated_by')} "
            f"updated rules={len(sanitised_rules)} promo_enabled={update_doc['promo_banner']['enabled']}"
        )
        return {"ok": True, "config": update_doc}
