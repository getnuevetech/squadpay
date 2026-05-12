"""Module Registry + RBAC layer (June 2025).

Layered on TOP of the existing `Role = super_admin | manager | support` system
in `/app/backend/admin.py`. Doesn't replace it — extends it.

Why a Module Registry?
======================
The admin panel has 19+ distinct modules (Dashboard, Users, Squads, Bulk SMS,
Credit Rules, Platform Fees, Reconciliations, …). Today each route hard-codes
`require_role("super_admin", ...)`. As we scale, we need:

  • A single source of truth — one place that knows about every module.
  • Per-admin overrides — sometimes you want to give a "support" agent access
    to ONE high-privilege module (e.g. Master Account) without promoting them
    to manager.
  • Frontend gating — the sidebar must hide entries the admin can't access,
    and a non-permitted user opening a deep link must see a friendly 403.

Data model
==========
Static (this file):
    MODULES = [{key, label, group, path, default_roles, sensitive?}, ...]

Per admin (already stored in db.admins[]):
    role                   ← unchanged (super_admin | manager | support)
    module_overrides       ← NEW: {[module_key]: "grant" | "deny"}
                             super_admin always has full access — overrides are
                             ignored for them.

Resolution:
    super_admin           → access to ALL modules.
    others                → role in module.default_roles, then per-admin
                            override flips it.

API surface (mounted under /api by the caller):
    GET    /admin/me/modules                 — for the current admin's sidebar
    GET    /admin/access/registry            — full registry (super_admin only)
    GET    /admin/access/admins              — admins + overrides (super_admin)
    PUT    /admin/access/admins/{admin_id}   — set role + overrides (super_admin)

Usage in a sensitive new route:
    @router.get("/foo")
    async def foo(_=Depends(require_module(db, "platform_fees"))):
        ...
"""
from typing import Optional, Dict, List, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# Static module registry
# -----------------------------------------------------------------------------
# `default_roles`: which legacy roles get access by default.
# `sensitive`: optional flag — modules marked sensitive surface a warning in
# the Access Control UI when granting them to a low-privilege user.

MODULES: List[Dict] = [
    # ----- Overview
    {"key": "dashboard",       "label": "Dashboard",          "group": "Overview",   "path": "/admin/dashboard",
     "default_roles": ["super_admin", "manager", "support"]},
    {"key": "analytics",       "label": "Analytics",          "group": "Overview",   "path": "/admin/analytics",
     "default_roles": ["super_admin", "manager"]},

    # ----- Operations
    {"key": "users",           "label": "Users",              "group": "Operations", "path": "/admin/users",
     "default_roles": ["super_admin", "manager", "support"]},
    {"key": "squads",          "label": "Squads",             "group": "Operations", "path": "/admin/groups",
     "default_roles": ["super_admin", "manager", "support"]},
    {"key": "customer_service","label": "Customer Service",   "group": "Operations", "path": "/admin/customer-service",
     "default_roles": ["super_admin", "manager", "support"]},

    # ----- Marketing
    {"key": "notifications",   "label": "Notifications",      "group": "Marketing",  "path": "/admin/notifications",
     "default_roles": ["super_admin", "manager"]},
    {"key": "bulk_sms",        "label": "Bulk SMS",           "group": "Marketing",  "path": "/admin/bulk-sms",
     "default_roles": ["super_admin", "manager"]},
    {"key": "credit_rules",    "label": "Credit Rules",       "group": "Marketing",  "path": "/admin/credit-rules",
     "default_roles": ["super_admin", "manager"]},
    {"key": "referrals",       "label": "Referrals",          "group": "Marketing",  "path": "/admin/referrals",
     "default_roles": ["super_admin", "manager"]},

    # ----- Finance (sensitive)
    {"key": "platform_fees",   "label": "Platform Fees",      "group": "Finance",    "path": "/admin/platform-fees",
     "default_roles": ["super_admin"], "sensitive": True},
    {"key": "income_fees",     "label": "Income & Fees",      "group": "Finance",    "path": "/admin/income-fees",
     "default_roles": ["super_admin"], "sensitive": True},
    {"key": "master_account",  "label": "Master Account",     "group": "Finance",    "path": "/admin/master-account",
     "default_roles": ["super_admin"], "sensitive": True},
    {"key": "reconciliations", "label": "Reconciliations",    "group": "Finance",    "path": "/admin/reconciliations",
     "default_roles": ["super_admin", "manager"]},

    # ----- System (super_admin)
    {"key": "integrations",    "label": "Integrations",       "group": "System",     "path": "/admin/integrations",
     "default_roles": ["super_admin"], "sensitive": True},
    {"key": "security",        "label": "Security",           "group": "System",     "path": "/admin/security",
     "default_roles": ["super_admin"], "sensitive": True},
    {"key": "audit",           "label": "Audit Log",          "group": "System",     "path": "/admin/audit",
     "default_roles": ["super_admin", "manager"]},
    {"key": "legal_pages",     "label": "Legal Pages",        "group": "System",     "path": "/admin/legal-pages",
     "default_roles": ["super_admin"]},
    {"key": "admins",          "label": "Admin Users",        "group": "System",     "path": "/admin/admins",
     "default_roles": ["super_admin"], "sensitive": True},
    {"key": "access",          "label": "Access Control",     "group": "System",     "path": "/admin/access",
     "default_roles": ["super_admin"], "sensitive": True},
]

