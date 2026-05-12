"""
Contact Us + Customer Service (Batch June 2025).

User-facing flow:
  POST /api/contact            → user submits a contact form
                                 - validates name + email + subject + message
                                 - silently attaches user_id + phone if authenticated
                                 - stores in db.contact_messages
                                 - emails help@squadpay.us via Gmail SMTP (best-effort)

Admin flow (/admin/customer-service):
  GET    /api/admin/contact-messages?status=&subject=&page=  paginated list
  GET    /api/admin/contact-messages/{id}                    single ticket
  PATCH  /api/admin/contact-messages/{id}                    status / notes / assignee
  POST   /api/admin/contact-messages/{id}/notes              append internal note

Statuses: new | open | resolved | closed
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger(__name__)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


VALID_SUBJECTS = {"general_enquiry", "technical_support", "account_refund", "others"}
SUBJECT_LABELS = {
    "general_enquiry": "General Enquiry",
    "technical_support": "Technical Support",
    "account_refund": "Account & Refund",
    "others": "Others",
}
STATUSES = {"new", "open", "resolved", "closed"}


# ---------- Schemas ----------

class ContactIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    subject: str
    message: str = Field(..., min_length=4, max_length=4000)
    user_id: Optional[str] = None        # silently attached client-side when logged in


class TicketPatchIn(BaseModel):
    status: Optional[str] = None
    assignee_email: Optional[str] = None


class TicketNoteIn(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)
    author_email: Optional[str] = None   # captured from admin profile by route


# ---------- Email helper ----------

def _send_via_gmail(subject: str, body_text: str, to_addr: str) -> Optional[str]:
    """Send a single email via Gmail SMTP. Returns None on success or an
    error string on failure. Designed to be called from a thread so the
    request handler doesn't block on the SMTP round-trip in tests."""
    user = os.environ.get("GMAIL_SMTP_USER") or os.environ.get("CONTACT_US_DEST")
    pwd = os.environ.get("GMAIL_APP_PASSWORD")
    from_name = os.environ.get("GMAIL_FROM_NAME", "SquadPay Customer Service")
    if not user or not pwd:
        return "Gmail SMTP credentials missing"
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = to_addr
    msg["Reply-To"] = user
    msg["Subject"] = subject
    msg.set_content(body_text)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(user, pwd)
            s.send_message(msg)
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


# ---------- Routes ----------

