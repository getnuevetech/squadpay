"""Module Registry + Role-Based Access Control (June 2025 — v2).

Replaces the v1 design (hardcoded roles + per-admin module overrides) with a
proper **role-centric** model:

  ┌─────────────────────────────────────────────────────────────────────┐
  │  db.roles                                                           │
  │    { id, slug, name, description, modules: [keys], is_system, ... } │
  │                                                                     │
  │  db.admins[].role  →  references a role slug from db.roles          │
  └─────────────────────────────────────────────────────────────────────┘

When an admin signs in, we look up their role slug in db.roles and use that
role's `modules` list to gate access.

Three SYSTEM roles are seeded at startup:
  • super_admin — every module, IMMUTABLE (name & modules & deletion locked)
  • manager     — sensible defaults (editable)
  • support     — minimal defaults (editable)

Super-admins can:
  • Create new custom roles via /admin/access/roles
  • Edit any role (modules + name + description) except super_admin
  • Delete a custom role (only if no admins are assigned to it)
  • Reassign admins between roles via the existing admin user management UI

Per-admin module overrides from v1 are GONE — purely role-driven now. The
field is no longer read; if it lingers on old admin docs it's silently ignored.
"""
from typing import Optional, Dict, List, Set
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
import re

# -----------------------------------------------------------------------------
# Static module registry
# -----------------------------------------------------------------------------
# `default_roles` here ONLY drives the FIRST-TIME seed of the system roles.
# Once roles are stored in db.roles, this list is irrelevant for access checks.

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
    {"key": "access",          "label": "Access Role Management", "group": "System", "path": "/admin/access",
     "default_roles": ["super_admin"], "sensitive": True},
    {"key": "capabilities",    "label": "Capabilities",       "group": "System",     "path": "/admin/capabilities",
     "default_roles": ["super_admin"], "sensitive": True},
]

VALID_KEYS: Set[str] = {m["key"] for m in MODULES}
GROUP_ORDER = ["Overview", "Operations", "Marketing", "Finance", "System"]
SYSTEM_SUPER_ADMIN_SLUG = "super_admin"
SYSTEM_ROLE_SLUGS = {SYSTEM_SUPER_ADMIN_SLUG, "manager", "support"}

# -----------------------------------------------------------------------------
# In-memory roles cache (slug → set of module keys)
# -----------------------------------------------------------------------------
# Refreshed on every CRUD mutation of db.roles. Sync access from request paths.
_ROLES_CACHE: Dict[str, Set[str]] = {}
# Companion metadata cache for /admin/me/modules — slug → role doc
_ROLE_DOCS_CACHE: Dict[str, Dict] = {}


async def load_roles_cache(db) -> None:
    """Reload _ROLES_CACHE + _ROLE_DOCS_CACHE from db.roles.

    Call this on startup AND after every role mutation.
    """
    global _ROLES_CACHE, _ROLE_DOCS_CACHE
    docs = await db.roles.find({}, {"_id": 0}).to_list(length=None)
    _ROLES_CACHE = {d["slug"]: set(d.get("modules") or []) for d in docs}
    _ROLE_DOCS_CACHE = {d["slug"]: d for d in docs}