VALID_KEYS = {m["key"] for m in MODULES}
GROUP_ORDER = ["Overview", "Operations", "Marketing", "Finance", "System"]


# -----------------------------------------------------------------------------
# Access-resolution helper
# -----------------------------------------------------------------------------

def admin_has_module(admin: Dict, module_key: str) -> bool:
    """Returns True iff the given admin doc has access to `module_key`.

    Resolution rules:
      • super_admin → always True.
      • Otherwise:  start with (role in module.default_roles), then flip with
                    admin.module_overrides[module_key] if present.
                    "grant" → True, "deny" → False.
    """
    if not admin:
        return False
    role = (admin.get("role") or "").lower()
    if role == "super_admin":
        return True

    mod = next((m for m in MODULES if m["key"] == module_key), None)
    if not mod:
        # Unknown module key → deny by default (defensive).
        return False

    base = role in mod["default_roles"]
    overrides = admin.get("module_overrides") or {}
    flip = overrides.get(module_key)
    if flip == "grant":
        return True
    if flip == "deny":
        return False
    return base


def admin_accessible_modules(admin: Dict) -> List[Dict]:
    """Filtered list of MODULES the given admin can see, in registry order."""
    return [m for m in MODULES if admin_has_module(admin, m["key"])]


# -----------------------------------------------------------------------------
# FastAPI dependency
# -----------------------------------------------------------------------------

def require_module(module_key: str):
    """FastAPI dependency that asserts the caller has access to the given module.

    Reads the admin from `request.state.admin`, which is populated by:
      • `_attach_admin` inside `build_admin_router` for legacy admin routes
      • `get_current_admin_factory_sync(db)` for standalone-router routes
        (its returned `_runtime` writes `request.state.admin = admin` itself)

    Usage:
        @router.get("/foo")
        async def foo(
            _admin=Depends(require_admin),        # populates request.state.admin
            _check=Depends(require_module("k")),  # asserts module access
        ):
            ...
    """
    if module_key not in VALID_KEYS:
        raise ValueError(f"unknown module_key: {module_key}")

    from fastapi import Request

    def _check(request: Request):
        admin = getattr(request.state, "admin", None)
        if not admin:
            raise HTTPException(401, "Admin auth required")
        if not admin_has_module(admin, module_key):
            raise HTTPException(
                403,
                f"Your role does not have access to the '{module_key}' module. "
                "Ask a super_admin to grant it via Access Control.",
            )
        return admin

    return _check


# Legacy factory kept for compatibility — internally delegates to require_module.
def require_module_legacy(get_current_admin, module_key: str):
    """Deprecated. Use require_module(module_key) directly. Kept for callers
    that explicitly wire get_current_admin into the dependency tree."""
    from fastapi import Depends as _D
    if module_key not in VALID_KEYS:
        raise ValueError(f"unknown module_key: {module_key}")

    async def _dep(admin=_D(get_current_admin)):
        if not admin_has_module(admin, module_key):
            raise HTTPException(
                403,
                f"Your role does not have access to the '{module_key}' module.",
            )
        return admin

    return _dep


# -----------------------------------------------------------------------------
# Pydantic models for the management API
# -----------------------------------------------------------------------------

class AdminAccessUpdate(BaseModel):
    role: Optional[Literal["super_admin", "manager", "support"]] = None
    module_overrides: Optional[Dict[str, Literal["grant", "deny"]]] = Field(
        default=None,
        description="Map of module_key → 'grant'|'deny'. Pass {} to clear all overrides.",
    )


