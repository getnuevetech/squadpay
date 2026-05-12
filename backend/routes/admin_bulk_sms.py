"""
Bulk SMS broadcaster (Batch June 2025).

Like the Notification Center but SMS-only and accepts ARBITRARY phone
numbers (uploaded list, typed list, single number) in addition to the
app's own user base. Designed for marketing pushes ("download SquadPay",
referral nudges, etc.).

Audience modes:
  - "all_users"   → all registered users with a phone
  - "leads"       → users who lead at least one squad
  - "members"     → users who joined a squad as non-lead
  - "groups"      → members + lead of specific squad ids
  - "numbers"     → free-form list of phone numbers (uploaded or typed)

Endpoints:
  POST /api/admin/bulk-sms/send
  GET  /api/admin/bulk-sms/history?page=1&page_size=20
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sms_providers

logger = logging.getLogger(__name__)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---------- Schemas ----------

class BulkSmsIn(BaseModel):
    message: str
    # audience: one of all_users | leads | members | groups | numbers
    audience: str
    # Used when audience="groups".
    group_ids: Optional[List[str]] = None
    # Used when audience="numbers". May be a CSV/newline-separated string or
    # a JSON array (the admin UI sends an array).
    phone_numbers: Optional[List[str]] = None


# ---------- Helpers ----------

# Strip everything that isn't a digit or leading "+". Accept E.164-ish:
#  +12025550123, 2025550123, (202) 555-0123, etc.
_RX_NUM = re.compile(r"[^0-9+]")

def _normalize_phone(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = _RX_NUM.sub("", raw.strip())
    if not s:
        return None
    if s.startswith("+"):
        digits = s[1:]
        if not digits.isdigit() or len(digits) < 7 or len(digits) > 15:
            return None
        return "+" + digits
    # Plain digits: leave as-is; the SMS provider will normalize further.
    if len(s) < 7 or len(s) > 15:
        return None
    return s


async def _resolve_targets(db, body: BulkSmsIn) -> List[str]:
    """Returns deduped E.164-ish phone strings."""
    a = (body.audience or "").lower().strip()
    phones: set[str] = set()

    if a in ("all_users", "leads", "members", "groups"):
        # User-centric audiences — phone numbers come from db.users.
        user_ids: set[str] = set()
        if a == "all_users":
            async for u in db.users.find({}, {"id": 1, "phone": 1}):
                p = _normalize_phone(u.get("phone") or "")
                if p:
                    phones.add(p)
            return list(phones)

        if a == "leads":
            async for g in db.groups.find({}, {"lead_id": 1}):
                if g.get("lead_id"):
                    user_ids.add(g["lead_id"])
        elif a == "members":
            async for g in db.groups.find({}, {"members": 1, "lead_id": 1}):
                lead = g.get("lead_id")
                for m in g.get("members") or []:
                    uid = m.get("user_id")
                    if uid and uid != lead:
                        user_ids.add(uid)
        elif a == "groups":
            if not body.group_ids:
                raise HTTPException(400, "Pick at least one Squad when audience is 'groups'.")
            async for g in db.groups.find({"id": {"$in": body.group_ids}}, {"members": 1, "lead_id": 1}):
                if g.get("lead_id"):
                    user_ids.add(g["lead_id"])
                for m in g.get("members") or []:
                    if m.get("user_id"):
                        user_ids.add(m["user_id"])

        if not user_ids:
            return []
        async for u in db.users.find({"id": {"$in": list(user_ids)}}, {"id": 1, "phone": 1}):
            p = _normalize_phone(u.get("phone") or "")
            if p:
                phones.add(p)
        return list(phones)

    if a == "numbers":
        raw = body.phone_numbers or []
        # Allow callers to send a single newline/comma blob too, just in case.
        flat: List[str] = []
        for s in raw:
            flat.extend(re.split(r"[,\s;]+", s or ""))
        for s in flat:
            p = _normalize_phone(s)
            if p:
                phones.add(p)
        return list(phones)

    raise HTTPException(400, "Audience must be 'all_users', 'leads', 'members', 'groups', or 'numbers'.")


# ---------- Routes ----------

def attach_bulk_sms_routes(api_router: APIRouter, db, get_current_admin):
    router = APIRouter()

    @router.post("/admin/bulk-sms/send")
    async def send_bulk(body: BulkSmsIn, admin=Depends(get_current_admin)):
        msg = (body.message or "").strip()
        if not msg:
            raise HTTPException(400, "Message text is required.")
        if len(msg) > 1000:
            raise HTTPException(400, "Message is too long. Please keep it under 1000 characters.")

        targets = await _resolve_targets(db, body)
        if not targets:
            raise HTTPException(404, "No phone numbers resolved for that audience.")

        broadcast_id = f"bsms_{uuid.uuid4().hex[:10]}"
        now = _now()
        sent = 0
        failed = 0
        for phone in targets:
            try:
                ok, _info, provider = await sms_providers.send_sms(db, phone, msg)
                if ok or provider == "mock":
                    sent += 1
                else:
                    failed += 1
            except Exception as e:
                logger.exception("[bulk-sms] failed for %s: %s", phone, e)
                failed += 1

        doc = {
            "id": broadcast_id,
            "message": msg,
            "audience": body.audience,
            "group_ids": body.group_ids or None,
            "recipient_count": len(targets),
            "sms_sent": sent,
            "sms_failed": failed,
            "sent_at": now,
            "sent_by": {"admin_id": admin.get("id"), "email": admin.get("email")},
        }
        await db.bulk_sms_broadcasts.insert_one(doc)
        return {
            "id": broadcast_id,
            "recipient_count": len(targets),
            "sms_sent": sent,
            "sms_failed": failed,
        }

    @router.get("/admin/bulk-sms/history")
    async def history(
        admin=Depends(get_current_admin),
        page: int = 1,
        page_size: int = 20,
    ):
        page = max(1, int(page or 1))
        page_size = max(1, min(100, int(page_size or 20)))
        skip = (page - 1) * page_size
        total = await db.bulk_sms_broadcasts.count_documents({})
        cursor = (
            db.bulk_sms_broadcasts
            .find({}, {"_id": 0})
            .sort("sent_at", -1)
            .skip(skip)
            .limit(page_size)
        )
        items = [doc async for doc in cursor]
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": (skip + len(items)) < total,
        }

    api_router.include_router(router)
