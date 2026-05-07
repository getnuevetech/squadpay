"""Phase H6 — SMS Mock/Live Mode + OTP refactor — focused regression tests.

Run with:  python3 /app/backend_test.py
"""
from __future__ import annotations
import os
import re
import sys
import time
import json
import asyncio
import httpx

BACKEND = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "[email protected]"
ADMIN_PASSWORD = "ChangeMe123!"

# Track results
PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def ok(name: str):
    PASSED.append(name)
    print(f"  ✅ {name}")


def fail(name: str, detail: str = ""):
    FAILED.append((name, detail))
    print(f"  ❌ {name} — {detail}")


def section(title: str):
    print(f"\n=== {title} ===")


async def admin_login(client: httpx.AsyncClient) -> str:
    r = await client.post(f"{BACKEND}/admin/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    r.raise_for_status()
    return r.json()["token"]


async def admin_get_integrations(client: httpx.AsyncClient, token: str) -> dict:
    r = await client.get(f"{BACKEND}/admin/integrations",
                         headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


async def set_sms_mode(client: httpx.AsyncClient, token: str, mode: str) -> httpx.Response:
    return await client.post(
        f"{BACKEND}/admin/integrations/sms-mode",
        headers={"Authorization": f"Bearer {token}"},
        json={"mode": mode},
    )


async def db_otp_record(user_id: str) -> dict | None:
    """Read otp_codes row directly from MongoDB."""
    from motor.motor_asyncio import AsyncIOMotorClient
    cli = AsyncIOMotorClient("mongodb://localhost:27017")
    db = cli["test_database"]
    rec = await db.otp_codes.find_one({"user_id": user_id}, {"_id": 0})
    cli.close()
    return rec


async def db_sensitive_otp_record(user_id: str) -> dict | None:
    from motor.motor_asyncio import AsyncIOMotorClient
    cli = AsyncIOMotorClient("mongodb://localhost:27017")
    db = cli["test_database"]
    rec = await db.sensitive_otp_codes.find_one({"user_id": user_id}, {"_id": 0})
    cli.close()
    return rec


async def disable_signalwire_via_db(disable: bool):
    """Toggle signalwire.enabled directly in DB, preserving creds."""
    from motor.motor_asyncio import AsyncIOMotorClient
    cli = AsyncIOMotorClient("mongodb://localhost:27017")
    db = cli["test_database"]
    rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0})
    sw = (rec or {}).get("signalwire") or {}
    sw["enabled"] = (not disable)
    await db.app_settings.update_one({"key": "integrations"},
                                     {"$set": {"signalwire": sw}}, upsert=True)
    cli.close()


# -------- TEST GROUPS --------

async def test_phone_normalization():
    section("2. Phone normalization (sms_providers._normalize_phone)")
    sys.path.insert(0, "/app/backend")
    from sms_providers import _normalize_phone
    cases = [
        ("8325933512", "+18325933512"),
        ("18325933512", "+18325933512"),
        ("+447712345678", "+447712345678"),
        ("(832) 593-3512", "+18325933512"),
        ("", ""),
        (None, ""),
        ("  +1 (832) 593-3512  ", "+18325933512"),
    ]
    for raw, exp in cases:
        got = _normalize_phone(raw)
        if got == exp:
            ok(f"normalize {raw!r} -> {got!r}")
        else:
            fail(f"normalize {raw!r}", f"expected {exp!r}, got {got!r}")