# -----------------------------------------------------------------------------
# Router factory
# -----------------------------------------------------------------------------

def attach_module_routes(router: APIRouter, db, get_current_admin):
    """Mounts the module-registry endpoints onto `router`.

    `router` must already be prefixed with /api (the server-wide api_router).
    """
    from fastapi import Depends as _D

    # -- For the current admin's sidebar
    @router.get("/admin/me/modules")
    async def my_modules(admin=_D(get_current_admin)):
        return {
            "role": admin.get("role"),
            "is_super_admin": (admin.get("role") or "").lower() == "super_admin",
            "modules": [
                {
                    "key": m["key"],
                    "label": m["label"],
                    "group": m["group"],
                    "path": m["path"],
                    "sensitive": bool(m.get("sensitive")),
                }
                for m in admin_accessible_modules(admin)
            ],
            "group_order": GROUP_ORDER,
        }

    # -- Super-admin: full registry
    def _require_super(admin=_D(get_current_admin)):
        if (admin.get("role") or "").lower() != "super_admin":
            raise HTTPException(403, "Only super_admin can manage access control.")
        return admin

    @router.get("/admin/access/registry")
    async def access_registry(_=_D(_require_super)):
        return {
            "modules": [
                {
                    "key": m["key"], "label": m["label"], "group": m["group"],
                    "path": m["path"], "default_roles": m["default_roles"],
                    "sensitive": bool(m.get("sensitive")),
                } for m in MODULES
            ],
            "group_order": GROUP_ORDER,
            "available_roles": ["super_admin", "manager", "support"],
        }

    @router.get("/admin/access/admins")
    async def access_admins(_=_D(_require_super)):
        cursor = db.admins.find(
            {},
            {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1,
             "is_active": 1, "module_overrides": 1, "last_login_at": 1},
        ).sort("email", 1)
        items = await cursor.to_list(length=500)
        # Enrich each row with the resolved list of module keys they can access.
        for it in items:
            it["accessible_modules"] = [
                m["key"] for m in MODULES if admin_has_module(it, m["key"])
            ]
            it.setdefault("module_overrides", {})
        return {"items": items, "count": len(items)}

    @router.put("/admin/access/admins/{admin_id}")
    async def set_admin_access(
        admin_id: str,
        body: AdminAccessUpdate,
        actor=_D(_require_super),
    ):
        target = await db.admins.find_one({"id": admin_id}, {"_id": 0})
        if not target:
            raise HTTPException(404, "Admin not found")

        update: Dict = {}

        # ----- Role change (with last-super-admin guard)
        if body.role is not None and body.role != target.get("role"):
            if target.get("role") == "super_admin" and body.role != "super_admin":
                other_supers = await db.admins.count_documents({
                    "role": "super_admin",
                    "is_active": True,
                    "id": {"$ne": admin_id},
                })
                if other_supers == 0:
                    raise HTTPException(
                        400,
                        "Cannot demote the last active super_admin. Create another "
                        "super_admin first, then retry.",
                    )
            if admin_id == actor["id"] and body.role != "super_admin":
                raise HTTPException(400, "You cannot demote your own super_admin account.")
            update["role"] = body.role

        # ----- Overrides
        if body.module_overrides is not None:
            cleaned: Dict[str, str] = {}
            for k, v in body.module_overrides.items():
                if k not in VALID_KEYS:
                    raise HTTPException(400, f"Unknown module key: {k}")
                if v not in ("grant", "deny"):
                    raise HTTPException(400, f"Invalid value for {k}: {v}")
                cleaned[k] = v
            update["module_overrides"] = cleaned

        if not update:
            return {"ok": True, "unchanged": True, "admin_id": admin_id}

        await db.admins.update_one({"id": admin_id}, {"$set": update})

        # Audit-log it (best-effort).
        try:
            from admin import write_audit
            await write_audit(
                db,
                actor=actor,
                action="admin.access.updated",
                target_type="admin",
                target_id=admin_id,
                payload={"changes": list(update.keys())},
                destructive=False,
            )
        except Exception:
            pass

        updated = await db.admins.find_one({"id": admin_id}, {"_id": 0})
        updated["accessible_modules"] = [
            m["key"] for m in MODULES if admin_has_module(updated, m["key"])
        ]
        updated.setdefault("module_overrides", {})
        return {"ok": True, "admin": updated}
