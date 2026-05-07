"""Reminder background job (Phase D).

Periodically scans open groups, finds members who haven't fully contributed yet,
and dispatches reminders at the configured offsets (in hours since group creation).
Each (group_id, user_id, offset_hour) is sent at most once. Sends via Twilio if enabled
& reminders.send_via_sms; otherwise audit-logs to console.
"""
from __future__ import annotations
import asyncio
import datetime as dt
import logging

from integrations import get_integrations_doc, send_sms_via_twilio

logger = logging.getLogger(__name__)


def _parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


async def _user_share(group: dict, user_id: str) -> float:
    """Best-effort: amount user owes. For fast/equal split, total / member_count.
    For other modes, returns total / member_count as a soft estimate."""
    members = group.get("members") or []
    n = max(1, len(members))
    return round(float(group.get("total_amount") or 0) / n, 2)


async def _member_already_paid(group: dict, user_id: str, share: float) -> bool:
    paid = 0.0
    for c in (group.get("contributions") or []):
        if c.get("user_id") == user_id:
            paid += float(c.get("amount") or 0)
    return paid + 0.01 >= share


async def run_reminder_pass(db, force: bool = False) -> dict:
    """One pass of the reminder loop. Returns counts {scanned, sent_real, logged, skipped}.

    If force=True: ignore reminders.enabled (used for admin "Run now" button).
    """
    rec = await get_integrations_doc(db)
    r = rec.get("reminders") or {}
    if not force and not r.get("enabled"):
        return {"enabled": False, "scanned": 0, "sent_real": 0, "logged": 0, "skipped": 0}

    schedule = sorted({int(h) for h in (r.get("schedule_hours") or [24, 72, 168]) if int(h) > 0})
    max_per_user = int(r.get("max_reminders_per_user") or 3)
    send_via_sms = bool(r.get("send_via_sms"))

    now = dt.datetime.now(dt.timezone.utc)
    open_groups = await db.groups.find(
        {"status": "open", "is_blocked": {"$ne": True}}, {"_id": 0}
    ).to_list(length=None)

    scanned = 0
    sent_real = 0
    logged = 0
    skipped = 0

    for g in open_groups:
        scanned += 1
        created = _parse_iso(g.get("created_at"))
        if not created:
            continue
        # naive UTC compare
        try:
            elapsed_h = (now - created.replace(tzinfo=dt.timezone.utc) if created.tzinfo is None else now - created).total_seconds() / 3600
        except Exception:
            continue

        for offset in schedule:
            if elapsed_h < offset:
                continue
            for m in (g.get("members") or []):
                uid = m.get("user_id")
                if not uid:
                    continue
                share = await _user_share(g, uid)
                if await _member_already_paid(g, uid, share):
                    continue
                # Idempotency: already sent for this (group, user, offset)?
                existing = await db.reminders.find_one(
                    {"group_id": g["id"], "user_id": uid, "offset_hour": offset},
                    {"_id": 0, "id": 1},
                )
                if existing:
                    skipped += 1
                    continue
                user = await db.users.find_one({"id": uid}, {"_id": 0})
                if not user or user.get("is_blocked"):
                    continue
                # Also enforce per-user max_per_user across this group
                count_for_user = await db.reminders.count_documents(
                    {"group_id": g["id"], "user_id": uid}
                )
                if count_for_user >= max_per_user:
                    continue
                phone = user.get("phone")
                msg = (
                    f"SquadPay: You still owe ${share:.2f} on \"{g.get('title') or 'a bill'}\""
                    f" (code {g.get('code')}). Pay your share to settle up."
                )
                sent = False
                info = "no phone"
                if send_via_sms and phone:
                    sent, info = await send_sms_via_twilio(db, phone, msg)
                else:
                    logger.info(f"[reminder-mock] -> {phone or uid}: {msg}")
                    info = "logged (sms disabled or no phone)"

                await db.reminders.insert_one({
                    "id": f"rm_{g['id'][:8]}_{uid[:8]}_{offset}",
                    "group_id": g["id"],
                    "user_id": uid,
                    "offset_hour": offset,
                    "phone": phone,
                    "amount": share,
                    "sent_real": bool(sent),
                    "info": info,
                    "at": now.isoformat(),
                })
                if sent:
                    sent_real += 1
                else:
                    logged += 1
    return {
        "enabled": True,
        "scanned": scanned,
        "sent_real": sent_real,
        "logged": logged,
        "skipped": skipped,
        "schedule_hours": schedule,
    }


_TASK: asyncio.Task | None = None


async def reminder_loop(db, interval_seconds: int = 900):
    """Run reminder_pass every interval_seconds (default 15min) in background."""
    while True:
        try:
            await run_reminder_pass(db)
        except Exception as e:
            logger.exception(f"[reminders] loop error: {e}")
        await asyncio.sleep(interval_seconds)


def start_reminder_loop(db, interval_seconds: int = 900):
    global _TASK
    if _TASK and not _TASK.done():
        return
    loop = asyncio.get_event_loop()
    _TASK = loop.create_task(reminder_loop(db, interval_seconds))
    logger.info(f"[reminders] background loop started (interval={interval_seconds}s)")
