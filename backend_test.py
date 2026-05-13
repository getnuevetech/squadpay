"""SquadPay backend test harness — June 2025 P1+P2 batch.

Focus areas (per review request):
  1. NEW Recurring-Bills endpoints (R1-R11)
  2. App-wide "Squad" terminology regression on HTTP error strings
  3. Regression smoke (admin login, root, groups list, create group, etc.)

Run:
    python /app/backend_test.py
"""
import os
import sys
import time
import json
from datetime import datetime, timedelta, timezone
from calendar import monthrange
from typing import Optional

import requests

BASE = "http://localhost:8001/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

EXISTING_GID = "g_7f6e457006"
EXISTING_LEAD = "u_4ab200b580"

passes = []
failures = []


def record(ok: bool, label: str, detail: str = ""):
    if ok:
        passes.append(label)
        print(f"  PASS  {label}")
    else:
        failures.append(f"{label} -- {detail}")
        print(f"  FAIL  {label} -- {detail}")


def expect_status(resp, want: int, label: str, want_detail_substr: Optional[str] = None):
    actual = resp.status_code
    body_txt = resp.text[:300]
    detail = None
    try:
        body = resp.json()
        if isinstance(body, dict):
            detail = body.get("detail")
    except Exception:
        body = None
    if actual != want:
        record(False, label, f"want {want}, got {actual}: {body_txt}")
        return False
    if want_detail_substr is not None:
        if not detail or want_detail_substr.lower() not in str(detail).lower():
            record(False, label, f"want detail '{want_detail_substr}', got '{detail}'")
            return False
    record(True, label)
    return True


def section(title: str):
    print(f"\n=== {title} ===")


