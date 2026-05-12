"""
Admin global search (Batch June 2025).

Server-side fuzzy search across users, squads (groups), admin users, and
audit logs. Returns small unified suggestion list grouped by source so
the admin top-bar can render with category headers.

  GET /api/admin/search?q=<query>&limit=20
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException


def attach_admin_search_routes(api_router: APIRouter, db, get_current_admin):
    r = APIRouter()

    @r.get("/admin/search")
    async def search(q: str = "", limit: int = 8, admin=Depends(get_current_admin)):
        q = (q or "").strip()
        if not q or len(q) < 2:
            return {"items": []}
        limit_each = max(2, min(10, int(limit or 8)))
        # Anchor at word boundaries when possible — keeps results sharp.
        rx = re.escape(q)
        suggestions: List[Dict[str, Any]] = []

        # ---- Users ----
        u_cursor = db.users.find(
            {"$or": [
                {"name": {"$regex": rx, "$options": "i"}},
                {"phone": {"$regex": rx, "$options": "i"}},
                {"id": {"$regex": rx, "$options": "i"}},
                {"email": {"$regex": rx, "$options": "i"}},
            ]},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "email": 1},
        ).limit(limit_each)
        async for u in u_cursor:
            suggestions.append({
                "category": "users",
                "label": u.get("name") or u.get("phone") or u.get("email") or u.get("id"),
                "sub": u.get("phone") or u.get("email") or u.get("id"),
                "href": f"/admin/users/{u.get('id')}",
                "id": u.get("id"),
            })

        # ---- Squads ----
        g_cursor = db.groups.find(
            {"$or": [
                {"title": {"$regex": rx, "$options": "i"}},
                {"code": {"$regex": rx, "$options": "i"}},
                {"id": {"$regex": rx, "$options": "i"}},
            ]},
            {"_id": 0, "id": 1, "title": 1, "code": 1, "status": 1},
        ).limit(limit_each)
        async for g in g_cursor:
            suggestions.append({
                "category": "squads",
                "label": g.get("title") or g.get("code") or g.get("id"),
                "sub": f"{(g.get('code') or '').upper()} · {g.get('status') or ''}",
                "href": f"/admin/groups/{g.get('id')}",
                "id": g.get("id"),
            })

        # ---- Admin users ----
        adm_cursor = db.admin_users.find(
            {"$or": [
                {"email": {"$regex": rx, "$options": "i"}},
                {"name": {"$regex": rx, "$options": "i"}},
            ]},
            {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1},
        ).limit(limit_each)
        async for a in adm_cursor:
            suggestions.append({
                "category": "admins",
                "label": a.get("name") or a.get("email"),
                "sub": f"{a.get('email')} · {a.get('role') or ''}",
                "href": "/admin/admins",
                "id": a.get("id") or a.get("email"),
            })

        # ---- Audit log ----
        try:
            aud_cursor = db.audit_logs.find(
                {"$or": [
                    {"action": {"$regex": rx, "$options": "i"}},
                    {"actor_email": {"$regex": rx, "$options": "i"}},
                    {"target_id": {"$regex": rx, "$options": "i"}},
                ]},
                {"_id": 0, "id": 1, "action": 1, "actor_email": 1, "target_id": 1, "created_at": 1},
            ).sort("created_at", -1).limit(limit_each)
            async for ev in aud_cursor:
                suggestions.append({
                    "category": "audit",
                    "label": ev.get("action") or "(unknown)",
                    "sub": f"{ev.get('actor_email') or ''} · {ev.get('target_id') or ''}",
                    "href": "/admin/audit",
                    "id": ev.get("id"),
                })
        except Exception:
            pass

        # ---- Contact tickets (extra ergonomic) ----
        try:
            c_cursor = db.contact_messages.find(
                {"$or": [
                    {"name": {"$regex": rx, "$options": "i"}},
                    {"email": {"$regex": rx, "$options": "i"}},
                    {"id": {"$regex": rx, "$options": "i"}},
                ]},
                {"_id": 0, "id": 1, "name": 1, "email": 1, "subject_label": 1, "status": 1},
            ).limit(limit_each)
            async for t in c_cursor:
                suggestions.append({
                    "category": "tickets",
                    "label": f"{t.get('name')} · {t.get('subject_label') or ''}",
                    "sub": f"{t.get('email')} · {t.get('status') or ''}",
                    "href": f"/admin/customer-service?id={t.get('id')}",
                    "id": t.get("id"),
                })
        except Exception:
            pass

        return {"items": suggestions}

    api_router.include_router(r)
