"""Landing-page dynamic visuals config (June 2025).

Lets admin define rotating-random pools for the unauth landing screen:
  • phone_frame_colors  — 1..10 hex colors for the phone frame border + Split Now btn
  • bg_purple_shades    — 1..10 hex shades for the page background
  • hashtags            — 1..10 short hashtag chips (e.g. "# SplitBill")
  • avatars             — three avatar slots, each with 1..5 image URLs

Stored in `app_config` under _id="landing_page". Sensible defaults are
seeded inline and used as fallbacks when the admin clears a field.

Public endpoint serves a single resolved snapshot per request (no auth
required since the landing screen runs before login).
"""
from __future__ import annotations
from typing import Any
import re
from core import now_iso

# ── Defaults (used as fallback + initial seed) ─────────────────────────
DEFAULT_PHONE_FRAME_COLORS = [
    "#7C3AED",  # primary violet
    "#5B2BC8",  # deep indigo
    "#8B5CF6",  # lavender violet
    "#A78BFA",  # soft lilac
    "#9333EA",  # vivid purple
]

DEFAULT_BG_PURPLE_SHADES = [
    "#F5F0FF",
    "#EDE4FE",
    "#F8F3FF",
    "#F0E7FE",
    "#FAF5FF",
]

DEFAULT_HASHTAGS = [
    "# SplitBill",
    "# EasyPay",
    "# SquadGoals",
]

# Three avatar "slots" — each renders one face on the hero illustration.
# Admin can register 1..5 URLs per slot; we pick one at random per visit.
DEFAULT_AVATARS = {
    "slot_left": [
        "https://images.unsplash.com/photo-1494790108377-be9c29b29330?crop=entropy&cs=srgb&fm=jpg&w=200&q=80",
        "https://images.unsplash.com/photo-1438761681033-6461ffad8d80?crop=entropy&cs=srgb&fm=jpg&w=200&q=80",
        "https://images.unsplash.com/photo-1487412720507-e7ab37603c6f?crop=entropy&cs=srgb&fm=jpg&w=200&q=80",
    ],
    "slot_right_man": [
        "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?crop=entropy&cs=srgb&fm=jpg&w=200&q=80",
        "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?crop=entropy&cs=srgb&fm=jpg&w=200&q=80",
        "https://images.unsplash.com/photo-1531427186611-ecfd6d936c79?crop=entropy&cs=srgb&fm=jpg&w=200&q=80",
    ],
    "slot_right_woman": [
        "https://images.unsplash.com/photo-1531123897727-8f129e1688ce?crop=entropy&cs=srgb&fm=jpg&w=200&q=80",
        "https://images.unsplash.com/photo-1534528741775-53994a69daeb?crop=entropy&cs=srgb&fm=jpg&w=200&q=80",
        "https://images.unsplash.com/photo-1554151228-14d9def656e4?crop=entropy&cs=srgb&fm=jpg&w=200&q=80",
    ],
}

AVATAR_SLOTS = ("slot_left", "slot_right_man", "slot_right_woman")
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _clean_hex_list(lst, fallback, max_n: int = 10) -> list[str]:
    out: list[str] = []
    for v in (lst or []):
        if isinstance(v, str) and HEX_RE.match(v.strip()):
            out.append(v.strip().upper())
    out = out[:max_n]
    return out or list(fallback)


def _clean_str_list(lst, fallback, max_n: int = 10, max_len: int = 32) -> list[str]:
    out: list[str] = []
    for v in (lst or []):
        if isinstance(v, str) and v.strip():
            out.append(v.strip()[:max_len])
    out = out[:max_n]
    return out or list(fallback)


def _clean_url_list(lst, fallback, max_n: int = 5) -> list[str]:
    out: list[str] = []
    for v in (lst or []):
        if isinstance(v, str) and (v.startswith("https://") or v.startswith("http://")):
            out.append(v.strip()[:500])
    out = out[:max_n]
    return out or list(fallback)


async def get_landing_page_config(db: Any) -> dict:
    doc = await db.app_config.find_one({"_id": "landing_page"}) or {}
    avatars_in = doc.get("avatars") or {}
    avatars_out: dict[str, list[str]] = {}
    for slot in AVATAR_SLOTS:
        avatars_out[slot] = _clean_url_list(avatars_in.get(slot), DEFAULT_AVATARS[slot])
    return {
        "phone_frame_colors": _clean_hex_list(doc.get("phone_frame_colors"), DEFAULT_PHONE_FRAME_COLORS),
        "bg_purple_shades": _clean_hex_list(doc.get("bg_purple_shades"), DEFAULT_BG_PURPLE_SHADES),
        "hashtags": _clean_str_list(doc.get("hashtags"), DEFAULT_HASHTAGS),
        "avatars": avatars_out,
        "updated_at": doc.get("updated_at"),
        "updated_by": doc.get("updated_by"),
    }


async def set_landing_page_config(
    db: Any,
    *,
    phone_frame_colors: list[str] | None = None,
    bg_purple_shades: list[str] | None = None,
    hashtags: list[str] | None = None,
    avatars: dict | None = None,
    admin_email: str | None = None,
) -> dict:
    cleaned_avatars: dict[str, list[str]] = {}
    for slot in AVATAR_SLOTS:
        cleaned_avatars[slot] = _clean_url_list(
            (avatars or {}).get(slot), DEFAULT_AVATARS[slot]
        )
    await db.app_config.update_one(
        {"_id": "landing_page"},
        {"$set": {
            "phone_frame_colors": _clean_hex_list(phone_frame_colors, DEFAULT_PHONE_FRAME_COLORS),
            "bg_purple_shades": _clean_hex_list(bg_purple_shades, DEFAULT_BG_PURPLE_SHADES),
            "hashtags": _clean_str_list(hashtags, DEFAULT_HASHTAGS),
            "avatars": cleaned_avatars,
            "updated_at": now_iso(),
            "updated_by": admin_email,
        }},
        upsert=True,
    )
    return await get_landing_page_config(db)