async def seed_system_roles(db) -> None:
    """Create the 3 system roles if they don't already exist.

    super_admin always has all modules; manager/support are seeded with the
    MODULES.default_roles assignments and then become user-editable.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    defaults = {
        "super_admin": {
            "slug": "super_admin",
            "name": "Super Admin",
            "description": "Full, irrevocable access to every module. Cannot be edited or deleted.",
            "modules": [m["key"] for m in MODULES],
            "is_system": True,
        },
        "manager": {
            "slug": "manager",
            "name": "Manager",
            "description": "Day-to-day operations + analytics + marketing.",
            "modules": [m["key"] for m in MODULES if "manager" in m["default_roles"]],
            "is_system": True,  # seeded by system but EDITABLE (modules can be changed)
        },
        "support": {
            "slug": "support",
            "name": "Support",
            "description": "Customer-facing read access.",
            "modules": [m["key"] for m in MODULES if "support" in m["default_roles"]],
            "is_system": True,
        },
    }

    for slug, defaults_doc in defaults.items():
        existing = await db.roles.find_one({"slug": slug}, {"_id": 0})
        if not existing:
            doc = {
                "id": f"role_{slug}",
                **defaults_doc,
                "created_at": now,
                "updated_at": now,
            }
            await db.roles.insert_one(doc)
        else:
            # For super_admin: enforce that its modules list is ALWAYS the
            # complete set, even if someone hand-edited it in mongo. Manager
            # and support are user-editable so we don't reset them.
            if slug == "super_admin":
                full = [m["key"] for m in MODULES]
                if set(existing.get("modules") or []) != set(full):
                    await db.roles.update_one(
                        {"slug": slug},
                        {"$set": {"modules": full, "updated_at": now}},
                    )

    await load_roles_cache(db)


# -----------------------------------------------------------------------------
# Access-resolution helpers
# -----------------------------------------------------------------------------

def admin_has_module(admin: Dict, module_key: str) -> bool:
    """Returns True iff the given admin doc has access to `module_key`.

    Resolution:
      • super_admin → always True (defensive — never gets locked out).
      • Otherwise → look up admin.role in _ROLES_CACHE; True iff module_key
        is in that role's module set.
      • If the role isn't in the cache (e.g. stale role slug), fall back to
        MODULES.default_roles so we don't accidentally lock everyone out.
    """
    if not admin:
        return False
    role = (admin.get("role") or "").lower()
    if role == SYSTEM_SUPER_ADMIN_SLUG:
        return True

    if role in _ROLES_CACHE:
        return module_key in _ROLES_CACHE[role]

    # Fallback only if cache is empty (e.g. before startup seed) — read the
    # static defaults list.
    mod = next((m for m in MODULES if m["key"] == module_key), None)
    if not mod:
        return False
    return role in (mod.get("default_roles") or [])


def admin_accessible_modules(admin: Dict) -> List[Dict]:
    """Filtered list of MODULES the given admin can see, in registry order."""
    return [m for m in MODULES if admin_has_module(admin, m["key"])]


# -----------------------------------------------------------------------------
# FastAPI dependency
# -----------------------------------------------------------------------------

def require_module(module_key: str):
    """FastAPI dependency that asserts the caller has access to the given module."""
    if module_key not in VALID_KEYS:
        raise ValueError(f"unknown module_key: {module_key}")

    def _check(request: Request):
        admin = getattr(request.state, "admin", None)
        if not admin:
            raise HTTPException(401, "Admin auth required")
        if not admin_has_module(admin, module_key):
            raise HTTPException(
                403,
                f"Your role does not have access to the '{module_key}' module. "
                "Ask a super_admin to grant it via Access Role Management.",
            )
        return admin

    return _check


# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _to_slug(name: str) -> str:
    s = _SLUG_RE.sub("_", (name or "").strip().lower()).strip("_")
    return s[:40] or "role"


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    description: Optional[str] = Field(default=None, max_length=300)
    modules: List[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=60)
    description: Optional[str] = Field(default=None, max_length=300)
    modules: Optional[List[str]] = None


# -----------------------------------------------------------------------------
# Router factory
# -----------------------------------------------------------------------------

def attach_module_routes(router: APIRouter, db, get_current_admin):
    """Mounts module-registry + role-CRUD endpoints onto `router`.

    `router` must already be prefixed with /api (the server-wide api_router).
    """
    from fastapi import Depends as _D

    # -- For the current admin's sidebar
    @router.get("/admin/me/modules")
    async def my_modules(admin=_D(get_current_admin)):
        role_slug = (admin.get("role") or "").lower()
        role_doc = _ROLE_DOCS_CACHE.get(role_slug)
        return {
            "role": role_slug,
            "role_name": (role_doc or {}).get("name") or role_slug,
            "is_super_admin": role_slug == SYSTEM_SUPER_ADMIN_SLUG,
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

    # Super-admin gate
    def _require_super(admin=_D(get_current_admin)):
        if (admin.get("role") or "").lower() != SYSTEM_SUPER_ADMIN_SLUG:
            raise HTTPException(403, "Only super_admin can manage access roles.")
        return admin

    # -- Module registry (for the role editor's checklist)
    @router.get("/admin/access/registry")
    async def access_registry(_=_D(_require_super)):
        return {
            "modules": [
                {
                    "key": m["key"], "label": m["label"], "group": m["group"],
                    "path": m["path"], "sensitive": bool(m.get("sensitive")),
                } for m in MODULES
            ],
            "group_order": GROUP_ORDER,
        }

    # ───────────────────────── Role CRUD ─────────────────────────

    async def _count_admins_in_role(slug: str) -> int:
        return await db.admins.count_documents({"role": slug})

    async def _annotate(role: Dict) -> Dict:
        return {**role, "assigned_admin_count": await _count_admins_in_role(role["slug"])}

    @router.get("/admin/access/roles")
    async def list_roles(_=_D(_require_super)):
        cursor = db.roles.find({}, {"_id": 0}).sort([("is_system", -1), ("name", 1)])
        docs = await cursor.to_list(length=200)
        items = [await _annotate(r) for r in docs]
        return {"items": items, "count": len(items)}

    @router.post("/admin/access/roles", status_code=201)
    async def create_role(body: RoleCreate, actor=_D(_require_super)):
        from datetime import datetime, timezone
        slug = _to_slug(body.name)
        if not slug:
            raise HTTPException(400, "Invalid role name")
        # Disallow reusing a system slug.
        if slug == SYSTEM_SUPER_ADMIN_SLUG:
            raise HTTPException(400, "That slug is reserved.")
        # Unique-by-slug
        if await db.roles.find_one({"slug": slug}, {"_id": 0, "id": 1}):
            raise HTTPException(409, f"A role with slug '{slug}' already exists.")
        # Validate modules
        bad = [k for k in body.modules if k not in VALID_KEYS]
        if bad:
            raise HTTPException(400, f"Unknown module key(s): {','.join(bad)}")

        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "id": f"role_{slug}",
            "slug": slug,
            "name": body.name.strip(),
            "description": (body.description or "").strip() or None,
            "modules": list(dict.fromkeys(body.modules)),  # dedupe, preserve order
            "is_system": False,
            "created_at": now,
            "created_by": actor.get("email"),
            "updated_at": now,
        }
        await db.roles.insert_one(doc)
        # Motor's insert_one mutates `doc` to add `_id`; strip it before any
        # JSON serialization downstream (FastAPI can't encode ObjectId).
        doc.pop("_id", None)
        await load_roles_cache(db)
        try:
            from admin import write_audit
            await write_audit(
                db, admin_id=actor["id"], admin_email=actor["email"],
                action="admin.role_created", target_type="role", target_id=doc["id"],
                payload={"slug": slug, "modules": doc["modules"]},
            )
        except Exception:
            pass
        return await _annotate(doc)

    @router.put("/admin/access/roles/{role_id}")
    async def update_role(role_id: str, body: RoleUpdate, actor=_D(_require_super)):
        from datetime import datetime, timezone
        role = await db.roles.find_one({"id": role_id}, {"_id": 0})
        if not role:
            raise HTTPException(404, "Role not found")

        # super_admin is fully immutable.
        if role["slug"] == SYSTEM_SUPER_ADMIN_SLUG:
            raise HTTPException(400, "The super_admin role is immutable.")

        update: Dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if body.name is not None:
            update["name"] = body.name.strip()
        if body.description is not None:
            update["description"] = body.description.strip() or None
        if body.modules is not None:
            bad = [k for k in body.modules if k not in VALID_KEYS]
            if bad:
                raise HTTPException(400, f"Unknown module key(s): {','.join(bad)}")
            update["modules"] = list(dict.fromkeys(body.modules))

        if len(update) == 1:  # only updated_at
            return await _annotate(role)

        await db.roles.update_one({"id": role_id}, {"$set": update})
        await load_roles_cache(db)
        try:
            from admin import write_audit
            await write_audit(
                db, admin_id=actor["id"], admin_email=actor["email"],
                action="admin.role_updated", target_type="role", target_id=role_id,
                payload={"changes": list(update.keys())},
            )
        except Exception:
            pass
        merged = {**role, **update}
        return await _annotate(merged)

    @router.delete("/admin/access/roles/{role_id}")
    async def delete_role(role_id: str, actor=_D(_require_super)):
        role = await db.roles.find_one({"id": role_id}, {"_id": 0})
        if not role:
            raise HTTPException(404, "Role not found")
        if role.get("is_system"):
            raise HTTPException(400, "System roles cannot be deleted.")
        count = await _count_admins_in_role(role["slug"])
        if count > 0:
            raise HTTPException(
                400,
                f"Cannot delete role — {count} admin user(s) are assigned to it. "
                "Reassign them to another role first.",
            )
        await db.roles.delete_one({"id": role_id})
        await load_roles_cache(db)
        try:
            from admin import write_audit
            await write_audit(
                db, admin_id=actor["id"], admin_email=actor["email"],
                action="admin.role_deleted", target_type="role", target_id=role_id,
                payload={"slug": role["slug"]},
            )
        except Exception:
            pass
        return {"ok": True, "deleted": role_id}

    # ───────────────────────── Helpers for admin-user form ─────────────────────────

    @router.get("/admin/access/roles/lookup")
    async def role_lookup(_=_D(get_current_admin)):
        """Lightweight role list for populating the role dropdown on the
        Admin Users page. Available to ANY admin (not just super_admin) so
        the Admin Users page can show what role each row holds; the actual
        edit form server-side still requires super_admin (existing `admins`
        module gate).
        """
        cursor = db.roles.find({}, {"_id": 0, "id": 1, "slug": 1, "name": 1, "description": 1, "is_system": 1})
        items = await cursor.to_list(length=200)
        items.sort(key=lambda r: (not r.get("is_system"), r.get("name", "")))
        return {"items": items}


# Helper exported for the admin-creation route to validate role slugs.
def role_slug_exists(slug: str) -> bool:
    """Synchronous check against the in-memory cache."""
    return slug in _ROLES_CACHE or slug == SYSTEM_SUPER_ADMIN_SLUG
