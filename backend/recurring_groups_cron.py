"""Recurring Bills (P2, June 2025).

When a squad is marked as recurring (e.g. weekly rent, monthly utilities),
we automatically clone it on the configured cadence. The fresh squad
inherits the same lead, members, items, tax/tip, split_mode, and title —
but starts with a clean contribution/payment state.

Schema lives on the source group document:
    groups.recurrence = {
        "enabled": bool,
        "cadence": "weekly" | "monthly",
        "anchor": int,           # 0-6 for weekly (Mon=0), 1-31 for monthly
        "next_run_at": ISO str,  # UTC, when the next clone should fire
        "last_run_at": ISO str | None,
        "last_clone_group_id": str | None,
        "skip_if_open": bool,    # if a clone from this template is still
                                  # open/unpaid, don't fire a new one
    }

We deliberately copy ITEMS but not contributions/repayments/notifications —
the new bill starts fresh. Members carry over so the lead doesn't have to
share the invite link every week.

Cadence rules:
- weekly: anchor=0 means Mon, 1=Tue, …, 6=Sun
- monthly: anchor=1..31 (clamped to month length, e.g. anchor=31 in Feb → 28/29)

The loop runs every 30 minutes by default (fairly cheap — small mongo scan).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core import new_id, now_iso, new_short_code, get_join_code_config

logger = logging.getLogger("recurring_groups_cron")


# ──────────────────────────── helpers ────────────────────────────────

def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # tolerate trailing Z
        s = s.replace("Z", "+00:00") if s.endswith("Z") else s
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def _iso_utc(d: datetime) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def compute_next_run(cadence: str, anchor: int, *, base: datetime | None = None) -> datetime:
    """Given a cadence + anchor, return the next ISO datetime (UTC) AFTER `base`."""
    now = (base or datetime.now(timezone.utc)).replace(microsecond=0, second=0)
    if cadence == "weekly":
        anchor = max(0, min(6, int(anchor)))
        # weekday(): Mon=0..Sun=6 — matches our convention.
        days_ahead = (anchor - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        # default time-of-day = 09:00 UTC (we keep this hard-coded for MVP;
        # later we can let the lead set a preferred hour).
        cand = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0)
        return cand
    if cadence == "monthly":
        anchor = max(1, min(31, int(anchor)))
        # next month boundary
        if now.month == 12:
            ny, nm = now.year + 1, 1
        else:
            ny, nm = now.year, now.month + 1
        # Try anchor in the current month if it's still in the future, else next month.
        from calendar import monthrange
        last_in_cur = monthrange(now.year, now.month)[1]
        anchor_this = min(anchor, last_in_cur)
        cand_this = now.replace(day=anchor_this, hour=9, minute=0)
        if cand_this > now:
            return cand_this
        last_in_next = monthrange(ny, nm)[1]
        anchor_next = min(anchor, last_in_next)
        return datetime(ny, nm, anchor_next, 9, 0, tzinfo=timezone.utc)
    # unknown cadence → 7 days out as a safety net
    return now + timedelta(days=7)


# ──────────────────────── clone-a-group logic ────────────────────────

async def _clone_group(db: Any, src: dict[str, Any]) -> dict[str, Any] | None:
    """Create a new group based on `src`. Returns the new group, or None."""
    new_gid = new_id("g_")
    # Members copy over but get a clean settle state — no contributions/
    # repayments/assignments — and the lead must still re-share the invite
    # if anyone leaves the recurring template.
    new_members = []
    for m in (src.get("members") or []):
        new_members.append({
            "user_id": m["user_id"],
            "name": m.get("name") or "Member",
            "joined_at": now_iso(),
        })
    new_items = []
    for it in (src.get("items") or []):
        new_items.append({
            "id": new_id("it_"),
            "name": it.get("name") or "Item",
            "price": float(it.get("price") or 0),
            "quantity": int(it.get("quantity") or 1),
        })

    # New invite code, honoring admin-configured charset/length.
    try:
        jc_cfg = await get_join_code_config(db)
        code = None
        for _ in range(10):
            cand = new_short_code(jc_cfg["length"], jc_cfg["charset"])
            if not await db.groups.find_one({"code": cand}, {"_id": 0, "id": 1}):
                code = cand
                break
        if not code:
            code = new_short_code(jc_cfg["length"] + 2, jc_cfg["charset"])
    except Exception:
        code = new_id("g_")[-6:].upper()

    new_group = {
        "id": new_gid,
        "code": code,
        "title": src.get("title") or "Recurring Bill",
        "lead_id": src["lead_id"],
        "total": float(src.get("total") or 0),
        "tax": float(src.get("tax") or 0),
        "tip": float(src.get("tip") or 0),
        "split_mode": src.get("split_mode") or "equal",
        "members": new_members,
        "items": new_items,
        "assignments": [],
        "contributions": [],
        "repayments": [],
        "notifications": [],
        "status": "open",
        "is_blocked": False,
        "funding_mode": None,
        "funding": {"total_contributed": 0.0},
        "created_at": now_iso(),
        # Trace back to the source template so the admin/lead can audit which
        # bills came from a recurring schedule.
        "recurrence_source": src["id"],
    }
    await db.groups.insert_one(new_group)
    logger.info("[recurring] cloned %s → %s (members=%d, items=%d)",
                src["id"], new_gid, len(new_members), len(new_items))
    return new_group


# ─────────────────────── main background loop ────────────────────────

async def _tick(db: Any) -> dict[str, int]:
    """One pass: find groups due to recur and clone them. Returns counts."""
    now = datetime.now(timezone.utc)
    cursor = db.groups.find({
        "recurrence.enabled": True,
        "recurrence.next_run_at": {"$lte": _iso_utc(now)},
    }, {"_id": 0})
    fired = 0
    skipped = 0
    errors = 0
    async for src in cursor:
        rec = src.get("recurrence") or {}
        try:
            # If the lead asked us to skip when an open clone already exists,
            # honor it (prevents stacking up if they're behind on payment).
            if rec.get("skip_if_open"):
                existing = await db.groups.find_one(
                    {"recurrence_source": src["id"], "status": {"$in": ["open"]}},
                    {"_id": 0, "id": 1},
                )
                if existing:
                    logger.info("[recurring] skip %s — open clone exists", src["id"])
                    next_dt = compute_next_run(rec.get("cadence", "weekly"),
                                                int(rec.get("anchor", 0)), base=now)
                    await db.groups.update_one(
                        {"id": src["id"]},
                        {"$set": {"recurrence.next_run_at": _iso_utc(next_dt)}},
                    )
                    skipped += 1
                    continue

            new_g = await _clone_group(db, src)
            if new_g is None:
                errors += 1
                continue

            next_dt = compute_next_run(rec.get("cadence", "weekly"),
                                        int(rec.get("anchor", 0)), base=now)
            await db.groups.update_one(
                {"id": src["id"]},
                {"$set": {
                    "recurrence.last_run_at": _iso_utc(now),
                    "recurrence.last_clone_group_id": new_g["id"],
                    "recurrence.next_run_at": _iso_utc(next_dt),
                }},
            )
            fired += 1
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("[recurring] failed for %s: %s", src.get("id"), e)
            errors += 1
    return {"fired": fired, "skipped": skipped, "errors": errors}


def start_recurring_loop(db: Any, *, interval_seconds: int = 1800) -> None:
    """Fire-and-forget background loop. Runs every `interval_seconds`."""
    async def _run():
        logger.info("[recurring] background loop started (interval=%ss)", interval_seconds)
        while True:
            try:
                stats = await _tick(db)
                if stats["fired"] or stats["skipped"] or stats["errors"]:
                    logger.info("[recurring] tick %s", stats)
            except Exception as e:  # pylint: disable=broad-except
                logger.warning("[recurring] tick failed: %s", e)
            await asyncio.sleep(interval_seconds)

    asyncio.create_task(_run())
