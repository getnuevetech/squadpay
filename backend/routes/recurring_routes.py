"""Recurring-bills routes (P2, June 2025).

Endpoints (mounted under /api):
  GET    /groups/{group_id}/recurrence              — lead only
  PUT    /groups/{group_id}/recurrence              — lead only, write/update
  DELETE /groups/{group_id}/recurrence              — lead only, disable

The lead can also turn off recurrence by sending {"enabled": false} to PUT.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import now_iso
from recurring_groups_cron import compute_next_run, _iso_utc
from datetime import datetime, timezone


class RecurrenceIn(BaseModel):
    enabled: bool = True
    cadence: str = Field("weekly", description="weekly | monthly")
    anchor: int = Field(0, description="0-6 (Mon=0) for weekly, 1-31 for monthly")
    skip_if_open: bool = False
    user_id: str


def attach_recurring_routes(router: APIRouter, db) -> None:
    @router.get("/groups/{group_id}/recurrence")
    async def get_recurrence(group_id: str, user_id: str):
        g = await db.groups.find_one({"id": group_id}, {"_id": 0, "lead_id": 1, "recurrence": 1})
        if not g:
            raise HTTPException(404, "Squad not found")
        if g.get("lead_id") != user_id:
            raise HTTPException(403, "Only the lead can view the recurrence schedule")
        return g.get("recurrence") or {"enabled": False}

    @router.put("/groups/{group_id}/recurrence")
    async def set_recurrence(group_id: str, body: RecurrenceIn, request: Request):
        g = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not g:
            raise HTTPException(404, "Squad not found")
        if g.get("lead_id") != body.user_id:
            raise HTTPException(403, "Only the lead can configure recurrence")
        if body.cadence not in ("weekly", "monthly"):
            raise HTTPException(400, "cadence must be 'weekly' or 'monthly'")
        if body.cadence == "weekly" and not (0 <= body.anchor <= 6):
            raise HTTPException(400, "anchor must be 0-6 for weekly cadence")
        if body.cadence == "monthly" and not (1 <= body.anchor <= 31):
            raise HTTPException(400, "anchor must be 1-31 for monthly cadence")

        if not body.enabled:
            await db.groups.update_one(
                {"id": group_id},
                {"$set": {
                    "recurrence.enabled": False,
                    "recurrence.disabled_at": now_iso(),
                }},
            )
            return {"ok": True, "enabled": False}

        next_dt = compute_next_run(body.cadence, body.anchor, base=datetime.now(timezone.utc))
        new_rec = {
            "enabled": True,
            "cadence": body.cadence,
            "anchor": int(body.anchor),
            "skip_if_open": bool(body.skip_if_open),
            "next_run_at": _iso_utc(next_dt),
            "updated_at": now_iso(),
            "updated_by": body.user_id,
        }
        # Preserve last_run_at + last_clone_group_id if previously set.
        prev = g.get("recurrence") or {}
        if prev.get("last_run_at"):
            new_rec["last_run_at"] = prev["last_run_at"]
        if prev.get("last_clone_group_id"):
            new_rec["last_clone_group_id"] = prev["last_clone_group_id"]

        await db.groups.update_one({"id": group_id}, {"$set": {"recurrence": new_rec}})
        return {"ok": True, **new_rec}

    @router.delete("/groups/{group_id}/recurrence")
    async def disable_recurrence(group_id: str, user_id: str):
        g = await db.groups.find_one({"id": group_id}, {"_id": 0, "lead_id": 1})
        if not g:
            raise HTTPException(404, "Squad not found")
        if g.get("lead_id") != user_id:
            raise HTTPException(403, "Only the lead can disable recurrence")
        await db.groups.update_one(
            {"id": group_id},
            {"$set": {"recurrence.enabled": False, "recurrence.disabled_at": now_iso()}},
        )
        return {"ok": True, "enabled": False}
