"""
Backend test for Admin Branding & Logos system
(/app/backend/routes/admin_logos.py).

Tests:
- Admin endpoints (auth required):
  - GET    /api/admin/logos
  - POST   /api/admin/logos/{slot}
  - DELETE /api/admin/logos/{slot}
- Public endpoints:
  - GET    /api/runtime/logo/{slot}

Run: python /app/backend_test.py
"""
import base64
import io
import os
import sys
import json
from typing import Any

import requests
from PIL import Image

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL",
                          "https://joint-pay-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

REQUIRED_SLOTS = {
    "brand_mark":       (256, 256),
    "web_favicon":      (256, 256),
    "splash_icon":      (1024, 1024),
    "app_icon_ios":     (1024, 1024),
    "app_icon_android": (1024, 1024),
    "landing_hero":     (1200, 800),
    "email_header":     (600, 200),
}

PASS = []
FAIL = []


def _check(cond: bool, label: str, info: str = ""):
    if cond:
        PASS.append(label)
        print(f"  ✅ {label}")
    else:
        FAIL.append(f"{label} {info}")
        print(f"  ❌ {label}  {info}")


def _gen_png(size=(64, 64), color=(255, 0, 128, 255)) -> bytes:
    """Generate a real PNG of approximately the desired size in bytes."""
    # 256x256 PNG to make sure it's a real, non-trivial image
    img = Image.new("RGBA", size, color)
    # Add some pattern to make it compress reasonably
    pixels = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            if (x + y) % 7 == 0:
                pixels[x, y] = (0, 100, 200, 255)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False)
    return out.getvalue()


def _gen_large_png_b64(min_chars: int) -> str:
    """Generate a base64 string with length > min_chars, mostly random data."""
    # Use random-ish bytes to avoid compression
    import random
    random.seed(42)
    needed_bytes = int(min_chars * 0.75) + 1000
    raw = bytes(random.randint(0, 255) for _ in range(needed_bytes))
    return base64.b64encode(raw).decode("ascii")