def attach_contact_routes(api_router: APIRouter, db, get_current_admin):
    # ---------- Public submit ----------
    public_r = APIRouter()

    @public_r.post("/contact")
    async def submit_contact(body: ContactIn, request: Request):
        subj = (body.subject or "").lower().strip()
        if subj not in VALID_SUBJECTS:
            raise HTTPException(400, "Pick a subject from the dropdown.")
        if not body.message.strip():
            raise HTTPException(400, "Please tell us what's going on.")

        # Silently attach phone + UID from the authenticated user when we
        # can identify them. We never trust the client for the phone — we
        # look it up from db.users to avoid spoofing.
        phone = None
        if body.user_id:
            try:
                u = await db.users.find_one({"id": body.user_id}, {"phone": 1, "name": 1, "id": 1})
                if u:
                    phone = u.get("phone")
            except Exception:
                pass

        ticket_id = f"cs_{uuid.uuid4().hex[:10]}"
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent", "")[:300]

        doc = {
            "id": ticket_id,
            "name": body.name.strip(),
            "email": body.email,
            "subject": subj,
            "subject_label": SUBJECT_LABELS[subj],
            "message": body.message.strip(),
            "user_id": body.user_id or None,
            "user_phone": phone,
            "status": "new",
            "assignee_email": None,
            "notes": [],
            "created_at": _now(),
            "updated_at": _now(),
            "ip": ip,
            "user_agent": ua,
            "email_dispatch": {"sent": False, "error": None, "attempted_at": _now()},
        }
        await db.contact_messages.insert_one(doc)

        # Best-effort: copy the inbound message to help@squadpay.us so the
        # CS team can reply directly from their inbox even if the admin
        # UI isn't open. Failures NEVER block the user-side submit.
        to_addr = os.environ.get("CONTACT_US_DEST") or "help@squadpay.us"
        body_text = (
            f"New SquadPay contact form submission\n"
            f"--------------------------------------\n"
            f"Ticket ID:  {ticket_id}\n"
            f"Subject:    {SUBJECT_LABELS[subj]}\n"
            f"From:       {body.name} <{body.email}>\n"
            f"User ID:    {body.user_id or '(anonymous)'}\n"
            f"User phone: {phone or '(none on file)'}\n"
            f"IP:         {ip or ''}\n"
            f"User agent: {ua}\n"
            f"\n"
            f"Message:\n{body.message.strip()}\n"
        )
        err = _send_via_gmail(
            subject=f"[SquadPay CS] {SUBJECT_LABELS[subj]} — {body.name}",
            body_text=body_text,
            to_addr=to_addr,
        )
        await db.contact_messages.update_one(
            {"id": ticket_id},
            {"$set": {"email_dispatch": {
                "sent": err is None,
                "error": err,
                "attempted_at": _now(),
            }}},
        )

        return {"ok": True, "ticket_id": ticket_id, "email_dispatched": err is None}

    api_router.include_router(public_r)

    # ---------- Admin ----------
    admin_r = APIRouter()

    @admin_r.get("/admin/contact-messages")
    async def list_tickets(
        admin=Depends(get_current_admin),
        page: int = 1,
        page_size: int = 25,
        status: Optional[str] = None,
        subject: Optional[str] = None,
        q: Optional[str] = None,
    ):
        page = max(1, int(page or 1))
        page_size = max(1, min(100, int(page_size or 25)))
        skip = (page - 1) * page_size
        flt: Dict[str, Any] = {}
        if status and status in STATUSES:
            flt["status"] = status
        if subject and subject in VALID_SUBJECTS:
            flt["subject"] = subject
        if q:
            flt["$or"] = [
                {"name": {"$regex": q, "$options": "i"}},
                {"email": {"$regex": q, "$options": "i"}},
                {"message": {"$regex": q, "$options": "i"}},
                {"id": q},
            ]
        total = await db.contact_messages.count_documents(flt)
        cursor = (
            db.contact_messages.find(flt, {"_id": 0})
            .sort("created_at", -1)
            .skip(skip)
            .limit(page_size)
        )
        items = [d async for d in cursor]
        # Status counters (small enough to compute on each list call).
        counters = {}
        for s in STATUSES:
            counters[s] = await db.contact_messages.count_documents({"status": s})
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": (skip + len(items)) < total,
            "counters": counters,
        }

    @admin_r.get("/admin/contact-messages/{ticket_id}")
    async def get_ticket(ticket_id: str, admin=Depends(get_current_admin)):
        doc = await db.contact_messages.find_one({"id": ticket_id}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Ticket not found.")
        return doc

    @admin_r.patch("/admin/contact-messages/{ticket_id}")
    async def patch_ticket(ticket_id: str, body: TicketPatchIn, admin=Depends(get_current_admin)):
        update: Dict[str, Any] = {"updated_at": _now()}
        if body.status is not None:
            if body.status not in STATUSES:
                raise HTTPException(400, "Invalid status.")
            update["status"] = body.status
        if body.assignee_email is not None:
            update["assignee_email"] = body.assignee_email or None
        res = await db.contact_messages.update_one({"id": ticket_id}, {"$set": update})
        if not res.matched_count:
            raise HTTPException(404, "Ticket not found.")
        return await db.contact_messages.find_one({"id": ticket_id}, {"_id": 0})

    @admin_r.post("/admin/contact-messages/{ticket_id}/notes")
    async def add_note(ticket_id: str, body: TicketNoteIn, admin=Depends(get_current_admin)):
        note = {
            "id": f"note_{uuid.uuid4().hex[:8]}",
            "note": body.note.strip(),
            "author_email": admin.get("email") if isinstance(admin, dict) else body.author_email,
            "created_at": _now(),
        }
        res = await db.contact_messages.update_one(
            {"id": ticket_id},
            {"$push": {"notes": note}, "$set": {"updated_at": _now()}},
        )
        if not res.matched_count:
            raise HTTPException(404, "Ticket not found.")
        return await db.contact_messages.find_one({"id": ticket_id}, {"_id": 0})

    api_router.include_router(admin_r)