async def test_sms_mode_toggle(client, token):
    section("1. SMS mode toggle endpoint /admin/integrations/sms-mode")
    # Set mock
    r = await set_sms_mode(client, token, "mock")
    if r.status_code == 200:
        cur = await admin_get_integrations(client, token)
        if cur.get("sms_routing", {}).get("mode") == "mock":
            ok("set mode=mock reflects mock in /admin/integrations")
        else:
            fail("mock mode reflect", f"sms_routing={cur.get('sms_routing')}")
    else:
        fail("set mode=mock", f"status={r.status_code} body={r.text[:200]}")

    # Set live
    r = await set_sms_mode(client, token, "live")
    if r.status_code == 200:
        cur = await admin_get_integrations(client, token)
        if cur.get("sms_routing", {}).get("mode") == "live":
            ok("set mode=live reflects live in /admin/integrations")
        else:
            fail("live mode reflect", f"sms_routing={cur.get('sms_routing')}")
    else:
        fail("set mode=live", f"status={r.status_code} body={r.text[:200]}")

    # Invalid mode
    r = await set_sms_mode(client, token, "live2")
    if r.status_code == 422:
        ok("invalid mode 'live2' -> 422")
    else:
        fail("invalid mode", f"expected 422, got {r.status_code} body={r.text[:200]}")

    # Unauthenticated
    r = await client.post(f"{BACKEND}/admin/integrations/sms-mode", json={"mode": "mock"})
    if r.status_code in (401, 403):
        ok(f"unauthenticated -> {r.status_code}")
    else:
        fail("unauthenticated mode toggle", f"expected 401/403, got {r.status_code}")

    # Non-super-admin (manager)
    # Create a fresh manager for the test
    ts = int(time.time())
    mgr_email = f"mgr_h6_{ts}@kwiktech.net"
    r = await client.post(
        f"{BACKEND}/admin/admins",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": mgr_email, "password": "ManagerPass1!", "name": "Mgr H6", "role": "manager"},
    )
    if r.status_code not in (200, 201):
        fail("create manager admin (precondition)", f"status={r.status_code} body={r.text[:200]}")
        return
    rl = await client.post(f"{BACKEND}/admin/auth/login",
                           json={"email": mgr_email, "password": "ManagerPass1!"})
    if rl.status_code != 200:
        fail("manager login (precondition)", f"status={rl.status_code}")
        return
    mgr_token = rl.json()["token"]
    r = await client.post(
        f"{BACKEND}/admin/integrations/sms-mode",
        headers={"Authorization": f"Bearer {mgr_token}"},
        json={"mode": "mock"},
    )
    if r.status_code == 403:
        ok("manager (non-super_admin) -> 403")
    else:
        fail("manager mode toggle", f"expected 403, got {r.status_code} body={r.text[:200]}")

    # Reset to mock for the next tests
    await set_sms_mode(client, token, "mock")


async def _register_user(client, name: str) -> str:
    r = await client.post(f"{BACKEND}/auth/register", json={"name": name})
    r.raise_for_status()
    return r.json()["id"]


async def test_send_otp_mock_mode(client, token):
    section("3a. /api/auth/send-otp — MOCK mode")
    await set_sms_mode(client, token, "mock")
    uid = await _register_user(client, f"MockUser{int(time.time())}")
    phone = f"+1832555{int(time.time()) % 10000:04d}"
    r = await client.post(f"{BACKEND}/auth/send-otp", json={"user_id": uid, "phone": phone})
    if r.status_code != 200:
        fail("mock send-otp 200", f"status={r.status_code} body={r.text[:300]}")
        return
    body = r.json()
    if body.get("mocked") is True and body.get("live") is False:
        ok("mock response: mocked=true live=false")
    else:
        fail("mock flags", f"mocked={body.get('mocked')} live={body.get('live')}")
    msg = body.get("message", "")
    if "123456" in msg or "Use 123456" in msg:
        ok("mock response message contains 'Use 123456'")
    else:
        fail("mock message", f"message={msg!r}")
    if "info" in body:
        ok("mock response has info field")
    else:
        fail("mock info", f"body keys={list(body.keys())}")
    rec = await db_otp_record(uid)
    if rec and rec.get("code") == "123456" and rec.get("mode") == "mock":
        ok("DB otp_codes row code=123456 mode=mock")
    else:
        fail("mock DB row", f"rec={rec}")
    return uid, phone


