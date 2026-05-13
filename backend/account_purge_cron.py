"""30-day Hard-Purge Cron for soft-deleted accounts (P1 — June 2025).

Soft delete (DELETE /api/users/me) flags the user as ``is_deleted=true`` and
sets ``deletion_scheduled_at = deleted_at + 30 days``. After that window we
must IRREVERSIBLY anonymise PII (name / phone / email) while preserving
foreign-key integrity to historical bills, contributions, audit log entries,
etc.

This module:
  • Defines ``purge_expired_accounts(db)`` — one-shot batch that finds all
    users past their grace period and anonymises them. Mirrors the logic in
    the admin manual-purge endpoint so behaviour is identical.
  • Defines ``start_purge_loop(db, interval_seconds=21600)`` — fire-and-forget
    asyncio task that runs the batch every 6 hours.
  • Exposes an admin endpoint ``POST /api/admin/users/run-purge-cron`` for
    manual triggering / testing (super-admin only).

Idempotent: only acts on rows where ``is_purged != true``. Safe to re-run.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        # Accept Z suffix
        if isinstance(s, str) and s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s) if isinstance(s, str) else None
    except Exception:
        return None


async def _anonymise_one(db, user: Dict[str, Any]) -> None:
    """Apply the same anonymisation as the admin manual-purge endpoint."""
    uid = user["id"]
    anonymised_name = f"Deleted User ({uid[-6:]})"
    await db.users.update_one(
        {"id": uid, "is_purged": {"$ne": True}},  # idempotent — skip if already purged
        {
            "$set": {
                "is_deleted": True,
                "is_purged": True,
                "deleted_at": user.get("deleted_at") or _now_iso(),
                "purged_at": _now_iso(),
                "name": anonymised_name,
                "phone": None,
                "email": None,
                "current_session_id": None,
                "deletion_scheduled_at": None,
            },
            "$unset": {
                "deletion_reason": "",
                "last_session_id_before_delete": "",
            },
        },
    )
    try:
        await db.audit_logs.insert_one({
            "type": "account_purged_auto",
            "user_id": uid,
            "by_admin": "system:purge-cron",
            "original_name": user.get("name"),
            "created_at": _now_iso(),
        })
    except Exception:
        # Audit failure is non-fatal — the purge already happened.
        pass


async def purge_expired_accounts(db) -> Dict[str, Any]:
    """Find users past their 30-day grace and anonymise them.

    Returns a small summary dict suitable for logging or returning from the
    admin manual-trigger endpoint.
    """
    now = _now_dt()
    now_iso = _now_iso()

    # Find candidates. We MUST do the comparison in Python (not Mongo $lt)
    # because deletion_scheduled_at is stored as an ISO string, not a real
    # BSON date. Strings compare lexicographically which works for ISO 8601
    # — but we still parse defensively in case some legacy rows have an
    # unusual format.
    cursor = db.users.find(
        {
            "is_deleted": True,
            "is_purged": {"$ne": True},
            "deletion_scheduled_at": {"$ne": None, "$lte": now_iso},
        },
        {"_id": 0, "id": 1, "name": 1, "deleted_at": 1, "deletion_scheduled_at": 1},
    )
    candidates: List[Dict[str, Any]] = await cursor.to_list(length=500)

    purged = 0
    skipped = 0
    for u in candidates:
        sched = _parse_iso(u.get("deletion_scheduled_at"))
        if sched is None or sched > now:
            skipped += 1
            continue
        try:
            await _anonymise_one(db, u)
            purged += 1
        except Exception as e:
            logger.exception(f"[purge-cron] failed to purge {u['id']}: {e}")
            skipped += 1

    summary = {
        "ok": True,
        "purged": purged,
        "skipped": skipped,
        "scanned": len(candidates),
        "ran_at": now_iso,
    }
    if purged or skipped:
        logger.info(
            f"[purge-cron] purged={purged} skipped={skipped} scanned={len(candidates)}"
        )
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Background loop (fire-and-forget, started from server.py)
# ─────────────────────────────────────────────────────────────────────────────

_LOOP_STARTED = False


async def _loop(db, interval_seconds: int) -> None:
    # Small initial delay so we don't compete with startup-time seeding.
    await asyncio.sleep(30)
    while True:
        try:
            await purge_expired_accounts(db)
        except Exception as e:
            logger.exception(f"[purge-cron] loop iteration failed: {e}")
        await asyncio.sleep(interval_seconds)


def start_purge_loop(db, interval_seconds: int = 21600) -> None:
    """Start the background purge loop. Idempotent — won't double-start."""
    global _LOOP_STARTED
    if _LOOP_STARTED:
        return
    _LOOP_STARTED = True
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_loop(db, interval_seconds))
        logger.info(f"[purge-cron] background loop started (interval={interval_seconds}s)")
    except Exception as e:
        logger.exception(f"[purge-cron] failed to start loop: {e}")
        _LOOP_STARTED = False  # allow retry on next call


# ─────────────────────────────────────────────────────────────────────────────
# Admin manual-trigger endpoint
# ─────────────────────────────────────────────────────────────────────────────

def attach_purge_admin_route(router, db, admin_dep) -> None:
    from fastapi import Depends

    @router.post("/admin/users/run-purge-cron")
    async def run_purge_cron(_admin=Depends(admin_dep)):
        """Manually trigger the 30-day hard-purge run (super-admin only)."""
        return await purge_expired_accounts(db)
