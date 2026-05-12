"""
Focused re-test of the Bulk SMS phone-normalization fix in
/app/backend/routes/admin_bulk_sms.py.

Per review request, ONLY:
  1. payload phone_numbers=["+12025550123", "2025550123", "(202) 555-0123"]
     → recipient_count == 1
  2. Sanity: simple "all_users" broadcast still works (recipient_count > 0).
  3. Sanity: empty message still 400, unauth still 401.
"""

import os
import sys
import requests

BACKEND_URL = "https://joint-pay-1.preview.emergentagent.com"
API = f"{BACKEND_URL}/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASS = "Letmein@2007#ForReal"

results = []


def record(name: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name} :: {detail}"
    print(line)
    results.append((name, ok, detail))


def login_admin() -> str:
    r = requests.post(
        f"{API}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"No token in login response: {data}"
    return tok


def ensure_mock_mode(token: str):
    """Ensure SMS routing is in mock mode so we don't burn real SMS."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.post(
            f"{API}/admin/integrations/sms-mode",
            json={"mode": "mock"},
            headers=headers,
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[WARN] could not force mock mode: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[WARN] ensure_mock_mode exception: {e}")


def test_dedup_phone_numbers(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "message": "SquadPay test: phone normalization dedup check",
        "audience": "numbers",
        "phone_numbers": ["+12025550123", "2025550123", "(202) 555-0123"],
    }
    r = requests.post(
        f"{API}/admin/bulk-sms/send",
        json=payload,
        headers=headers,
        timeout=60,
    )
    if r.status_code != 200:
        record(
            "1. dedup phone normalization → 200",
            False,
            f"status={r.status_code} body={r.text[:300]}",
        )
        return
    data = r.json()
    rc = data.get("recipient_count")
    record(
        "1. dedup phone normalization → recipient_count == 1",
        rc == 1,
        f"recipient_count={rc}, full_response={data}",
    )


def test_all_users_sanity(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "message": "SquadPay sanity broadcast — please ignore.",
        "audience": "all_users",
    }
    r = requests.post(
        f"{API}/admin/bulk-sms/send",
        json=payload,
        headers=headers,
        timeout=120,
    )
    if r.status_code == 404:
        # 404 is "No phone numbers resolved" — unexpected for a real db with users.
        record(
            "2. all_users sanity broadcast",
            False,
            f"404 No phone numbers resolved: {r.text[:200]}",
        )
        return
    if r.status_code != 200:
        record(
            "2. all_users sanity broadcast → 200",
            False,
            f"status={r.status_code} body={r.text[:300]}",
        )
        return
    data = r.json()
    rc = data.get("recipient_count") or 0
    record(
        "2. all_users sanity broadcast → recipient_count > 0",
        rc > 0,
        f"recipient_count={rc}, sent={data.get('sms_sent')}, failed={data.get('sms_failed')}",
    )


def test_empty_message(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(
        f"{API}/admin/bulk-sms/send",
        json={"message": "   ", "audience": "all_users"},
        headers=headers,
        timeout=30,
    )
    record(
        "3a. empty message → 400",
        r.status_code == 400,
        f"status={r.status_code} body={r.text[:200]}",
    )


def test_unauth():
    r = requests.post(
        f"{API}/admin/bulk-sms/send",
        json={"message": "x", "audience": "all_users"},
        timeout=30,
    )
    # FastAPI HTTPBearer returns 403 when missing; accept 401 or 403 as
    # "rejected because not authenticated". The review request says 401.
    record(
        "3b. no auth → 401",
        r.status_code == 401,
        f"status={r.status_code} body={r.text[:200]}",
    )


def main():
    try:
        token = login_admin()
    except Exception as e:
        print(f"FATAL: admin login failed: {e}")
        sys.exit(2)

    ensure_mock_mode(token)

    test_dedup_phone_numbers(token)
    test_all_users_sanity(token)
    test_empty_message(token)
    test_unauth()

    failed = [r for r in results if not r[1]]
    print("\n=== SUMMARY ===")
    print(f"Total: {len(results)}, Passed: {len(results) - len(failed)}, Failed: {len(failed)}")
    if failed:
        for n, _, d in failed:
            print(f"  FAIL: {n} :: {d}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
