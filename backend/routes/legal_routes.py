"""SquadPay — Admin-managed legal pages (Support / Privacy / Terms).

Storage model (rebuilt May 2026):
  - `legal_pages` collection: { slug, title, content_md, content_html,
                                 updated_at, updated_by }
    • content_md   — the authoritative source admin edits
    • content_html — derived from content_md at save-time (and on the fly
                     for legacy docs that only had HTML) so the public
                     reader doesn't need to know markdown.
  - `legal_media` collection: { id, mime_type, base64, size, uploaded_at,
                                uploaded_by }
    Media is referenced inside content_md as ![](/api/legal/media/{id})
    and inside content_html as <img src="/api/legal/media/{id}">.

Public endpoints (unauthenticated):
  GET  /api/legal/pages/{slug}   → { slug, title, content_md, content_html, … }
  GET  /api/legal/media/{id}     → serves uploaded image/video bytes

Admin endpoints (require admin auth):
  GET    /api/admin/legal/pages              → list all pages (md + html)
  PUT    /api/admin/legal/pages/{slug}       → update title + content_md
                                                (content_html re-derived)
  POST   /api/admin/legal/upload             → upload image/video → returns URL

Migration:
  - Pages with `content_md` use it as the source of truth.
  - Pages with only `content_html` (legacy) are auto-converted to markdown
    on first read via html2text so the admin editor opens cleanly.
"""
import base64
import logging
from typing import Optional

import html2text
import markdown as md_lib
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

# Markdown extensions we want on the public side: GFM-ish basics (fenced
# blocks, tables, nl2br) but NOT raw HTML pass-through to keep the output
# clean and predictable.
MD_EXTENSIONS = ["extra", "nl2br", "sane_lists"]


def _md_to_html(text: str) -> str:
    """Convert markdown → HTML. Safe to call with empty or None values."""
    if not text:
        return ""
    try:
        return md_lib.markdown(
            text,
            extensions=MD_EXTENSIONS,
            output_format="html5",
        )
    except Exception as e:
        logger.warning(f"[legal] md→html convert failed: {e}")
        return text  # fail open — better than a 500 in the admin editor


# Reusable converter for the HTML → markdown legacy fallback. Keeping this
# at module-level avoids re-creating it on every request.
_html2text = html2text.HTML2Text()
_html2text.body_width = 0          # never auto-wrap lines
_html2text.ignore_images = False
_html2text.ignore_links = False
_html2text.protect_links = True


def _html_to_md(html: str) -> str:
    if not html:
        return ""
    try:
        return _html2text.handle(html).strip()
    except Exception as e:
        logger.warning(f"[legal] html→md convert failed: {e}")
        return html


# Default content shipped with the app. Now authored in markdown so the
# default editor experience matches what the admin will create from scratch.
DEFAULT_PAGES = {
    "support": {
        "title": "Support",
        "content_md": """\
## Need help?

Our support team is here for you. Email us at <help@getsquadpay.com> and we'll respond within 24 hours.

### Frequently Asked Questions

#### I didn't receive my OTP code

Codes can take up to 60 seconds. Check that your phone has signal and the country code is correct. If it still doesn't arrive, tap **Resend** on the OTP screen or email us.

#### My contribution failed

Stripe processes all payments. If a card is declined, double-check the card details, ZIP code, and that there are sufficient funds.

#### How do I leave a squad?

Open the squad, tap the menu in the top right, and choose **Leave squad**.

#### Is my data secure?

We never store full card numbers — only Stripe tokens. Phone numbers and personal info are encrypted at rest.
""",
    },
    "privacy": {
        "title": "Privacy Policy",
        "content_md": """\
## Privacy Policy

*Last updated: June 2026*

SquadPay ("we", "us") respects your privacy. This policy explains what we collect, why, and how we protect it.

### Information We Collect

- **Account info:** name, phone number (optional), referral code.
- **Payment info:** handled by Stripe — we never store full card numbers.
- **Usage:** squad membership, items claimed, payment status.

### How We Use It

To provide the service: split bills, send OTPs, process payments, send receipts. We do not sell your data.

### Your Rights

You can request export or deletion of your data at any time by emailing <help@getsquadpay.com>.
""",
    },
    "terms": {
        "title": "Terms & Conditions",
        "content_md": """\
## Terms & Conditions

*Last updated: June 2026*

By using SquadPay, you agree to the following terms. Please read them carefully.

### Use of Service

You must be 18 or older. You agree to provide accurate information and not abuse the service (spam, fraud, etc.).

### Payments

Payments are processed by Stripe. You are responsible for ensuring your card details are valid. Funds contributed to a squad are non-refundable except as required by law.

### Account Termination

We may suspend or terminate accounts that violate these terms. You may close your account at any time by contacting support.

### Liability

SquadPay is provided "as is". We are not liable for damages arising from misuse, payment failures, or third-party issues (e.g. Stripe outages).

### Changes

We may update these terms. Material changes will be communicated via email or in-app notification.
""",
    },
}

