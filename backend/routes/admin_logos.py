"""
admin_logos.py — Admin-uploadable brand logo slots.

Lets a super_admin/manager replace the logos used by SquadPay at runtime
without redeploying the codebase. For native (iOS/Android) app icons the
upload still requires an EAS rebuild to take effect on installed devices;
we mark those slots as `requires_native_build` so the UI can warn.

Routes mounted under /api/admin/logos (admin-only) and /api/runtime/logo
(public, used by the frontend at boot to pick up overrides).

Storage: a Mongo collection `brand_logos` keyed by `slot` with one
document per slot:
  {
    id: "lg_<slot>",
    slot: "brand_mark",
    mime: "image/png",
    data_b64: "<base64>",
    dim: { w: 256, h: 256 },
    uploaded_at: ISO,
    uploaded_by: admin_id,
  }
Defaults live on disk (the bundled assets in /app/frontend/assets/images);
when no override exists we stream those files inline so the public
`/api/runtime/logo/{slot}` endpoint always returns a real PNG regardless of
whether the request came from the frontend's same origin or a different
one (which is the typical case in dev — backend on :8001, web on :3000).
"""
from __future__ import annotations

import base64
import io
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

logger = logging.getLogger("admin_logos")

# Slot registry — single source of truth shared between API + UI.
# Keep `slot` keys snake_case; the frontend maps them to nice labels.
LOGO_SLOTS = [
    {
        "slot": "brand_mark",
        "label": "In-app brand mark",
        "where": "Header pill in the landing page and the home screen.",
        "width": 256,
        "height": 256,
        "background": "transparent",
        "requires_native_build": False,
    },
    {
        "slot": "web_favicon",
        "label": "Web favicon",
        "where": "Browser tab icon for the marketing site and web app.",
        "width": 256,
        "height": 256,
        "background": "white",
        "requires_native_build": False,
    },
    {
        "slot": "splash_icon",
        "label": "Splash screen icon",
        "where": "Centered logo on the launch splash (web + native).",
        "width": 1024,
        "height": 1024,
        "background": "transparent",
        "requires_native_build": True,  # native takes effect after EAS build
    },
    {
        "slot": "app_icon_ios",
        "label": "iOS app icon",
        "where": "Home-screen icon on iPhone / iPad. Must be opaque (Apple rule).",
        "width": 1024,
        "height": 1024,
        "background": "white",
        "requires_native_build": True,
    },
    {
        "slot": "app_icon_android",
        "label": "Android adaptive icon (foreground)",
        "where": "Android launcher; system supplies the background colour.",
        "width": 1024,
        "height": 1024,
        "background": "transparent",
        "requires_native_build": True,
    },
    {
        "slot": "landing_hero",
        "label": "Landing hero illustration",
        "where": "Big illustration above the marketing CTAs.",
        "width": 1200,
        "height": 800,
        "background": "any",
        "requires_native_build": False,
    },
    {
        "slot": "email_header",
        "label": "Email header banner",
        "where": "Top banner of outbound transactional emails.",
        "width": 600,
        "height": 200,
        "background": "white",
        "requires_native_build": False,
    },
]

SLOT_BY_KEY = {s["slot"]: s for s in LOGO_SLOTS}

