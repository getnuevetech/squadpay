"""Background settlement cron (June 2025).

Polls for Squads in `lead_paid` state whose `lead_payout_paid_at` is older
than the admin-configured delay → flips them to `closed` ("Bill Settled").

Runs every 60s.  Idempotent — if a group is already `closed` we skip it.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from core import now_iso
from settlement_config import get_settlement_delay_minutes

logger = logging.getLogger("settlement_cron")

POLL_INTERVAL_SECONDS = 60


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # core.now_iso() produces e.g. "2026-05-13T15:00:00.000Z"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


async def _flip_overdue_groups(db) -> int:
    """Find groups in `lead_paid` past the delay and flip to `closed`.
    Returns the number flipped."""
    delay_min = await get_settlement_delay_minutes(db)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=delay_min)
    cur = db.groups.find(
        {"status": "lead_paid", "lead_payout_paid_at": {"$exists": True}},
        {"_id": 0, "id": 1, "lead_payout_paid_at": 1},
    )
    flipped = 0
    async for g in cur:
        paid_at = _parse_iso(g.get("lead_payout_paid_at"))
        if paid_at is None:
            continue
        if paid_at.tzinfo is None:
            paid_at = paid_at.replace(tzinfo=timezone.utc)
        if paid_at <= cutoff:
            res = await db.groups.update_one(
                {"id": g["id"], "status": "lead_paid"},
                {"$set": {
                    "status": "closed",
                    "bill_settled_at": now_iso(),
                    "updated_at": now_iso(),
                }},
            )
            if res.modified_count:
                flipped += 1
                logger.info("[settlement-cron] %s → closed (Bill Settled)", g["id"])
    return flipped


async def settlement_cron_loop(db) -> None:
    logger.info(
        "[settlement-cron] background loop started (interval=%ss)",
        POLL_INTERVAL_SECONDS,
    )
    while True:
        try:
            await _flip_overdue_groups(db)
        except Exception as e:
            logger.warning("[settlement-cron] tick failed: %s", e)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