async def test_send_otp_live_mode(client, token):
    section("3b. /api/auth/send-otp — LIVE mode (with SignalWire)")
    # Make sure SignalWire is enabled
    await disable_signalwire_via_db(disable=False)
    await set_sms_mode(client, token, "live")
    uid = await _register_user(client, f"LiveUser{int(time.time())}")
    # Use a US 10-digit number that SignalWire will return 4xx for unverified
    # — we just want to verify our endpoint behavior.
    phone = f"+1832555{int(time.time()) % 10000:04d}"
    r = await client.post(f"{BACKEND}/auth/send-otp", json={"user_id": uid, "phone": phone})
    # SignalWire creds in DB are real per setup → expect 200 with sent_real flag
    # But if SignalWire returns a 4xx (caller-id verification), our endpoint
    # raises 502. Let's accept either 200 with {mocked:false,live:true} OR 502 case
    # However, the review says: "Live mode (with SignalWire configured & enabled in DB):
    #   response has mocked: false, live: true, message contains 'OTP sent via SMS'"
    # So if 502 occurs we report that, but it might still be a valid behavior.
    if r.status_code == 200:
        body = r.json()
        if body.get("mocked") is False and body.get("live") is True:
            ok("live response: mocked=false live=true")
        else:
            fail("live flags", f"mocked={body.get('mocked')} live={body.get('live')}")
        msg = body.get("message", "")
        if "OTP sent" in msg or "sent via SMS" in msg:
            ok(f"live response message contains 'OTP sent via SMS' (got: {msg!r})")
        else:
            fail("live message", f"message={msg!r}")
        if "123456" not in msg and re.search(r"\b\d{6}\b", msg) is None:
            ok("live response message does NOT leak the code")
        else:
            fail("live no-code-leak", f"message={msg!r} contains digits")
        rec = await db_otp_record(uid)
        if rec and rec.get("mode") == "live":
            code = rec.get("code", "")
            if re.fullmatch(r"\d{6}", code) and code != "123456":
                ok(f"live DB row: 6-digit code {code!r} != 123456, mode=live")
            else:
                fail("live DB code", f"code={code!r}")
        else:
            fail("live DB row mode", f"rec={rec}")
        return uid, phone
    elif r.status_code == 502:
        # SignalWire likely returned 4xx (e.g. unverified caller id). The endpoint
        # behavior for "provider returned non-2xx" is what's tested in 3c. Still:
        # ensure no code in detail.
        detail = r.json().get("detail", "")
        if "Could not send" in detail and "123456" not in detail and not re.search(r"\b\d{6}\b", detail):
            ok(f"live with provider 4xx -> 502, no code leak (detail truncated)")
        else:
            fail("live 502 detail", f"detail={detail!r}")
        # DB should still have a 6-digit code != 123456 and mode=live
        rec = await db_otp_record(uid)
        if rec and rec.get("mode") == "live":
            code = rec.get("code", "")
            if re.fullmatch(r"\d{6}", code) and code != "123456":
                ok(f"live DB row (after 502): 6-digit code {code!r} != 123456")
            else:
                fail("live DB code (after 502)", f"code={code!r}")
        else:
            fail("live DB row (after 502)", f"rec={rec}")
        return uid, phone
    else:
        fail("live send-otp status", f"status={r.status_code} body={r.text[:300]}")
        return uid, phone


async def test_send_otp_live_mode_failure(client, token):
    section("3c. /api/auth/send-otp — LIVE mode + provider DISABLED (forced failure)")
    await disable_signalwire_via_db(disable=True)
    await set_sms_mode(client, token, "live")
    uid = await _register_user(client, f"LiveFailUser{int(time.time())}")
    phone = f"+1832555{int(time.time()) % 10000:04d}"
    r = await client.post(f"{BACKEND}/auth/send-otp", json={"user_id": uid, "phone": phone})
    if r.status_code == 502:
        detail = r.json().get("detail", "")
        if "Could not send verification SMS" in detail:
            ok("live mode + provider failure -> 502 'Could not send verification SMS'")
        else:
            fail("502 detail content", f"detail={detail!r}")
        if "123456" not in detail and re.search(r"\b\d{6}\b", detail) is None:
            ok("502 response does NOT leak code")
        else:
            fail("502 leaks code", f"detail={detail!r}")
    else:
        fail("live failure status", f"expected 502, got {r.status_code} body={r.text[:300]}")
    # Re-enable SignalWire for next tests
    await disable_signalwire_via_db(disable=False)


