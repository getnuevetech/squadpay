"""
Phase K — Admin Change-Password flow verification
Tests the new /api/admin/auth/change-password endpoint and related profile shape.
"""

import os
import sys
import time
import requests

BASE = os.environ.get("BACKEND_URL", "https://joint-pay-1.preview.emergentagent.com") + "/api"
ADMIN_EMAIL = "admin@squadpay.us"
ORIGINAL_PASSWORD = "Letmein@2007#ForReal"
NEW_PASSWORD = "NewLetmein@2007#ForReal"

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((status, name, detail))
    print(f"[{status}] {name}{('  -> ' + detail) if detail and not cond else ''}")
    return cond


def login(password):
    r = requests.post(
        f"{BASE}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": password},
        timeout=15,
    )
    return r


def main():
    print(f"=== Phase K: Admin Change-Password Flow against {BASE} ===\n")

    # Step 1: Login with original password
    r = login(ORIGINAL_PASSWORD)
    check("1. Login with original password returns 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        print("Cannot continue without initial login.")
        return summarize()
    body = r.json()
    token = body.get("token")
    profile_key = "profile" if "profile" in body else ("admin" if "admin" in body else None)
    check("1b. Login response includes token", bool(token))
    check("1c. Login response includes profile/admin object",
          profile_key is not None,
          f"actual keys: {list(body.keys())}")

    headers = {"Authorization": f"Bearer {token}"}

    # Step 2: GET /me — must include must_change_default_password (boolean)
    r = requests.get(f"{BASE}/admin/auth/me", headers=headers, timeout=15)
    check("2. GET /admin/auth/me returns 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:200]}")
    me = r.json() if r.status_code == 200 else {}
    has_field = "must_change_default_password" in me
    check("2b. /me includes 'must_change_default_password' field", has_field,
          f"keys: {list(me.keys())}")
    if has_field:
        check("2c. must_change_default_password is bool",
              isinstance(me["must_change_default_password"], bool),
              f"type={type(me['must_change_default_password']).__name__} value={me['must_change_default_password']}")

    # Step 3: Change-password without Authorization → 401
    r = requests.post(
        f"{BASE}/admin/auth/change-password",
        json={"current_password": ORIGINAL_PASSWORD, "new_password": "Anything123!"},
        timeout=15,
    )
    check("3. Change-password without Authorization → 401",
          r.status_code == 401, f"got {r.status_code}: {r.text[:200]}")

    # Step 4: Wrong current password → 401, "Current password is incorrect"
    r = requests.post(
        f"{BASE}/admin/auth/change-password",
        headers=headers,
        json={"current_password": "definitely-wrong", "new_password": "NewLongPass123!"},
        timeout=15,
    )
    pass4a = r.status_code == 401
    detail4 = ""
    try:
        detail4 = r.json().get("detail", "")
    except Exception:
        detail4 = r.text
    check("4. Wrong current password → 401", pass4a,
          f"got {r.status_code}: {r.text[:200]}")
    check("4b. Detail = 'Current password is incorrect'",
          detail4 == "Current password is incorrect",
          f"detail: {detail4!r}")

    # Step 5: New too short → 400 "New password must be at least 8 characters"
    r = requests.post(
        f"{BASE}/admin/auth/change-password",
        headers=headers,
        json={"current_password": ORIGINAL_PASSWORD, "new_password": "abc"},
        timeout=15,
    )
    detail5 = ""
    try:
        detail5 = r.json().get("detail", "")
    except Exception:
        detail5 = r.text
    check("5. New password too short → 400", r.status_code == 400,
          f"got {r.status_code}: {r.text[:200]}")
    check("5b. Detail = 'New password must be at least 8 characters'",
          detail5 == "New password must be at least 8 characters",
          f"detail: {detail5!r}")

    # Step 6: New same as current → 400 "New password must differ from current password"
    r = requests.post(
        f"{BASE}/admin/auth/change-password",
        headers=headers,
        json={"current_password": ORIGINAL_PASSWORD, "new_password": ORIGINAL_PASSWORD},
        timeout=15,
    )
    detail6 = ""
    try:
        detail6 = r.json().get("detail", "")
    except Exception:
        detail6 = r.text
    check("6. New same as current → 400", r.status_code == 400,
          f"got {r.status_code}: {r.text[:200]}")
    check("6b. Detail = 'New password must differ from current password'",
          detail6 == "New password must differ from current password",
          f"detail: {detail6!r}")

    # Step 7: Happy path — change to NEW_PASSWORD
    r = requests.post(
        f"{BASE}/admin/auth/change-password",
        headers=headers,
        json={"current_password": ORIGINAL_PASSWORD, "new_password": NEW_PASSWORD},
        timeout=15,
    )
    check("7. Happy path change-password → 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:200]}")
    try:
        ok_body = r.json()
        check("7b. Response is {ok:true}", ok_body == {"ok": True} or ok_body.get("ok") is True,
              f"body: {ok_body!r}")
    except Exception:
        check("7b. Response JSON parses", False, r.text[:200])

    # Step 8: Old password should now be rejected
    r = login(ORIGINAL_PASSWORD)
    check("8. Login with OLD password → 401", r.status_code == 401,
          f"got {r.status_code}: {r.text[:200]}")

    # Step 9: New password works → fresh token
    r = login(NEW_PASSWORD)
    check("9. Login with NEW password → 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:200]}")
    new_token = None
    if r.status_code == 200:
        new_body = r.json()
        new_token = new_body.get("token")
        check("9b. Fresh token returned", bool(new_token) and new_token != token)

    # Step 10: /me after rotation → must_change_default_password == False
    if new_token:
        r = requests.get(
            f"{BASE}/admin/auth/me",
            headers={"Authorization": f"Bearer {new_token}"},
            timeout=15,
        )
        check("10. GET /me with new bearer → 200", r.status_code == 200,
              f"got {r.status_code}")
        if r.status_code == 200:
            me2 = r.json()
            check("10b. must_change_default_password == False",
                  me2.get("must_change_default_password") is False,
                  f"value: {me2.get('must_change_default_password')!r}")
    else:
        check("10. /me after rotation (skipped — no new token)", False)

    # Step 11: Audit row exists for admin.change_password by admin@squadpay.us
    if new_token:
        r = requests.get(
            f"{BASE}/admin/audit-log",
            headers={"Authorization": f"Bearer {new_token}"},
            params={"limit": 50, "action": "admin.change_password"},
            timeout=15,
        )
        check("11. GET /admin/audit-log → 200", r.status_code == 200,
              f"got {r.status_code}: {r.text[:200]}")
        if r.status_code == 200:
            items = r.json().get("items", [])
            match = [
                it for it in items
                if it.get("action") == "admin.change_password"
                and it.get("admin_email") == ADMIN_EMAIL
            ]
            check("11b. Recent audit row exists with action=admin.change_password and admin_email=admin@squadpay.us",
                  len(match) >= 1,
                  f"matching rows: {len(match)}; first item: {items[0] if items else 'none'}")
    else:
        check("11. Audit row check (skipped — no new token)", False)

    # Step 12: RESTORE the password (CRITICAL)
    restore_ok = False
    if new_token:
        r = requests.post(
            f"{BASE}/admin/auth/change-password",
            headers={"Authorization": f"Bearer {new_token}"},
            json={"current_password": NEW_PASSWORD, "new_password": ORIGINAL_PASSWORD},
            timeout=15,
        )
        check("12. RESTORE password change → 200", r.status_code == 200,
              f"got {r.status_code}: {r.text[:200]}")
        # Confirm by logging back in with original
        r2 = login(ORIGINAL_PASSWORD)
        restore_ok = r2.status_code == 200
        check("12b. Login with ORIGINAL password works again → 200",
              restore_ok, f"got {r2.status_code}: {r2.text[:200]}")
    else:
        check("12. RESTORE password (CRITICAL — could not restore, no new_token)", False)

    summarize()
    return restore_ok


def summarize():
    passed = sum(1 for s, *_ in results if s == "PASS")
    failed = sum(1 for s, *_ in results if s == "FAIL")
    print(f"\n=== Phase K SUMMARY: {passed} PASS, {failed} FAIL ===")
    if failed:
        print("FAILED checks:")
        for s, name, detail in results:
            if s == "FAIL":
                print(f"  - {name}: {detail}")


if __name__ == "__main__":
    main()
