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

    # ----- Auth -----
    @router.post("/auth/login", response_model=AdminAuthResponse)
    async def login(body: AdminLoginIn, request: Request):
        # Make sure the seed admin exists every time (idempotent).
        await ensure_seed_admin(db)
        admin = await db.admins.find_one({"email": body.email.lower()}, {"_id": 0})
        if not admin or not verify_password(body.password, admin.get("password_hash", "")):
            raise HTTPException(401, "Invalid email or password")
        if not admin.get("is_active", True):
            raise HTTPException(403, "Account is disabled")
        token = create_access_token(admin["id"], admin["role"])
        await db.admins.update_one(
            {"id": admin["id"]},
            {"$set": {"last_login_at": dt.datetime.now(dt.timezone.utc).isoformat()}},
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