async def test_verify_otp_mode_safety(client, token):
    section("4. /api/auth/verify-otp — mode safety (live closes 123456 backdoor)")
    # Live mode setup
    await disable_signalwire_via_db(disable=False)
    await set_sms_mode(client, token, "live")
    uid = await _register_user(client, f"VerifyUser{int(time.time())}")
    phone = f"+1832444{int(time.time()) % 10000:04d}"
    r = await client.post(f"{BACKEND}/auth/send-otp", json={"user_id": uid, "phone": phone})
    # Read code from DB (not from response)
    rec = await db_otp_record(uid)
    if not rec:
        fail("verify-otp setup", "no OTP DB record")
        return
    real_code = rec.get("code")

    # 4a: 123456 must be REJECTED in live mode
    r = await client.post(f"{BACKEND}/auth/verify-otp",
                          json={"user_id": uid, "phone": phone, "code": "123456"})
    if r.status_code == 400 and "Invalid OTP code" in r.json().get("detail", ""):
        ok("live mode + verify with '123456' -> 400 Invalid OTP code (backdoor closed)")
    else:
        fail("live backdoor", f"status={r.status_code} body={r.text[:200]}")

    # 4b: real code succeeds
    r = await client.post(f"{BACKEND}/auth/verify-otp",
                          json={"user_id": uid, "phone": phone, "code": real_code})
    if r.status_code == 200 and r.json().get("verified") is True:
        ok(f"live verify with real DB code succeeds, verified=true")
    else:
        fail("live real-code verify", f"status={r.status_code} body={r.text[:200]} (real_code={real_code})")

    # 4c: mock mode — 123456 succeeds
    await set_sms_mode(client, token, "mock")
    uid2 = await _register_user(client, f"MockVerify{int(time.time())}")
    phone2 = f"+1832555{(int(time.time()) + 1) % 10000:04d}"
    await client.post(f"{BACKEND}/auth/send-otp", json={"user_id": uid2, "phone": phone2})
    r = await client.post(f"{BACKEND}/auth/verify-otp",
                          json={"user_id": uid2, "phone": phone2, "code": "123456"})
    if r.status_code == 200 and r.json().get("verified") is True:
        ok("mock mode + verify with '123456' -> 200 verified")
    else:
        fail("mock verify 123456", f"status={r.status_code} body={r.text[:200]}")


async def test_sensitive_otp(client, token):
    section("5. /api/auth/sensitive/send-otp — same helper, mode-aware")
    # Need a fully-verified user with a phone first
    await set_sms_mode(client, token, "mock")
    uid = await _register_user(client, f"CardUser{int(time.time())}")
    phone = f"+1832666{int(time.time()) % 10000:04d}"
    await client.post(f"{BACKEND}/auth/send-otp", json={"user_id": uid, "phone": phone})
    rv = await client.post(f"{BACKEND}/auth/verify-otp",
                           json={"user_id": uid, "phone": phone, "code": "123456"})
    if rv.status_code != 200:
        fail("sensitive otp prereq verify", f"status={rv.status_code} body={rv.text[:200]}")
        return
    real_uid = rv.json()["id"]  # may collapse

    # 5a: mock mode sensitive OTP → message contains 123456
    r = await client.post(f"{BACKEND}/auth/sensitive/send-otp", json={"user_id": real_uid})
    if r.status_code == 200:
        body = r.json()
        if body.get("mocked") is True and "123456" in body.get("message", ""):
            ok("sensitive send-otp mock -> mocked=true, '123456' in message")
        else:
            fail("sensitive mock", f"body={body}")
        rec = await db_sensitive_otp_record(real_uid)
        if rec and rec.get("code") == "123456" and rec.get("mode") == "mock":
            ok("sensitive DB row code=123456 mode=mock")
        else:
            fail("sensitive mock DB", f"rec={rec}")
    else:
        fail("sensitive mock send 200", f"status={r.status_code} body={r.text[:200]}")

    # 5b: live mode sensitive OTP
    await disable_signalwire_via_db(disable=False)
    await set_sms_mode(client, token, "live")
    r = await client.post(f"{BACKEND}/auth/sensitive/send-otp", json={"user_id": real_uid})
    if r.status_code in (200, 502):
        if r.status_code == 200:
            body = r.json()
            if body.get("live") is True and body.get("mocked") is False:
                ok("sensitive live -> live=true mocked=false")
            else:
                fail("sensitive live flags", f"body={body}")
            msg = body.get("message", "")
            if "123456" not in msg and not re.search(r"\b\d{6}\b", msg):
                ok("sensitive live message has no code leak")
            else:
                fail("sensitive live message", f"message={msg!r}")
        rec = await db_sensitive_otp_record(real_uid)
        if rec and rec.get("mode") == "live":
            code = rec.get("code", "")
            if re.fullmatch(r"\d{6}", code) and code != "123456":
                ok(f"sensitive live DB code {code!r} != 123456")
            else:
                fail("sensitive live DB code", f"code={code!r}")
            # Verify with 123456 -> 400
            r2 = await client.post(f"{BACKEND}/auth/sensitive/verify-otp",
                                   json={"user_id": real_uid, "code": "123456"})
            if r2.status_code == 400:
                ok("sensitive live verify with '123456' -> 400 (backdoor closed)")
            else:
                fail("sensitive live backdoor", f"status={r2.status_code} body={r2.text[:200]}")
    else:
        fail("sensitive live status", f"status={r.status_code} body={r.text[:300]}")

    await set_sms_mode(client, token, "mock")


