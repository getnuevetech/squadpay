"""
Admin-configurable extra platform fees.

MVP scope:
  • Admin can configure up to 2 extra fees on top of the existing
    transaction & platform fees.
  • Each fee has: name, type ("percent" or "flat"), value, enabled.
  • Stored as a singleton document in the `platform_config` collection
    (doc _id = "platform_fees_config").
  • Applied globally to all NEW bills (the per_user breakdown in core.py
    pulls active fees from this collection).
  • Split equally across all members.
"""
from typing import List, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

CONFIG_ID = "platform_fees_config"
DEFAULT_FEES: List[dict] = [
    {"id": "extra_1", "name": "Extra Fee 1", "type": "flat", "value": 0.0, "enabled": False},
    {"id": "extra_2", "name": "Extra Fee 2", "type": "flat", "value": 0.0, "enabled": False},
]


class FeeIn(BaseModel):
    id: str
    name: str = Field(..., min_length=1, max_length=40)
    type: Literal["percent", "flat"]
    value: float = Field(..., ge=0)
    enabled: bool = False


class FeesPayload(BaseModel):
    fees: List[FeeIn]


async def load_fees_config(db) -> List[dict]:
    """Helper used by the bill-calc to fetch the active config.

    Always returns a list with the canonical 2 slots — missing slots are
    filled with defaults so the admin UI can render predictable rows.
    """
    doc = await db.platform_config.find_one({"_id": CONFIG_ID})
    fees = (doc or {}).get("fees") or []
    by_id = {f.get("id"): f for f in fees if isinstance(f, dict) and f.get("id")}
    out: List[dict] = []
    for default in DEFAULT_FEES:
        merged = {**default, **(by_id.get(default["id"]) or {})}
        # Strip mongo-only fields if any
        out.append({
            "id": merged["id"],
            "name": str(merged.get("name") or default["name"]),
            "type": "percent" if merged.get("type") == "percent" else "flat",
            "value": float(merged.get("value") or 0),
            "enabled": bool(merged.get("enabled")),
        })
    return out


def attach_platform_fees_routes(api_router: APIRouter, db, require_admin):
    """Attach admin platform-fees CRUD endpoints to the main router."""
    # Lazy import so this module doesn't import the heavy core graph at load time
    from core import set_extra_fees_cache  # type: ignore

    async def _refresh_cache():
        set_extra_fees_cache(await load_fees_config(db))

    @api_router.get("/admin/platform-fees")
    async def get_platform_fees(_admin=Depends(require_admin)):
        return {"fees": await load_fees_config(db)}

    @api_router.put("/admin/platform-fees")
    async def update_platform_fees(payload: FeesPayload, _admin=Depends(require_admin)):
        allowed_ids = {f["id"] for f in DEFAULT_FEES}
        cleaned: List[dict] = []
        seen = set()
        for f in payload.fees:
            if f.id not in allowed_ids:
                raise HTTPException(400, f"unknown_fee_slot:{f.id}")
            if f.id in seen:
                raise HTTPException(400, f"duplicate_fee_slot:{f.id}")
            seen.add(f.id)
            cleaned.append({
                "id": f.id,
                "name": f.name.strip(),
                "type": f.type,
                "value": round(float(f.value), 4),
                "enabled": bool(f.enabled),
            })
        # Backfill any missing slot.
        by_id = {c["id"]: c for c in cleaned}
        for default in DEFAULT_FEES:
            if default["id"] not in by_id:
                cleaned.append(default)
        await db.platform_config.update_one(
            {"_id": CONFIG_ID},
            # Mirror to BOTH `fees` (legacy) and `extra_fees` (new). The new
            # admin app-config endpoint reads `extra_fees or fees`, so without
            # the mirror, a legacy PUT silently fails to propagate once the
            # new endpoint has ever been written. Keeping them in lockstep
            # is the cheapest path to consistency.
            {"$set": {"fees": cleaned, "extra_fees": cleaned}},
            upsert=True,
        )
        await _refresh_cache()
        return {"fees": await load_fees_config(db)}

    # Return the refresh helper so the server can call it on startup.
    return _refresh_cache