# Default static paths on disk that we stream inline when there is no
# admin-uploaded override. Keep these absolute so the backend works whether
# it's launched from /app or elsewhere.
ASSETS_ROOT = os.environ.get("FRONTEND_ASSETS_ROOT", "/app/frontend/assets/images")
DEFAULT_DISK_FILE = {
    "brand_mark":        "squadpay-mark.png",
    "web_favicon":       "favicon.png",
    "splash_icon":       "splash-icon.png",
    "app_icon_ios":      "icon.png",
    "app_icon_android":  "adaptive-icon.png",
    "landing_hero":      "app-image.png",
    "email_header":      "squadpay-logo.png",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _process_upload(b64: str, target_w: int, target_h: int, want_alpha: bool) -> tuple[bytes, dict]:
    """Decode a base64 PNG/JPEG, auto-resize to (w,h) preserving aspect with
    transparent padding (or white if want_alpha is False). Returns the new
    PNG bytes + metadata dict.

    Raises HTTPException(400) on any decoding/resize failure so the admin
    UI can show a clean error message.
    """
    try:
        from PIL import Image  # imported lazily so the server can boot without Pillow
    except Exception:
        raise HTTPException(500, "Pillow not installed on backend")

    # Strip data-URI prefix if present.
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception as e:
        raise HTTPException(400, f"Invalid base64 payload: {e}")
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception as e:
        raise HTTPException(400, f"Could not decode image: {e}")

    # Resize fit-with-padding so we never crop content.
    bg = (0, 0, 0, 0) if want_alpha else (255, 255, 255, 255)
    canvas = Image.new("RGBA", (target_w, target_h), bg)
    iw, ih = img.size
    scale = min(target_w / iw, target_h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    canvas.paste(resized, ((target_w - nw) // 2, (target_h - nh) // 2), resized)

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    data = out.getvalue()
    return data, {
        "original_size": [iw, ih],
        "rendered_size": [target_w, target_h],
        "bytes": len(data),
    }


def attach_admin_logos_routes(api_router: APIRouter, db, get_current_admin, require_role=None):
    """Mount admin + public logo routes.

    - get_current_admin: the FastAPI dependency function returned by
      `admin_routes.get_current_admin_factory_sync(db)`. Mirrors the
      pattern used by every other admin router in server.py.
    """

    @api_router.get("/admin/logos")
    async def list_logos(admin=Depends(get_current_admin)):
        # Pull all overrides in one shot to avoid N round-trips.
        rows = await db.brand_logos.find({}, {"_id": 0, "data_b64": 0}).to_list(None)
        by_slot = {r["slot"]: r for r in rows}
        out = []
        for s in LOGO_SLOTS:
            override = by_slot.get(s["slot"])
            out.append({
                **s,
                "has_override": bool(override),
                "uploaded_at": (override or {}).get("uploaded_at"),
                "uploaded_by": (override or {}).get("uploaded_by"),
                "current_url": f"/api/runtime/logo/{s['slot']}?v={int(time.time() * 1000)}",
            })
        return {"slots": out}

    @api_router.post("/admin/logos/{slot}")
    async def upload_logo(slot: str, payload: dict = Body(...), admin=Depends(get_current_admin)):
        meta = SLOT_BY_KEY.get(slot)
        if not meta:
            raise HTTPException(404, f"Unknown logo slot '{slot}'")
        b64 = (payload or {}).get("data_b64") or ""
        if not b64:
            raise HTTPException(400, "Missing 'data_b64' field")

        # Reject obviously huge payloads (>4MB base64 ≈ 3MB binary) before decoding.
        if len(b64) > 5_500_000:
            raise HTTPException(413, "Image too large (max ~4MB base64)")

        want_alpha = meta["background"] != "white"  # everything but the white-bg slots
        png_bytes, dim_meta = _process_upload(b64, meta["width"], meta["height"], want_alpha)
        encoded = base64.b64encode(png_bytes).decode("ascii")

        doc = {
            "id": f"lg_{slot}",
            "slot": slot,
            "mime": "image/png",
            "data_b64": encoded,
            "dim": {"w": meta["width"], "h": meta["height"]},
            "uploaded_at": _now_iso(),
            "uploaded_by": (admin or {}).get("id") if isinstance(admin, dict) else getattr(admin, "id", None),
            "byte_size": dim_meta["bytes"],
        }
        await db.brand_logos.update_one({"slot": slot}, {"$set": doc}, upsert=True)
        return {
            "ok": True,
            "slot": slot,
            "rendered_size": dim_meta["rendered_size"],
            "bytes": dim_meta["bytes"],
            "current_url": f"/api/runtime/logo/{slot}?v={int(time.time() * 1000)}",
        }

    @api_router.delete("/admin/logos/{slot}")
    async def reset_logo(slot: str, admin=Depends(get_current_admin)):
        if slot not in SLOT_BY_KEY:
            raise HTTPException(404, f"Unknown logo slot '{slot}'")
        res = await db.brand_logos.delete_one({"slot": slot})
        return {"ok": True, "slot": slot, "deleted": res.deleted_count}

    # ── Public read endpoint — used by the frontend brand hook + favicon link
    @api_router.get("/runtime/logo/{slot}")
    async def fetch_logo(slot: str, request: Request):
        meta = SLOT_BY_KEY.get(slot)
        if not meta:
            raise HTTPException(404, f"Unknown logo slot '{slot}'")
        row = await db.brand_logos.find_one({"slot": slot}, {"_id": 0})
        if row and row.get("data_b64"):
            try:
                data = base64.b64decode(row["data_b64"])
            except Exception:
                data = None
            if data:
                return Response(
                    content=data,
                    media_type=row.get("mime", "image/png"),
                    headers={"Cache-Control": "public, max-age=60"},
                )
        # No override — stream the bundled default PNG directly so we don't
        # depend on the frontend's static asset serving. Falls back to a 1×1
        # transparent PNG if the default is missing (should never happen).
        fname = DEFAULT_DISK_FILE.get(slot)
        if fname:
            path = os.path.join(ASSETS_ROOT, fname)
            if os.path.isfile(path):
                try:
                    with open(path, "rb") as fh:
                        data = fh.read()
                    return Response(
                        content=data,
                        media_type="image/png",
                        headers={
                            "Cache-Control": "public, max-age=300",
                            "X-Logo-Source": "bundled",
                        },
                    )
                except Exception as e:
                    logger.warning("logo default read failed slot=%s err=%s", slot, e)
        # Last-resort 1×1 transparent PNG.
        TINY = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0dIDATx\x9cc\xfc\xff\xff?\x00\x05\xfe\x02\xfe\xa3\x4a\xeb\xea\x00\x00\x00\x00IEND\xaeB`\x82"
        return Response(content=TINY, media_type="image/png")
