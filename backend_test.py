"""Phase F2.2 — SignalWire SMS provider integration + multi-provider failover tests.

Runs against the live preview backend. Verifies:
  1) GET /api/admin/integrations now exposes signalwire + sms_routing.
  2) POST /api/admin/integrations/signalwire (super_admin) — masking, normalization,
     enabled-toggle preserves creds.
  3) POST /api/admin/integrations/sms-routing — primary/fallback handling, equal -> null.
  4) POST /api/admin/integrations/signalwire/test — graceful 200 with sent_real=false
     when disabled / creds incomplete.
  5) Audit log entries: admin.update_signalwire_settings, admin.update_sms_routing,
     admin.test_signalwire.
  6) Regression — /api/auth/send-otp + /api/admin/integrations/twilio still work.
  7) Role enforcement — non-super_admin blocked from signalwire / sms-routing writes.
"""
import os
import sys
import time
import json
import re
from typing import Any, Optional

import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://joint-pay-1.preview.emergentagent.com"
API = f"{BASE.rstrip('/')}/api"

ADMIN_EMAIL = "[email protected]"
ADMIN_PASS = "ChangeMe123!"

PASS = []
FAIL = []
TS = int(time.time())


def _log(ok: bool, name: str, detail: str = ""):
    target = PASS if ok else FAIL
    target.append((name, detail))
    icon = "PASS" if ok else "FAIL"
    print(f"[{icon}] {name}" + (f" :: {detail}" if detail else ""))


