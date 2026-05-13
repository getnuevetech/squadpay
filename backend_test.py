"""Phase B + Phase C — SquadPay admin endpoints test (admin_phase_bc.py).

Covers per review request:
  A) OCR config defaults + PUT + RBAC
  B) Income & Fees CSV export (headers + exact first line + since-filter)
  C) Income & Fees PDF export (content-type + %PDF prefix)
  D) Customer Service replies + per-user tickets lookup
  E) CMS public + admin CRUD with slug uniqueness
  F) Admin activity log (POST + GET by email + GET by id)
  G) Super_admin-only admin edit (PUT /admin/admins/{id})
  REGRESSION: audit-log/export, users/{id}, contribute-payment-intent
"""
from __future__ import annotations
import asyncio
import csv
import datetime as dt
import io
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://joint-pay-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client[DB_NAME]

results: List[Tuple[str, bool, str]] = []
failures_verbatim: List[str] = []


def record(name: str, ok: bool, info: str = ""):
    results.append((name, ok, info))
    status = "OK " if ok else "FAIL"
    snippet = info[:300] if info else ""
    print(f"  [{status}] {name} {('— ' + snippet) if snippet else ''}")
    if not ok and info:
        failures_verbatim.append(f"{name}: {info}")


# ── helpers ─────────────────────────────────────────────────────────────
async def admin_login(client: httpx.AsyncClient, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD) -> Dict[str, Any]:
    r = await client.post(
        f"{API}/admin/auth/login",
        json={"email": email, "password": password},
    )
    r.raise_for_status()
    return r.json()  # {token, admin}


async def ensure_sms_mock(client: httpx.AsyncClient, token: str):
    r = await client.post(
        f"{API}/admin/integrations/sms-mode",
        headers={"Authorization": f"Bearer {token}"},
        json={"mode": "mock"},
    )
    if r.status_code not in (200, 204):
        print(f"[warn] could not set sms mock: {r.status_code} {r.text[:200]}")


def fresh_phone(seed: int) -> str:
    return f"+1832{seed % 10000000:07d}"


async def register_user(client: httpx.AsyncClient, name: str, phone: str) -> Dict[str, Any]:
    """Register and mark verified via direct mongo write to avoid the 5/min
    send-otp rate-limit. Matches what /verify-otp would set."""
    r = await client.post(f"{API}/auth/register", json={"name": name})
    r.raise_for_status()
    user = r.json()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "phone": phone,
            "verified": True,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }},
    )
    user["phone"] = phone
    user["verified"] = True
    return user


async def register_user_real_otp(client: httpx.AsyncClient, name: str, phone: str) -> Dict[str, Any]:
    """Register + send-otp + verify-otp via the real endpoint chain (SMS mock mode)."""
    r = await client.post(f"{API}/auth/register", json={"name": name})
    r.raise_for_status()
    user = r.json()
    r = await client.post(f"{API}/auth/send-otp", json={"user_id": user["id"], "phone": phone})
    if r.status_code != 200:
        # Fall back to direct mongo verify if rate-limited or live mode failed.
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"phone": phone, "verified": True}},
        )
        user["phone"] = phone
        user["verified"] = True
        return user
    r = await client.post(f"{API}/auth/verify-otp",
                          json={"user_id": user["id"], "phone": phone, "code": "123456"})
    if r.status_code != 200:
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"phone": phone, "verified": True}},
        )
        user["phone"] = phone
        user["verified"] = True
        return user
    out = r.json()
    # Return the merged/existing user record.
    return out.get("user") if isinstance(out, dict) and out.get("user") else (out or user)


