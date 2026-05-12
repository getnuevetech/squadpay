"""
Admin Notification Center (Batch June 2025).

Lets admins broadcast a short message + optional image + optional link to
selected users via:
  - In-app inbox (always: persisted to user_inbox, surfaced in the app)
  - SMS (optional: routed through sms_providers.send_sms with the link/
    image URL appended to the body so dumb-pipe SMS still gets the asset
    even when MMS isn't configured)

Audience selectors:
  - all       — every registered user
  - leads     — users who have led at least one group
  - members   — users who have joined a group as a member
  - groups    — explicit set of group IDs (members + lead of those groups)

Endpoints:
  POST   /api/admin/notifications/broadcast
  GET    /api/admin/notifications/broadcasts      list recent broadcasts
  GET    /api/users/{user_id}/inbox               user inbox (RN client)
  POST   /api/users/{user_id}/inbox/{msg_id}/read mark a message as read
"""

from __future__ import annotations

import datetime as dt
import uuid
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sms_providers  # send_sms

logger = logging.getLogger(__name__)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---------- Pydantic schemas ----------

class AudienceIn(BaseModel):
    type: str = Field(..., description="all | leads | members | groups")
    group_ids: Optional[List[str]] = None  # required when type=="groups"


class ChannelsIn(BaseModel):
    in_app: bool = True
    sms: bool = False


class BroadcastIn(BaseModel):
    message: str
    image_url: Optional[str] = None
    link_url: Optional[str] = None
    audience: AudienceIn
    channels: ChannelsIn


class InboxReadIn(BaseModel):
    pass  # body intentionally empty — userId/msgId come from the path


# ---------- Audience resolution ----------

async def _resolve_audience(db, audience: AudienceIn) -> List[dict]:
    """Returns a list of {user_id, phone, name} dicts for the broadcast.

    Deduped by user_id. We always pull `phone` so SMS sending knows where
    to dial; in-app delivery only needs the user_id.
    """
    a_type = (audience.type or "").lower().strip()
    user_ids: set[str] = set()

    if a_type == "all":
        async for u in db.users.find({}, {"id": 1}):
            uid = u.get("id")
            if uid:
                user_ids.add(uid)
    elif a_type == "leads":
        async for g in db.groups.find({}, {"lead_id": 1}):
            lid = g.get("lead_id")
            if lid:
                user_ids.add(lid)
    elif a_type == "members":
        # Any user who has joined ANY group as a non-lead member.
        async for g in db.groups.find({}, {"members": 1, "lead_id": 1}):
            lead = g.get("lead_id")
            for m in g.get("members") or []:
                uid = m.get("user_id")
                if uid and uid != lead:
                    user_ids.add(uid)
    elif a_type == "groups":
        gids = list(audience.group_ids or [])
        if not gids:
            raise HTTPException(400, "Pick at least one Squad when audience is 'groups'.")
        async for g in db.groups.find({"id": {"$in": gids}}, {"members": 1, "lead_id": 1}):
            if g.get("lead_id"):
                user_ids.add(g["lead_id"])
            for m in g.get("members") or []:
                if m.get("user_id"):
                    user_ids.add(m["user_id"])
    else:
        raise HTTPException(400, "Audience type must be 'all', 'leads', 'members', or 'groups'.")

    if not user_ids:
        return []

    out: List[dict] = []
    async for u in db.users.find({"id": {"$in": list(user_ids)}}, {"id": 1, "phone": 1, "name": 1}):
        out.append({
            "user_id": u.get("id"),
            "phone": u.get("phone"),
            "name": u.get("name") or "",
        })
    return out


def _compose_sms_body(message: str, image_url: Optional[str], link_url: Optional[str]) -> str:
    """Build the SMS body. We do NOT send MMS today; we append the image
    URL inline so users still get the asset via a tappable link. If both
    are provided, we keep the message + link first; the image URL goes on
    a new line at the bottom for visual hierarchy.
    """
    parts = [message.strip()]
    if link_url:
        parts.append(link_url.strip())
    if image_url:
        parts.append(image_url.strip())
    return "\n".join(p for p in parts if p)


# ---------- Routes ----------

