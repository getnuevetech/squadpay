"""
Phase M backend test — Admin-configurable platform fees.

Covers:
  1. GET /api/admin/platform-fees without admin auth → 401
  2. GET /api/admin/platform-fees with admin token → 2 default disabled slots
  3. PUT /api/admin/platform-fees with valid payload → 200 returns persisted fees
  4. Create a new bill with multiple members, verify per_user.extra_fees correctness
  5. PUT with unknown slot id → 400 "unknown_fee_slot"
  6. PUT with invalid type → 422
  7. Disable both fees → NEW bill has no extra_fees
"""
import os
import sys
import time
import json
from typing import Any, Dict, List, Optional

import requests

BACKEND_URL = os.environ.get(
    "BACKEND_URL",
    "https://joint-pay-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BACKEND_URL}/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

TS = int(time.time())
RESULTS: List[Dict[str, Any]] = []


def record(name: str, ok: bool, info: str = ""):
    RESULTS.append({"name": name, "ok": ok, "info": info})
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {name}" + (f"  -- {info}" if info else ""))


def assert_eq(name: str, actual, expected, tol: float = 0.0):
    if isinstance(expected, float) or isinstance(actual, float):
        ok = abs(float(actual) - float(expected)) <= tol
    else:
        ok = actual == expected
    record(name, ok, "" if ok else f"expected={expected!r} actual={actual!r}")


def admin_login() -> str:
    r = requests.post(
        f"{API}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"admin login failed: {r.status_code} {r.text}")
    body = r.json()
    tok = body.get("access_token") or body.get("token")
    if not tok:
        raise RuntimeError(f"no token in login response: {body}")
    return tok


def auth_headers(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def register_user(name: str) -> str:
    r = requests.post(f"{API}/auth/register", json={"name": name}, timeout=15)
    r.raise_for_status()
    return r.json()["id"]


def send_otp(user_id: str, phone: str) -> Dict[str, Any]:
    r = requests.post(
        f"{API}/auth/send-otp",
        json={"user_id": user_id, "phone": phone},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def verify_otp(user_id: str, phone: str, code: str = "123456") -> Dict[str, Any]:
    r = requests.post(
        f"{API}/auth/verify-otp",
        json={"user_id": user_id, "phone": phone, "code": code},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"verify-otp failed: {r.status_code} {r.text}")
    return r.json()


def create_verified_user(name: str, phone_suffix: int) -> str:
    """Register + OTP + verify a user. Returns user_id (possibly merged)."""
    uid = register_user(name)
    # Build a unique 10-digit US phone: area=832, mid=<TS last 4>, last=<3-digit suffix>
    last4 = f"{TS % 10000:04d}"
    suffix = f"{phone_suffix:03d}"
    phone = f"+1832{last4}{suffix}"  # +1 + 10 digits = 12 chars
    send_otp(uid, phone)
    resp = verify_otp(uid, phone, "123456")
    # The verify endpoint may return the merged user; prefer that id if present
    return resp.get("user", {}).get("id") or resp.get("id") or uid


def create_fast_group(lead_id: str, title: str, total: float) -> str:
    body = {
        "lead_id": lead_id,
        "title": title,
        "total_amount": total,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r = requests.post(f"{API}/groups", json=body, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"create group failed: {r.status_code} {r.text}")
    return r.json()["id"]


def join_group(gid: str, uid: str):
    r = requests.post(f"{API}/groups/{gid}/join", json={"user_id": uid}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"join failed: {r.status_code} {r.text}")


def get_group(gid: str) -> Dict[str, Any]:
    r = requests.get(f"{API}/groups/{gid}", timeout=20)
    r.raise_for_status()
    return r.json()


def main() -> int:
    print(f"=== Phase M Test against {API} ===")

    # ---------- 1. GET without admin token → 401 ----------
    r = requests.get(f"{API}/admin/platform-fees", timeout=15)
    assert_eq("1. GET /admin/platform-fees no-auth → 401", r.status_code, 401)

    # ---------- admin login ----------
    try:
        tok = admin_login()
        record("admin login", True)
    except Exception as e:
        record("admin login", False, str(e))
        print("Cannot continue without admin token.")
        return 1

    H = auth_headers(tok)

    # ---------- 2. GET with admin → 2 default disabled slots ----------
    r = requests.get(f"{API}/admin/platform-fees", headers=H, timeout=15)
    assert_eq("2a. GET /admin/platform-fees status", r.status_code, 200)
    if r.status_code == 200:
        payload = r.json()
        fees = payload.get("fees", [])
        assert_eq("2b. fees length == 2", len(fees), 2)
        ids = {f.get("id") for f in fees}
        assert_eq("2c. fees contain extra_1 + extra_2", ids, {"extra_1", "extra_2"})
        # Reset the slots to a known disabled state first to make test idempotent.
        reset_payload = {
            "fees": [
                {"id": "extra_1", "name": "Extra Fee 1", "type": "flat", "value": 0.0, "enabled": False},
                {"id": "extra_2", "name": "Extra Fee 2", "type": "flat", "value": 0.0, "enabled": False},
            ]
        }
        rr = requests.put(f"{API}/admin/platform-fees", headers=H, json=reset_payload, timeout=15)
        if rr.status_code == 200:
            rr2 = requests.get(f"{API}/admin/platform-fees", headers=H, timeout=15)
            fees2 = rr2.json().get("fees", [])
            disabled_ok = all(f.get("enabled") is False for f in fees2)
            record("2d. After reset, both slots enabled=false", disabled_ok,
                   "" if disabled_ok else f"fees={fees2}")
        else:
            record("2d. reset to defaults", False, f"{rr.status_code} {rr.text}")

    # ---------- 3. PUT valid payload ----------
    valid_payload = {
        "fees": [
            {"id": "extra_1", "name": "Service Fee", "type": "percent", "value": 1.5, "enabled": True},
            {"id": "extra_2", "name": "Insurance", "type": "flat", "value": 0.25, "enabled": True},
        ]
    }
    r = requests.put(f"{API}/admin/platform-fees", headers=H, json=valid_payload, timeout=15)
    assert_eq("3a. PUT valid payload status", r.status_code, 200)
    if r.status_code == 200:
        persisted = r.json().get("fees", [])
        by_id = {f["id"]: f for f in persisted}
        e1 = by_id.get("extra_1") or {}
        e2 = by_id.get("extra_2") or {}
        assert_eq("3b. extra_1.name", e1.get("name"), "Service Fee")
        assert_eq("3c. extra_1.type", e1.get("type"), "percent")
        assert_eq("3d. extra_1.value", float(e1.get("value", 0)), 1.5, tol=1e-6)
        assert_eq("3e. extra_1.enabled", e1.get("enabled"), True)
        assert_eq("3f. extra_2.name", e2.get("name"), "Insurance")
        assert_eq("3g. extra_2.type", e2.get("type"), "flat")
        assert_eq("3h. extra_2.value", float(e2.get("value", 0)), 0.25, tol=1e-6)
        assert_eq("3i. extra_2.enabled", e2.get("enabled"), True)

    # ---------- 4. Create new bill with multiple members, verify extras ----------
    # Build 3 verified users (lead + 2 members) so member_count == 3
    try:
        lead_id = create_verified_user(f"Lead M{TS}", 0)
        m1_id = create_verified_user(f"Mem1 M{TS}", 1)
        m2_id = create_verified_user(f"Mem2 M{TS}", 2)
        record("4a. created 3 verified users", True,
               f"lead={lead_id} m1={m1_id} m2={m2_id}")
    except Exception as e:
        record("4a. created 3 verified users", False, str(e))
        lead_id = m1_id = m2_id = None

    total_amount = 60.0  # convenient for math
    if lead_id and m1_id and m2_id:
        try:
            gid = create_fast_group(lead_id, "Phase M Test Bill", total_amount)
            join_group(gid, m1_id)
            join_group(gid, m2_id)
            grp = get_group(gid)
            record("4b. created group with 3 members", True, f"gid={gid}")
            per_user = grp.get("per_user", [])
            member_count = len(per_user)
            assert_eq("4c. per_user member count", member_count, 3)

            # In fast split with $60 / 3 = $20 merchant_share each
            expected_merchant_share = round(total_amount / member_count, 2)
            # percent fee per member: 1.5% of merchant_share / member_count
            #   = (1.5/100) * 20 / 3 = 0.10
            expected_pct = round((1.5 / 100.0) * expected_merchant_share / member_count, 2)
            # flat per member: 0.25 / 3 = 0.0833 → rounds to 0.08
            expected_flat = round(0.25 / member_count, 2)
            expected_extras_total = round(expected_pct + expected_flat, 2)

            print(f"  expected merchant_share={expected_merchant_share}, "
                  f"pct={expected_pct}, flat={expected_flat}, "
                  f"extras_total={expected_extras_total}")

            all_ok_extras = True
            all_ok_totals = True
            for p in per_user:
                ef = p.get("extra_fees") or []
                ids = {e.get("id") for e in ef}
                if ids != {"extra_1", "extra_2"}:
                    all_ok_extras = False
                    record(f"4d. user {p['user_id']} extra_fees ids",
                           False, f"got {ids}")
                    continue
                by_id = {e["id"]: e for e in ef}
                pct_amt = round(float(by_id["extra_1"]["amount"]), 2)
                flat_amt = round(float(by_id["extra_2"]["amount"]), 2)
                if pct_amt != expected_pct or flat_amt != expected_flat:
                    all_ok_extras = False
                    record(f"4d. user {p['user_id']} extra amts",
                           False, f"pct={pct_amt} flat={flat_amt}")
                tot_extras = round(float(p.get("extra_fees_total", 0)), 2)
                if tot_extras != expected_extras_total:
                    all_ok_extras = False
                    record(f"4e. user {p['user_id']} extra_fees_total",
                           False, f"got {tot_extras} exp {expected_extras_total}")
                # total should include extras
                merchant_share = float(p.get("merchant_share", 0))
                txn_fee = float(p.get("transaction_fee", 0))
                plat_fee = float(p.get("platform_fee", 0))
                expected_total = round(merchant_share + txn_fee + plat_fee + tot_extras, 2)
                got_total = round(float(p.get("total", 0)), 2)
                if abs(got_total - expected_total) > 0.02:
                    all_ok_totals = False
                    record(f"4g. user {p['user_id']} total includes extras",
                           False, f"got {got_total} exp {expected_total}")
            record("4d. each member has both extra_fees with correct amounts",
                   all_ok_extras)
            record("4f. extra_fees_total = sum of extras", all_ok_extras)
            record("4g. per_user.total now INCLUDES extras", all_ok_totals)
        except Exception as e:
            record("4b. created group with 3 members", False, str(e))

    # ---------- 5. PUT with unknown slot id → 400 unknown_fee_slot ----------
    bad_id_payload = {
        "fees": [
            {"id": "extra_3", "name": "Bogus", "type": "flat", "value": 1.0, "enabled": True},
        ]
    }
    r = requests.put(f"{API}/admin/platform-fees", headers=H, json=bad_id_payload, timeout=15)
    assert_eq("5a. PUT unknown slot id status", r.status_code, 400)
    detail = ""
    try:
        detail = (r.json().get("detail") or "")
    except Exception:
        detail = r.text
    record("5b. detail contains 'unknown_fee_slot'",
           "unknown_fee_slot" in str(detail),
           f"detail={detail!r}")

    # ---------- 6. PUT with invalid type → 422 ----------
    bad_type_payload = {
        "fees": [
            {"id": "extra_1", "name": "Bad", "type": "xyz", "value": 1.0, "enabled": True},
        ]
    }
    r = requests.put(f"{API}/admin/platform-fees", headers=H, json=bad_type_payload, timeout=15)
    assert_eq("6. PUT invalid type → 422", r.status_code, 422)

    # ---------- 7. Disable both fees → NEW bill has empty/missing extra_fees ----------
    disable_payload = {
        "fees": [
            {"id": "extra_1", "name": "Service Fee", "type": "percent", "value": 1.5, "enabled": False},
            {"id": "extra_2", "name": "Insurance", "type": "flat", "value": 0.25, "enabled": False},
        ]
    }
    r = requests.put(f"{API}/admin/platform-fees", headers=H, json=disable_payload, timeout=15)
    assert_eq("7a. PUT disable both status", r.status_code, 200)
    if r.status_code == 200 and lead_id and m1_id and m2_id:
        try:
            gid2 = create_fast_group(lead_id, "Phase M Disabled Bill", 30.0)
            join_group(gid2, m1_id)
            join_group(gid2, m2_id)
            grp2 = get_group(gid2)
            per_user2 = grp2.get("per_user", [])
            all_empty = True
            details = []
            for p in per_user2:
                ef = p.get("extra_fees")
                if ef:  # non-empty list
                    all_empty = False
                    details.append(f"{p['user_id']}: {ef}")
                if float(p.get("extra_fees_total", 0)) != 0:
                    all_empty = False
                    details.append(f"{p['user_id']} extra_fees_total={p.get('extra_fees_total')}")
            record("7b. new bill has empty/missing extra_fees", all_empty,
                   "; ".join(details) if details else "")
        except Exception as e:
            record("7b. new bill has empty/missing extra_fees", False, str(e))

    # ---------- summary ----------
    print()
    print("=" * 60)
    passed = sum(1 for x in RESULTS if x["ok"])
    failed = sum(1 for x in RESULTS if not x["ok"])
    print(f"TOTAL: {passed} pass / {failed} fail")
    if failed:
        print("\nFailures:")
        for x in RESULTS:
            if not x["ok"]:
                print(f"  - {x['name']}  {x['info']}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
