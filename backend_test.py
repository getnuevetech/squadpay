"""Phase G3 — Per-lead Stripe Issuing cardholder + KYC toggle backend tests."""
import os
import sys
import time
import json
import requests
from typing import Dict


def _read_env(path: str, key: str):
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        return None
    return None


BASE = (_read_env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")
        or _read_env("/app/frontend/.env", "REACT_APP_BACKEND_URL")
        or "")
assert BASE, "EXPO_PUBLIC_BACKEND_URL not set"
API = BASE.rstrip("/") + "/api"

ADMIN_EMAIL = "[email protected]"
ADMIN_PW = "ChangeMe123!"

PASS = []
FAIL = []
TS = int(time.time())


def _log(name, ok, detail=""):
    line = f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else "")
    print(line)
    (PASS if ok else FAIL).append((name, detail))


def assert_eq(name, got, exp):
    _log(name, got == exp, f"got={got!r} expected={exp!r}")


def assert_true(name, cond, detail=""):
    _log(name, bool(cond), detail)


def admin_login() -> str:
    r = requests.post(f"{API}/admin/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PW},
                      timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def hdr(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def register(name: str) -> str:
    r = requests.post(f"{API}/auth/register", json={"name": name}, timeout=20)
    r.raise_for_status()
    return r.json()["id"]


_phone_seq = [0]


def fresh_phone() -> str:
    _phone_seq[0] += 1
    return f"+1555{(TS % 1000):03d}{_phone_seq[0]:05d}"


def verify_user(name: str):
    uid = register(name)
    phone = fresh_phone()
    r = requests.post(f"{API}/auth/send-otp", json={"user_id": uid, "phone": phone}, timeout=20)
    r.raise_for_status()
    r = requests.post(f"{API}/auth/verify-otp",
                      json={"user_id": uid, "phone": phone, "code": "123456"},
                      timeout=20)
    r.raise_for_status()
    j = r.json()
    return j["id"], phone


def main():
    print(f"BASE={BASE}\nAPI={API}\n")

    tok = admin_login()
    _log("RG.admin_login", True, "obtained admin bearer token")

    # ---- 1) GET /admin/integrations/issuing (with explicit reset to False first) ----
    r = requests.get(f"{API}/admin/integrations/issuing", headers=hdr(tok), timeout=20)
    assert_eq("1.GET_issuing_status", r.status_code, 200)
    body = r.json() if r.ok else {}
    assert_true("1.has_require_lead_kyc_field", "require_lead_kyc" in body,
                f"keys={list(body.keys())}")
    r = requests.post(f"{API}/admin/integrations/issuing",
                      headers=hdr(tok), json={"require_lead_kyc": False}, timeout=20)
    assert_eq("1.reset_to_false_pre", r.status_code, 200)
    r = requests.get(f"{API}/admin/integrations/issuing", headers=hdr(tok), timeout=20)
    assert_eq("1.require_lead_kyc_false", r.json().get("require_lead_kyc"), False)

    # ---- 2) Toggle ON ----
    r = requests.post(f"{API}/admin/integrations/issuing",
                      headers=hdr(tok), json={"require_lead_kyc": True}, timeout=20)
    assert_eq("2.POST_set_true_status", r.status_code, 200)
    assert_eq("2.body_require_lead_kyc_true", r.json().get("require_lead_kyc"), True)
    r = requests.get(f"{API}/admin/integrations/issuing", headers=hdr(tok), timeout=20)
    assert_eq("2.GET_after_true", r.json().get("require_lead_kyc"), True)

    r = requests.get(f"{API}/admin/audit-log", headers=hdr(tok), params={"limit": 50}, timeout=20)
    assert_eq("2.audit_log_status", r.status_code, 200)
    items = r.json().get("items", []) if r.ok else []
    found_audit = any(it.get("action") == "admin.update_issuing_settings" for it in items)
    assert_true("2.audit_update_issuing_settings_present", found_audit,
                f"found={found_audit} item_count={len(items)}")

    # ---- 3) Toggle OFF ----
    r = requests.post(f"{API}/admin/integrations/issuing",
                      headers=hdr(tok), json={"require_lead_kyc": False}, timeout=20)
    assert_eq("3.POST_set_false_status", r.status_code, 200)
    r = requests.get(f"{API}/admin/integrations/issuing", headers=hdr(tok), timeout=20)
    assert_eq("3.GET_after_false", r.json().get("require_lead_kyc"), False)

    # ---- 4) Create user; GET /kyc shape ----
    lead_id, lead_phone = verify_user(f"Avery Lead {TS}")
    r = requests.get(f"{API}/users/{lead_id}/kyc", timeout=20)
    assert_eq("4.GET_kyc_status", r.status_code, 200)
    j = r.json() if r.ok else {}
    assert_eq("4.user_id", j.get("user_id"), lead_id)
    assert_eq("4.cardholder_id_null", j.get("stripe_cardholder_id"), None)
    assert_eq("4.kyc_status_none", j.get("kyc_status"), "none")
    assert_eq("4.kyc_disabled_reason_null", j.get("kyc_disabled_reason"), None)
    assert_eq("4.kyc_last_checked_at_null", j.get("kyc_last_checked_at"), None)
    assert_eq("4.stripe_status_null", j.get("stripe_status"), None)
    assert_eq("4.required_false", j.get("required"), False)

    # ---- 5) /kyc/start with require_lead_kyc=False ----
    r = requests.post(f"{API}/users/{lead_id}/kyc/start", timeout=20)
    assert_eq("5.start_kyc_off_status", r.status_code, 200)
    j = r.json() if r.ok else {}
    assert_eq("5.required_false", j.get("required"), False)
    msg = (j.get("message") or "").lower()
    assert_true("5.message_not_required",
                "not currently required" in msg or "not required" in msg,
                f"message={j.get('message')!r}")

    # ---- 6) Unverified user → 403 ----
    raw_id = register(f"Unverified {TS}")
    r = requests.post(f"{API}/users/{raw_id}/kyc/start", timeout=20)
    assert_eq("6.unverified_403", r.status_code, 403)
    assert_true("6.detail_phone_verification",
                "phone verification" in (r.text or "").lower(),
                f"detail={r.text}")

    # ---- 7) Toggle ON; start kyc with verified user ----
    r = requests.post(f"{API}/admin/integrations/issuing",
                      headers=hdr(tok), json={"require_lead_kyc": True}, timeout=20)
    assert_eq("7.toggle_true_again", r.status_code, 200)

    r = requests.post(f"{API}/users/{lead_id}/kyc/start", timeout=60)
    code = r.status_code
    try:
        body7 = r.json()
    except Exception:
        body7 = {"raw": r.text[:300]}
    assert_true("7.no_500", code != 500, f"got {code} body={body7}")
    if code == 200:
        assert_eq("7.required_true", body7.get("required"), True)
        cid = body7.get("stripe_cardholder_id")
        assert_true("7.cardholder_id_set",
                    bool(cid and isinstance(cid, str) and cid.startswith("ich_")),
                    f"cid={cid}")
    elif code == 502:
        assert_true("7.502_has_stripe_message",
                    "stripe" in (r.text or "").lower(),
                    f"detail={r.text[:300]}")
    else:
        _log("7.unexpected_status", False, f"got {code} body={body7}")

    # ---- 8) Idempotency ----
    cid_before = None
    rg = requests.get(f"{API}/users/{lead_id}/kyc", timeout=30)
    if rg.ok:
        cid_before = rg.json().get("stripe_cardholder_id")
    r2 = requests.post(f"{API}/users/{lead_id}/kyc/start", timeout=60)
    assert_true("8.second_call_no_500", r2.status_code != 500,
                f"got {r2.status_code} body={r2.text[:200]}")
    if r2.status_code == 200 and cid_before:
        cid_after = r2.json().get("stripe_cardholder_id")
        assert_eq("8.idempotent_same_cardholder_id", cid_after, cid_before)
    elif r2.status_code == 502:
        assert_true("8.idempotent_502_consistent",
                    "stripe" in (r2.text or "").lower(),
                    f"detail={r2.text[:200]}")

    # ---- 9) GET /kyc reflects DB ----
    rg = requests.get(f"{API}/users/{lead_id}/kyc", timeout=30)
    assert_eq("9.get_kyc_status", rg.status_code, 200)
    j9 = rg.json() if rg.ok else {}
    if cid_before:
        assert_eq("9.cardholder_id_persisted", j9.get("stripe_cardholder_id"), cid_before)
        assert_true("9.kyc_status_set",
                    j9.get("kyc_status") in ("verified", "pending", "blocked"),
                    f"kyc_status={j9.get('kyc_status')}")
    assert_eq("9.required_true", j9.get("required"), True)

    # ---- 10) Blocked user → 403 ----
    blocked_id, _ = verify_user(f"Blocked Lead {TS}")
    rb = requests.post(f"{API}/admin/users/{blocked_id}/block",
                       headers=hdr(tok),
                       json={"is_blocked": True, "reason": "g3 test"},
                       timeout=20)
    assert_true("10.admin_block_user", rb.status_code == 200,
                f"status={rb.status_code} body={rb.text[:200]}")
    rk = requests.post(f"{API}/users/{blocked_id}/kyc/start", timeout=30)
    assert_eq("10.blocked_user_403", rk.status_code, 403)
    requests.post(f"{API}/admin/users/{blocked_id}/block",
                  headers=hdr(tok), json={"is_blocked": False, "reason": "cleanup"}, timeout=20)

    # ---- 11) Regression spot checks ----
    _log("11a.admin_login_OK", True)
    rint = requests.get(f"{API}/admin/integrations", headers=hdr(tok), timeout=20)
    assert_eq("11b.GET_admin_integrations", rint.status_code, 200)
    if rint.ok:
        topkeys = set(rint.json().keys())
        for k in ["stripe", "twilio", "signalwire", "sms_routing", "reconciliation"]:
            assert_true(f"11b.has_{k}", k in topkeys, f"keys={topkeys}")
    rkms = requests.get(f"{API}/admin/security/kms-status", headers=hdr(tok), timeout=20)
    assert_eq("11c.kms_status", rkms.status_code, 200)

    flow_id = None
    try:
        flow_id, _ = verify_user(f"Reg Spot {TS}")
        _log("11d.auth_flow_OK", True, f"new uid={flow_id}")
    except Exception as e:
        _log("11d.auth_flow_OK", False, f"err={e}")

    if flow_id:
        try:
            rg2 = requests.post(f"{API}/groups", json={
                "lead_id": flow_id,
                "title": f"G3 Test Group {TS}",
                "total_amount": 30.0,
                "split_mode": "fast_split",
                "tax": 0.0, "tip": 0.0, "items": [],
            }, timeout=20)
            assert_eq("11e.create_group_status", rg2.status_code, 200)
            if rg2.ok:
                assert_true("11e.group_has_id", bool(rg2.json().get("id")), "")
        except Exception as e:
            _log("11e.create_group_status", False, f"err={e}")

    # ---- RESET ----
    r = requests.post(f"{API}/admin/integrations/issuing",
                      headers=hdr(tok), json={"require_lead_kyc": False}, timeout=20)
    assert_eq("RESET.require_lead_kyc_false", r.status_code, 200)
    rg = requests.get(f"{API}/admin/integrations/issuing", headers=hdr(tok), timeout=20)
    assert_eq("RESET.GET_after", rg.json().get("require_lead_kyc"), False)

    print("\n=========================================")
    print(f"PASS: {len(PASS)}  FAIL: {len(FAIL)}")
    if FAIL:
        print("\nFailures:")
        for n, d in FAIL:
            print(f"  - {n}: {d}")
    print("=========================================")
    sys.exit(0 if not FAIL else 1)


if __name__ == "__main__":
    main()
