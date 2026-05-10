"""Admin API router — Phase A (auth, metrics, audit log, admin management)."""
import datetime as dt
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, EmailStr

from admin import (
    AdminLoginIn,
    AdminCreateIn,
    AdminOut,
    AdminAuthResponse,
    create_access_token,
    hash_password,
    verify_password,
    get_current_admin_factory,
    require_role,
    write_audit,
    ensure_seed_admin,
)


def _strip(admin: dict) -> dict:
    """Sanitize an admin doc for serialization (no password_hash)."""
    out = {k: v for k, v in admin.items() if k != "password_hash"}
    return out


def build_admin_router(db):
    router = APIRouter(prefix="/admin", tags=["admin"])
    get_current_admin = Depends(get_current_admin_factory_sync(db))

    async def _attach_admin(request: Request, admin=get_current_admin):
        request.state.admin = admin
        return admin

    # Phase B: users + groups admin routes (registered at end of factory)
    from admin_users_groups import attach_users_and_groups_routes  # noqa: F401
    # Phase C1: referrals admin routes
    from admin_referrals import attach_referrals_routes  # noqa: F401
    # Phase C2: credits + discounts admin routes
    from admin_credits import attach_credits_routes  # noqa: F401
    # Phase D: integrations admin routes
    from admin_integrations import attach_integrations_routes  # noqa: F401

    # ----- Auth -----
    LOGIN_ATTEMPT_LIMIT = 3
    LOGIN_LOCK_MIN = 15

    # Rate-limit the login endpoint to slow brute-force attempts.
    # The DB-level lockout (3 attempts → 15 min) is the primary defense, but a
    # network-level throttle blocks distributed attempts before they hit Mongo.
    try:
        from server import limiter as _limiter
    except Exception:
        _limiter = None

    def _maybe_limit(spec: str):
        """Decorator that applies the slowapi rate limit only when available."""
        def deco(fn):
            return _limiter.limit(spec)(fn) if _limiter else fn
        return deco

    @router.post("/auth/login", response_model=AdminAuthResponse)
    @_maybe_limit("10/minute")
    async def login(request: Request, body: AdminLoginIn):
        # Make sure the seed admin exists every time (idempotent).
        await ensure_seed_admin(db)
        admin = await db.admins.find_one({"email": body.email.lower()}, {"_id": 0})
        if not admin:
            raise HTTPException(401, "Invalid email or password")

        now = dt.datetime.now(dt.timezone.utc)

        # ── Hard block: previously-flagged force-reset state.
        if admin.get("force_password_reset"):
            raise HTTPException(
                status_code=423,
                detail={
                    "code": "password_reset_required",
                    "message": (
                        "Your account is locked due to repeated failed sign-ins. "
                        "Please reset your password to continue."
                    ),
                },
            )

        # ── Soft block: temporary lockout window not yet expired.
        locked_until_iso = admin.get("locked_until")
        if locked_until_iso:
            try:
                locked_until = dt.datetime.fromisoformat(locked_until_iso)
            except Exception:
                locked_until = None
            if locked_until and locked_until > now:
                remaining = max(0, int((locked_until - now).total_seconds()))
                raise HTTPException(
                    status_code=423,
                    detail={
                        "code": "locked",
                        "message": f"Too many failed sign-ins. Try again in {(remaining + 59) // 60} minute(s).",
                        "retry_after_seconds": remaining,
                    },
                )

        # ── Verify password.
        if not verify_password(body.password, admin.get("password_hash", "")):
            failed = int(admin.get("failed_logins", 0)) + 1
            lock_round = int(admin.get("lock_round", 0))
            updates: dict = {"failed_logins": failed}

            # Hit the per-round threshold? Apply lock or escalate to forced reset.
            if failed >= LOGIN_ATTEMPT_LIMIT:
                if lock_round == 0:
                    # First lockout: 15-min cool-off.
                    lock_until = (now + dt.timedelta(minutes=LOGIN_LOCK_MIN)).isoformat()
                    updates.update({
                        "locked_until": lock_until,
                        "lock_round": 1,
                        "failed_logins": 0,  # reset counter for next round
                    })
                    user_msg = (
                        f"Account locked for {LOGIN_LOCK_MIN} minutes after "
                        f"{LOGIN_ATTEMPT_LIMIT} failed sign-ins."
                    )
                else:
                    # Already had one lockout round — escalate to forced password reset.
                    updates.update({
                        "force_password_reset": True,
                        "locked_until": None,
                        "failed_logins": 0,
                    })
                    user_msg = (
                        "Too many failed sign-ins. Your account is locked — "
                        "please reset your password to continue."
                    )
                await db.admins.update_one({"id": admin["id"]}, {"$set": updates})
                await write_audit(
                    db, admin_id=admin["id"], admin_email=admin["email"],
                    action="admin.login_locked",
                    payload={"lock_round": updates.get("lock_round", lock_round),
                             "force_reset": bool(updates.get("force_password_reset"))},
                    request=request,
                )
                raise HTTPException(
                    status_code=423,
                    detail={
                        "code": "password_reset_required" if updates.get("force_password_reset") else "locked",
                        "message": user_msg,
                        "retry_after_seconds": LOGIN_LOCK_MIN * 60 if not updates.get("force_password_reset") else None,
                    },
                )

            await db.admins.update_one({"id": admin["id"]}, {"$set": updates})
            await write_audit(
                db, admin_id=admin["id"], admin_email=admin["email"],
                action="admin.login_failed",
                payload={"attempt": failed, "limit": LOGIN_ATTEMPT_LIMIT},
                request=request,
            )
            attempts_left = LOGIN_ATTEMPT_LIMIT - failed
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "invalid_credentials",
                    "message": (
                        f"Invalid email or password. {attempts_left} attempt"
                        f"{'s' if attempts_left != 1 else ''} remaining before lock."
                    ),
                    "attempts_left": attempts_left,
                },
            )

        if not admin.get("is_active", True):
            raise HTTPException(403, "Account is disabled")

        # ── Success: reset counters and issue token.
        token = create_access_token(admin["id"], admin["role"])
        await db.admins.update_one(
            {"id": admin["id"]},
            {"$set": {
                "last_login_at": now.isoformat(),
                "failed_logins": 0,
                "locked_until": None,
                "lock_round": 0,
                "force_password_reset": False,
            }},
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.login",
            request=request,
        )
        admin_clean = _strip(admin)
        return {"token": token, "admin": admin_clean}

    @router.get("/auth/me", response_model=AdminOut)
    async def me(admin=Depends(_attach_admin)):
        return _strip(admin)

    # ---- Change password (clears must_change_default_password nudge) ----
    class ChangePasswordIn(BaseModel):
        current_password: str
        new_password: str

    @router.post("/auth/change-password")
    async def change_password(
        body: ChangePasswordIn,
        request: Request,
        admin=Depends(_attach_admin),
    ):
        # Soft password policy — keep aligned with AdminCreateIn (>=8 chars).
        if not body.new_password or len(body.new_password) < 8:
            raise HTTPException(400, "New password must be at least 8 characters")
        if body.new_password == body.current_password:
            raise HTTPException(400, "New password must differ from current password")
        if not verify_password(body.current_password, admin.get("password_hash", "")):
            raise HTTPException(401, "Current password is incorrect")
        await db.admins.update_one(
            {"id": admin["id"]},
            {"$set": {
                "password_hash": hash_password(body.new_password),
                "password_updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "must_change_default_password": False,
                "force_password_reset": False,
            }},
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.change_password",
            request=request,
        )
        return {"ok": True}

    @router.post("/auth/logout")
    async def logout(request: Request, admin=Depends(_attach_admin)):
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.logout",
            request=request,
        )
        return {"ok": True}

    # ----- Metrics dashboard -----
    @router.get("/metrics")
    async def metrics(admin=Depends(_attach_admin)):
        groups = await db.groups.find({}, {"_id": 0, "status": 1, "total_amount": 1, "contributions": 1}).to_list(length=None)
        users_count = await db.users.count_documents({})
        admins_count = await db.admins.count_documents({})
        active = sum(1 for g in groups if g.get("status") != "closed")
        settled = sum(1 for g in groups if g.get("status") == "closed")
        paid = sum(1 for g in groups if g.get("status") == "paid")
        total_processed = sum(float(g.get("total_amount") or 0) for g in groups)
        total_contributed = sum(
            sum(float(c.get("amount") or 0) for c in (g.get("contributions") or [])) for g in groups
        )
        return {
            "groups_total": len(groups),
            "groups_active": active,
            "groups_paid": paid,
            "groups_settled": settled,
            "users_total": users_count,
            "admins_total": admins_count,
            "total_billed": round(total_processed, 2),
            "total_contributed": round(total_contributed, 2),
        }

    # ----- Audit log -----
    @router.get("/audit-log")
    async def audit_log(
        request: Request,
        limit: int = Query(50, ge=1, le=500),
        skip: int = Query(0, ge=0),
        action: Optional[str] = None,
        admin_email: Optional[str] = None,
        admin=Depends(_attach_admin),
        _check=Depends(require_role("super_admin", "manager")),
    ):
        q: dict = {}
        if action:
            q["action"] = action
        if admin_email:
            q["admin_email"] = admin_email.lower()
        cursor = db.audit_log.find(q, {"_id": 0}).sort("at", -1).skip(skip).limit(limit)
        return {"items": await cursor.to_list(length=None), "skip": skip, "limit": limit}

    # ----- Admin management (super_admin only) -----
    @router.get("/admins", response_model=List[AdminOut])
    async def list_admins(
        admin=Depends(_attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        rows = await db.admins.find({}, {"_id": 0}).to_list(length=None)
        return [_strip(a) for a in rows]

    @router.post("/admins", response_model=AdminOut)
    async def create_admin(
        body: AdminCreateIn,
        request: Request,
        admin=Depends(_attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        existing = await db.admins.find_one({"email": body.email.lower()})
        if existing:
            raise HTTPException(409, "Admin with that email already exists")
        rec = {
            "id": "ad_" + uuid_short(),
            "email": body.email.lower(),
            "password_hash": hash_password(body.password),
            "name": body.name,
            "role": body.role,
            "is_active": True,
            "last_login_at": None,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        await db.admins.insert_one(rec)
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.create_admin",
            target_type="admin",
            target_id=rec["id"],
            payload={"email": rec["email"], "role": rec["role"]},
            request=request,
        )
        return _strip(rec)

    class TogglePayload(BaseModel):
        is_active: bool

    @router.patch("/admins/{admin_id}/active", response_model=AdminOut)
    async def toggle_admin(
        admin_id: str,
        body: TogglePayload,
        request: Request,
        admin=Depends(_attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        target = await db.admins.find_one({"id": admin_id}, {"_id": 0})
        if not target:
            raise HTTPException(404, "Admin not found")
        if target["id"] == admin["id"]:
            raise HTTPException(400, "Cannot toggle your own account")
        await db.admins.update_one({"id": admin_id}, {"$set": {"is_active": body.is_active}})
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.toggle_active",
            target_type="admin",
            target_id=admin_id,
            payload={"is_active": body.is_active},
            request=request,
        )
        target["is_active"] = body.is_active
        return _strip(target)

    # Mount Phase B users + groups admin routes
    attach_users_and_groups_routes(router, db, _attach_admin)
    # Mount Phase C1 referrals admin routes
    attach_referrals_routes(router, db, _attach_admin)
    # Mount Phase C2 credits + discounts admin routes
    attach_credits_routes(router, db, _attach_admin)
    # Mount Phase D integrations admin routes
    attach_integrations_routes(router, db, _attach_admin)
    # Phase G1: Reconciliation admin routes
    from admin_reconciliation import attach_reconciliation_routes
    attach_reconciliation_routes(router, db, _attach_admin)
    # Phase G2: Security/KMS admin routes
    from admin_security import attach_security_routes
    attach_security_routes(router, db, _attach_admin)
    # Phase G5: Analytics admin routes
    from admin_analytics import attach_analytics_routes
    attach_analytics_routes(router, db, _attach_admin)
    # Admin actions: push reset / push OTP / change role
    from admin_actions import attach_admin_actions_routes
    attach_admin_actions_routes(router, db, _attach_admin)

    return router


def get_current_admin_factory_sync(db):
    """Returns a FastAPI dependency that yields the current admin doc."""
    from fastapi import Depends, Request
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    from admin import decode_token

    sec = HTTPBearer(auto_error=False)

    async def _runtime(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(sec),
    ):
        token: Optional[str] = None
        if credentials and credentials.scheme.lower() == "bearer":
            token = credentials.credentials
        if not token:
            token = request.query_params.get("token")
        if not token:
            raise HTTPException(401, "Admin auth required")
        payload = decode_token(token)
        admin = await db.admins.find_one({"id": payload["sub"]}, {"_id": 0})
        if not admin or not admin.get("is_active", True):
            raise HTTPException(401, "Account inactive or not found")
        return admin

    return _runtime


def uuid_short() -> str:
    import uuid
    return uuid.uuid4().hex[:10]
