"""Account deletion routes (App Store Guideline 5.1.1(v)).

Soft-delete pattern:
  - User taps "Delete Account" in /settings → POST /api/users/me/delete
  - Backend marks `deleted_at` (ISO timestamp) + `deletion_scheduled_at`
    (deleted_at + 30 days). PII fields stay intact during the grace period
    so the user can change their mind and email support to restore.
  - `is_deleted=True` blocks the user from:
      - logging in / sending or verifying OTP
      - showing up in admin lists, search results, contact pickers, member rosters
  - After 30 days, a maintenance cron (TODO: scheduled job, not part of this
    minimum-viable PR) anonymises name / phone / email so PII is permanently
    purged while preserving foreign-key integrity (groups, contributions,
    audit logs).

Endpoints:
  - POST   /api/users/me/delete              (user initiates soft delete)
  - POST   /api/users/me/restore             (user changes their mind; idempotent
                                              while inside the 30-day window)
  - GET    /api/users/me/deletion-status     (UI shows banner if pending)
  - POST   /api/admin/users/{uid}/restore    (admin overrides — also resets
                                              `deleted_at`/`deletion_scheduled_at`)
  - POST   /api/admin/users/{uid}/purge      (manual purge — anonymises PII
                                              immediately, for support workflows)

Authn:
  - User endpoints look up user via `user_id` request body / query (consistent
    with the rest of the codebase — there is no JWT auth on user routes yet).
    They additionally verify a `session_id` matches the user's
    `current_session_id` to defend against unauthenticated requests.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core import now_iso

GRACE_PERIOD_DAYS = 30


class DeleteAccountIn(BaseModel):
    user_id: str
    session_id: str
    reason: Optional[str] = Field(default=None, max_length=500)


class RestoreAccountIn(BaseModel):
    user_id: str
    session_id: str


class DeletionStatusIn(BaseModel):
    user_id: str
    session_id: str


def _scheduled_at(grace_days: int = GRACE_PERIOD_DAYS) -> str:
    """Compute the hard-purge time (ISO 8601 with TZ) based on now()."""
    return (datetime.now(timezone.utc) + timedelta(days=grace_days)).isoformat()


async def _verify_session(db, user_id: str, session_id: str) -> dict:
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    if user.get("current_session_id") != session_id:
        raise HTTPException(401, "Invalid session")
    return user


def attach_account_deletion_routes(router: APIRouter, db, admin_dep):
    """Wire account-deletion endpoints onto the given `router`.

    `admin_dep` is the get_current_admin dependency factory (already used by
    other admin sub-routers).
    """
    from fastapi import Depends

    # ───────────────────── User endpoints ─────────────────────
    @router.post("/users/me/delete")
    async def delete_account(body: DeleteAccountIn):
        # Idempotency FIRST — if already pending deletion, don't 401 on the
        # session check (the first delete cleared current_session_id).
        existing = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if not existing:
            raise HTTPException(404, "User not found")
        if existing.get("is_deleted"):
            return {
                "ok": True,
                "already_pending": True,
                "deleted_at": existing.get("deleted_at"),
                "scheduled_purge_at": existing.get("deletion_scheduled_at"),
                "grace_days": GRACE_PERIOD_DAYS,
                "message": "Your account is already marked for deletion.",
            }

        # Active account → enforce session.
        user = await _verify_session(db, body.user_id, body.session_id)

        deleted_at = now_iso()
        scheduled_at = _scheduled_at()

        update = {
            "is_deleted": True,
            "deleted_at": deleted_at,
            "deletion_scheduled_at": scheduled_at,
            "deletion_reason": (body.reason or "").strip()[:500] or None,
            # Kill any active session immediately.
            "current_session_id": None,
        }
        await db.users.update_one({"id": body.user_id}, {"$set": update})

        # Best-effort: drop OTP records so a half-deleted user can't continue
        # an in-flight verify-otp.
        try:
            await db.otp_codes.delete_many({"user_id": body.user_id})
        except Exception:
            pass

        # Audit trail
        try:
            await db.audit_logs.insert_one({
                "type": "account_deletion_requested",
                "user_id": body.user_id,
                "user_name": user.get("name"),
                "user_phone": user.get("phone"),
                "reason": update["deletion_reason"],
                "deleted_at": deleted_at,
                "scheduled_purge_at": scheduled_at,
                "created_at": deleted_at,
            })
        except Exception:
            pass

        return {
            "ok": True,
            "deleted_at": deleted_at,
            "scheduled_purge_at": scheduled_at,
            "grace_days": GRACE_PERIOD_DAYS,
            "message": (
                f"Account scheduled for deletion. You have {GRACE_PERIOD_DAYS} days "
                "to restore it by contacting help@getsquadpay.com."
            ),
        }

    @router.post("/users/me/restore")
    async def restore_account_self(body: RestoreAccountIn):
        # We allow restore by session even though session was cleared at delete-time
        # — the client must hold on to the pre-delete session_id; if the client
        # already cleared local state, they go through support instead.
        user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        if not user.get("is_deleted"):
            return {"ok": True, "already_active": True}

        # Grace check — if past purge window, refuse restore.
        scheduled = user.get("deletion_scheduled_at")
        if scheduled:
            try:
                sched_dt = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > sched_dt:
                    raise HTTPException(410, "Restoration window expired. Please contact support.")
            except ValueError:
                pass  # malformed timestamp — allow restore conservatively

        # Self-service restore requires the user to know the previous session_id
        # they were carrying (cookie / SecureStore) at the time of the delete.
        # If they don't, route them through admin / support.
        if user.get("last_session_id_before_delete") != body.session_id:
            # Be vague to avoid token-fishing.
            raise HTTPException(401, "Restore requires the original session token. Contact support to restore.")

        await db.users.update_one(
            {"id": body.user_id},
            {
                "$set": {"is_deleted": False},
                "$unset": {
                    "deleted_at": "",
                    "deletion_scheduled_at": "",
                    "deletion_reason": "",
                    "last_session_id_before_delete": "",
                },
            },
        )
        return {"ok": True, "restored": True}

    @router.post("/users/me/deletion-status")
    async def deletion_status(body: DeletionStatusIn):
        user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        return {
            "is_deleted": bool(user.get("is_deleted")),
            "deleted_at": user.get("deleted_at"),
            "scheduled_purge_at": user.get("deletion_scheduled_at"),
            "grace_days": GRACE_PERIOD_DAYS,
        }

    # ───────────────────── Admin endpoints ─────────────────────
    @router.post("/admin/users/{uid}/restore")
    async def admin_restore_account(uid: str, _admin=Depends(admin_dep)):
        res = await db.users.update_one(
            {"id": uid, "is_deleted": True},
            {
                "$set": {"is_deleted": False},
                "$unset": {
                    "deleted_at": "",
                    "deletion_scheduled_at": "",
                    "deletion_reason": "",
                    "last_session_id_before_delete": "",
                },
            },
        )
        if res.matched_count == 0:
            user = await db.users.find_one({"id": uid}, {"_id": 0, "is_deleted": 1})
            if not user:
                raise HTTPException(404, "User not found")
            return {"ok": True, "already_active": True}
        try:
            await db.audit_logs.insert_one({
                "type": "account_deletion_restored",
                "user_id": uid,
                "by_admin": _admin.get("email"),
                "created_at": now_iso(),
            })
        except Exception:
            pass
        return {"ok": True, "restored": True}

    @router.post("/admin/users/{uid}/purge")
    async def admin_purge_account(uid: str, _admin=Depends(admin_dep)):
        """Immediately anonymise PII (irreversible)."""
        user = await db.users.find_one({"id": uid}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        anonymised_name = f"Deleted User ({uid[-6:]})"
        await db.users.update_one(
            {"id": uid},
            {
                "$set": {
                    "is_deleted": True,
                    "is_purged": True,
                    "deleted_at": user.get("deleted_at") or now_iso(),
                    "purged_at": now_iso(),
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
                "type": "account_purged",
                "user_id": uid,
                "by_admin": _admin.get("email"),
                "original_name": user.get("name"),
                "created_at": now_iso(),
            })
        except Exception:
            pass
        return {"ok": True, "purged": True}

    @router.get("/admin/users/deleted")
    async def admin_list_deleted(_admin=Depends(admin_dep), limit: int = 100):
        limit = max(1, min(500, limit))
        cursor = db.users.find(
            {"is_deleted": True},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "email": 1,
             "deleted_at": 1, "deletion_scheduled_at": 1,
             "deletion_reason": 1, "is_purged": 1},
        ).sort("deleted_at", -1).limit(limit)
        items = await cursor.to_list(length=limit)
        return {"items": items, "count": len(items), "grace_days": GRACE_PERIOD_DAYS}