def login_admin() -> str:
    print("\n=== Admin login ===")
    r = requests.post(f"{API}/admin/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=30)
    if r.status_code != 200:
        print("Login failed:", r.status_code, r.text[:500])
        sys.exit(1)
    body = r.json()
    token = body.get("token") or body.get("access_token")
    print(f"  ✅ Got admin token (length={len(token)})")
    return token


def test_list_logos(headers):
    print("\n=== GET /api/admin/logos ===")
    r = requests.get(f"{API}/admin/logos", headers=headers, timeout=30)
    _check(r.status_code == 200, "GET /api/admin/logos returns 200",
           f"status={r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        return
    data = r.json()
    _check("slots" in data, "Response has 'slots' key")
    slots = data.get("slots", [])
    _check(len(slots) == 7, f"Returned 7 slots (got {len(slots)})")
    slot_keys = {s["slot"] for s in slots}
    _check(slot_keys == set(REQUIRED_SLOTS.keys()),
           "All 7 expected slot keys present",
           f"got={slot_keys}")
    required_fields = {"label", "width", "height", "background",
                       "requires_native_build", "has_override", "current_url"}
    for s in slots:
        missing = required_fields - set(s.keys())
        _check(not missing, f"Slot '{s.get('slot')}' has all required fields",
               f"missing={missing}")
    # All overrides start as false (we'll DELETE later if anything exists)
    overrides = [s["slot"] for s in slots if s.get("has_override")]
    if overrides:
        print(f"  ℹ Pre-existing overrides found: {overrides} — clearing first")
        for slot in overrides:
            requests.delete(f"{API}/admin/logos/{slot}", headers=headers, timeout=30)


def test_unauth_admin():
    print("\n=== Unauthenticated admin endpoints should return 401 ===")
    r = requests.get(f"{API}/admin/logos", timeout=30)
    _check(r.status_code == 401, "GET /admin/logos without auth → 401",
           f"got {r.status_code}")
    r = requests.post(f"{API}/admin/logos/brand_mark",
                      json={"data_b64": "AAAA"}, timeout=30)
    _check(r.status_code == 401, "POST /admin/logos/{slot} without auth → 401",
           f"got {r.status_code}")
    r = requests.delete(f"{API}/admin/logos/brand_mark", timeout=30)
    _check(r.status_code == 401, "DELETE /admin/logos/{slot} without auth → 401",
           f"got {r.status_code}")


def test_upload_unknown_slot(headers):
    print("\n=== POST /api/admin/logos/unknown_slot → 404 ===")
    png = _gen_png((50, 50))
    b64 = base64.b64encode(png).decode()
    r = requests.post(f"{API}/admin/logos/unknown_slot",
                      headers=headers, json={"data_b64": b64}, timeout=30)
    _check(r.status_code == 404,
           "POST unknown slot returns 404",
           f"got {r.status_code} body={r.text[:200]}")


def test_upload_bad_base64(headers):
    print("\n=== POST /api/admin/logos/brand_mark with junk base64 → 400 ===")
    r = requests.post(f"{API}/admin/logos/brand_mark",
                      headers=headers,
                      json={"data_b64": "not-base64-***"},
                      timeout=30)
    # Implementation uses validate=False so base64.b64decode may not raise on
    # bad input — but Pillow should fail to decode the resulting bytes,
    # producing a 400 "Could not decode image".
    _check(r.status_code == 400,
           "POST with junk base64 returns 400",
           f"got {r.status_code} body={r.text[:200]}")


def test_upload_oversized(headers):
    print("\n=== POST /api/admin/logos/brand_mark with oversized payload → 413 ===")
    big_b64 = _gen_large_png_b64(5_600_000)  # >5_500_000 limit
    r = requests.post(f"{API}/admin/logos/brand_mark",
                      headers=headers,
                      json={"data_b64": big_b64},
                      timeout=60)
    _check(r.status_code == 413,
           "POST with >5.5M base64 returns 413",
           f"got {r.status_code} body={r.text[:200]}")


def test_upload_happy_path(headers):
    """Upload a real ~30KB PNG, verify response + dimensions."""
    print("\n=== POST /api/admin/logos/brand_mark with real PNG ===")
    # Generate a PNG that's reasonably sized (~30KB). 256x256 RGBA with pattern.
    png = _gen_png((256, 256))
    print(f"  Source PNG size: {len(png)} bytes")
    b64 = base64.b64encode(png).decode()
    r = requests.post(f"{API}/admin/logos/brand_mark",
                      headers=headers, json={"data_b64": b64}, timeout=60)
    _check(r.status_code == 200, "Upload brand_mark returns 200",
           f"status={r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        return None
    data = r.json()
    _check(data.get("ok") is True, "Response.ok == true")
    rendered = data.get("rendered_size")
    _check(rendered == [256, 256],
           f"rendered_size == [256, 256] (got {rendered})")
    _check(isinstance(data.get("bytes"), int) and data["bytes"] > 0,
           f"bytes field present and > 0 (got {data.get('bytes')})")
    _check("current_url" in data, "current_url field present")
    return data


def test_runtime_logo_override(headers):
    """After upload, runtime endpoint returns override bytes (image/png), 256x256."""
    print("\n=== GET /api/runtime/logo/brand_mark (with override) ===")
    r = requests.get(f"{API}/runtime/logo/brand_mark", timeout=30)
    _check(r.status_code == 200, "Runtime endpoint returns 200",
           f"status={r.status_code}")
    if r.status_code != 200:
        return None
    ctype = r.headers.get("content-type", "")
    _check("image/png" in ctype, f"Content-Type contains image/png (got {ctype})")
    _check(r.headers.get("X-Logo-Source") != "bundled",
           f"X-Logo-Source != 'bundled' when override exists (got {r.headers.get('X-Logo-Source')})")
    try:
        img = Image.open(io.BytesIO(r.content))
        _check(img.size == (256, 256), f"Override PNG is 256×256 (got {img.size})")
    except Exception as e:
        _check(False, "Override response is a valid PNG", f"err={e}")
    return r.content


def test_runtime_unknown_slot():
    print("\n=== GET /api/runtime/logo/unknown_slot → 404 ===")
    r = requests.get(f"{API}/runtime/logo/unknown_slot", timeout=30)
    _check(r.status_code == 404,
           "Unknown slot returns 404",
           f"got {r.status_code} body={r.text[:200]}")


def test_auto_resize_small_upload(headers):
    """Upload a 50x50 PNG to brand_mark, fetch — should be 256x256."""
    print("\n=== Upload 50×50 PNG → runtime returns 256×256 ===")
    png = _gen_png((50, 50))
    b64 = base64.b64encode(png).decode()
    r = requests.post(f"{API}/admin/logos/brand_mark",
                      headers=headers, json={"data_b64": b64}, timeout=30)
    _check(r.status_code == 200, "Upload 50×50 PNG: 200",
           f"status={r.status_code}")
    if r.status_code != 200:
        return
    _check(r.json().get("rendered_size") == [256, 256],
           f"rendered_size == [256, 256] (got {r.json().get('rendered_size')})")
    g = requests.get(f"{API}/runtime/logo/brand_mark", timeout=30)
    _check(g.status_code == 200, "GET runtime/logo: 200")
    try:
        img = Image.open(io.BytesIO(g.content))
        _check(img.size == (256, 256),
               f"Runtime image auto-resized to 256×256 (got {img.size})")
    except Exception as e:
        _check(False, "Resized image is valid PNG", f"err={e}")


def test_has_override_flag(headers):
    print("\n=== GET /api/admin/logos shows has_override=true for brand_mark ===")
    r = requests.get(f"{API}/admin/logos", headers=headers, timeout=30)
    if r.status_code != 200:
        _check(False, "GET /admin/logos: 200", f"got {r.status_code}")
        return
    by_slot = {s["slot"]: s for s in r.json().get("slots", [])}
    _check(by_slot.get("brand_mark", {}).get("has_override") is True,
           "brand_mark has_override == true after upload")


def test_delete_idempotent(headers):
    print("\n=== DELETE /api/admin/logos/brand_mark ===")
    r = requests.delete(f"{API}/admin/logos/brand_mark", headers=headers, timeout=30)
    _check(r.status_code == 200, "First DELETE: 200", f"got {r.status_code}")
    body = r.json() if r.status_code == 200 else {}
    _check(body.get("ok") is True, "First DELETE: ok=true")
    _check(body.get("deleted") == 1, f"First DELETE: deleted=1 (got {body.get('deleted')})")

    r2 = requests.delete(f"{API}/admin/logos/brand_mark", headers=headers, timeout=30)
    _check(r2.status_code == 200, "Second DELETE (idempotent): 200")
    body2 = r2.json() if r2.status_code == 200 else {}
    _check(body2.get("deleted") == 0,
           f"Second DELETE: deleted=0 (got {body2.get('deleted')})")


def test_runtime_bundled_default(headers):
    """After DELETE, runtime endpoint streams the bundled default PNG."""
    print("\n=== GET /api/runtime/logo/brand_mark (no override) → bundled ===")
    r = requests.get(f"{API}/runtime/logo/brand_mark", timeout=30)
    _check(r.status_code == 200, "Runtime returns 200 (bundled)")
    _check(r.headers.get("X-Logo-Source") == "bundled",
           f"X-Logo-Source == 'bundled' (got {r.headers.get('X-Logo-Source')})")
    _check("image/png" in r.headers.get("content-type", ""),
           f"Content-Type image/png")
    try:
        img = Image.open(io.BytesIO(r.content))
        # The bundled squadpay-mark.png — check it's a valid PNG; size is whatever
        # the file has. Per review request: PIL-open to confirm valid PNG.
        _check(img.format == "PNG",
               f"Bundled image is a valid PNG (format={img.format})")
        print(f"  ℹ Bundled brand_mark size: {img.size}")
    except Exception as e:
        _check(False, "Bundled image opens as PNG", f"err={e}")


def test_persistence_via_mongo(headers):
    """Upload to web_favicon, fetch twice — bytes should be identical."""
    print("\n=== Persistence: upload web_favicon, fetch twice ===")
    png = _gen_png((100, 100), color=(0, 200, 0, 255))
    b64 = base64.b64encode(png).decode()
    r = requests.post(f"{API}/admin/logos/web_favicon",
                      headers=headers, json={"data_b64": b64}, timeout=30)
    _check(r.status_code == 200, "Upload web_favicon: 200",
           f"status={r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        return
    _check(r.json().get("rendered_size") == [256, 256],
           f"web_favicon rendered_size == [256, 256] (got {r.json().get('rendered_size')})")
    a = requests.get(f"{API}/runtime/logo/web_favicon", timeout=30)
    b = requests.get(f"{API}/runtime/logo/web_favicon", timeout=30)
    _check(a.status_code == 200 and b.status_code == 200,
           "Two GETs both return 200")
    _check(a.content == b.content,
           f"Both fetches return identical bytes ({len(a.content)} vs {len(b.content)})")
    # Confirm 256×256
    try:
        img = Image.open(io.BytesIO(a.content))
        _check(img.size == (256, 256),
               f"web_favicon is 256×256 (got {img.size})")
    except Exception as e:
        _check(False, "web_favicon opens as PNG", f"err={e}")
    # Cleanup
    requests.delete(f"{API}/admin/logos/web_favicon", headers=headers, timeout=30)


def main():
    print(f"\n{'='*70}")
    print(f"Admin Branding & Logos backend test")
    print(f"Target: {API}")
    print(f"{'='*70}")

    # 1) Pre-auth checks
    test_unauth_admin()

    # 2) Login
    token = login_admin()
    headers = {"Authorization": f"Bearer {token}"}

    # 3) List initially
    test_list_logos(headers)

    # 4) Validation cases
    test_upload_unknown_slot(headers)
    test_upload_bad_base64(headers)
    test_upload_oversized(headers)
    test_runtime_unknown_slot()

    # 5) Happy path: upload, fetch, verify
    test_upload_happy_path(headers)
    test_has_override_flag(headers)
    test_runtime_logo_override(headers)

    # 6) Auto-resize from small upload
    test_auto_resize_small_upload(headers)

    # 7) DELETE idempotency
    test_delete_idempotent(headers)

    # 8) Bundled default after delete
    test_runtime_bundled_default(headers)

    # 9) Persistence (Mongo)
    test_persistence_via_mongo(headers)

    print(f"\n{'='*70}")
    print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
    print(f"{'='*70}")
    if FAIL:
        print("\nFAILURES:")
        for f in FAIL:
            print(f"  ❌ {f}")
        sys.exit(1)
    print("\nAll assertions passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
