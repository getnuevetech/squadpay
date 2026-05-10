"""
Backend test for POST /api/admin/groups/{group_id}/reassign-lead

Runs 8 scenarios against the live preview backend and reports PASS/FAIL.
"""

import json
import sys
import time
import uuid
import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
SUPER_EMAIL = "admin@squadpay.us"
SUPER_PASSWORD = "Letmein@2007#ForReal"


def jprint(label, resp):
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    print(f"  {label}: HTTP {resp.status_code}  body={json.dumps(body, default=str)[:600]}")
    return body


def login_super():
    r = requests.post(
        f"{BASE}/admin/auth/login",
        json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"super-admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def create_support_admin(super_token):
    """Create a support-role admin (non super_admin) for the role-guard test."""
    ts = int(time.time())
    email = f"support+{ts}@squadpay.us"
    password = "SupportTest@2026"
    r = requests.post(
        f"{BASE}/admin/admins",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "email": email,
            "password": password,
            "name": f"Support Tester {ts}",
            "role": "support",
        },
        timeout=30,
    )
    assert r.status_code == 200, f"create support admin failed: {r.status_code} {r.text}"
    # Login
    r = requests.post(
        f"{BASE}/admin/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"support login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def find_group_with_2plus(super_token):
    """Find a group with member_count >= 2; return (group_id, lead_id, members)."""
    headers = {"Authorization": f"Bearer {super_token}"}
    # Pull a few pages to find one with >= 2 members
    for skip in range(0, 200, 20):
        r = requests.get(
            f"{BASE}/admin/groups?limit=20&skip={skip}",
            headers=headers,
            timeout=30,
        )
        if r.status_code != 200:
            break
        data = r.json()
        items = data.get("items", []) if isinstance(data, dict) else data
        if not items:
            break
        for g in items:
            mc = g.get("members_count") or g.get("member_count") or len(g.get("members") or [])
            if mc and mc >= 2:
                gid = g.get("id")
                # Get full detail
                r2 = requests.get(f"{BASE}/admin/groups/{gid}", headers=headers, timeout=30)
                if r2.status_code != 200:
                    continue
                detail = r2.json()
                members = detail.get("members") or []
                lead_id = detail.get("lead_id")
                if lead_id and len(members) >= 2:
                    return gid, lead_id, members, detail
    return None, None, None, None


def main():
    results = []  # list of (case_name, pass_bool, info)

    print("=== STEP 1: super-admin login ===")
    super_token = login_super()
    print(f"  Got super-admin token (first 20 chars): {super_token[:20]}...")
    super_headers = {"Authorization": f"Bearer {super_token}"}

    print("\n=== STEP 2: find group with >= 2 members ===")
    gid, lead_id, members, detail = find_group_with_2plus(super_token)
    if not gid:
        print("FATAL: no group with >= 2 members found in /admin/groups. Cannot run tests.")
        sys.exit(2)
    print(f"  Group: {gid}")
    print(f"  Current lead_id: {lead_id}")
    print(f"  Members ({len(members)}):")
    for m in members[:10]:
        print(f"    - user_id={m.get('user_id')!r:40s} name={m.get('name')!r}")
    non_lead = [m for m in members if m.get("user_id") and m.get("user_id") != lead_id]
    if not non_lead:
        print("FATAL: no non-lead member found.")
        sys.exit(2)
    new_lead = non_lead[0]["user_id"]
    print(f"  Will use new_lead user_id={new_lead}")

    print("\n=== STEP 3: create support admin (for role-guard test) ===")
    try:
        support_token = create_support_admin(super_token)
        print(f"  support token (first 20): {support_token[:20]}...")
    except Exception as e:
        print(f"  FAILED to create support admin: {e}")
        support_token = None

    print("\n=== TEST CASES ===")

    # ---- Case 1: No auth ----
    print("\n[Case 1] No auth")
    url = f"{BASE}/admin/groups/{gid}/reassign-lead"
    payload = {"new_lead_user_id": "u_x"}
    r = requests.post(url, json=payload, timeout=30)
    body = jprint("response", r)
    detail_str = (body.get("detail") if isinstance(body, dict) else str(body)) or ""
    ok = (r.status_code == 401) and ("Admin auth required" in str(detail_str))
    results.append(("Case 1 — No auth → 401 'Admin auth required'", ok, {
        "request": {"url": url, "headers": {}, "body": payload},
        "status": r.status_code, "body": body,
    }))
    print(f"  -> {'PASS' if ok else 'FAIL'}")

    # ---- Case 2: Insufficient role ----
    print("\n[Case 2] Insufficient role (support admin)")
    if support_token:
        r = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {support_token}"},
            timeout=30,
        )
        body = jprint("response", r)
        ok = (r.status_code == 403)
        results.append(("Case 2 — Insufficient role → 403", ok, {
            "request": {"url": url, "headers": "Bearer <support>", "body": payload},
            "status": r.status_code, "body": body,
        }))
        print(f"  -> {'PASS' if ok else 'FAIL'}")
    else:
        results.append(("Case 2 — Insufficient role → 403", False, "support admin creation failed"))
        print("  -> FAIL (could not create support admin)")

    # ---- Case 3: Unknown group ----
    print("\n[Case 3] Unknown group")
    bad_url = f"{BASE}/admin/groups/g_doesnotexist_xxx/reassign-lead"
    r = requests.post(bad_url, json={"new_lead_user_id": "u_x"}, headers=super_headers, timeout=30)
    body = jprint("response", r)
    detail_str = (body.get("detail") if isinstance(body, dict) else str(body)) or ""
    ok = (r.status_code == 404) and ("Group not found" in str(detail_str))
    results.append(("Case 3 — Unknown group → 404 'Group not found'", ok, {
        "request": {"url": bad_url, "body": {"new_lead_user_id": "u_x"}},
        "status": r.status_code, "body": body,
    }))
    print(f"  -> {'PASS' if ok else 'FAIL'}")

    # ---- Case 4: Empty body ----
    print("\n[Case 4] Empty new_lead_user_id")
    r = requests.post(url, json={"new_lead_user_id": ""}, headers=super_headers, timeout=30)
    body = jprint("response", r)
    detail_str = (body.get("detail") if isinstance(body, dict) else str(body)) or ""
    ok = (r.status_code == 400) and ("required" in str(detail_str).lower())
    results.append(("Case 4 — Empty body → 400 'required'", ok, {
        "request": {"url": url, "body": {"new_lead_user_id": ""}},
        "status": r.status_code, "body": body,
    }))
    print(f"  -> {'PASS' if ok else 'FAIL'}")

    # ---- Case 5: Stranger as new lead ----
    print("\n[Case 5] Stranger as new lead")
    r = requests.post(url, json={"new_lead_user_id": "u_strangertest9999"}, headers=super_headers, timeout=30)
    body = jprint("response", r)
    detail_str = (body.get("detail") if isinstance(body, dict) else str(body)) or ""
    ok = (r.status_code == 400) and ("existing member" in str(detail_str).lower())
    results.append(("Case 5 — Stranger → 400 'existing member of this group'", ok, {
        "request": {"url": url, "body": {"new_lead_user_id": "u_strangertest9999"}},
        "status": r.status_code, "body": body,
    }))
    print(f"  -> {'PASS' if ok else 'FAIL'}")

    # ---- Case 6: Idempotent same user ----
    print("\n[Case 6] Idempotent same user (current lead)")
    r = requests.post(url, json={"new_lead_user_id": lead_id}, headers=super_headers, timeout=30)
    body = jprint("response", r)
    ok = (
        r.status_code == 200
        and isinstance(body, dict)
        and body.get("ok") is True
        and body.get("lead_id") == lead_id
        and body.get("no_change") is True
    )
    results.append(("Case 6 — Idempotent same user → 200 ok+no_change=true", ok, {
        "request": {"url": url, "body": {"new_lead_user_id": lead_id}},
        "status": r.status_code, "body": body,
    }))
    print(f"  -> {'PASS' if ok else 'FAIL'}")

    # ---- Case 7: Happy path ----
    print(f"\n[Case 7] Happy path — assign to non-lead user_id={new_lead}")
    r = requests.post(url, json={"new_lead_user_id": new_lead}, headers=super_headers, timeout=30)
    body = jprint("response", r)
    ok_post = (
        r.status_code == 200
        and isinstance(body, dict)
        and body.get("ok") is True
        and body.get("lead_id") == new_lead
    )
    # Verify persistence + lead_reassigned_at
    r2 = requests.get(f"{BASE}/admin/groups/{gid}", headers=super_headers, timeout=30)
    detail2 = r2.json() if r2.status_code == 200 else {}
    persisted_lead = detail2.get("lead_id")
    reassigned_at = detail2.get("lead_reassigned_at")
    print(f"  re-GET lead_id={persisted_lead!r}  lead_reassigned_at={reassigned_at!r}")
    ok_persist = (persisted_lead == new_lead) and bool(reassigned_at)
    ok7 = ok_post and ok_persist
    results.append(("Case 7 — Happy path → 200 + persisted lead_id + lead_reassigned_at set", ok7, {
        "request": {"url": url, "body": {"new_lead_user_id": new_lead}},
        "status": r.status_code, "body": body,
        "persisted_lead": persisted_lead, "lead_reassigned_at": reassigned_at,
    }))
    print(f"  -> {'PASS' if ok7 else 'FAIL'}")

    # ---- Case 8: Cleanup — reassign back ----
    print(f"\n[Case 8] Cleanup — restore original lead {lead_id}")
    r = requests.post(url, json={"new_lead_user_id": lead_id}, headers=super_headers, timeout=30)
    body = jprint("response", r)
    ok = (
        r.status_code == 200
        and isinstance(body, dict)
        and body.get("ok") is True
        and body.get("lead_id") == lead_id
    )
    r3 = requests.get(f"{BASE}/admin/groups/{gid}", headers=super_headers, timeout=30)
    if r3.status_code == 200:
        post_lead = r3.json().get("lead_id")
        print(f"  re-GET lead_id post-cleanup={post_lead!r}")
        ok = ok and (post_lead == lead_id)
    results.append(("Case 8 — Cleanup → restored to original lead", ok, {
        "request": {"url": url, "body": {"new_lead_user_id": lead_id}},
        "status": r.status_code, "body": body,
    }))
    print(f"  -> {'PASS' if ok else 'FAIL'}")

    # ---- Tally ----
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 70)
    print("FINAL RESULTS:")
    print("=" * 70)
    for name, ok, info in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            print(f"         info: {json.dumps(info, default=str)[:800]}")
    print(f"\n{passed} of {total} PASS")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