# Precompute the HTML for the defaults so we never recompute it per request.
for _slug, _d in DEFAULT_PAGES.items():
    _d["content_html"] = _md_to_html(_d["content_md"])


class UpdatePageIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    # New: admin posts markdown. Legacy HTML field still accepted for
    # back-compat from older clients (auto-converted on save).
    content_md: Optional[str] = Field(default=None, max_length=500_000)
    content_html: Optional[str] = Field(default=None, max_length=500_000)


def _hydrate(page: dict) -> dict:
    """Ensure both content_md and content_html are present on a page row.
    Legacy rows may only have content_html — we generate the markdown
    so the editor can open them cleanly. Pure rows untouched.
    """
    md = page.get("content_md")
    html = page.get("content_html")
    if md and html:
        return page
    if md and not html:
        page["content_html"] = _md_to_html(md)
    elif html and not md:
        page["content_md"] = _html_to_md(html)
    else:
        page["content_md"] = ""
        page["content_html"] = ""
    return page


def attach_legal_routes(api_router: APIRouter, db, require_admin):
    """Attach public + admin legal-pages routes to the existing api_router."""

    # ─────────────────── Public ───────────────────

    # Cache headers for both public reads — admin edits must show on the
    # next refresh, not after a Vercel / CDN TTL. We tell every layer
    # explicitly NOT to cache. Vercel honours `cdn-cache-control`,
    # Cloudflare honours `cache-control`; sending both keeps each one in
    # check no matter where in the path the request terminates.
    NO_CACHE_HEADERS = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "CDN-Cache-Control": "no-store",
        "Vercel-CDN-Cache-Control": "no-store",
        "Pragma": "no-cache",
    }

    @api_router.get("/legal/pages/{slug}")
    async def get_legal_page(slug: str):
        if slug not in VALID_SLUGS:
            raise HTTPException(404, "Unknown legal page")
        page = await db.legal_pages.find_one({"slug": slug}, {"_id": 0})
        if page:
            # Stored rows are user-customized; make the flag explicit so
            # public consumers can rely on its presence (mirrors what the
            # admin-list endpoint does).
            from fastapi.responses import JSONResponse
            return JSONResponse({**_hydrate(page), "is_default": False}, headers=NO_CACHE_HEADERS)
        # Fallback to defaults (read-only). Admins can save edits to override.
        from fastapi.responses import JSONResponse
        d = DEFAULT_PAGES[slug]
        return JSONResponse({
            "slug": slug,
            "title": d["title"],
            "content_md": d["content_md"],
            "content_html": d["content_html"],
            "updated_at": None,
            "is_default": True,
        }, headers=NO_CACHE_HEADERS)

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
        by_slug = {r["slug"]: _hydrate(r) for r in rows}
        out = []
        for slug in ("support", "privacy", "terms"):
            if slug in by_slug:
                out.append({**by_slug[slug], "is_default": False})
            else:
                d = DEFAULT_PAGES[slug]
                out.append(
                    {
                        "slug": slug,
                        "title": d["title"],
                        "content_md": d["content_md"],
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

        # The admin editor now sends markdown; we re-derive HTML server-side.
        # If a legacy client sends only HTML, convert it back to markdown
        # so the stored source-of-truth stays consistent.
        content_md = body.content_md
        content_html = body.content_html
        if content_md is None and content_html is None:
            raise HTTPException(400, "Either content_md or content_html must be provided")
        if content_md is None:
            content_md = _html_to_md(content_html or "")
        # Always recompute html from md so the two columns stay in sync.
        content_html = _md_to_html(content_md)

        record = {
            "slug": slug,
            "title": body.title,
            "content_md": content_md,
            "content_html": content_html,
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
