"""Phase G2 — KMS + key rotation backend tests."""
import os
import re
import time
import json
import sys
import requests

BASE = os.environ.get("BACKEND_URL") or "https://joint-pay-1.preview.emergentagent.com"
API = BASE.rstrip("/") + "/api"

ADMIN_EMAIL = "[email protected]"
ADMIN_PASSWORD = "ChangeMe123!"

results = []


def rec(name, ok, detail=""):
    results.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))


def login(email, password):
    r = requests.post(f"{API}/admin/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        return None, r
    return r.json()["token"], r


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def ensure_manager_admin(super_tok):
    """Create a manager admin (or re-use existing) and return its token."""
    ts = int(time.time())
    email = f"kms_mgr_{ts}@kwiktech.net"
    pw = "MgrPass12345!"
    r = requests.post(
        f"{API}/admin/admins",
        headers=auth(super_tok),
        json={"email": email, "password": pw, "name": "KMS Mgr", "role": "manager"},
        timeout=20,
    )
    if r.status_code not in (200, 409):
        print("manager create unexpected", r.status_code, r.text[:200])
        return None
    tok, _ = login(email, pw)
    return tok


def main():
    print(f"Target: {API}")

    # ------- 0. super_admin login -------
    stok, r = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    rec("0. super_admin login", bool(stok), f"status={r.status_code}")
    if not stok:
        print("aborting; cannot login as super_admin")
        sys.exit(1)

    # ------- 1. GET /security/kms-status with super_admin -------
    r = requests.get(f"{API}/admin/security/kms-status", headers=auth(stok), timeout=20)
    ok = r.status_code == 200
    body = r.json() if ok else {}
    rec("1.a GET kms-status returns 200", ok, f"status={r.status_code} body={str(body)[:180]}")

    if ok:
        key_source = body.get("key_source")
        secure = body.get("secure")
        fp = body.get("primary_fingerprint")
        legacy = body.get("legacy_fingerprints")
        warn = body.get("warning")
        enc_count = body.get("encrypted_field_count")
        rec("1.b key_source == 'jwt_derived'", key_source == "jwt_derived", f"got {key_source!r}")
        rec("1.c secure == false", secure is False, f"got {secure!r}")
        rec("1.d primary_fingerprint is 8 hex chars", isinstance(fp, str) and bool(re.fullmatch(r"[0-9a-f]{8}", fp or "")), f"got {fp!r}")
        rec("1.e legacy_fingerprints == []", isinstance(legacy, list) and legacy == [], f"got {legacy!r}")
        rec("1.f warning non-null str", isinstance(warn, str) and len(warn) > 0, f"got {str(warn)[:60]!r}")
        rec("1.g encrypted_field_count is int", isinstance(enc_count, int), f"got {enc_count!r} ({type(enc_count).__name__})")

    initial_fp = body.get("primary_fingerprint") if ok else None

    # ------- 2. POST /security/kms-rotate (twice — idempotent) -------
    r1 = requests.post(f"{API}/admin/security/kms-rotate", headers=auth(stok), timeout=30)
    ok1 = r1.status_code == 200
    j1 = r1.json() if ok1 else {}
    rec("2.a kms-rotate 1st call 200", ok1, f"status={r1.status_code} body={str(j1)[:220]}")
    if ok1:
        for key in ("rotated", "skipped", "failed", "elapsed_ms", "primary_fingerprint", "key_source"):
            rec(f"2.a shape has {key}", key in j1, f"keys={sorted(j1.keys())}")
        rec("2.a failed == 0", j1.get("failed") == 0, f"failed={j1.get('failed')!r}")
        rec("2.a primary_fingerprint matches status", j1.get("primary_fingerprint") == initial_fp,
            f"rotate={j1.get('primary_fingerprint')!r} status={initial_fp!r}")

    # Second call — must still be 200 and failed==0
    r2 = requests.post(f"{API}/admin/security/kms-rotate", headers=auth(stok), timeout=30)
    ok2 = r2.status_code == 200
    j2 = r2.json() if ok2 else {}
    rec("2.b kms-rotate 2nd call 200 (idempotent)", ok2, f"status={r2.status_code} body={str(j2)[:220]}")
    if ok2:
        rec("2.b 2nd call failed == 0", j2.get("failed") == 0, f"failed={j2.get('failed')!r}")

    # ------- 3. POST /security/kms-reload -------
    r = requests.post(f"{API}/admin/security/kms-reload", headers=auth(stok), timeout=20)
    ok = r.status_code == 200
    body3 = r.json() if ok else {}
    rec("3.a kms-reload 200", ok, f"status={r.status_code} body={str(body3)[:220]}")
    if ok:
        for k in ("key_source", "secure", "primary_fingerprint", "legacy_fingerprints", "warning"):
            rec(f"3.b reload has {k}", k in body3, f"keys={sorted(body3.keys())}")
        rec("3.c reload key_source == 'jwt_derived'", body3.get("key_source") == "jwt_derived",
            f"got {body3.get('key_source')!r}")

    # ------- 4. RBAC -------
    mtok = ensure_manager_admin(stok)
    if not mtok:
        rec("4. manager login", False, "could not create or login as manager")
    else:
        rec("4.0 manager login", True)

        r = requests.post(f"{API}/admin/security/kms-rotate", headers=auth(mtok), timeout=20)
        rec("4.a kms-rotate as manager → 403", r.status_code == 403,
            f"status={r.status_code} body={r.text[:120]}")

        r = requests.post(f"{API}/admin/security/kms-reload", headers=auth(mtok), timeout=20)
        rec("4.b kms-reload as manager → 403", r.status_code == 403,
            f"status={r.status_code} body={r.text[:120]}")

        r = requests.get(f"{API}/admin/security/kms-status", headers=auth(mtok), timeout=20)
        rec("4.c kms-status as manager → 200", r.status_code == 200,
            f"status={r.status_code} body={r.text[:120]}")

    # ------- 5. Audit log entries -------
    r = requests.get(f"{API}/admin/audit-log?limit=100", headers=auth(stok), timeout=20)
    if r.status_code != 200:
        rec("5. audit-log fetch", False, f"status={r.status_code}")
    else:
        items = r.json().get("items") or []
        rotate_items = [it for it in items if it.get("action") == "admin.kms_rotate"]
        reload_items = [it for it in items if it.get("action") == "admin.kms_reload"]
        rec("5.a audit has admin.kms_rotate entry", len(rotate_items) >= 1,
            f"found {len(rotate_items)} rotate entries")
        if rotate_items:
            rec("5.b admin.kms_rotate destructive=true", rotate_items[0].get("destructive") is True,
                f"destructive={rotate_items[0].get('destructive')!r}")
        rec("5.c audit has admin.kms_reload entry", len(reload_items) >= 1,
            f"found {len(reload_items)} reload entries")
        if reload_items:
            rec("5.d admin.kms_reload destructive=false", reload_items[0].get("destructive") is False,
                f"destructive={reload_items[0].get('destructive')!r}")

    # ------- 6. Regression -------
    # 6.a Twilio disable
    r = requests.post(
        f"{API}/admin/integrations/twilio",
        headers=auth(stok),
        json={"enabled": False},
        timeout=20,
    )
    rec("6.a POST /integrations/twilio {enabled:false} → 200", r.status_code == 200,
        f"status={r.status_code} body={r.text[:160]}")

    # 6.b SignalWire disable
    r = requests.post(
        f"{API}/admin/integrations/signalwire",
        headers=auth(stok),
        json={"enabled": False},
        timeout=20,
    )
    rec("6.b POST /integrations/signalwire {enabled:false} → 200", r.status_code == 200,
        f"status={r.status_code} body={r.text[:160]}")

    # 6.c GET integrations has expected keys
    r = requests.get(f"{API}/admin/integrations", headers=auth(stok), timeout=20)
    ok = r.status_code == 200
    j = r.json() if ok else {}
    rec("6.c GET /integrations → 200", ok, f"status={r.status_code}")
    for k in ("stripe", "twilio", "signalwire", "sms_routing"):
        rec(f"6.c GET /integrations has '{k}'", k in j, f"keys={sorted(j.keys())}")

    # 6.d admin auth path still works (login + /me)
    stok2, r_login2 = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    rec("6.d admin login → 200", bool(stok2), f"status={r_login2.status_code}")
    if stok2:
        r = requests.get(f"{API}/admin/auth/me", headers=auth(stok2), timeout=20)
        rec("6.d admin /auth/me → 200", r.status_code == 200,
            f"status={r.status_code} body={r.text[:160]}")

    # 6.e /auth/send-otp for a user
    ts = int(time.time())
    r = requests.post(f"{API}/auth/register", json={"name": f"KMS Test {ts}"}, timeout=20)
    if r.status_code == 200:
        uid = r.json().get("user_id") or r.json().get("id")
        phone = f"+1555911{ts % 10000:04d}"
        r = requests.post(f"{API}/auth/send-otp", json={"user_id": uid, "phone": phone}, timeout=20)
        rec("6.e POST /auth/send-otp → 200", r.status_code == 200,
            f"status={r.status_code} body={r.text[:160]}")
    else:
        rec("6.e auth/register precondition", False, f"register status={r.status_code}")

    # ------- 7. Twilio save + round-trip via crypto_kms -------
    r = requests.post(
        f"{API}/admin/integrations/twilio",
        headers=auth(stok),
        json={"enabled": True, "account_sid": "AC123", "auth_token": "abc", "from_number": "+15555550001"},
        timeout=20,
    )
    rec("7.a POST /twilio with AC123/abc → 200", r.status_code == 200,
        f"status={r.status_code} body={r.text[:200]}")

    r = requests.get(f"{API}/admin/integrations", headers=auth(stok), timeout=20)
    if r.status_code == 200:
        t = (r.json() or {}).get("twilio") or {}
        sid_m = t.get("account_sid_masked") or ""
        sid_set = t.get("account_sid_set")
        tok_set = t.get("auth_token_set")
        tok_m = t.get("auth_token_masked") or ""
        rec("7.b account_sid_set==true", sid_set is True, f"got {sid_set!r}")
        rec("7.b auth_token_set==true", tok_set is True, f"got {tok_set!r}")
        # AC123 has 5 chars; mask_secret returns last 4 visible — "*C123"
        rec("7.c account_sid_masked ends with 'C123'", sid_m.endswith("C123"),
            f"got {sid_m!r}")
        rec("7.c auth_token_masked is masked (not 'abc' plaintext)",
            tok_m != "abc" and "*" in tok_m,
            f"got {tok_m!r}")
        rec("7.d raw plaintext 'AC123' NOT present in payload",
            "AC123" not in r.text,
            f"response contains 'AC123'" if "AC123" in r.text else "ok")
    else:
        rec("7.b GET integrations after twilio save", False, f"status={r.status_code}")

    # Clean up — disable twilio again
    requests.post(
        f"{API}/admin/integrations/twilio",
        headers=auth(stok),
        json={"enabled": False},
        timeout=20,
    )

    # ------- summary -------
    print("\n=========== SUMMARY ===========")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"Passed: {passed}/{len(results)}   Failed: {failed}")
    if failed:
        print("\nFAILED CASES:")
        for name, ok, detail in results:
            if not ok:
                print(f"  [FAIL] {name} — {detail}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
