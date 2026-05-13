"""Settlement-delay configuration (June 2025).

After the Stripe Connect payout for the Lead lands (status=`paid` webhook),
we hold the Squad in `lead_paid` state for an admin-configurable grace
period before transitioning to `closed` / "Bill Settled". This gives the
Lead a chance to spot any anomalies before the bill is locked as final.

Admin-configurable via:
    GET  /api/admin/settlement-delay
    PUT  /api/admin/settlement-delay

Stored in `app_config` under _id="settlement_delay":
    { "minutes": 20, "updated_at": ISO, "updated_by": "admin@…" }

Bounds: 0..240 minutes. Default 20.
"""
from __future__ import annotations
from typing import Any
from core import now_iso

DEFAULT_DELAY_MIN = 20
MIN_DELAY_MIN = 0
MAX_DELAY_MIN = 240


async def get_settlement_delay_minutes(db: Any) -> int:
    doc = await db.app_config.find_one({"_id": "settlement_delay"}) or {}
    try:
        m = int(doc.get("minutes", DEFAULT_DELAY_MIN))
    except Exception:
        m = DEFAULT_DELAY_MIN
    return max(MIN_DELAY_MIN, min(MAX_DELAY_MIN, m))


async def set_settlement_delay_minutes(
    db: Any, *, minutes: int, admin_email: str | None = None
) -> dict:
    m = int(minutes)
    if m < MIN_DELAY_MIN or m > MAX_DELAY_MIN:
        raise ValueError(f"minutes must be {MIN_DELAY_MIN}..{MAX_DELAY_MIN}")
    await db.app_config.update_one(
        {"_id": "settlement_delay"},
        {"$set": {
            "minutes": m,
            "updated_at": now_iso(),
            "updated_by": admin_email,
        }},
        upsert=True,
    )
    return {"minutes": m}