async def test_admin_test_endpoints_bypass_enabled(client, token):
    section("6. Admin Test SMS endpoints bypass `enabled=false`")
    # Disable SignalWire but keep creds
    await disable_signalwire_via_db(disable=True)
    cur = await admin_get_integrations(client, token)
    if cur["signalwire"]["enabled"] is False:
        ok("SignalWire enabled=false in DB (precondition)")
    else:
        fail("SignalWire disable precondition", f"sw={cur['signalwire']}")
    # Call test endpoint
    r = await client.post(
        f"{BACKEND}/admin/integrations/signalwire/test",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_number": "+18325551234", "body": "test"},
    )
    if r.status_code == 200:
        body = r.json()
        info = body.get("info", "")
        # must have attempted the network call — info should NOT be "not enabled"
        if "not enabled" not in info.lower():
            ok(f"signalwire test bypassed enabled flag (info={info[:120]!r})")
        else:
            fail("signalwire test bypass", f"info still says not enabled: {info!r}")
    else:
        fail("signalwire test 200", f"status={r.status_code} body={r.text[:200]}")

    # Twilio test — Twilio is also disabled in DB. The legacy send_sms_via_twilio
    # short-circuits if disabled. Per review request, Twilio test should also bypass.
    r = await client.post(
        f"{BACKEND}/admin/integrations/twilio/test",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_number": "+18325551234", "body": "test"},
    )
    if r.status_code == 200:
        body = r.json()
        info = body.get("info", "")
        if "disabled" not in info.lower():
            ok(f"twilio test bypassed enabled flag (info={info[:120]!r})")
        else:
            fail("twilio test bypass", f"info says disabled: {info!r}")
    else:
        fail("twilio test status", f"status={r.status_code} body={r.text[:200]}")

    await disable_signalwire_via_db(disable=False)


