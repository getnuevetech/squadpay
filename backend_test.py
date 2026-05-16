"""Test suite for the rebuilt Legal pages markdown pipeline.

Endpoints under test (see /app/backend/routes/legal_routes.py):
  - GET  /api/legal/pages/{slug}     (public)
  - GET  /api/admin/legal/pages      (admin)
  - PUT  /api/admin/legal/pages/{slug} (admin)
  - POST /api/admin/legal/upload     (admin)
  - GET  /api/legal/media/{id}       (public)
"""
import io
import struct
import sys
import zlib

import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append((name, detail))
        print(f"  ❌ {name}  {detail}")


def admin_login():
    r = requests.post(
        f"{BASE}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    j = r.json()
    tok = j.get("access_token") or j.get("token")
    assert tok, f"no token: {j}"
    return {"Authorization": f"Bearer {tok}"}


def make_tiny_png():
    """Build a valid 1x1 PNG without depending on Pillow."""
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(typ, data):
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\xff\xff"
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def section(t):
    print(f"\n=== {t} ===")


def main():
    headers = admin_login()

    # ── 1) Public read with both formats present ──
    section("1) Public GET /api/legal/pages/{slug} — defaults")
    for slug in ("support", "privacy", "terms"):
        r = requests.get(f"{BASE}/legal/pages/{slug}", timeout=15)
        check(f"GET /legal/pages/{slug} -> 200", r.status_code == 200, f"got {r.status_code}")
        if r.status_code == 200:
            body = r.json()
            for k in ("title", "slug", "updated_at", "is_default", "content_md", "content_html"):
                check(f"  has key '{k}' [{slug}]", k in body)
            if slug == "support":
                check(
                    "  support content_md starts with '## Need help?'",
                    isinstance(body.get("content_md"), str) and body["content_md"].lstrip().startswith("## Need help?"),
                    f"got: {body.get('content_md','')[:60]!r}",
                )
                check(
                    "  support content_html starts with '<h2>Need help?</h2>'",
                    isinstance(body.get("content_html"), str) and body["content_html"].lstrip().startswith("<h2>Need help?</h2>"),
                    f"got: {body.get('content_html','')[:80]!r}",
                )
            else:
                check(f"  {slug} content_md non-empty", bool(body.get("content_md")))
                check(f"  {slug} content_html non-empty", bool(body.get("content_html")))

    r = requests.get(f"{BASE}/legal/pages/unknown", timeout=15)
    check("GET /legal/pages/unknown -> 404", r.status_code == 404, f"got {r.status_code}")

    # ── 2) Admin list ──
    section("2) Admin GET /api/admin/legal/pages")
    r = requests.get(f"{BASE}/admin/legal/pages", headers=headers, timeout=15)
    check("GET /admin/legal/pages -> 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        pages = body.get("pages") or []
        check("pages array has 3 items", len(pages) == 3, f"got {len(pages)}")
        slugs = {p.get("slug") for p in pages}
        check("pages cover support/privacy/terms", slugs == {"support", "privacy", "terms"}, f"got {slugs}")
        for p in pages:
            check(
                f"  page[{p.get('slug')}] has content_md",
                isinstance(p.get("content_md"), str) and len(p["content_md"]) > 0,
            )
            check(
                f"  page[{p.get('slug')}] has content_html",
                isinstance(p.get("content_html"), str) and len(p["content_html"]) > 0,
            )

    # ── 3) PUT with markdown ──
    section("3) PUT /api/admin/legal/pages/privacy with markdown")
    md_body = "# Hello\n\nThis is **bold**."
    r = requests.put(
        f"{BASE}/admin/legal/pages/privacy",
        headers=headers,
        json={"title": "Privacy Policy", "content_md": md_body},
        timeout=15,
    )
    check("PUT privacy md -> 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
    put_html = None
    if r.status_code == 200:
        body = r.json()
        check("PUT response ok=true", body.get("ok") is True)
        put_html = body.get("content_html") or ""
        check("PUT content_html includes <h1>Hello</h1>", "<h1>Hello</h1>" in put_html, f"got: {put_html!r}")
        check("PUT content_html includes <strong>bold</strong>", "<strong>bold</strong>" in put_html, f"got: {put_html!r}")

    # ── 4) Round-trip ──
    section("4) Round-trip GET /api/legal/pages/privacy")
    r = requests.get(f"{BASE}/legal/pages/privacy", timeout=15)
    check("GET privacy -> 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        check(
            "content_md equals exact submitted markdown",
            body.get("content_md") == md_body,
            f"got: {body.get('content_md')!r}",
        )
        if put_html is not None:
            check(
                "content_html matches PUT response",
                body.get("content_html") == put_html,
                f"PUT={put_html!r} GET={body.get('content_html')!r}",
            )

    # ── 5) Reject empty body ──
    section("5) PUT with neither content_md nor content_html -> 400")
    r = requests.put(
        f"{BASE}/admin/legal/pages/privacy",
        headers=headers,
        json={"title": "Privacy Policy"},
        timeout=15,
    )
    check("PUT privacy no content -> 400", r.status_code == 400, f"got {r.status_code} {r.text[:200]}")

    # ── 6) Legacy shape — content_html only ──
    section("6) PUT /api/admin/legal/pages/terms with content_html (legacy)")
    legacy_html = "<p>Hello <b>world</b></p>"
    r = requests.put(
        f"{BASE}/admin/legal/pages/terms",
        headers=headers,
        json={"title": "Terms & Conditions", "content_html": legacy_html},
        timeout=15,
    )
    check("PUT terms html -> 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        check(
            "PUT terms response content_md non-empty (html->md fallback)",
            isinstance(body.get("content_md"), str) and len(body["content_md"].strip()) > 0,
            f"got: {body.get('content_md')!r}",
        )
        check("PUT terms response content_html present", bool(body.get("content_html")))

    # ── 7) Slug validation + auth ──
    section("7) PUT garbage slug -> 400; PUT without auth -> 401")
    r = requests.put(
        f"{BASE}/admin/legal/pages/garbage",
        headers=headers,
        json={"title": "X", "content_md": "y"},
        timeout=15,
    )
    check("PUT garbage slug -> 400", r.status_code == 400, f"got {r.status_code} {r.text[:200]}")

    r = requests.put(
        f"{BASE}/admin/legal/pages/support",
        json={"title": "Support", "content_md": "x"},
        timeout=15,
    )
    check("PUT support without auth -> 401", r.status_code == 401, f"got {r.status_code} {r.text[:200]}")

    # ── 8) Media upload smoke test ──
    section("8) Upload tiny PNG + read it back")
    png_bytes = make_tiny_png()
    files = {"file": ("tiny.png", io.BytesIO(png_bytes), "image/png")}
    r = requests.post(f"{BASE}/admin/legal/upload", headers=headers, files=files, timeout=20)
    check("POST /admin/legal/upload -> 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
    media_id = None
    if r.status_code == 200:
        body = r.json()
        media_id = body.get("id")
        check("upload returns id", bool(media_id))
        check(
            "upload returns url",
            isinstance(body.get("url"), str) and "/api/legal/media/" in (body.get("url") or ""),
        )
        check("upload returns size", body.get("size") == len(png_bytes), f"got {body.get('size')} expected {len(png_bytes)}")
        check("upload returns mime_type=image/png", body.get("mime_type") == "image/png", f"got {body.get('mime_type')}")
    if media_id:
        r = requests.get(f"{BASE}/legal/media/{media_id}", timeout=15)
        check("GET /legal/media/{id} -> 200", r.status_code == 200, f"got {r.status_code}")
        check("media bytes round-trip equal", r.content == png_bytes,
              f"got {len(r.content)} vs {len(png_bytes)}")
        check("media content-type image/png",
              r.headers.get("content-type", "").startswith("image/png"),
              f"got {r.headers.get('content-type')}")

    # ── 9) Cleanup — restore defaults ──
    section("9) Cleanup — restore privacy & terms to defaults")
    try:
        sys.path.insert(0, "/app/backend")
        from routes.legal_routes import DEFAULT_PAGES  # type: ignore
        for slug in ("privacy", "terms"):
            d = DEFAULT_PAGES[slug]
            rr = requests.put(
                f"{BASE}/admin/legal/pages/{slug}",
                headers=headers,
                json={"title": d["title"], "content_md": d["content_md"]},
                timeout=15,
            )
            check(f"cleanup restore {slug} -> 200", rr.status_code == 200, f"got {rr.status_code}")
    except Exception as e:
        print(f"  (cleanup skipped — could not import DEFAULT_PAGES: {e})")

    print(f"\n=== RESULT: {len(PASS)} pass, {len(FAIL)} fail ===")
    if FAIL:
        for n, d in FAIL:
            print(f"  FAIL: {n}  {d}")
        sys.exit(1)


if __name__ == "__main__":
    main()
