"""Phase D — Integrations (Stripe + Twilio + Reminders) backend test suite.

Run: python /app/backend_test.py
Reads EXPO_PUBLIC_BACKEND_URL from /app/frontend/.env, all calls under /api.
Admin credentials: super_admin from /app/memory/test_credentials.md.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, List, Optional

import requests


def _load_backend_url() -> str:
    env_path = "/app/frontend/.env"
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not found")


BASE = _load_backend_url().rstrip("/") + "/api"
SUPER_EMAIL = "[email protected]"
SUPER_PASS = "ChangeMe123!"
OTP = "123456"
TS = int(time.time())

PASSED: List[str] = []
FAILED: List[str] = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  PASS {label}")
        PASSED.append(label)
    else:
        print(f"  FAIL {label} :: {detail}")
        FAILED.append(f"{label} :: {detail}")


def req(method: str, path: str, token: Optional[str] = None, json_body=None, expect=None, ok_codes=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{BASE}{path}"
    try:
        r = requests.request(method, url, headers=headers, json=json_body, timeout=30)
    except Exception as e:
        print(f"    HTTP EXCEPTION {method} {path}: {e}")
        raise
    if expect is not None and r.status_code != expect:
        print(f"    !! {method} {path} expected {expect}, got {r.status_code}: {r.text[:200]}")
    elif ok_codes is not None and r.status_code not in ok_codes:
        print(f"    !! {method} {path} expected one of {ok_codes}, got {r.status_code}: {r.text[:200]}")
    return r


def admin_login(email=SUPER_EMAIL, password=SUPER_PASS) -> str:
    r = req("POST", "/admin/auth/login", json_body={"email": email, "password": password}, expect=200)
    return r.json()["token"]


def create_support_admin(super_token: str, role: str = "support") -> Dict[str, str]:
    email = f"{role}_{TS}@example.com"
    password = "SupportPass123!"
    body = {"email": email, "password": password, "name": f"{role.capitalize()} {TS}", "role": role}
    r = req("POST", "/admin/admins", token=super_token, json_body=body)
    if r.status_code not in (200, 409):
        raise RuntimeError(f"Failed to create {role} admin: {r.status_code} {r.text[:200]}")
    lr = req("POST", "/admin/auth/login", json_body={"email": email, "password": password}, expect=200)
    return {"email": email, "password": password, "token": lr.json()["token"]}


def register_user(name: str) -> str:
    r = req("POST", "/auth/register", json_body={"name": name}, expect=200)
    return r.json()["id"]


# ---------- MAIN ----------

def main():
    print(f"BASE={BASE}")
    print(f"TS={TS}")
    print()

    # --- Admin logins ---
    super_token = admin_login()
    print("Super admin logged in OK")

    support = create_support_admin(super_token, role="support")
    manager = create_support_admin(super_token, role="manager")
    print(f"Support admin: {support['email']}")
    print(f"Manager admin: {manager['email']}")
    print()

    # ================= A) Auth & shape =================
    print("===== A) Auth & shape =====")
    r = req("GET", "/admin/integrations")
    check("A.no-bearer-401", r.status_code == 401, f"status={r.status_code}")

    r = req("GET", "/admin/integrations", token=super_token)
    check("A.super-200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    data = r.json() if r.status_code == 200 else {}
    check("A.has-stripe", isinstance(data.get("stripe"), dict))
    check("A.has-twilio", isinstance(data.get("twilio"), dict))
    check("A.has-reminders", isinstance(data.get("reminders"), dict))
    # no plaintext secret fields present in any sub-object
    forbidden = {"secret_key", "auth_token", "webhook_secret"}
    any_forbidden = False
    for key in ("stripe", "twilio", "reminders"):
        sub = data.get(key) or {}
        if any(f in sub for f in forbidden):
            any_forbidden = True
            break
    check("A.no-plaintext-keys", not any_forbidden, f"plaintext keys present in {data}")

    # ================= B) Stripe save =================
    print()
    print("===== B) Stripe save =====")
    body = {
        "enabled": True,
        "mode": "test",
        "publishable_key": "pk_test_PHASEDX",
        "secret_key": "sk_test_PHDsecret9999",
        "webhook_secret": "whsec_PHDhook12345",
    }
    r = req("POST", "/admin/integrations/stripe", token=super_token, json_body=body)
    check("B.stripe-save-200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    r = req("GET", "/admin/integrations", token=super_token, expect=200)
    s = r.json().get("stripe", {})
    check("B.publishable-key", s.get("publishable_key") == "pk_test_PHASEDX", f"got={s.get('publishable_key')}")
    check("B.secret-set", s.get("secret_key_set") is True)
    secret_masked = s.get("secret_key_masked", "")
    check("B.secret-masked-ends-9999", secret_masked.endswith("9999"), f"got={secret_masked!r}")
    check("B.secret-masked-has-asterisk", "*" in secret_masked, f"got={secret_masked!r}")
    check("B.webhook-set", s.get("webhook_secret_set") is True)
    webhook_masked = s.get("webhook_secret_masked", "")
    check("B.webhook-masked-ends-2345", webhook_masked.endswith("2345"), f"got={webhook_masked!r}")

    # Re-save with omitted secret_key -> preserve existing
    body2 = {
        "enabled": True,
        "mode": "test",
        "publishable_key": "pk_test_PHASEDX",
    }
    r = req("POST", "/admin/integrations/stripe", token=super_token, json_body=body2, expect=200)
    r = req("GET", "/admin/integrations", token=super_token, expect=200)
    s = r.json().get("stripe", {})
    check("B.resave-secret-preserved-set", s.get("secret_key_set") is True)
    check("B.resave-secret-preserved-masked-9999", s.get("secret_key_masked", "").endswith("9999"),
          f"got={s.get('secret_key_masked')!r}")

    # Support admin cannot POST stripe
    r = req("POST", "/admin/integrations/stripe", token=support["token"], json_body=body2)
    check("B.support-stripe-403", r.status_code == 403, f"status={r.status_code} body={r.text[:200]}")

    # ================= C) Twilio save =================
    print()
    print("===== C) Twilio save =====")
    body_tw = {
        "enabled": False,
        "account_sid": "AC_PHDsidXXX",
        "auth_token": "tokPHDXXX",
        "from_number": "+15555550001",
    }
    r = req("POST", "/admin/integrations/twilio", token=super_token, json_body=body_tw)
    check("C.twilio-save-200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    r = req("GET", "/admin/integrations", token=super_token, expect=200)
    t = r.json().get("twilio", {})
    check("C.sid-set", t.get("account_sid_set") is True)
    # last 4 chars of 'AC_PHDsidXXX' are 'dXXX'
    check("C.sid-masked-ends-dXXX", t.get("account_sid_masked", "").endswith("dXXX"),
          f"got={t.get('account_sid_masked')!r}")
    check("C.from-number", t.get("from_number") == "+15555550001", f"got={t.get('from_number')}")

    # Manager admin should NOT be able to POST twilio (super_admin only)
    r = req("POST", "/admin/integrations/twilio", token=manager["token"], json_body=body_tw)
    check("C.manager-twilio-403", r.status_code == 403, f"status={r.status_code} body={r.text[:200]}")
    err_msg = (r.json().get("detail") or "") if r.status_code == 403 else ""
    check("C.manager-error-mentions-super_admin", "super_admin" in err_msg, f"detail={err_msg!r}")

    # ================= D) Twilio test SMS (disabled) =================
    print()
    print("===== D) Twilio test SMS (disabled) =====")
    r = req("POST", "/admin/integrations/twilio/test", token=super_token,
            json_body={"to_number": "+15551234567"})
    check("D.test-200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    tdata = r.json() if r.status_code == 200 else {}
    check("D.sent-real-false", tdata.get("sent_real") is False, f"got={tdata}")
    info = (tdata.get("info") or "").lower()
    check("D.info-has-twilio-disabled", "twilio disabled" in info, f"info={info!r}")

    # Support admin -> 403
    r = req("POST", "/admin/integrations/twilio/test", token=support["token"],
            json_body={"to_number": "+15551234567"})
    check("D.support-test-403", r.status_code == 403, f"status={r.status_code} body={r.text[:200]}")

    # ================= E) Reminders save + sanitization =================
    print()
    print("===== E) Reminders save + sanitization =====")
    r = req("POST", "/admin/integrations/reminders", token=super_token,
            json_body={"enabled": True, "schedule_hours": [24, 72, 168],
                       "max_reminders_per_user": 3, "send_via_sms": True})
    check("E.save-200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    rem = r.json().get("reminders", {})
    check("E.schedule-normal", rem.get("schedule_hours") == [24, 72, 168],
          f"got={rem.get('schedule_hours')}")

    # Sanitization: [0,-5,24,24,2000,72] -> [24,72,2000]
    r = req("POST", "/admin/integrations/reminders", token=super_token,
            json_body={"enabled": True, "schedule_hours": [0, -5, 24, 24, 2000, 72],
                       "max_reminders_per_user": 3, "send_via_sms": True})
    check("E.sanitize-200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    rem = r.json().get("reminders", {})
    check("E.schedule-sanitized", rem.get("schedule_hours") == [24, 72, 2000],
          f"got={rem.get('schedule_hours')}")

    # Support admin -> 403
    r = req("POST", "/admin/integrations/reminders", token=support["token"],
            json_body={"enabled": False, "schedule_hours": [24]})
    check("E.support-reminders-403", r.status_code == 403, f"status={r.status_code} body={r.text[:200]}")

    # ================= F) Reminders run-now =================
    print()
    print("===== F) Reminders run-now =====")
    r1 = req("POST", "/admin/integrations/reminders/run-now", token=super_token)
    check("F.runnow-200", r1.status_code == 200, f"status={r1.status_code} body={r1.text[:200]}")
    res1 = r1.json() if r1.status_code == 200 else {}
    check("F.enabled-true", res1.get("enabled") is True, f"got={res1.get('enabled')}")
    for key in ("scanned", "sent_real", "logged", "skipped", "schedule_hours"):
        check(f"F.has-{key}", key in res1, f"missing in {res1}")

    # ================= G) Reminders idempotency =================
    print()
    print("===== G) Reminders idempotency =====")
    r2 = req("POST", "/admin/integrations/reminders/run-now", token=super_token, expect=200)
    res2 = r2.json() if r2.status_code == 200 else {}
    # second call: logged+sent_real should be 0 (all already dedup'd) OR skipped >= first logged+sent_real
    first_new = int(res1.get("logged", 0)) + int(res1.get("sent_real", 0))
    second_new = int(res2.get("logged", 0)) + int(res2.get("sent_real", 0))
    second_skipped = int(res2.get("skipped", 0))
    check("G.idempotent",
          second_new == 0 or second_skipped >= first_new,
          f"first_new={first_new} second_new={second_new} second_skipped={second_skipped}")
    check("G.scanned-equal", res2.get("scanned") == res1.get("scanned"),
          f"first={res1.get('scanned')} second={res2.get('scanned')}")

    # ================= H) OTP with Twilio disabled =================
    print()
    print("===== H) OTP send-flow with Twilio disabled =====")
    user_id = register_user(f"PhaseDUser{TS}")
    phone = f"+15558887{TS % 1000:03d}"  # unique-ish
    r = req("POST", "/auth/send-otp", json_body={"user_id": user_id, "phone": phone})
    check("H.send-otp-200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    otp_data = r.json() if r.status_code == 200 else {}
    check("H.mocked-true", otp_data.get("mocked") is True, f"got={otp_data}")
    tw_info = (otp_data.get("twilio_info") or "").lower()
    check("H.twilio-info-has-disabled", "twilio disabled" in tw_info, f"info={tw_info!r}")

    # verify with mock OTP 123456
    r = req("POST", "/auth/verify-otp",
            json_body={"user_id": user_id, "phone": phone, "code": OTP})
    check("H.verify-otp-success", r.status_code == 200,
          f"status={r.status_code} body={r.text[:200]}")

    # ================= I) Encryption sanity =================
    print()
    print("===== I) Encryption sanity =====")
    r = req("GET", "/admin/integrations", token=super_token, expect=200)
    raw = r.text
    jraw = r.json()
    # No plaintext field names
    has_secret_key_field = any(f'"{k}"' in raw for k in ["secret_key", "auth_token", "webhook_secret"])
    # We need to allow *_masked and *_set keys, so check for exact "secret_key":, "auth_token":, "webhook_secret":
    import re
    bad_keys = re.findall(r'"(secret_key|auth_token|webhook_secret)"\s*:', raw)
    check("I.no-plaintext-field-names", len(bad_keys) == 0,
          f"found: {bad_keys}")
    # No values starting with 'sk_' or 'gAAAA' (Fernet)
    for bad_prefix in ["sk_test_PHDsecret", "gAAAA"]:
        check(f"I.no-value-{bad_prefix[:6]}", bad_prefix not in raw,
              f"Found substring {bad_prefix!r} in response (possible leak)")

    # ================= J) Audit destructive flags =================
    print()
    print("===== J) Audit destructive flags =====")
    r = req("GET", "/admin/audit-log?limit=50", token=super_token, expect=200)
    items = r.json().get("items", []) if r.status_code == 200 else []
    required = [
        "admin.update_stripe_settings",
        "admin.update_twilio_settings",
        "admin.test_twilio",
        "admin.update_reminder_settings",
        "admin.run_reminders_now",
    ]
    by_action: Dict[str, List[dict]] = {}
    for it in items:
        by_action.setdefault(it.get("action"), []).append(it)
    for action in required:
        rows = by_action.get(action, [])
        check(f"J.present-{action}", len(rows) > 0, f"no audit rows of {action}")
        if rows:
            check(f"J.destructive-{action}", rows[0].get("destructive") is True,
                  f"destructive={rows[0].get('destructive')}")

    # ================= K) Cleanup =================
    print()
    print("===== K) Cleanup =====")
    r = req("POST", "/admin/integrations/stripe", token=super_token,
            json_body={"enabled": False, "mode": "test"})
    check("K.stripe-cleanup-200", r.status_code == 200)

    r = req("POST", "/admin/integrations/twilio", token=super_token,
            json_body={"enabled": False})
    check("K.twilio-cleanup-200", r.status_code == 200)

    r = req("POST", "/admin/integrations/reminders", token=super_token,
            json_body={"enabled": False, "schedule_hours": [24, 72, 168],
                       "max_reminders_per_user": 3, "send_via_sms": True})
    check("K.reminders-cleanup-200", r.status_code == 200)

    # ---------- Summary ----------
    print()
    print("=" * 72)
    print(f"RESULTS: {len(PASSED)} PASSED, {len(FAILED)} FAILED")
    if FAILED:
        print()
        print("FAILED:")
        for f in FAILED:
            print(f"  - {f}")
    print("=" * 72)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