def admin_login() -> str:
    r = requests.post(f"{API}/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def section(title: str):
    print()
    print("=" * 70)
    print(f"# {title}")
    print("=" * 70)


# ---------------- 1) GET /api/admin/integrations shape ----------------

def test_get_integrations_shape(tok: str):
    section("1) GET /api/admin/integrations — shape")
    r = requests.get(f"{API}/admin/integrations", headers=hdr(tok), timeout=20)
    _log(r.status_code == 200, "GET /admin/integrations status==200", f"got {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return None
    data = r.json()
    _log("signalwire" in data, "response includes 'signalwire' key")
    _log("sms_routing" in data, "response includes 'sms_routing' key")
    sw = data.get("signalwire") or {}
    routing = data.get("sms_routing") or {}
    for f in ("enabled", "project_id_masked", "project_id_set", "api_token_set", "api_token_masked", "space_url", "from_number"):
        _log(f in sw, f"signalwire.{f} present", f"keys={list(sw.keys())}")
    _log("primary" in routing and "fallback" in routing, "sms_routing.primary/fallback present")
    return data


# ---------------- 2) POST /api/admin/integrations/signalwire ----------------

def test_set_signalwire(tok: str):
    section("2) POST /api/admin/integrations/signalwire (super_admin)")
    body = {
        "enabled": True,
        "project_id": "PA-1234",
        "api_token": "PT_secret_token_xyz",
        "space_url": "https://example.signalwire.com/",
        "from_number": "+15551234567",
    }
    r = requests.post(f"{API}/admin/integrations/signalwire", headers=hdr(tok), json=body, timeout=20)
    _log(r.status_code == 200, "POST signalwire status==200", f"got {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return
    data = r.json()
    sw = data.get("signalwire") or {}
    _log(sw.get("enabled") is True, "signalwire.enabled True after save")
    _log(sw.get("project_id_set") is True, "project_id_set True")
    _log(sw.get("api_token_set") is True, "api_token_set True")
    pid = sw.get("project_id_masked") or ""
    _log(pid.endswith("1234") and "*" in pid, f"project_id_masked='{pid}' ends with '1234' and contains '*'")
    _log(sw.get("space_url") == "example.signalwire.com",
         f"space_url normalized (no scheme/trailing slash) -> got '{sw.get('space_url')}'")
    _log(sw.get("from_number") == "+15551234567", f"from_number persists -> '{sw.get('from_number')}'")

    # Now: send only enabled=false → should not wipe creds
    r2 = requests.post(f"{API}/admin/integrations/signalwire", headers=hdr(tok), json={"enabled": False}, timeout=20)
    _log(r2.status_code == 200, "POST signalwire {enabled:false} status==200", f"got {r2.status_code}: {r2.text[:200]}")
    if r2.status_code == 200:
        sw2 = (r2.json().get("signalwire") or {})
        _log(sw2.get("enabled") is False, "second update — enabled False")
        _log(sw2.get("project_id_set") is True, "project_id_set still True after toggle (creds preserved)")
        _log(sw2.get("api_token_set") is True, "api_token_set still True after toggle (creds preserved)")
        _log(sw2.get("space_url") == "example.signalwire.com",
             f"space_url still 'example.signalwire.com' -> '{sw2.get('space_url')}'")


# ---------------- 3) POST /api/admin/integrations/sms-routing ----------------

def test_sms_routing(tok: str):
    section("3) POST /api/admin/integrations/sms-routing")

    r1 = requests.post(f"{API}/admin/integrations/sms-routing", headers=hdr(tok),
                       json={"primary": "signalwire", "fallback": "twilio"}, timeout=20)
    _log(r1.status_code == 200, "routing primary=signalwire fallback=twilio: 200",
         f"got {r1.status_code}: {r1.text[:200]}")
    if r1.status_code == 200:
        rt = r1.json().get("sms_routing") or {}
        _log(rt.get("primary") == "signalwire", f"primary == signalwire (got {rt.get('primary')})")
        _log(rt.get("fallback") == "twilio", f"fallback == twilio (got {rt.get('fallback')})")

    r2 = requests.post(f"{API}/admin/integrations/sms-routing", headers=hdr(tok),
                       json={"primary": "twilio", "fallback": None}, timeout=20)
    _log(r2.status_code == 200, "routing primary=twilio fallback=null: 200",
         f"got {r2.status_code}: {r2.text[:200]}")
    if r2.status_code == 200:
        rt = r2.json().get("sms_routing") or {}
        _log(rt.get("primary") == "twilio", f"primary == twilio (got {rt.get('primary')})")
        _log(rt.get("fallback") is None, f"fallback is None (got {rt.get('fallback')})")

    r3 = requests.post(f"{API}/admin/integrations/sms-routing", headers=hdr(tok),
                       json={"primary": "signalwire", "fallback": "signalwire"}, timeout=20)
    _log(r3.status_code == 200, "routing primary=fallback=signalwire: 200",
         f"got {r3.status_code}: {r3.text[:200]}")
    if r3.status_code == 200:
        rt = r3.json().get("sms_routing") or {}
        _log(rt.get("primary") == "signalwire", f"primary == signalwire")
        _log(rt.get("fallback") is None,
             f"fallback nulled when equal to primary (got {rt.get('fallback')})")


# ---------------- 4) signalwire/test endpoint ----------------

def test_signalwire_test_endpoint(tok: str):
    section("4) POST /api/admin/integrations/signalwire/test (disabled)")
    # We just disabled SW above (enabled=false but creds present). The test endpoint
    # should still gracefully return 200 with sent_real=false.
    body = {"to_number": "+15551234567"}
    r = requests.post(f"{API}/admin/integrations/signalwire/test", headers=hdr(tok), json=body, timeout=20)
    _log(r.status_code == 200, "signalwire/test status==200 (no 500)",
         f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        d = r.json()
        _log(d.get("sent_real") is False, f"sent_real False (got {d.get('sent_real')})")
        info = (d.get("info") or "").lower()
        _log(any(s in info for s in ["not enabled", "credentials incomplete", "disabled", "incomplete"]),
             f"info contains explanatory message (got '{d.get('info')}')")


# ---------------- 5) Audit log ----------------

def test_audit_log_entries(tok: str):
    section("5) Audit log entries")
    r = requests.get(f"{API}/admin/audit-log", headers=hdr(tok), params={"limit": 200}, timeout=20)
    _log(r.status_code == 200, "GET /admin/audit-log status==200", f"got {r.status_code}")
    if r.status_code != 200:
        return
    actions = [it.get("action") for it in (r.json().get("items") or [])]
    for needed in ("admin.update_signalwire_settings", "admin.update_sms_routing", "admin.test_signalwire"):
        _log(needed in actions, f"audit-log contains '{needed}'", f"actions sample={actions[:10]}")


# ---------------- 6) Regression — OTP + Twilio admin endpoint ----------------

def test_regressions(tok: str):
    section("6) Regression — OTP send & Twilio admin endpoint")

    # 6a) Register a fresh user, send OTP
    name = f"PhaseF22User{TS}"
    rr = requests.post(f"{API}/auth/register", json={"name": name}, timeout=20)
    _log(rr.status_code == 200, "register fresh user 200", f"got {rr.status_code}: {rr.text[:160]}")
    if rr.status_code != 200:
        return
    uid = rr.json().get("user_id") or rr.json().get("id")
    phone = "+15555550100"
    rs = requests.post(f"{API}/auth/send-otp", json={"user_id": uid, "phone": phone}, timeout=20)
    _log(rs.status_code == 200, f"send-otp 200 (no 500) phone={phone}",
         f"got {rs.status_code}: {rs.text[:200]}")
    # verify-otp with mock 123456 should still work
    rv = requests.post(f"{API}/auth/verify-otp", json={"user_id": uid, "phone": phone, "code": "123456"}, timeout=20)
    _log(rv.status_code in (200, 403), f"verify-otp returns 200 or 403 (no 500) (got {rv.status_code})",
         rv.text[:200])

    # 6b) Twilio admin endpoint still works
    rt = requests.post(f"{API}/admin/integrations/twilio",
                       headers=hdr(tok),
                       json={"enabled": False, "from_number": "+15555550001"},
                       timeout=20)
    _log(rt.status_code == 200, "POST /admin/integrations/twilio 200",
         f"got {rt.status_code}: {rt.text[:200]}")
    # Sanity GET
    rg = requests.get(f"{API}/admin/integrations", headers=hdr(tok), timeout=20)
    _log(rg.status_code == 200 and "twilio" in rg.json(), "GET integrations still has twilio block")


# ---------------- 7) Role enforcement ----------------

def test_role_enforcement(super_tok: str):
    section("7) Role enforcement (manager admin -> 403 on signalwire/sms-routing)")
    # Create a manager-role admin
    email = f"mgr_f22_{TS}@kwiktech.net"
    pw = "MgrPass123!"
    r = requests.post(f"{API}/admin/admins", headers=hdr(super_tok),
                      json={"email": email, "password": pw, "role": "manager", "name": "F22 Mgr"}, timeout=20)
    if r.status_code not in (200, 201):
        _log(False, "create manager admin (could not test RBAC)", f"{r.status_code}: {r.text[:200]}")
        return
    # Login as manager
    rl = requests.post(f"{API}/admin/auth/login", json={"email": email, "password": pw}, timeout=20)
    if rl.status_code != 200:
        _log(False, "manager login (could not test RBAC)", f"{rl.status_code}: {rl.text[:200]}")
        return
    mgr_tok = rl.json()["token"]

    rsw = requests.post(f"{API}/admin/integrations/signalwire", headers=hdr(mgr_tok),
                        json={"enabled": False}, timeout=20)
    _log(rsw.status_code == 403, "manager cannot POST signalwire (403)", f"got {rsw.status_code}: {rsw.text[:200]}")

    rrt = requests.post(f"{API}/admin/integrations/sms-routing", headers=hdr(mgr_tok),
                        json={"primary": "twilio", "fallback": None}, timeout=20)
    _log(rrt.status_code == 403, "manager cannot POST sms-routing (403)", f"got {rrt.status_code}: {rrt.text[:200]}")

    # Manager IS allowed on signalwire/test (super_admin OR manager)
    rt = requests.post(f"{API}/admin/integrations/signalwire/test", headers=hdr(mgr_tok),
                       json={"to_number": "+15551234567"}, timeout=20)
    _log(rt.status_code == 200, "manager CAN POST signalwire/test (200)",
         f"got {rt.status_code}: {rt.text[:200]}")


def main():
    print(f"BASE={BASE}")
    print(f"API={API}")
    tok = admin_login()
    test_get_integrations_shape(tok)
    test_set_signalwire(tok)
    test_sms_routing(tok)
    test_signalwire_test_endpoint(tok)
    test_audit_log_entries(tok)
    test_regressions(tok)
    test_role_enforcement(tok)

    print()
    print("=" * 70)
    print(f"PASS: {len(PASS)}    FAIL: {len(FAIL)}")
    print("=" * 70)
    if FAIL:
        print("\nFAILED ASSERTIONS:")
        for n, d in FAIL:
            print(f"  - {n} :: {d}")
    sys.exit(0 if not FAIL else 1)


if __name__ == "__main__":
    main()