async def test_signalwire_save_ux_guard(client, token):
    section("7. SignalWire save UX guard — auto-flip enabled when all fields set")
    # Back up encrypted secrets so we can restore them after the test
    from motor.motor_asyncio import AsyncIOMotorClient
    cli = AsyncIOMotorClient("mongodb://localhost:27017")
    db = cli["test_database"]
    backup_rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0})
    backup_sw = dict((backup_rec or {}).get("signalwire") or {})
    cli.close()

    # First: ensure full creds, set enabled=false via DB, then re-save with enabled=false
    # WITHOUT new project_id/api_token → should auto-flip to enabled=true.
    await disable_signalwire_via_db(disable=True)
    cur = await admin_get_integrations(client, token)
    # Save with enabled=false BUT no new project_id/api_token, full space+from_number echoed
    payload = {
        "enabled": False,
        "space_url": cur["signalwire"]["space_url"],
        "from_number": cur["signalwire"]["from_number"],
    }
    r = await client.post(
        f"{BACKEND}/admin/integrations/signalwire",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    if r.status_code == 200:
        cur2 = await admin_get_integrations(client, token)
        if cur2["signalwire"]["enabled"] is True:
            ok("save with enabled=false + no new creds + all 4 fields → auto-flipped to enabled=true")
        else:
            fail("UX guard auto-flip", f"signalwire still disabled: {cur2['signalwire']}")
    else:
        fail("UX guard save status", f"status={r.status_code} body={r.text[:200]}")

    # 7b: save with enabled=false AND a new project_id → respect explicit toggle
    payload = {
        "enabled": False,
        "project_id": "PROJ_TEST_NEW_VAL_PHASEH6",
        "space_url": cur["signalwire"]["space_url"],
        "from_number": cur["signalwire"]["from_number"],
    }
    r = await client.post(
        f"{BACKEND}/admin/integrations/signalwire",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    if r.status_code == 200:
        cur2 = await admin_get_integrations(client, token)
        if cur2["signalwire"]["enabled"] is False:
            ok("save with enabled=false + new project_id → respects explicit disable")
        else:
            fail("UX guard respect explicit", f"signalwire={cur2['signalwire']}")
    else:
        fail("UX guard explicit save status", f"status={r.status_code} body={r.text[:200]}")

    # Restore the real signalwire creds (we wrote a fake project_id_enc above).
    cli = AsyncIOMotorClient("mongodb://localhost:27017")
    db = cli["test_database"]
    # Restore enabled, project_id_enc, api_token_enc to backed-up values
    restore_set = {
        "signalwire.project_id_enc": backup_sw.get("project_id_enc"),
        "signalwire.api_token_enc": backup_sw.get("api_token_enc"),
        "signalwire.enabled": backup_sw.get("enabled", True),
        "signalwire.space_url": backup_sw.get("space_url"),
        "signalwire.from_number": backup_sw.get("from_number"),
    }
    await db.app_settings.update_one({"key": "integrations"}, {"$set": restore_set})
    cli.close()
    print("    [info] Real SignalWire creds restored from backup.")


async def test_lookup_phone(client, token):
    section("8. /api/auth/lookup-phone — regression check")
    # Create + verify a user (mock mode)
    await set_sms_mode(client, token, "mock")
    uid = await _register_user(client, f"LookupUser{int(time.time())}")
    phone = f"+1832777{int(time.time()) % 10000:04d}"
    await client.post(f"{BACKEND}/auth/send-otp", json={"user_id": uid, "phone": phone})
    rv = await client.post(f"{BACKEND}/auth/verify-otp",
                           json={"user_id": uid, "phone": phone, "code": "123456"})
    if rv.status_code != 200:
        fail("lookup-phone setup", f"verify status={rv.status_code}")
        return
    # Look up by phone
    r = await client.get(f"{BACKEND}/auth/lookup-phone", params={"phone": phone})
    if r.status_code == 200:
        body = r.json()
        if body.get("exists") is True and body.get("name", "").startswith("LookupUser"):
            ok(f"lookup-phone existing user -> exists=true, name={body.get('name')}")
        else:
            fail("lookup-phone existing", f"body={body}")
    else:
        fail("lookup-phone status", f"status={r.status_code} body={r.text[:200]}")
    # Unknown phone
    r = await client.get(f"{BACKEND}/auth/lookup-phone", params={"phone": "+19999990001"})
    if r.status_code == 200 and r.json().get("exists") is False:
        ok("lookup-phone unknown -> exists=false")
    else:
        fail("lookup-phone unknown", f"status={r.status_code} body={r.text[:200]}")


async def test_reminders_imports():
    section("9. Reminders module imports + ends up using mode-aware send_sms")
    sys.path.insert(0, "/app/backend")
    try:
        import importlib
        import reminders
        importlib.reload(reminders)
        ok("reminders.py imports without error")
    except Exception as e:
        fail("reminders import", f"{e}")
        return
    # reminders.py uses send_sms_via_twilio (legacy alias) — but inspect integrations.py
    # to confirm it's a thin wrapper that delegates to sms_providers.send_sms (mode-aware).
    import inspect
    import integrations
    legacy_src = inspect.getsource(integrations.send_sms_via_twilio)
    if "sms_providers" in legacy_src and "send_sms" in legacy_src:
        ok("integrations.send_sms_via_twilio delegates to sms_providers.send_sms (mode-aware)")
    else:
        fail("legacy delegation", "send_sms_via_twilio does NOT delegate to multi-provider")
    rsrc = inspect.getsource(reminders)
    if "send_sms_via_twilio" in rsrc:
        ok("reminders.py calls send_sms_via_twilio → which delegates to mode-aware send_sms()")
    else:
        fail("reminders source", "expected send_sms_via_twilio call in reminders.py")


async def cleanup(client, token):
    section("Cleanup — leave system in mock mode")
    await set_sms_mode(client, token, "mock")
    cur = await admin_get_integrations(client, token)
    print(f"    Final state: sms_routing={cur.get('sms_routing')}")


async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        token = await admin_login(client)
        print(f"Admin login OK. Backend: {BACKEND}")

        await test_phone_normalization()
        await test_sms_mode_toggle(client, token)
        await test_send_otp_mock_mode(client, token)
        await test_send_otp_live_mode(client, token)
        await test_send_otp_live_mode_failure(client, token)
        await test_verify_otp_mode_safety(client, token)
        await test_sensitive_otp(client, token)
        await test_admin_test_endpoints_bypass_enabled(client, token)
        await test_signalwire_save_ux_guard(client, token)
        await test_lookup_phone(client, token)
        await test_reminders_imports()

        await cleanup(client, token)

    print("\n" + "=" * 60)
    print(f"PASSED: {len(PASSED)}")
    print(f"FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for n, d in FAILED:
            print(f"  ❌ {n}: {d}")
        sys.exit(1)
    else:
        print("All H6 assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
