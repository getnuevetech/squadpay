"""Phase G5 — Admin Analytics dashboard backend tests."""
import os
import sys
import time
import uuid
from datetime import date

import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://joint-pay-1.preview.emergentagent.com"
API = BASE.rstrip("/") + "/api"

ADMIN_EMAIL = "[email protected]"
ADMIN_PASSWORD = "ChangeMe123!"

PASS = 0
FAIL = 0
FAILS: list = []


def check(cond: bool, label: str, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        FAILS.append(f"{label} :: {detail}")
        print(f"  FAIL  {label}  -- {detail}")


def login_super_admin() -> str:
    r = requests.post(
        f"{API}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["token"]


def hdr(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def is_iso_date(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        date.fromisoformat(s)
        return True
    except Exception:
        return False


def section(title):
    print(f"\n=== {title} ===")


def test_default_range(token):
    section("2) GET /api/admin/analytics (no range) -> default 30")
    r = requests.get(f"{API}/admin/analytics", headers=hdr(token), timeout=30)
    check(r.status_code == 200, "default range 200", f"status={r.status_code} body={r.text[:300]}")
    if r.status_code == 200:
        data = r.json()
        check(data.get("range_days") == 30, "default range_days==30", f"got={data.get('range_days')}")
        return data
    return None


def test_range(token, rng_param, expected_days):
    section(f"GET /api/admin/analytics?range={rng_param} -> {expected_days} entries")
    r = requests.get(f"{API}/admin/analytics", params={"range": rng_param}, headers=hdr(token), timeout=30)
    check(r.status_code == 200, f"range={rng_param} 200", f"status={r.status_code} body={r.text[:300]}")
    if r.status_code != 200:
        return None
    data = r.json()
    check(data.get("range_days") == expected_days, f"range_days=={expected_days}", f"got={data.get('range_days')}")

    arrays = ["signups_per_day", "groups_per_day", "gmv_per_day", "aov_per_day", "contributions_per_day"]
    for k in arrays:
        arr = data.get(k)
        check(isinstance(arr, list), f"{k} is list", f"got={type(arr).__name__}")
        if isinstance(arr, list):
            check(len(arr) == expected_days, f"{k} has {expected_days} entries", f"got={len(arr)}")
            if arr:
                iso_ok = all(is_iso_date(x.get("date")) for x in arr)
                check(iso_ok, f"{k} entries have ISO date strings", f"sample={arr[0]}")
    return data


def test_invalid_range(token):
    section("5) GET /api/admin/analytics?range=invalid -> defaults to 30")
    r = requests.get(f"{API}/admin/analytics", params={"range": "invalid"}, headers=hdr(token), timeout=30)
    check(r.status_code == 200, "invalid range graceful 200", f"status={r.status_code} body={r.text[:300]}")
    if r.status_code == 200:
        data = r.json()
        check(data.get("range_days") == 30, "invalid range defaulted to 30", f"got={data.get('range_days')}")
    check(r.status_code != 500, "invalid range NOT 500", f"status={r.status_code}")


def test_shape(data):
    section("6) Shape verification - required top-level keys")
    required_keys = [
        "range_days", "start_date", "end_date",
        "groups_per_day", "gmv_per_day", "aov_per_day",
        "signups_per_day", "contributions_per_day",
        "top_referrers", "card_metrics", "master_account",
        "funnel", "totals",
    ]
    for k in required_keys:
        check(k in data, f"top-level key '{k}'", f"keys={list(data.keys())}")
    check(is_iso_date(data.get("start_date")), "start_date ISO", f"got={data.get('start_date')}")
    check(is_iso_date(data.get("end_date")), "end_date ISO", f"got={data.get('end_date')}")


def test_totals(data):
    section("7) totals object keys")
    totals = data.get("totals") or {}
    required = ["users", "verified_users", "groups", "groups_in_range", "contributions",
                "gmv", "gmv_in_range", "gross_processed_in_range", "signups_in_range", "verified_in_range"]
    for k in required:
        check(k in totals, f"totals.{k} present", f"totals keys={list(totals.keys())}")


def test_funnel(data):
    section("8) funnel object")
    funnel = data.get("funnel") or {}
    required = ["signups", "verified", "joined_group", "contributed", "settled_groups"]
    for k in required:
        check(k in funnel, f"funnel.{k} present", f"funnel keys={list(funnel.keys())}")
    totals = data.get("totals") or {}
    check(funnel.get("signups") == totals.get("users"),
          "funnel.signups == totals.users",
          f"funnel.signups={funnel.get('signups')} totals.users={totals.get('users')}")
    check(funnel.get("verified") == totals.get("verified_users"),
          "funnel.verified == totals.verified_users",
          f"funnel.verified={funnel.get('verified')} totals.verified_users={totals.get('verified_users')}")


def test_card_metrics(data):
    section("9) card_metrics object")
    cm = data.get("card_metrics") or {}
    for k in ["total_issued", "active", "inactive", "total_spent"]:
        check(k in cm, f"card_metrics.{k} present", f"keys={list(cm.keys())}")
    if all(k in cm for k in ["total_issued", "active", "inactive"]):
        check(cm["active"] + cm["inactive"] <= cm["total_issued"],
              "active+inactive <= total_issued",
              f"active={cm['active']} inactive={cm['inactive']} total={cm['total_issued']}")


def test_master_account(data):
    section("10) master_account object")
    ma = data.get("master_account") or {}
    check("balance" in ma, "master_account.balance present", f"keys={list(ma.keys())}")
    check("entries" in ma, "master_account.entries present", f"keys={list(ma.keys())}")
    check(isinstance(ma.get("balance"), (int, float)), "balance is number", f"type={type(ma.get('balance')).__name__}")
    check(isinstance(ma.get("entries"), (int, float)), "entries is number", f"type={type(ma.get('entries')).__name__}")


def test_top_referrers(data):
    section("11) top_referrers array shape")
    tr = data.get("top_referrers")
    check(isinstance(tr, list), "top_referrers is list", f"type={type(tr).__name__}")
    if isinstance(tr, list):
        check(len(tr) <= 10, "top_referrers length <=10", f"len={len(tr)}")
        for i, item in enumerate(tr):
            for k in ["user_id", "name", "referral_code", "signups", "verified_signups"]:
                check(k in item, f"top_referrers[{i}].{k} present", f"keys={list(item.keys())}")


def test_auth(token):
    section("12) Auth: no token -> 401; manager-role -> 200")
    r = requests.get(f"{API}/admin/analytics", timeout=20)
    check(r.status_code == 401, "no token -> 401", f"status={r.status_code} body={r.text[:200]}")

    suffix = uuid.uuid4().hex[:8]
    mgr_email = f"mgr_g5_{suffix}@kwiktech.net"
    mgr_password = "ManagerPass123!"
    r = requests.post(
        f"{API}/admin/admins",
        headers={**hdr(token), "Content-Type": "application/json"},
        json={"email": mgr_email, "password": mgr_password, "name": "Manager G5", "role": "manager"},
        timeout=20,
    )
    if r.status_code not in (200, 409):
        check(False, "create manager admin", f"status={r.status_code} body={r.text[:300]}")
        return
    r = requests.post(
        f"{API}/admin/auth/login",
        json={"email": mgr_email, "password": mgr_password},
        timeout=20,
    )
    if r.status_code != 200:
        check(False, "manager login", f"status={r.status_code} body={r.text[:300]}")
        return
    mgr_token = r.json()["token"]
    r = requests.get(f"{API}/admin/analytics", headers=hdr(mgr_token), timeout=30)
    check(r.status_code == 200, "manager-role analytics -> 200", f"status={r.status_code} body={r.text[:300]}")


def test_regressions(token):
    section("13) Regression spot-checks")
    endpoints = [
        "/admin/integrations/issuing",
        "/admin/security/kms-status",
        "/admin/reconciliations",
        "/admin/master-account",
    ]
    for path in endpoints:
        r = requests.get(f"{API}{path}", headers=hdr(token), timeout=20)
        check(r.status_code == 200, f"GET {path} -> 200", f"status={r.status_code} body={r.text[:300]}")

    suffix = uuid.uuid4().hex[:6]
    name = f"AnalyticsUser_{suffix}"
    r = requests.post(f"{API}/auth/register", json={"name": name}, timeout=20)
    if r.status_code != 200:
        check(False, "POST /auth/register (helper)", f"status={r.status_code} body={r.text[:300]}")
        return
    j = r.json()
    uid = j.get("id") or j.get("user_id")
    phone = f"+1555{int(time.time()) % 10000000:07d}"
    r = requests.post(f"{API}/auth/send-otp", json={"user_id": uid, "phone": phone}, timeout=20)
    check(r.status_code == 200, "POST /auth/send-otp -> 200", f"status={r.status_code} body={r.text[:300]}")


def main():
    print(f"BASE={BASE}")
    print(f"API ={API}")
    print(f"Logging in super_admin {ADMIN_EMAIL}...")
    try:
        token = login_super_admin()
        print("  PASS  super_admin login")
    except Exception as e:
        print(f"  FAIL  super_admin login failed: {e}")
        sys.exit(2)

    data30_default = test_default_range(token)
    data7 = test_range(token, "7d", 7)
    data30 = test_range(token, "30d", 30)
    data90 = test_range(token, "90d", 90)
    test_invalid_range(token)

    pick = data30 or data7 or data30_default or data90
    if pick:
        test_shape(pick)
        test_totals(pick)
        test_funnel(pick)
        test_card_metrics(pick)
        test_master_account(pick)
        test_top_referrers(pick)
    else:
        check(False, "have analytics payload to inspect", "all calls failed")

    test_auth(token)
    test_regressions(token)

    print("\n=========================================")
    print(f"PASS: {PASS}  FAIL: {FAIL}")
    if FAILS:
        print("FAILED:")
        for f in FAILS:
            print(f"  - {f}")
    print("=========================================")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