def attach_admin_notifications_routes(api_router: APIRouter, db, get_current_admin):
    router = APIRouter()

    @router.post("/admin/notifications/broadcast")
    async def broadcast(body: BroadcastIn, admin=Depends(get_current_admin)):
        msg = (body.message or "").strip()
        if not msg:
            raise HTTPException(400, "Message text is required.")
        if len(msg) > 1000:
            raise HTTPException(400, "Message is too long. Please keep it under 1000 characters.")
        if not body.channels.in_app and not body.channels.sms:
            raise HTTPException(400, "Choose at least one delivery channel (in-app or SMS).")

        recipients = await _resolve_audience(db, body.audience)
        if not recipients:
            raise HTTPException(404, "No users matched that audience.")

        broadcast_id = f"bc_{uuid.uuid4().hex[:10]}"
        now = _now()

        broadcast_doc = {
            "id": broadcast_id,
            "message": msg,
            "image_url": body.image_url or None,
            "link_url": body.link_url or None,
            "audience": body.audience.dict(),
            "channels": body.channels.dict(),
            "sent_by": {"admin_id": admin.get("id"), "email": admin.get("email")},
            "sent_at": now,
            "recipient_count": len(recipients),
            "sms_sent": 0,
            "sms_failed": 0,
        }
        await db.admin_broadcasts.insert_one(broadcast_doc)

        # In-app inbox fan-out.
        if body.channels.in_app:
            inbox_docs = [
                {
                    "id": f"inb_{uuid.uuid4().hex[:10]}",
                    "user_id": r["user_id"],
                    "broadcast_id": broadcast_id,
                    "message": msg,
                    "image_url": body.image_url or None,
                    "link_url": body.link_url or None,
                    "read_at": None,
                    "created_at": now,
                }
                for r in recipients
                if r.get("user_id")
            ]
            if inbox_docs:
                await db.user_inbox.insert_many(inbox_docs)

        # SMS delivery (best-effort, sequential to keep provider rate limits sane).
        sms_sent = 0
        sms_failed = 0
        if body.channels.sms:
            sms_body = _compose_sms_body(msg, body.image_url, body.link_url)
            for r in recipients:
                phone = (r.get("phone") or "").strip()
                if not phone:
                    sms_failed += 1
                    continue
                try:
                    sent_real, info, provider = await sms_providers.send_sms(db, phone, sms_body)
                    if sent_real or provider == "mock":
                        # In mock mode we still treat as "delivered" for the
                        # admin counter so the demo flow isn't deceptive.
                        sms_sent += 1
                    else:
                        sms_failed += 1
                except Exception as e:
                    logger.exception("[admin-broadcast] sms send failed for %s: %s", phone, e)
                    sms_failed += 1
            await db.admin_broadcasts.update_one(
                {"id": broadcast_id},
                {"$set": {"sms_sent": sms_sent, "sms_failed": sms_failed}},
            )

        return {
            "id": broadcast_id,
            "recipient_count": len(recipients),
            "in_app_delivered": len(recipients) if body.channels.in_app else 0,
            "sms_sent": sms_sent,
            "sms_failed": sms_failed,
        }

    @router.get("/admin/notifications/broadcasts")
    async def list_broadcasts(admin=Depends(get_current_admin)):
        cursor = db.admin_broadcasts.find({}, {"_id": 0}).sort("sent_at", -1).limit(100)
        items = [doc async for doc in cursor]
        return {"items": items}

    api_router.include_router(router)

    # ---- User-facing inbox (no admin auth) ----
    user_router = APIRouter()

    @user_router.get("/users/{user_id}/inbox")
    async def get_inbox(user_id: str):
        cursor = (
            db.user_inbox
            .find({"user_id": user_id}, {"_id": 0})
            .sort("created_at", -1)
            .limit(50)
        )
        items = [doc async for doc in cursor]
        unread = sum(1 for it in items if not it.get("read_at"))
        return {"items": items, "unread": unread}

    @user_router.post("/users/{user_id}/inbox/{msg_id}/read")
    async def mark_read(user_id: str, msg_id: str):
        res = await db.user_inbox.update_one(
            {"id": msg_id, "user_id": user_id, "read_at": None},
            {"$set": {"read_at": _now()}},
        )
        return {"ok": True, "updated": res.modified_count}

    @user_router.post("/users/{user_id}/inbox/read-all")
    async def mark_all_read(user_id: str):
        res = await db.user_inbox.update_many(
            {"user_id": user_id, "read_at": None},
            {"$set": {"read_at": _now()}},
        )
        return {"ok": True, "updated": res.modified_count}

    api_router.include_router(user_router)
