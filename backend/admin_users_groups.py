"""Admin endpoints for managing platform users and groups (Phase B).

Mounted onto the main admin router by admin_routes.build_admin_router().
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel

from admin import write_audit, require_role  # noqa: F401  (kept for back-compat)
from admin_modules import require_module


class BlockPayload(BaseModel):
    is_blocked: bool
    reason: Optional[str] = None


def _user_public(u: dict) -> dict:
    return {
        "id": u.get("id"),
        "name": u.get("name"),
        "phone": u.get("phone"),
        "verified": u.get("verified", False),
        "is_blocked": bool(u.get("is_blocked")),
        "blocked_reason": u.get("blocked_reason"),
        "blocked_at": u.get("blocked_at"),
        "created_at": u.get("created_at"),
        # T&C acceptance — surfaced in admin so support can confirm a user
        # has agreed to the latest terms (or hasn't, for legacy accounts).
        "terms_accepted_at": u.get("terms_accepted_at"),
    }


def _group_public(g: dict) -> dict:
    return {
        "id": g.get("id"),
        "code": g.get("code"),
        "title": g.get("title"),
        "lead_id": g.get("lead_id"),
        "status": g.get("status"),
        "is_blocked": bool(g.get("is_blocked")),
        "blocked_reason": g.get("blocked_reason"),
        "blocked_at": g.get("blocked_at"),
        "total_amount": g.get("total_amount"),
        "tax": g.get("tax", 0),
        "tip": g.get("tip", 0),
        "members_count": len(g.get("members", []) or []),
        "items_count": len(g.get("items", []) or []),
        "contributions_total": round(sum(float(c.get("amount") or 0) for c in (g.get("contributions") or [])), 2),
        "created_at": g.get("created_at"),
    }


def attach_users_and_groups_routes(router: APIRouter, db, attach_admin):
    """attach_admin is the dependency that sets request.state.admin and returns it."""

    # =========================================================
    # USERS
    # =========================================================

    @router.get("/users")
    async def list_users(
        request: Request,
        q: Optional[str] = Query(None, description="Search by name or phone (substring, case-insensitive)"),
        verified: Optional[bool] = None,
        blocked: Optional[bool] = None,
        limit: int = Query(50, ge=1, le=500),
        skip: int = Query(0, ge=0),
        admin=Depends(attach_admin),
    ):
        mongo_q: dict = {}
        if q:
            # Strip + and spaces; do case-insensitive regex on either name or phone
            esc = q.strip().replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace(".", "\\.").replace("+", "\\+")
            mongo_q["$or"] = [
                {"name": {"$regex": esc, "$options": "i"}},
                {"phone": {"$regex": esc, "$options": "i"}},
            ]
        if verified is not None:
            mongo_q["verified"] = verified
        if blocked is not None:
            mongo_q["is_blocked"] = blocked

        total = await db.users.count_documents(mongo_q)
        cursor = db.users.find(mongo_q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        users = await cursor.to_list(length=None)

        # Attach group counts (lead + member) per user — small N so cheap loop
        # Build aggregate counts in one pass over groups for performance
        all_groups = await db.groups.find(
            {}, {"_id": 0, "id": 1, "lead_id": 1, "members": 1, "status": 1, "total_amount": 1}
        ).to_list(length=None)
        led: dict = {}
        joined: dict = {}
        led_billed: dict = {}
        for g in all_groups:
            lid = g.get("lead_id")
            if lid:
                led[lid] = led.get(lid, 0) + 1
                led_billed[lid] = led_billed.get(lid, 0.0) + float(g.get("total_amount") or 0)
            for m in (g.get("members") or []):
                uid = m.get("user_id")
                if uid:
                    joined[uid] = joined.get(uid, 0) + 1

        items = []
        for u in users:
            row = _user_public(u)
            uid = u.get("id")
            row["groups_led"] = led.get(uid, 0)
            row["groups_joined"] = joined.get(uid, 0)
            row["total_billed_as_lead"] = round(led_billed.get(uid, 0.0), 2)
            items.append(row)

        return {"items": items, "total": total, "skip": skip, "limit": limit}

    @router.get("/users/{user_id}")
    async def get_user_detail(user_id: str, admin=Depends(attach_admin)):
        u = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not u:
            raise HTTPException(404, "User not found")
        # Find groups where user is lead OR member
        led_groups = await db.groups.find(
            {"lead_id": user_id}, {"_id": 0}
        ).sort("created_at", -1).to_list(length=None)
        joined_groups = await db.groups.find(
            {"members.user_id": user_id, "lead_id": {"$ne": user_id}}, {"_id": 0}
        ).sort("created_at", -1).to_list(length=None)

        return {
            **_user_public(u),
            "led_groups": [_group_public(g) for g in led_groups],
            "joined_groups": [_group_public(g) for g in joined_groups],
        }

    @router.post("/users/{user_id}/block")
    async def block_user(
        user_id: str,
        body: BlockPayload,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_module("users")),
    ):
        u = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not u:
            raise HTTPException(404, "User not found")
        import datetime as dt
        update = {
            "is_blocked": bool(body.is_blocked),
            "blocked_reason": body.reason if body.is_blocked else None,
            "blocked_at": dt.datetime.now(dt.timezone.utc).isoformat() if body.is_blocked else None,
            "blocked_by": admin["email"] if body.is_blocked else None,
        }
        await db.users.update_one({"id": user_id}, {"$set": update})
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.block_user" if body.is_blocked else "admin.unblock_user",
            target_type="user",
            target_id=user_id,
            payload={"reason": body.reason, "phone": u.get("phone"), "name": u.get("name")},
            request=request,
        )
        u2 = await db.users.find_one({"id": user_id}, {"_id": 0})
        return _user_public(u2)

    # =========================================================
    # GROUPS
    # =========================================================

    @router.get("/groups")
    async def list_groups(
        request: Request,
        q: Optional[str] = Query(None, description="Search by title or code"),
        status: Optional[str] = Query(None, description="open | paid | closed"),
        blocked: Optional[bool] = None,
        lead_id: Optional[str] = None,
        limit: int = Query(50, ge=1, le=500),
        skip: int = Query(0, ge=0),
        admin=Depends(attach_admin),
    ):
        mongo_q: dict = {}
        if q:
            esc = q.strip().replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace(".", "\\.")
            mongo_q["$or"] = [
                {"title": {"$regex": esc, "$options": "i"}},
                {"code": {"$regex": esc, "$options": "i"}},
            ]
        if status:
            mongo_q["status"] = status
        if blocked is not None:
            mongo_q["is_blocked"] = blocked
        if lead_id:
            mongo_q["lead_id"] = lead_id

        total = await db.groups.count_documents(mongo_q)
        cursor = db.groups.find(mongo_q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        groups = await cursor.to_list(length=None)

        # Resolve lead names
        lead_ids = list({g.get("lead_id") for g in groups if g.get("lead_id")})
        leads = await db.users.find({"id": {"$in": lead_ids}}, {"_id": 0, "id": 1, "name": 1, "phone": 1}).to_list(length=None)
        lead_map = {u["id"]: u for u in leads}

        items = []
        for g in groups:
            row = _group_public(g)
            lead = lead_map.get(g.get("lead_id"), {})
            row["lead_name"] = lead.get("name")
            row["lead_phone"] = lead.get("phone")
            items.append(row)
        return {"items": items, "total": total, "skip": skip, "limit": limit}

    @router.get("/groups/{group_id}")
    async def get_group_detail(group_id: str, admin=Depends(attach_admin)):
        g = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not g:
            raise HTTPException(404, "Group not found")
        member_ids = [m["user_id"] for m in (g.get("members") or [])]
        users = await db.users.find({"id": {"$in": member_ids}}, {"_id": 0}).to_list(length=None)
        user_map = {u["id"]: u for u in users}
        members_full = []
        for m in (g.get("members") or []):
            u = user_map.get(m["user_id"], {})
            members_full.append({
                "user_id": m["user_id"],
                "role": m.get("role"),
                "joined_at": m.get("joined_at"),
                "name": u.get("name"),
                "phone": u.get("phone"),
                "verified": u.get("verified", False),
                "is_blocked": bool(u.get("is_blocked")),
            })
        lead = user_map.get(g.get("lead_id"), {})
        return {
            **_group_public(g),
            "lead_name": lead.get("name"),
            "lead_phone": lead.get("phone"),
            "items": g.get("items", []),
            "assignments": g.get("assignments", []),
            "members": members_full,
            "contributions": g.get("contributions", []),
            "repayments": g.get("repayments", []),
            "split_mode": g.get("split_mode"),
            "funding_mode": g.get("funding_mode"),
            "lead_paid_at": g.get("lead_paid_at"),
            "lead_reassigned_at": g.get("lead_reassigned_at"),
        }

    @router.post("/groups/{group_id}/block")
    async def block_group(
        group_id: str,
        body: BlockPayload,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_module("squads")),
    ):
        g = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not g:
            raise HTTPException(404, "Group not found")
        import datetime as dt
        update = {
            "is_blocked": bool(body.is_blocked),
            "blocked_reason": body.reason if body.is_blocked else None,
            "blocked_at": dt.datetime.now(dt.timezone.utc).isoformat() if body.is_blocked else None,
            "blocked_by": admin["email"] if body.is_blocked else None,
        }
        await db.groups.update_one({"id": group_id}, {"$set": update})
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.block_group" if body.is_blocked else "admin.unblock_group",
            target_type="group",
            target_id=group_id,
            payload={"reason": body.reason, "title": g.get("title"), "code": g.get("code")},
            request=request,
        )
        g2 = await db.groups.find_one({"id": group_id}, {"_id": 0})
        return _group_public(g2)
