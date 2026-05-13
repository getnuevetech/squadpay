"""
Phase B + Phase C admin endpoints — bundled.

Phase B
-------
B1) OCR provider chain config
    GET  /api/admin/ocr-config        → current chain + recent attempts
    PUT  /api/admin/ocr-config        → reorder/replace chain (super_admin)

B2) Income & Fees CSV + PDF exports
    GET  /api/admin/income-fees/export.csv
    GET  /api/admin/income-fees/export.pdf

Phase C
-------
C1) Customer Service replies + per-user tickets
    POST /api/admin/contact-messages/{id}/reply  → admin replies (emails user)
    GET  /api/admin/users/{user_id}/tickets      → list all tickets for a user

C2) CMS admin pages (public + admin)
    Public:
      GET  /api/cms/pages              → list published pages
      GET  /api/cms/pages/{slug}       → fetch one published page by slug
    Admin:
      GET    /api/admin/cms/pages
      POST   /api/admin/cms/pages
      GET    /api/admin/cms/pages/{id}
      PUT    /api/admin/cms/pages/{id}
      DELETE /api/admin/cms/pages/{id}

C3) Admin RBAC: super_admin-only edit + per-admin activity log
    POST /api/admin/activity              → record an admin activity event (called by admin app)
    GET  /api/admin/admins/{id}/activity  → activity log for one admin
    PUT  /api/admin/admins/{id}           → super_admin-only edit (override existing PUT if any)
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:10]}"


def _slugify(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or _new_id("p_")


# ───────────────────────────────────────────────────────────────────────────
# Email helper (reused from contact_routes flow — duplicated here to keep
# this module standalone so it can be removed independently if needed)
# ───────────────────────────────────────────────────────────────────────────
def _send_via_gmail(subject: str, body_text: str, to_addr: str) -> Optional[str]:
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
    except Exception as e:  # pylint: disable=broad-except
        return f"{type(e).__name__}: {e}"


# ───────────────────────────────────────────────────────────────────────────
# Schemas
# ───────────────────────────────────────────────────────────────────────────
class OcrProvider(BaseModel):
    provider: str = Field(..., min_length=2, max_length=32)
    model: str = Field(..., min_length=2, max_length=80)


class OcrConfigIn(BaseModel):
    # Ordered list — first one is tried first, falling back through the rest.
    providers: List[OcrProvider]


class TicketReplyIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    also_send_email: bool = True


# Module-level so FastAPI can introspect it (closure-defined Pydantic
# models break Body() resolution under pydantic v2 → 422 "missing body").
class WalletConfigIn(BaseModel):
    apple_pay_enabled: bool = True
    google_pay_enabled: bool = True
    issuing_enabled: bool = True


# KYC incentive (June 2025) — short rotating messages + a one-time
# credit awarded the first time a lead completes Stripe Connect KYC.
class KycIncentiveIn(BaseModel):
    enabled: bool = True
    # Two reward strategies. Admin picks one — see kyc_incentive.py.
    reward_mode: str = Field("credit_off_next_bill", description="credit_off_next_bill | waive_platform_fees_next_bill")
    credit_amount: float = Field(10.0, ge=0, le=500)
    messages: list[str] = Field(default_factory=list)


class CmsPageIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    slug: Optional[str] = Field(default=None, max_length=120)
    body: str = Field(..., min_length=1)
    # 'markdown' (default) or 'plain'. Frontend renders accordingly.
    body_format: str = Field(default="markdown")
    published: bool = True
    # 'web' | 'mobile' | 'both' — controls which surfaces show the page.
    visibility: str = Field(default="both")
    meta_description: Optional[str] = Field(default=None, max_length=400)


class CmsPagePatch(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    body: Optional[str] = None
    body_format: Optional[str] = None
    published: Optional[bool] = None
    visibility: Optional[str] = None
    meta_description: Optional[str] = None


class AdminActivityIn(BaseModel):
    action: str = Field(..., min_length=1, max_length=120)
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class AdminEditIn(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


# ───────────────────────────────────────────────────────────────────────────
# Income & Fees export helpers — shared with admin_income_fees module
# ───────────────────────────────────────────────────────────────────────────
def _safe_iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.isoformat()
    return str(v) if v else None


def _fee_breakdown_for_group(group: Dict[str, Any]) -> Dict[str, float]:
    per_user = group.get("per_user") or []
    transaction = sum(float(p.get("transaction_fee") or 0) for p in per_user)
    platform = sum(float(p.get("platform_fee") or 0) for p in per_user)
    extra_1 = 0.0
    extra_2 = 0.0
    extra_other = 0.0
    for p in per_user:
        for ef in (p.get("extra_fees") or []):
            amt = float(ef.get("amount") or 0)
            fid = str(ef.get("id") or "")
            if fid == "extra_1":
                extra_1 += amt
            elif fid == "extra_2":
                extra_2 += amt
            else:
                extra_other += amt
    total = transaction + platform + extra_1 + extra_2 + extra_other
    return {
        "transaction_fees": round(transaction, 2),
        "platform_fees": round(platform, 2),
        "extra_1": round(extra_1, 2),
        "extra_2": round(extra_2, 2),
        "extra_other": round(extra_other, 2),
        "total_retained": round(total, 2),
    }


def _money(x: Any) -> str:
    try:
        return f"${float(x or 0):.2f}"
    except Exception:
        return "$0.00"


# ───────────────────────────────────────────────────────────────────────────
# Routes
# ───────────────────────────────────────────────────────────────────────────
def attach_phase_bc_routes(api_router: APIRouter, db, get_current_admin, require_role):
    """Mount all Phase B + Phase C endpoints."""
    r = APIRouter()

    # ============================ B1 — OCR config =========================
    @r.get("/admin/ocr-config")
    async def get_ocr_config(admin=Depends(get_current_admin)):
        cfg = await db.app_config.find_one({"_id": "ocr"}) or {}
        providers = cfg.get("providers") or [
            {"provider": "openai", "model": "gpt-4o"},
            {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
            {"provider": "gemini", "model": "gemini-2.5-flash"},
        ]
        # Last 25 attempts so admins can spot a flaky provider.
        recent = await db.ocr_attempts.find({}, {"_id": 0}).sort("at", -1).limit(25).to_list(length=None)
        return {"providers": providers, "recent_attempts": recent, "updated_at": cfg.get("updated_at")}

    @r.put("/admin/ocr-config")
    async def set_ocr_config(
        body: OcrConfigIn,
        admin=Depends(get_current_admin),
        _gate=Depends(require_role("super_admin", "manager")),
    ):
        if not body.providers:
            raise HTTPException(400, "At least one provider required.")
        # Persist as plain dicts so we can read it back without pydantic.
        await db.app_config.update_one(
            {"_id": "ocr"},
            {"$set": {
                "providers": [p.model_dump() for p in body.providers],
                "updated_at": _now(),
                "updated_by": (admin.get("email") if isinstance(admin, dict) else None),
            }},
            upsert=True,
        )
        # Audit
        try:
            await db.audit_log.insert_one({
                "id": _new_id("aud_"),
                "at": _now(),
                "admin_email": (admin.get("email") if isinstance(admin, dict) else "?"),
                "action": "admin.ocr_config_update",
                "destructive": False,
                "target_type": "settings",
                "target_id": "ocr",
                "payload": {"providers": [p.model_dump() for p in body.providers]},
            })
        except Exception:
            pass
        return {"ok": True, "providers": [p.model_dump() for p in body.providers]}

    # ============================ B2 — Income & Fees export ==============
    async def _collect_income_groups(status: Optional[str], since: Optional[str], until: Optional[str]):
        q: Dict[str, Any] = {}
        if status:
            q["status"] = status
        if since:
            q.setdefault("created_at", {})["$gte"] = since
        if until:
            q.setdefault("created_at", {})["$lte"] = until
        cursor = db.groups.find(q).sort("created_at", -1)
        out = []
        async for g in cursor:
            out.append(g)
        return out

    @r.get("/admin/income-fees/export.csv")
    async def income_fees_csv(
        status: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        admin=Depends(get_current_admin),
    ):
        groups = await _collect_income_groups(status, since, until)
        buf = io.StringIO()
        w = csv.writer(buf)
        # Header row matches the on-screen per-group ledger columns plus a few
        # bookkeeping fields (Group ID, lead, created/settled) for traceability.
        w.writerow([
            "Squad ID", "Squad Name / Details", "Status", "Created at", "Settled at",
            "Lead ID", "Members",
            "Transaction", "Platform Fee", "Extra 1", "Extra 2",
            "Tax", "Tips", "Total Items",
            "Member's Contribution", "Total Retained",
        ])
        for g in groups:
            fees = _fee_breakdown_for_group(g)
            tax = float(g.get("tax") or 0)
            tips = float(g.get("tip") or g.get("tips") or 0)
            total_items = len(g.get("items") or [])
            w.writerow([
                g.get("id"), g.get("title") or "Bill", g.get("status"),
                _safe_iso(g.get("created_at")),
                _safe_iso(g.get("paid_at") or g.get("settled_at")),
                g.get("lead_id"),
                len(g.get("members") or []),
                f"{fees['transaction_fees']:.2f}",
                f"{fees['platform_fees']:.2f}",
                f"{fees['extra_1']:.2f}",
                f"{fees['extra_2']:.2f}",
                f"{tax:.2f}",
                f"{tips:.2f}",
                total_items,
                f"{float((g.get('funding') or {}).get('total_contributed') or 0):.2f}",
                f"{fees['total_retained']:.2f}",
            ])
        body = buf.getvalue()
        fn = f"income_fees_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            iter([body]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fn}"'},
        )

    @r.get("/admin/income-fees/export.pdf")
    async def income_fees_pdf(
        status: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        admin=Depends(get_current_admin),
    ):
        # Lazy-import so reportlab can't crash module load if it's missing.
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

        groups = await _collect_income_groups(status, since, until)
        out = io.BytesIO()
        doc = SimpleDocTemplate(
            out, pagesize=landscape(letter),
            leftMargin=24, rightMargin=24, topMargin=28, bottomMargin=24,
        )
        styles = getSampleStyleSheet()
        story: List[Any] = [
            Paragraph("<b>SquadPay — Income & Fees Ledger</b>", styles["Title"]),
            Paragraph(
                f"Generated {dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · "
                f"{len(groups)} squad(s)"
                + (f" · status={status}" if status else "")
                + (f" · since={since}" if since else "")
                + (f" · until={until}" if until else ""),
                styles["Normal"],
            ),
            Spacer(1, 10),
        ]
        # Totals row
        agg = {"tx": 0.0, "pl": 0.0, "e1": 0.0, "e2": 0.0, "tax": 0.0, "tips": 0.0, "items": 0, "contrib": 0.0, "total": 0.0}
        rows: List[List[Any]] = [[
            "Squad", "Status", "Created", "Lead", "Members",
            "Transaction", "Platform Fee", "Extra 1", "Extra 2",
            "Tax", "Tips", "Items",
            "Member's Contribution", "Total Retained",
        ]]
        for g in groups:
            fees = _fee_breakdown_for_group(g)
            tax = float(g.get("tax") or 0)
            tips = float(g.get("tip") or g.get("tips") or 0)
            items_n = len(g.get("items") or [])
            gross = float((g.get("funding") or {}).get("total_contributed") or 0)
            agg["tx"] += fees["transaction_fees"]
            agg["pl"] += fees["platform_fees"]
            agg["e1"] += fees["extra_1"]
            agg["e2"] += fees["extra_2"]
            agg["tax"] += tax
            agg["tips"] += tips
            agg["items"] += items_n
            agg["contrib"] += gross
            agg["total"] += fees["total_retained"]
            rows.append([
                (g.get("title") or "Bill")[:32],
                g.get("status") or "",
                (_safe_iso(g.get("created_at")) or "")[:10],
                (g.get("lead_id") or "")[:12],
                str(len(g.get("members") or [])),
                _money(fees["transaction_fees"]),
                _money(fees["platform_fees"]),
                _money(fees["extra_1"]),
                _money(fees["extra_2"]),
                _money(tax),
                _money(tips),
                str(items_n),
                _money(gross),
                _money(fees["total_retained"]),
            ])
        rows.append([
            "TOTAL", "", "", "", "",
            _money(agg["tx"]), _money(agg["pl"]),
            _money(agg["e1"]), _money(agg["e2"]),
            _money(agg["tax"]), _money(agg["tips"]),
            str(agg["items"]),
            _money(agg["contrib"]), _money(agg["total"]),
        ])
        tbl = Table(rows, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7a3fef")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ALIGN", (5, 1), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f5f3ff")]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ede9fe")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(tbl)
        doc.build(story)
        fn = f"income_fees_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        return StreamingResponse(
            iter([out.getvalue()]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fn}"'},
        )

    # ============================ C1 — Customer Service replies ==========
    @r.post("/admin/contact-messages/{ticket_id}/reply")
    async def reply_to_ticket(
        ticket_id: str,
        body: TicketReplyIn,
        admin=Depends(get_current_admin),
    ):
        t = await db.contact_messages.find_one({"id": ticket_id})
        if not t:
            raise HTTPException(404, "Ticket not found.")
        reply = {
            "id": _new_id("rep_"),
            "ticket_id": ticket_id,
            "direction": "outgoing",
            "from_email": admin.get("email") if isinstance(admin, dict) else "admin",
            "message": body.message.strip(),
            "created_at": _now(),
            "email_dispatch": {"sent": False, "error": None},
        }
        # Email the user the reply (best-effort).
        if body.also_send_email:
            err = _send_via_gmail(
                subject=f"[SquadPay] Re: {t.get('subject_label') or 'Your message'}",
                body_text=(
                    f"Hi {t.get('name') or ''},\n\n{body.message.strip()}\n\n"
                    "— SquadPay Customer Service\n\n"
                    f"(Ticket {ticket_id})"
                ),
                to_addr=t.get("email") or "",
            )
            reply["email_dispatch"] = {"sent": err is None, "error": err}
        # Push reply, bump updated_at, mark open if currently new.
        new_status = t.get("status")
        if new_status == "new":
            new_status = "open"
        await db.contact_messages.update_one(
            {"id": ticket_id},
            {"$push": {"replies": reply}, "$set": {"updated_at": _now(), "status": new_status}},
        )
        return await db.contact_messages.find_one({"id": ticket_id}, {"_id": 0})

    @r.get("/admin/users/{user_id}/tickets")
    async def list_user_tickets(user_id: str, admin=Depends(get_current_admin)):
        """All contact tickets associated with a user UID."""
        items = await db.contact_messages.find(
            {"user_id": user_id}, {"_id": 0},
        ).sort("created_at", -1).to_list(length=None)
        return {"items": items, "total": len(items)}

    # ============================ C2 — CMS pages ==========================
    public_r = APIRouter()

    @public_r.get("/cms/pages")
    async def cms_list_public():
        cursor = db.cms_pages.find(
            {"published": True}, {"_id": 0, "body": 0},
        ).sort("title", 1)
        items = []
        async for p in cursor:
            items.append(p)
        return {"items": items}

    @public_r.get("/cms/pages/{slug}")
    async def cms_get_public(slug: str):
        p = await db.cms_pages.find_one({"slug": slug, "published": True}, {"_id": 0})
        if not p:
            raise HTTPException(404, "Page not found")
        return p

    # Item 6/7 (June 2025) — Public, unauthenticated read of the wallet/issuing
    # config. The app needs this to decide whether to render the per-squad
    # "Card" button on the lead dashboard, and whether the in-app Apple/Google
    # Pay buttons should appear. We deliberately only expose the boolean
    # flags (no admin metadata) so we don't leak operator emails.
    @public_r.get("/runtime/wallet-config")
    async def public_wallet_config():
        cfg = await db.app_config.find_one({"_id": "wallet"}) or {}
        return {
            "apple_pay_enabled": bool(cfg.get("apple_pay_enabled", False)),
            "google_pay_enabled": bool(cfg.get("google_pay_enabled", False)),
            "issuing_enabled": bool(cfg.get("issuing_enabled", True)),
        }

    # KYC incentive (June 2025) — public read so the Pay Out screen can show
    # a short, randomly-rotated message + the configured credit amount
    # BEFORE redirecting the lead into Stripe's hosted KYC flow.
    @public_r.get("/runtime/kyc-incentive")
    async def public_kyc_incentive():
        from kyc_incentive import get_kyc_incentive
        return await get_kyc_incentive(db)

    @r.get("/admin/cms/pages")
    async def cms_admin_list(admin=Depends(get_current_admin)):
        cursor = db.cms_pages.find({}, {"_id": 0}).sort("updated_at", -1)
        items = await cursor.to_list(length=None)
        return {"items": items, "total": len(items)}

    @r.post("/admin/cms/pages")
    async def cms_admin_create(body: CmsPageIn, admin=Depends(get_current_admin)):
        slug = (body.slug or _slugify(body.title)).strip().lstrip("/")
        slug = _slugify(slug)
        if await db.cms_pages.find_one({"slug": slug}):
            raise HTTPException(409, f"Slug '{slug}' already in use.")
        doc = {
            "id": _new_id("cms_"),
            "title": body.title.strip(),
            "slug": slug,
            "body": body.body,
            "body_format": body.body_format or "markdown",
            "published": body.published,
            "visibility": body.visibility or "both",
            "meta_description": body.meta_description,
            "created_at": _now(),
            "updated_at": _now(),
            "created_by": admin.get("email") if isinstance(admin, dict) else None,
        }
        await db.cms_pages.insert_one(doc)
        doc.pop("_id", None)
        return doc

    @r.get("/admin/cms/pages/{page_id}")
    async def cms_admin_get(page_id: str, admin=Depends(get_current_admin)):
        p = await db.cms_pages.find_one({"id": page_id}, {"_id": 0})
        if not p:
            raise HTTPException(404, "Page not found")
        return p

    @r.put("/admin/cms/pages/{page_id}")
    async def cms_admin_update(page_id: str, body: CmsPagePatch, admin=Depends(get_current_admin)):
        existing = await db.cms_pages.find_one({"id": page_id})
        if not existing:
            raise HTTPException(404, "Page not found")
        upd: Dict[str, Any] = {"updated_at": _now()}
        if body.title is not None:
            upd["title"] = body.title.strip()
        if body.slug is not None:
            new_slug = _slugify(body.slug)
            if new_slug != existing.get("slug"):
                if await db.cms_pages.find_one({"slug": new_slug, "id": {"$ne": page_id}}):
                    raise HTTPException(409, f"Slug '{new_slug}' already in use.")
                upd["slug"] = new_slug
        if body.body is not None:
            upd["body"] = body.body
        if body.body_format is not None:
            upd["body_format"] = body.body_format
        if body.published is not None:
            upd["published"] = body.published
        if body.visibility is not None:
            upd["visibility"] = body.visibility
        if body.meta_description is not None:
            upd["meta_description"] = body.meta_description
        await db.cms_pages.update_one({"id": page_id}, {"$set": upd})
        return await db.cms_pages.find_one({"id": page_id}, {"_id": 0})

    @r.delete("/admin/cms/pages/{page_id}")
    async def cms_admin_delete(
        page_id: str,
        admin=Depends(get_current_admin),
        _gate=Depends(require_role("super_admin", "manager")),
    ):
        res = await db.cms_pages.delete_one({"id": page_id})
        if not res.deleted_count:
            raise HTTPException(404, "Page not found")
        return {"ok": True}

    # ============================ C3 — Admin activity + RBAC =============
    @r.post("/admin/activity")
    async def record_admin_activity(
        body: AdminActivityIn,
        request: Request,
        admin=Depends(get_current_admin),
    ):
        """Called by the admin app to record session activity (login, navigations,
        button clicks). Also auto-called by the FE on app start with a 'login' action."""
        doc = {
            "id": _new_id("act_"),
            "at": _now(),
            "admin_email": admin.get("email") if isinstance(admin, dict) else "?",
            "admin_id": admin.get("id") if isinstance(admin, dict) else None,
            "action": body.action,
            "target_type": body.target_type,
            "target_id": body.target_id,
            "payload": body.payload or {},
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent", "")[:300],
        }
        await db.admin_activity.insert_one(doc)
        return {"ok": True, "id": doc["id"]}

    @r.get("/admin/admins/{admin_id}/activity")
    async def list_admin_activity(
        admin_id: str,
        limit: int = Query(50, ge=1, le=500),
        skip: int = Query(0, ge=0),
        admin=Depends(get_current_admin),
    ):
        # We accept either admin_id or admin_email so the FE can call this with whatever it has.
        flt = {"$or": [{"admin_id": admin_id}, {"admin_email": admin_id}]}
        total = await db.admin_activity.count_documents(flt)
        items = await db.admin_activity.find(flt, {"_id": 0}).sort("at", -1).skip(skip).limit(limit).to_list(length=None)
        return {"items": items, "total": total, "skip": skip, "limit": limit}

    @r.put("/admin/admins/{admin_id}")
    async def edit_admin(
        admin_id: str,
        body: AdminEditIn,
        admin=Depends(get_current_admin),
        _gate=Depends(require_role("super_admin")),
    ):
        """Edit an admin record — restricted to super_admin only.

        This intentionally overrides any previously-mounted PUT /admin/admins/{id}
        because the prior implementation allowed managers to edit roles, which
        leaks privilege. Last-route-wins on FastAPI for duplicate paths.
        """
        target = await db.admins.find_one({"id": admin_id})
        if not target:
            raise HTTPException(404, "Admin not found")
        upd: Dict[str, Any] = {"updated_at": _now()}
        if body.name is not None:
            upd["name"] = body.name.strip()
        if body.role is not None:
            upd["role"] = body.role
        if body.is_active is not None:
            upd["is_active"] = body.is_active
        if body.notes is not None:
            upd["notes"] = body.notes
        await db.admins.update_one({"id": admin_id}, {"$set": upd})
        # Audit
        await db.audit_log.insert_one({
            "id": _new_id("aud_"),
            "at": _now(),
            "admin_email": admin.get("email") if isinstance(admin, dict) else "?",
            "action": "admin.admin_edit",
            "destructive": False,
            "target_type": "admin",
            "target_id": admin_id,
            "payload": upd,
        })
        out = await db.admins.find_one({"id": admin_id}, {"_id": 0, "password_hash": 0})
        return out

    # ============================ Wallet (Apple/Google Pay) config ===
    # Phase D (#13) — admins can independently enable/disable Apple Pay and
    # Google Pay buttons in the member checkout flow. When disabled, the FE
    # falls back to Stripe Checkout WebView (which still surfaces wallet
    # buttons in supported browsers — cheaper-per-transaction trade-off).
    # WalletConfigIn is module-level (above) — closure-defined Pydantic
    # models break FastAPI Body() resolution under pydantic v2.

    @r.get("/admin/wallet-config")
    async def get_wallet_config(admin=Depends(get_current_admin)):
        cfg = await db.app_config.find_one({"_id": "wallet"}) or {}
        return {
            "apple_pay_enabled": cfg.get("apple_pay_enabled", True),
            "google_pay_enabled": cfg.get("google_pay_enabled", True),
            "issuing_enabled": cfg.get("issuing_enabled", True),
            "updated_at": cfg.get("updated_at"),
            "updated_by": cfg.get("updated_by"),
        }

    @r.put("/admin/wallet-config")
    async def set_wallet_config(
        body: WalletConfigIn = Body(...),
        admin=Depends(get_current_admin),
        _gate=Depends(require_role("super_admin", "manager")),
    ):
        await db.app_config.update_one(
            {"_id": "wallet"},
            {"$set": {
                "apple_pay_enabled": body.apple_pay_enabled,
                "google_pay_enabled": body.google_pay_enabled,
                "issuing_enabled": body.issuing_enabled,
                "updated_at": _now(),
                "updated_by": (admin.get("email") if isinstance(admin, dict) else None),
            }},
            upsert=True,
        )
        try:
            await db.audit_log.insert_one({
                "id": _new_id("aud_"),
                "at": _now(),
                "admin_email": (admin.get("email") if isinstance(admin, dict) else "?"),
                "action": "admin.wallet_config_update",
                "destructive": False,
                "target_type": "settings",
                "target_id": "wallet",
                "payload": body.model_dump(),
            })
        except Exception:
            pass
        return {"ok": True, **body.model_dump()}

    # ─────────────────────────── KYC Incentive ──────────────────────────
    # Admin can configure: enabled toggle, one-time credit amount, and a
    # rotating message pool (3-10 short messages). The Pay Out screen
    # picks one at random per visit. Granting is idempotent — see
    # /app/backend/kyc_incentive.py.
    @r.get("/admin/kyc-incentive")
    async def admin_get_kyc_incentive(admin=Depends(get_current_admin)):
        from kyc_incentive import get_kyc_incentive
        return await get_kyc_incentive(db)

    @r.put("/admin/kyc-incentive")
    async def admin_set_kyc_incentive(
        body: KycIncentiveIn = Body(...),
        admin=Depends(get_current_admin),
        _gate=Depends(require_role("super_admin", "manager")),
    ):
        from kyc_incentive import set_kyc_incentive
        admin_email = admin.get("email") if isinstance(admin, dict) else None
        try:
            cfg = await set_kyc_incentive(
                db,
                enabled=body.enabled,
                reward_mode=body.reward_mode,
                credit_amount=body.credit_amount,
                messages=body.messages,
                admin_email=admin_email,
            )
        except ValueError as ve:
            raise HTTPException(400, str(ve))
        try:
            await db.audit_log.insert_one({
                "id": _new_id("aud_"),
                "at": _now(),
                "admin_email": admin_email or "?",
                "action": "admin.kyc_incentive_update",
                "destructive": False,
                "target_type": "settings",
                "target_id": "kyc_incentive",
                "payload": body.model_dump(),
            })
        except Exception:
            pass
        return {"ok": True, **cfg}

    api_router.include_router(public_r)
    api_router.include_router(r)


class JoinCodeConfigIn(BaseModel):
    charset: str = Field(..., description="numeric | alpha | alphanumeric")
    length: int = Field(..., ge=4, le=12)


class StoreReceiptIn(BaseModel):
    group_id: str
    image_base64: str  # raw base64 (no data: prefix)
    compress: bool = True


def attach_phase_d_routes(api_router: APIRouter, db, get_current_admin, require_role):
    """Phase D — admin-configurable join code + OCR receipt storage."""
    r = APIRouter()

    # ============================ Join code config (#5) ===================
    @r.get("/admin/join-code-config")
    async def get_join_code_config(admin=Depends(get_current_admin)):
        cfg = await db.app_config.find_one({"_id": "join_code"}) or {}
        return {
            "charset": cfg.get("charset") or "numeric",
            "length": int(cfg.get("length") or 6),
            "updated_at": cfg.get("updated_at"),
            "updated_by": cfg.get("updated_by"),
        }

    @r.put("/admin/join-code-config")
    async def set_join_code_config(
        body: JoinCodeConfigIn = Body(...),
        admin=Depends(get_current_admin),
        _gate=Depends(require_role("super_admin", "manager")),
    ):
        if body.charset not in ("numeric", "alpha", "alphanumeric"):
            raise HTTPException(400, "charset must be numeric, alpha, or alphanumeric")
        await db.app_config.update_one(
            {"_id": "join_code"},
            {"$set": {
                "charset": body.charset,
                "length": body.length,
                "updated_at": _now(),
                "updated_by": (admin.get("email") if isinstance(admin, dict) else None),
            }},
            upsert=True,
        )
        return {"ok": True, "charset": body.charset, "length": body.length}

    # ============================ OCR receipt storage (#9) ================
    @r.post("/receipts/store")
    async def store_receipt(body: StoreReceiptIn = Body(...)):
        from PIL import Image
        import base64
        import io as _io

        # Strip optional data-URI prefix
        b64 = body.image_base64
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]

        try:
            raw = base64.b64decode(b64)
        except Exception:
            raise HTTPException(400, "image_base64 is not valid base64")

        original_size = len(raw)
        stored_b64 = b64
        mime = "image/jpeg"
        if body.compress:
            try:
                im = Image.open(_io.BytesIO(raw))
                if im.mode in ("RGBA", "P"):
                    im = im.convert("RGB")
                # Cap longest side at 1600px — keeps text readable and shrinks
                # 6-12MB phone photos down to ~200-400KB JPEG.
                max_side = 1600
                if max(im.size) > max_side:
                    ratio = max_side / max(im.size)
                    new_size = (int(im.size[0] * ratio), int(im.size[1] * ratio))
                    im = im.resize(new_size, Image.LANCZOS)
                out = _io.BytesIO()
                im.save(out, format="JPEG", quality=72, optimize=True)
                compressed = out.getvalue()
                stored_b64 = base64.b64encode(compressed).decode("ascii")
                mime = "image/jpeg"
            except Exception as e:
                logger.warning("[receipt-store] compress failed, storing raw: %s", e)

        now_dt = dt.datetime.now(dt.timezone.utc)
        expires_dt = now_dt + dt.timedelta(days=90)
        doc = {
            "id": _new_id("rcpt_"),
            "group_id": body.group_id,
            "mime": mime,
            "image_base64": stored_b64,
            "original_size": original_size,
            "stored_size": len(stored_b64),
            "created_at": now_dt.isoformat(),
            # Mongo TTL index on this field auto-deletes after 90 days.
            "expires_at": expires_dt,
        }
        await db.receipts.insert_one(doc)

        # Push a lightweight reference onto the group so callers can find
        # it without scanning the receipts collection.
        ref = {
            "receipt_id": doc["id"],
            "mime": mime,
            "stored_size": len(stored_b64),
            "created_at": doc["created_at"],
            "expires_at": expires_dt.isoformat(),
        }
        await db.groups.update_one(
            {"id": body.group_id},
            {"$push": {"receipt_images": ref}, "$set": {"last_receipt_id": doc["id"]}},
        )

        # Ensure the TTL index exists (no-op if already created).
        try:
            await db.receipts.create_index("expires_at", expireAfterSeconds=0)
        except Exception:
            pass

        return {
            "ok": True,
            "receipt_id": doc["id"],
            "mime": mime,
            "stored_bytes": len(stored_b64),
            "original_bytes": original_size,
            "expires_at": expires_dt.isoformat(),
            "url": f"/api/receipts/{doc['id']}",
        }

    @r.get("/receipts/{receipt_id}")
    async def get_receipt(receipt_id: str):
        rcpt = await db.receipts.find_one({"id": receipt_id}, {"_id": 0})
        if not rcpt:
            raise HTTPException(404, "Receipt not found (or it has expired)")
        return {
            "id": rcpt["id"],
            "group_id": rcpt.get("group_id"),
            "mime": rcpt.get("mime"),
            "image_base64": rcpt.get("image_base64"),
            "created_at": rcpt.get("created_at"),
            "expires_at": rcpt.get("expires_at").isoformat() if isinstance(rcpt.get("expires_at"), dt.datetime) else rcpt.get("expires_at"),
        }

    @r.get("/groups/{group_id}/receipts")
    async def list_group_receipts(group_id: str):
        g = await db.groups.find_one({"id": group_id}, {"_id": 0, "receipt_images": 1, "last_receipt_id": 1})
        if not g:
            raise HTTPException(404, "Squad not found")
        return {"items": g.get("receipt_images") or [], "last_receipt_id": g.get("last_receipt_id")}

    api_router.include_router(r)
