"""SquadPay — Admin-managed legal pages (Support / Privacy / Terms).

Public endpoints:
  GET  /api/legal/pages/{slug}   → returns { slug, title, content_html, updated_at }
  GET  /api/legal/media/{id}     → serves uploaded image/video bytes

Admin endpoints (require admin auth):
  GET    /api/admin/legal/pages              → list all pages
  PUT    /api/admin/legal/pages/{slug}       → update title + content_html
  POST   /api/admin/legal/upload             → upload image/video → returns URL

Storage model:
  - `legal_pages` collection: { slug, title, content_html, updated_at, updated_by }
  - `legal_media` collection: { id, mime_type, base64, size, uploaded_at, uploaded_by }
    Media is referenced inside content_html as <img src="/api/legal/media/{id}">.

Seeding:
  On first GET, if a page doesn't exist, returns a default skeleton (so the
  user-facing pages never 404). Admins can then save real content over it.
"""
import base64
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Body, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core import new_id, now_iso

logger = logging.getLogger(__name__)

# Whitelisted slugs — cannot create arbitrary pages, only edit these three.
VALID_SLUGS = {"support", "privacy", "terms"}

# 10 MB hard limit per media upload (base64 inflates ~33%, so raw <= ~7.5 MB).
MAX_MEDIA_BYTES = 10 * 1024 * 1024

ALLOWED_MIME_PREFIXES = ("image/", "video/")


# Default content used when a slug has not yet been customized by an admin.
# Mirrors the static text the app shipped with so users see consistent copy.
DEFAULT_PAGES = {
    "support": {
        "title": "Support",
        "content_html": """
<h2>Need help?</h2>
<p>Our support team is here for you. Email us at <a href="mailto:support@squadpay.us">support@squadpay.us</a> and we'll respond within 24 hours.</p>
<h3>Frequently Asked Questions</h3>
<h4>I didn't receive my OTP code</h4>
<p>Codes can take up to 60 seconds. Check that your phone has signal and the country code is correct. If it still doesn't arrive, tap "Resend" on the OTP screen or email us.</p>
<h4>My contribution failed</h4>
<p>Stripe processes all payments. If a card is declined, double-check the card details, ZIP code, and that there are sufficient funds.</p>
<h4>How do I leave a group?</h4>
<p>Open the group, tap the menu in the top right, and choose "Leave group."</p>
<h4>Is my data secure?</h4>
<p>We never store full card numbers — only Stripe tokens. Phone numbers and personal info are encrypted at rest.</p>
""".strip(),
    },
    "privacy": {
        "title": "Privacy Policy",
        "content_html": """
<h2>Privacy Policy</h2>
<p><em>Last updated: June 2026</em></p>
<p>SquadPay ("we", "us") respects your privacy. This policy explains what we collect, why, and how we protect it.</p>
<h3>Information We Collect</h3>
<ul>
  <li><strong>Account info:</strong> name, phone number (optional), referral code.</li>
  <li><strong>Payment info:</strong> handled by Stripe — we never store full card numbers.</li>
  <li><strong>Usage:</strong> group membership, items claimed, payment status.</li>
</ul>
<h3>How We Use It</h3>
<p>To provide the service: split bills, send OTPs, process payments, send receipts. We do not sell your data.</p>
<h3>Your Rights</h3>
<p>You can request export or deletion of your data at any time by emailing <a href="mailto:support@squadpay.us">support@squadpay.us</a>.</p>
""".strip(),
    },
    "terms": {
        "title": "Terms & Conditions",
        "content_html": """
<h2>Terms & Conditions</h2>
<p><em>Last updated: June 2026</em></p>
<p>By using SquadPay, you agree to the following terms. Please read them carefully.</p>
<h3>Use of Service</h3>
<p>You must be 18 or older. You agree to provide accurate information and not abuse the service (spam, fraud, etc.).</p>
<h3>Payments</h3>
<p>Payments are processed by Stripe. You are responsible for ensuring your card details are valid. Funds contributed to a group are non-refundable except as required by law.</p>
<h3>Account Termination</h3>
<p>We may suspend or terminate accounts that violate these terms. You may close your account at any time by contacting support.</p>
<h3>Liability</h3>
<p>SquadPay is provided "as is". We are not liable for damages arising from misuse, payment failures, or third-party issues (e.g. Stripe outages).</p>
<h3>Changes</h3>
<p>We may update these terms. Material changes will be communicated via email or in-app notification.</p>
""".strip(),
    },
}


class UpdatePageIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content_html: str = Field(..., min_length=0, max_length=500_000)


def attach_legal_routes(api_router: APIRouter, db, require_admin):
    """Attach public + admin legal-pages routes to the existing api_router."""

    # ─────────────────── Public ───────────────────

    @api_router.get("/legal/pages/{slug}")
    async def get_legal_page(slug: str):
        if slug not in VALID_SLUGS:
            raise HTTPException(404, "Unknown legal page")
        page = await db.legal_pages.find_one({"slug": slug}, {"_id": 0})
        if page:
            return page
        # Fallback to defaults (read-only). Admins can save edits to override.
        defaults = DEFAULT_PAGES[slug]
        return {
            "slug": slug,
            "title": defaults["title"],
            "content_html": defaults["content_html"],
            "updated_at": None,
            "is_default": True,
        }

    @api_router.get("/legal/media/{media_id}")
    async def get_legal_media(media_id: str):
        m = await db.legal_media.find_one({"id": media_id}, {"_id": 0})
        if not m:
            raise HTTPException(404, "Media not found")
        try:
            data = base64.b64decode(m["base64"])
        except Exception:
            raise HTTPException(500, "Corrupt media")
        return Response(
            content=data,
            media_type=m.get("mime_type", "application/octet-stream"),
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # ─────────────────── Admin ───────────────────

    @api_router.get("/admin/legal/pages")
    async def admin_list_pages(_: dict = Depends(require_admin)):
        rows = await db.legal_pages.find({}, {"_id": 0}).to_list(length=20)
        by_slug = {r["slug"]: r for r in rows}
        # Always return all 3 slots (with defaults if not yet customized).
        out = []
        for slug in ("support", "privacy", "terms"):
            if slug in by_slug:
                p = by_slug[slug]
                out.append({**p, "is_default": False})
            else:
                d = DEFAULT_PAGES[slug]
                out.append(
                    {
                        "slug": slug,
                        "title": d["title"],
                        "content_html": d["content_html"],
                        "updated_at": None,
                        "is_default": True,
                    }
                )
        return {"pages": out}

    @api_router.put("/admin/legal/pages/{slug}")
    async def admin_update_page(
        slug: str,
        body: UpdatePageIn,
        admin: dict = Depends(require_admin),
    ):
        if slug not in VALID_SLUGS:
            raise HTTPException(400, "Invalid slug")
        record = {
            "slug": slug,
            "title": body.title,
            "content_html": body.content_html,
            "updated_at": now_iso(),
            "updated_by": admin.get("id") or admin.get("email") or "admin",
        }
        await db.legal_pages.update_one(
            {"slug": slug}, {"$set": record}, upsert=True
        )
        return {"ok": True, **record}

    @api_router.post("/admin/legal/upload")
    async def admin_upload_media(
        file: UploadFile = File(...),
        admin: dict = Depends(require_admin),
    ):
        if not file.content_type or not file.content_type.startswith(
            ALLOWED_MIME_PREFIXES
        ):
            raise HTTPException(400, "Only images and videos are allowed")
        data = await file.read()
        if len(data) > MAX_MEDIA_BYTES:
            raise HTTPException(
                413, f"File too large (max {MAX_MEDIA_BYTES // (1024 * 1024)} MB)"
            )
        media_id = new_id("media")
        await db.legal_media.insert_one(
            {
                "id": media_id,
                "mime_type": file.content_type,
                "base64": base64.b64encode(data).decode("ascii"),
                "size": len(data),
                "uploaded_at": now_iso(),
                "uploaded_by": admin.get("id") or admin.get("email") or "admin",
            }
        )
        return {
            "id": media_id,
            "url": f"/api/legal/media/{media_id}",
            "size": len(data),
            "mime_type": file.content_type,
        }