# ── A) OCR config ────────────────────────────────────────────────────────
async def test_A_ocr_config(client: httpx.AsyncClient, token: str):
    print("\n[A] OCR config — defaults + PUT + RBAC")
    H = {"Authorization": f"Bearer {token}"}

    # Snapshot existing config so we can restore at the end.
    existing = await db.app_config.find_one({"_id": "ocr"})
    print(f"  pre-test app_config.ocr present? {existing is not None}")

    # GET should return providers list with ≥1 entry. If db empty → default chain.
    r = await client.get(f"{API}/admin/ocr-config", headers=H)
    record("A.get_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        providers = body.get("providers") or []
        record("A.get_providers_nonempty", len(providers) >= 1, f"len={len(providers)} providers={providers}")
        record("A.get_has_recent_attempts_field", "recent_attempts" in body, "")
        # If there is no persisted config, default must match the spec.
        if existing is None:
            expected_default = [
                {"provider": "openai", "model": "gpt-4o"},
                {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
                {"provider": "gemini", "model": "gemini-2.5-flash"},
            ]
            record("A.default_chain_when_empty", providers == expected_default,
                   f"got {providers}")

    # PUT new chain (super_admin).
    new_chain = [
        {"provider": "openai", "model": "gpt-4o-mini"},
        {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    ]
    r = await client.put(f"{API}/admin/ocr-config", headers=H, json={"providers": new_chain})
    record("A.put_200", r.status_code == 200, f"{r.status_code}: {r.text[:300]}")

    # GET again — readback must match.
    r = await client.get(f"{API}/admin/ocr-config", headers=H)
    if r.status_code == 200:
        got = r.json().get("providers") or []
        record("A.readback_matches", got == new_chain, f"got {got}")

    # PUT empty providers → 400.
    r = await client.put(f"{API}/admin/ocr-config", headers=H, json={"providers": []})
    record("A.put_empty_422_or_400", r.status_code in (400, 422), f"{r.status_code}: {r.text[:200]}")

    # PUT without auth → 401.
    r = await client.put(f"{API}/admin/ocr-config", json={"providers": new_chain})
    record("A.put_no_auth_401", r.status_code == 401, f"{r.status_code}: {r.text[:200]}")

    # PUT as support-role admin → 403.
    support_email = f"support_bc_{int(time.time())}@squadpay.us"
    r = await client.post(
        f"{API}/admin/admins",
        headers=H,
        json={"email": support_email, "password": "Supp@1234!", "name": "Support BC", "role": "support"},
    )
    if r.status_code == 200:
        support_token = (await admin_login(client, support_email, "Supp@1234!"))["token"]
        r = await client.put(
            f"{API}/admin/ocr-config",
            headers={"Authorization": f"Bearer {support_token}"},
            json={"providers": new_chain},
        )
        record("A.put_support_403", r.status_code == 403, f"{r.status_code}: {r.text[:200]}")
    else:
        record("A.support_admin_created", False, f"could not create support admin: {r.status_code} {r.text[:200]}")

    # Restore previous config (or remove if it was absent).
    if existing is None:
        await db.app_config.delete_one({"_id": "ocr"})
    else:
        await db.app_config.replace_one({"_id": "ocr"}, existing, upsert=True)


# ── B) Income & Fees CSV export ─────────────────────────────────────────
async def test_B_income_fees_csv(client: httpx.AsyncClient, token: str):
    print("\n[B] Income & Fees CSV export")
    H = {"Authorization": f"Bearer {token}"}

    r = await client.get(f"{API}/admin/income-fees/export.csv", headers=H)
    record("B.csv_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        ctype = r.headers.get("content-type", "")
        cdisp = r.headers.get("content-disposition", "")
        record("B.csv_content_type", "text/csv" in ctype, f"content-type={ctype}")
        record("B.csv_attachment", "attachment" in cdisp.lower(), f"content-disposition={cdisp}")
        first_line = r.text.splitlines()[0] if r.text else ""
        expected = ("Group ID,Title,Status,Created at,Settled at,Lead ID,Members,"
                    "Gross contributed,Transaction fees,Platform fees,"
                    "Extra 1,Extra 2,Extra other,Total retained")
        record("B.csv_first_line_exact", first_line == expected, f"got={first_line!r}")

    # Since-filter in the far future → only header, no data rows.
    r = await client.get(
        f"{API}/admin/income-fees/export.csv",
        headers=H,
        params={"since": "2099-01-01T00:00:00.000Z"},
    )
    record("B.csv_future_since_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        lines = [ln for ln in r.text.splitlines() if ln.strip()]
        record("B.csv_future_since_only_header", len(lines) == 1, f"lines={len(lines)} first={lines[0] if lines else ''}")


# ── C) Income & Fees PDF export ─────────────────────────────────────────
async def test_C_income_fees_pdf(client: httpx.AsyncClient, token: str):
    print("\n[C] Income & Fees PDF export")
    H = {"Authorization": f"Bearer {token}"}

    r = await client.get(f"{API}/admin/income-fees/export.pdf", headers=H)
    record("C.pdf_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        ctype = r.headers.get("content-type", "")
        cdisp = r.headers.get("content-disposition", "")
        record("C.pdf_content_type", "application/pdf" in ctype, f"content-type={ctype}")
        record("C.pdf_attachment", "attachment" in cdisp.lower(), f"content-disposition={cdisp}")
        record("C.pdf_magic_prefix", r.content[:4] == b"%PDF", f"first8={r.content[:8]!r}")


# ── D) Customer Service replies + tickets lookup ────────────────────────
async def test_D_customer_service(client: httpx.AsyncClient, token: str):
    print("\n[D] Customer Service replies + user-tickets lookup")
    H = {"Authorization": f"Bearer {token}"}

    ts = int(time.time())
    tom = await register_user(client, f"TomQ {ts}", fresh_phone(ts * 11 + 7))
    record("D.tom_registered", tom.get("verified") is True, f"id={tom['id']}")

    r = await client.post(
        f"{API}/contact",
        json={
            "name": tom["name"],
            "email": "tomq@example.com",
            "subject": "general_enquiry",
            "message": "Phase B+C test",
            "user_id": tom["id"],
        },
    )
    record("D.contact_post_200", r.status_code == 200, f"{r.status_code}: {r.text[:300]}")
    ticket_id = None
    if r.status_code == 200:
        ticket_id = r.json().get("ticket_id")
        record("D.contact_returned_ticket_id", bool(ticket_id), f"ticket_id={ticket_id}")
    if not ticket_id:
        return

    # GET /admin/users/{tom.id}/tickets → 1 item.
    r = await client.get(f"{API}/admin/users/{tom['id']}/tickets", headers=H)
    record("D.tickets_list_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        items = body.get("items") or []
        total = body.get("total")
        record("D.tickets_count_1", len(items) == 1 and total == 1,
               f"len={len(items)} total={total}")

    # Reply.
    r = await client.post(
        f"{API}/admin/contact-messages/{ticket_id}/reply",
        headers=H,
        json={"message": "Thanks Tom — we'll get back to you", "also_send_email": False},
    )
    record("D.reply_200", r.status_code == 200, f"{r.status_code}: {r.text[:300]}")
    if r.status_code == 200:
        t = r.json()
        replies = t.get("replies") or []
        record("D.reply_replies_len_1", len(replies) == 1, f"len={len(replies)} replies={replies[:1]}")
        if replies:
            rep = replies[0]
            record("D.reply_direction_outgoing", rep.get("direction") == "outgoing", f"direction={rep.get('direction')}")
            record("D.reply_from_email_admin", rep.get("from_email") == ADMIN_EMAIL, f"from_email={rep.get('from_email')}")
        record("D.reply_status_open", t.get("status") == "open", f"status={t.get('status')}")

    # Re-fetch list — reply reflected.
    r = await client.get(f"{API}/admin/users/{tom['id']}/tickets", headers=H)
    if r.status_code == 200:
        items = r.json().get("items") or []
        if items:
            replies = items[0].get("replies") or []
            record("D.tickets_list_reflects_reply", len(replies) == 1, f"replies len={len(replies)}")


# ── E) CMS pages public + admin CRUD ────────────────────────────────────
async def test_E_cms(client: httpx.AsyncClient, token: str):
    print("\n[E] CMS public + admin CRUD")
    H = {"Authorization": f"Bearer {token}"}

    # Public list (no auth).
    r = await client.get(f"{API}/cms/pages")
    record("E.public_list_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        record("E.public_list_items_key", "items" in r.json(), "")

    # Clean any previous test pages so we get a deterministic 409 later.
    await db.cms_pages.delete_many({"slug": {"$in": ["about-squadpay-bc-test", "about-bc"]}})

    # Create.
    r = await client.post(
        f"{API}/admin/cms/pages",
        headers=H,
        json={"title": "About SquadPay (BC test)", "body": "# About\n\nHello", "visibility": "both"},
    )
    record("E.create_200", r.status_code == 200, f"{r.status_code}: {r.text[:300]}")
    page_id = None
    if r.status_code == 200:
        body = r.json()
        page_id = body.get("id")
        slug = body.get("slug")
        record("E.create_slug_autogen", slug == "about-squadpay-bc-test", f"slug={slug}")

    # Public fetch new slug.
    r = await client.get(f"{API}/cms/pages/about-squadpay-bc-test")
    record("E.public_get_new_slug_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        record("E.public_get_has_body", bool(body.get("body")), f"body_present={bool(body.get('body'))}")

    # Conflict on duplicate title (slugs collide).
    r = await client.post(
        f"{API}/admin/cms/pages",
        headers=H,
        json={"title": "About SquadPay (BC test)", "body": "Hi", "visibility": "both"},
    )
    record("E.duplicate_409", r.status_code == 409, f"{r.status_code}: {r.text[:200]}")

    if page_id:
        # Rename slug to about-bc.
        r = await client.put(
            f"{API}/admin/cms/pages/{page_id}",
            headers=H,
            json={"slug": "about-bc"},
        )
        record("E.rename_200", r.status_code == 200, f"{r.status_code}: {r.text[:300]}")
        if r.status_code == 200:
            record("E.rename_slug_about_bc", r.json().get("slug") == "about-bc", f"slug={r.json().get('slug')}")

        # New slug works.
        r = await client.get(f"{API}/cms/pages/about-bc")
        record("E.public_new_slug_200", r.status_code == 200, f"{r.status_code}")
        # Old slug 404.
        r = await client.get(f"{API}/cms/pages/about-squadpay-bc-test")
        record("E.public_old_slug_404", r.status_code == 404, f"{r.status_code}")

        # DELETE as super_admin → 200 with {ok:true}.
        r = await client.delete(f"{API}/admin/cms/pages/{page_id}", headers=H)
        record("E.delete_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
        if r.status_code == 200:
            record("E.delete_ok_true", r.json().get("ok") is True, f"body={r.text[:200]}")
        # Public 404 after delete.
        r = await client.get(f"{API}/cms/pages/about-bc")
        record("E.deleted_public_404", r.status_code == 404, f"{r.status_code}")

    # Unknown id → 404.
    r = await client.get(f"{API}/admin/cms/pages/cms_DOESNOTEXIST", headers=H)
    record("E.unknown_id_404", r.status_code == 404, f"{r.status_code}: {r.text[:200]}")


# ── F) Admin activity log ───────────────────────────────────────────────
async def test_F_admin_activity(client: httpx.AsyncClient, token: str, admin_user: Dict[str, Any]):
    print("\n[F] Admin activity log")
    H = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        f"{API}/admin/activity",
        headers=H,
        json={"action": "qa.test_event", "payload": {"note": "hello"}},
    )
    record("F.activity_post_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    activity_id = None
    if r.status_code == 200:
        activity_id = r.json().get("id")
        record("F.activity_post_has_id", bool(activity_id), f"id={activity_id}")

    # GET by email.
    r = await client.get(f"{API}/admin/admins/{ADMIN_EMAIL}/activity", headers=H)
    record("F.activity_get_by_email_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        items = r.json().get("items") or []
        actions = {it.get("action") for it in items}
        record("F.activity_get_by_email_has_event", "qa.test_event" in actions,
               f"actions sample={list(actions)[:10]}")

    # GET by admin_id.
    admin_id = admin_user.get("id")
    if admin_id:
        r = await client.get(f"{API}/admin/admins/{admin_id}/activity", headers=H)
        record("F.activity_get_by_id_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
        if r.status_code == 200:
            items = r.json().get("items") or []
            actions = {it.get("action") for it in items}
            record("F.activity_get_by_id_has_event", "qa.test_event" in actions,
                   f"actions sample={list(actions)[:10]}")


# ── G) Super_admin-only admin edit ──────────────────────────────────────
async def test_G_admin_edit_rbac(client: httpx.AsyncClient, token: str, admin_user: Dict[str, Any]):
    print("\n[G] Super_admin-only admin edit")
    H = {"Authorization": f"Bearer {token}"}
    super_admin_id = admin_user["id"]
    original_name = admin_user.get("name")

    # Edit as super_admin → 200.
    r = await client.put(
        f"{API}/admin/admins/{super_admin_id}",
        headers=H,
        json={"name": "Renamed (BC test)"},
    )
    record("G.super_admin_edit_200", r.status_code == 200, f"{r.status_code}: {r.text[:300]}")
    if r.status_code == 200:
        record("G.super_admin_name_updated", r.json().get("name") == "Renamed (BC test)",
               f"name={r.json().get('name')}")

    # Audit log has admin.admin_edit entry.
    cnt = await db.audit_log.count_documents(
        {"action": "admin.admin_edit", "target_id": super_admin_id}
    )
    record("G.audit_log_has_admin_edit", cnt >= 1, f"count={cnt}")

    # Revert name.
    r = await client.put(
        f"{API}/admin/admins/{super_admin_id}",
        headers=H,
        json={"name": original_name or "Super Admin"},
    )
    record("G.super_admin_revert_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")

    # Create manager admin and try to PUT super_admin → 403.
    mgr_email = f"manager_bc_{int(time.time())}@squadpay.us"
    mgr_pw = "Mgr@9999!"
    r = await client.post(
        f"{API}/admin/admins",
        headers=H,
        json={"email": mgr_email, "password": mgr_pw, "name": "Manager BC", "role": "manager"},
    )
    if r.status_code == 200:
        mgr_login = await admin_login(client, mgr_email, mgr_pw)
        mgr_token = mgr_login["token"]
        r = await client.put(
            f"{API}/admin/admins/{super_admin_id}",
            headers={"Authorization": f"Bearer {mgr_token}"},
            json={"name": "Hacked by manager"},
        )
        record("G.manager_edit_403", r.status_code == 403, f"{r.status_code}: {r.text[:200]}")
    else:
        record("G.manager_created", False, f"could not create manager admin: {r.status_code} {r.text[:200]}")


# ── REGRESSION smoke ────────────────────────────────────────────────────
async def test_regression(client: httpx.AsyncClient, token: str):
    print("\n[R] Regression smoke")
    H = {"Authorization": f"Bearer {token}"}

    # Phase A audit-log/export with action=block → CSV 200.
    r = await client.get(f"{API}/admin/audit-log/export", headers=H, params={"action": "block"})
    record("R.audit_log_export_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        ctype = r.headers.get("content-type", "")
        record("R.audit_log_export_csv", "text/csv" in ctype, f"content-type={ctype}")

    # Phase A: GET /admin/users/{tom.id} → total_contributed present.
    ts = int(time.time())
    tom = await register_user(client, f"TomR {ts}", fresh_phone(ts * 13 + 5))
    r = await client.get(f"{API}/admin/users/{tom['id']}", headers=H)
    record("R.user_detail_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        record("R.user_total_contributed_present", "total_contributed" in r.json(),
               f"keys={list(r.json().keys())[:10]}")

    # Phase 7: contribute-payment-intent for a fast-split $30 group, tom+alice members.
    alice = await register_user(client, f"AliceR {ts}", fresh_phone(ts * 13 + 6))
    r = await client.post(
        f"{API}/groups",
        json={
            "lead_id": tom["id"],
            "title": f"BC-regress {ts}",
            "total_amount": 30.0,
            "split_mode": "fast",
            "tax": 0.0, "tip": 0.0, "items": [],
        },
    )
    if r.status_code == 200:
        g = r.json()
        # alice joins
        r = await client.post(f"{API}/groups/{g['id']}/join",
                              json={"user_id": alice["id"], "joined_via": "code"})
        # tom contribute-payment-intent (Phase 7)
        r = await client.post(
            f"{API}/groups/{g['id']}/contribute-payment-intent",
            json={"user_id": tom["id"], "amount": 15.0, "notify_on_settled": False},
        )
        record("R.contribute_payment_intent_200", r.status_code == 200,
               f"{r.status_code}: {r.text[:300]}")
    else:
        record("R.group_create_200", False, f"{r.status_code}: {r.text[:300]}")


# ── main ────────────────────────────────────────────────────────────────
async def main():
    print(f"Target backend: {API}\n")
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        login = await admin_login(client)
        token = login["token"]
        admin_user = login.get("admin") or {}
        await ensure_sms_mock(client, token)

        await test_A_ocr_config(client, token)
        await test_B_income_fees_csv(client, token)
        await test_C_income_fees_pdf(client, token)
        await test_D_customer_service(client, token)
        await test_E_cms(client, token)
        await test_F_admin_activity(client, token, admin_user)
        await test_G_admin_edit_rbac(client, token, admin_user)
        await test_regression(client, token)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n=== TOTAL: {passed} PASS / {failed} FAIL / {len(results)} TOTAL ===")
    if failures_verbatim:
        print("\nFAILURES (verbatim):")
        for line in failures_verbatim:
            print(f"  - {line}")


if __name__ == "__main__":
    asyncio.run(main())