def admin_login() -> Optional[str]:
    r = requests.post(f"{BASE}/admin/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    if r.status_code == 200:
        tok = r.json().get("token")
        record(bool(tok), "admin login (/admin/auth/login) returns token",
               "no token in response" if not tok else "")
        return tok
    record(False, "admin login (/admin/auth/login) returns token",
           f"{r.status_code}: {r.text[:200]}")
    # Also try the path the review-request mentioned, for transparency.
    r2 = requests.post(f"{BASE}/admin/login",
                       json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                       timeout=10)
    record(r2.status_code == 200,
           "admin login (/admin/login alias) returns 200",
           f"{r2.status_code}: {r2.text[:120]}")
    return None


def make_user(name: str) -> Optional[dict]:
    """Register + verify (mock OTP)."""
    phone = f"+1832{int(time.time() * 1000) % 10000000:07d}"
    r = requests.post(f"{BASE}/auth/register", json={"name": name, "phone": phone}, timeout=10)
    if r.status_code != 200:
        return None
    user = r.json()
    requests.post(f"{BASE}/auth/send-otp", json={"phone": phone}, timeout=10)
    r2 = requests.post(f"{BASE}/auth/verify-otp",
                       json={"phone": phone, "code": "123456", "name": name},
                       timeout=10)
    return r2.json() if r2.status_code == 200 else user


def create_fresh_squad(lead_id: str):
    body = {
        "lead_id": lead_id,
        "title": "Recur Test Bill",
        "total_amount": 30.0,
        "split_mode": "fast",
        "items": [],
        "tax": 0.0,
        "tip": 0.0,
    }
    r = requests.post(f"{BASE}/groups", json=body, timeout=15)
    if r.status_code == 200:
        return r.json().get("id"), r.json()
    return None, None


def test_terminology():
    section("2. Squad terminology regression on HTTP 404 detail strings")
    cases = [
        ("GET", "/groups/g_invalidnope", None, "GET /groups/{id} → 404 Squad not found"),
        ("POST", "/groups/g_invalidnope/contribute",
         {"user_id": "u_x", "amount": 1},
         "POST /groups/{id}/contribute → 404 Squad not found"),
        ("POST", "/groups/g_invalidnope/pay",
         {"user_id": "u_x"},
         "POST /groups/{id}/pay → 404 Squad not found"),
        ("POST", "/groups/g_invalidnope/repay",
         {"user_id": "u_x", "amount": 1},
         "POST /groups/{id}/repay → 404 Squad not found"),
        ("POST", "/groups/g_invalidnope/refund",
         {"user_id": "u_x"},
         "POST /groups/{id}/refund → 404 Squad not found"),
        ("POST", "/groups/g_invalidnope/payout",
         {"user_id": "u_x"},
         "POST /groups/{id}/payout → 404 Squad not found"),
    ]
    for method, path, body, label in cases:
        if method == "GET":
            r = requests.get(f"{BASE}{path}", timeout=10)
        else:
            r = requests.post(f"{BASE}{path}", json=body, timeout=10)
        expect_status(r, 404, label, "Squad not found")


def test_recurrence(lead_id: str, gid: str, non_lead_id: str):
    section("1. Recurring Bills endpoints")

    # R1 — Non-lead caller → 403
    r = requests.put(f"{BASE}/groups/{gid}/recurrence",
                     json={"user_id": non_lead_id, "enabled": True,
                           "cadence": "weekly", "anchor": 2, "skip_if_open": False},
                     timeout=10)
    expect_status(r, 403, "R1 PUT recurrence as non-lead → 403",
                  "Only the lead can configure recurrence")

    # R2 — Lead enables weekly Wed 09:00 UTC anchor=2
    base_now = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    r = requests.put(f"{BASE}/groups/{gid}/recurrence",
                     json={"user_id": lead_id, "enabled": True,
                           "cadence": "weekly", "anchor": 2, "skip_if_open": False},
                     timeout=10)
    ok = expect_status(r, 200, "R2 PUT recurrence as lead → 200")
    if ok:
        body = r.json()
        nxt = body.get("next_run_at")
        if not nxt or not isinstance(nxt, str) or not nxt.endswith("Z"):
            record(False, "R2 next_run_at is ISO 'Z' string", f"got {nxt!r}")
        else:
            record(True, "R2 next_run_at is ISO 'Z' string")
            try:
                dt = datetime.fromisoformat(nxt.replace("Z", "+00:00"))
                today_wd = base_now.weekday()
                days_ahead = (2 - today_wd) % 7
                if days_ahead == 0:
                    days_ahead = 7
                expected = (base_now + timedelta(days=days_ahead)).replace(
                    hour=9, minute=0, second=0, microsecond=0)
                if abs((dt - expected).total_seconds()) <= 120 and dt.weekday() == 2:
                    record(True, "R2 next_run_at is next Wednesday 09:00 UTC")
                else:
                    record(False, "R2 next_run_at is next Wednesday 09:00 UTC",
                           f"got {dt.isoformat()}, expected ~{expected.isoformat()}")
            except Exception as e:
                record(False, "R2 next_run_at parse", str(e))

    # R3 — GET as lead returns same payload
    r = requests.get(f"{BASE}/groups/{gid}/recurrence", params={"user_id": lead_id}, timeout=10)
    if expect_status(r, 200, "R3 GET recurrence as lead → 200"):
        body = r.json()
        ok = (body.get("enabled") is True
              and body.get("cadence") == "weekly"
              and int(body.get("anchor", -1)) == 2
              and "next_run_at" in body)
        record(ok, "R3 GET returns same recurrence payload",
               str(body)[:200] if not ok else "")

    # R4 — Disable
    r = requests.put(f"{BASE}/groups/{gid}/recurrence",
                     json={"user_id": lead_id, "enabled": False,
                           "cadence": "weekly", "anchor": 0},
                     timeout=10)
    if expect_status(r, 200, "R4 PUT enabled:false → 200"):
        body = r.json()
        record(body.get("ok") is True and body.get("enabled") is False,
               "R4 response is {ok:true, enabled:false}", str(body))
    r = requests.get(f"{BASE}/groups/{gid}/recurrence", params={"user_id": lead_id}, timeout=10)
    if expect_status(r, 200, "R4 GET after disable → 200"):
        record(r.json().get("enabled") is False,
               "R4 GET enabled:false", str(r.json()))

    # R5 — Monthly anchor=31 clamp
    r = requests.put(f"{BASE}/groups/{gid}/recurrence",
                     json={"user_id": lead_id, "enabled": True,
                           "cadence": "monthly", "anchor": 31, "skip_if_open": False},
                     timeout=10)
    if expect_status(r, 200, "R5 PUT monthly anchor=31 → 200"):
        body = r.json()
        nxt = body.get("next_run_at")
        if nxt:
            try:
                dt = datetime.fromisoformat(nxt.replace("Z", "+00:00"))
                last_day = monthrange(dt.year, dt.month)[1]
                if dt.day == last_day and dt.hour == 9:
                    record(True,
                           f"R5 monthly anchor=31 clamps to last day "
                           f"(month={dt.month}, day={dt.day}, last={last_day})")
                else:
                    record(False, "R5 monthly anchor=31 clamps to last day",
                           f"got day={dt.day}, last_day={last_day}")
            except Exception as e:
                record(False, "R5 monthly parse", str(e))

    # R6 — invalid cadence
    r = requests.put(f"{BASE}/groups/{gid}/recurrence",
                     json={"user_id": lead_id, "enabled": True,
                           "cadence": "biweekly", "anchor": 0},
                     timeout=10)
    expect_status(r, 400, "R6 PUT cadence=biweekly → 400")

    # R7 — weekly anchor=7
    r = requests.put(f"{BASE}/groups/{gid}/recurrence",
                     json={"user_id": lead_id, "enabled": True,
                           "cadence": "weekly", "anchor": 7},
                     timeout=10)
    expect_status(r, 400, "R7 PUT weekly anchor=7 → 400")

    # R8 — monthly anchor=32
    r = requests.put(f"{BASE}/groups/{gid}/recurrence",
                     json={"user_id": lead_id, "enabled": True,
                           "cadence": "monthly", "anchor": 32},
                     timeout=10)
    expect_status(r, 400, "R8 PUT monthly anchor=32 → 400")

    # R9 — DELETE
    r = requests.delete(f"{BASE}/groups/{gid}/recurrence",
                        params={"user_id": lead_id}, timeout=10)
    expect_status(r, 200, "R9 DELETE recurrence as lead → 200")
    r = requests.get(f"{BASE}/groups/{gid}/recurrence",
                     params={"user_id": lead_id}, timeout=10)
    if expect_status(r, 200, "R9 GET after DELETE → 200"):
        record(r.json().get("enabled") is False,
               "R9 GET enabled:false after DELETE", str(r.json()))

    # R10 — Non-lead GET → 403
    r = requests.get(f"{BASE}/groups/{gid}/recurrence",
                     params={"user_id": non_lead_id}, timeout=10)
    expect_status(r, 403, "R10 GET as non-lead → 403")

    # R11 — Unknown group → "Squad not found"
    r = requests.put(f"{BASE}/groups/g_doesnotexist/recurrence",
                     json={"user_id": lead_id, "enabled": True,
                           "cadence": "weekly", "anchor": 0},
                     timeout=10)
    expect_status(r, 404, "R11 PUT unknown group → 404", "Squad not found")
    r = requests.get(f"{BASE}/groups/g_doesnotexist/recurrence",
                     params={"user_id": lead_id}, timeout=10)
    expect_status(r, 404, "R11 GET unknown group → 404", "Squad not found")


def test_smoke(admin_token: Optional[str]):
    section("3. Regression smoke")

    r = requests.get(f"{BASE}/", timeout=10)
    if expect_status(r, 200, "GET / → 200"):
        try:
            msg = r.json().get("message", "")
            record("SquadPay" in msg, "GET / message contains 'SquadPay'", msg)
        except Exception:
            record(False, "GET / message JSON", r.text[:200])

    r = requests.get(f"{BASE}/users/{EXISTING_LEAD}/groups", timeout=15)
    expect_status(r, 200, "GET /users/{lead}/groups → 200")

    fresh = make_user("RegSmokeUser")
    if fresh:
        # `title` is required by the CreateGroupIn model, but the route applies
        # `body.title or "Squad Bill"` so an empty string falls through to the
        # new default. This verifies the rename from "Group Bill" → "Squad Bill".
        body = {
            "lead_id": fresh["id"],
            "title": "",
            "total_amount": 12.5,
            "split_mode": "fast",
            "items": [],
            "tax": 0.0,
            "tip": 0.0,
        }
        r = requests.post(f"{BASE}/groups", json=body, timeout=15)
        if expect_status(r, 200, "POST /groups (empty title) → 200"):
            title = r.json().get("title")
            record(title == "Squad Bill",
                   "Default title is 'Squad Bill'",
                   f"got {title!r}")
            new_gid = r.json().get("id")
            r2 = requests.get(f"{BASE}/groups/{new_gid}", timeout=10)
            expect_status(r2, 200, "GET /groups/{new_gid} → 200")

    if admin_token:
        r = requests.get(f"{BASE}/admin/metrics",
                         headers={"Authorization": f"Bearer {admin_token}"},
                         timeout=15)
        expect_status(r, 200, "GET /admin/metrics with super_admin → 200")


def main():
    print(f"Backend: {BASE}\n")

    section("0. Admin login")
    admin_token = admin_login()

    section("Setup: create fresh users + squad for recurrence tests")
    lead = make_user("RecLead")
    time.sleep(0.05)
    non_lead = make_user("RecNonLead")
    if not lead or not non_lead:
        record(False, "Setup users (fresh)",
               "Could not create test users — falling back to existing IDs")
        gid = EXISTING_GID
        lead_id_for_rec = EXISTING_LEAD
        non_lead_id = (non_lead or {}).get("id") or "u_nopermission"
    else:
        record(True, "Setup users (fresh)")
        gid, _ = create_fresh_squad(lead["id"])
        if not gid:
            record(False, "Setup fresh squad", "fallback to EXISTING_GID")
            gid = EXISTING_GID
            lead_id_for_rec = EXISTING_LEAD
        else:
            record(True, "Setup fresh squad")
            lead_id_for_rec = lead["id"]
        non_lead_id = non_lead["id"]

    test_terminology()
    test_recurrence(lead_id_for_rec, gid, non_lead_id)
    test_smoke(admin_token)

    print(f"\n{'='*60}\nSUMMARY: {len(passes)} PASS · {len(failures)} FAIL\n{'='*60}")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
