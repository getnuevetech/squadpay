"""Focused re-test of the 4 previously-failing assertions for the
Account Deletion task (App Store Guideline 5.1.1(v)).

Cases:
  A5 / D-list: GET /api/admin/users/deleted → 200, sorted by deleted_at desc.
  B3 second call: 2nd POST /api/users/me/delete → 200 with already_pending:true.
  D1 re-check after restore: user no longer present in /admin/users/deleted.
  D2/D3 purge & list: purged user appears with anonymised name + phone=null.
"""
import json
import time
import sys
import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

SUFFIX = int(time.time()) % 100000
PHONE = f"+1555123{SUFFIX:04d}"[:12]  # keep US-style E.164 11 digits where possible
# Use a deterministic test phone (review used +15551237777 originally)
PHONE_A = f"+1555{(SUFFIX * 7) % 10000000:07d}"
PHONE_B = f"+1555{(SUFFIX * 11) % 10000000:07d}"

OK = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

results = []


def assertion(name: str, cond: bool, detail: str = ""):
    mark = OK if cond else FAIL
    print(f"  {mark} {name}{(' — ' + detail) if detail else ''}")
    results.append((name, bool(cond), detail))
    return cond


def post(path, json_body=None, headers=None):
    r = requests.post(BASE + path, json=json_body or {}, headers=headers or {}, timeout=30)
    return r


def get(path, headers=None):
    r = requests.get(BASE + path, headers=headers or {}, timeout=30)
    return r


def login_admin():
    r = post("/admin/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        print(f"FATAL: admin login failed {r.status_code}: {r.text}")
        sys.exit(1)
    token = r.json().get("token") or r.json().get("access_token")
    if not token:
        print(f"FATAL: admin login returned no token: {r.json()}")
        sys.exit(1)
    return {"Authorization": f"Bearer {token}"}


def force_sms_mock(admin_h):
    try:
        post("/admin/integrations/sms-mode", {"mode": "mock"}, headers=admin_h)
    except Exception:
        pass


def register_verify(name: str, phone: str):
    """Register + send-otp (mock 123456) + verify-otp → return user_id + session_id."""
    r = post("/auth/register", {"name": name})
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    uid = r.json()["id"]
    # send-otp may be rate-limited; back off if needed
    for attempt in range(3):
        rs = post("/auth/send-otp", {"user_id": uid, "phone": phone})
        if rs.status_code == 200:
            break
        if rs.status_code == 429 or "rate" in rs.text.lower():
            time.sleep(15)
            continue
        # try once more after a wait
        time.sleep(5)
    assert rs.status_code == 200, f"send-otp failed: {rs.status_code} {rs.text}"

    rv = post("/auth/verify-otp", {"user_id": uid, "phone": phone, "code": "123456"})
    assert rv.status_code == 200, f"verify-otp failed: {rv.status_code} {rv.text}"
    body = rv.json()
    # In case of phone collapse, returned id may differ.
    real_uid = body.get("id") or uid
    session_id = body.get("session_id")
    assert session_id, f"verify-otp didn't return session_id: {body}"
    return real_uid, session_id


def cleanup_prior(admin_h, phone: str):
    """Purge any previous user owning this phone so we start clean."""
    # use admin search
    r = get(f"/admin/users?q={phone}", headers=admin_h)
    if r.status_code != 200:
        return
    for item in (r.json().get("items") or []):
        uid = item.get("id")
        if not uid:
            continue
        try:
            post(f"/admin/users/{uid}/purge", headers=admin_h)
        except Exception:
            pass


def main():
    print(f"\n=== Account Deletion focused retest — base={BASE} ===\n")
    admin_h = login_admin()
    print(f"{OK} Admin login OK")
    force_sms_mock(admin_h)

    # Pre-clean any stale users using our test phones
    cleanup_prior(admin_h, PHONE_A)
    cleanup_prior(admin_h, PHONE_B)

    # ─────────────────────────────────────────────────────────
    # SETUP A: User A — happy path delete (B3 idempotency)
    # ─────────────────────────────────────────────────────────
    print("\n[B3] Idempotent double-delete")
    user_a_name = f"DelTestA_{SUFFIX}"
    uid_a, sess_a = register_verify(user_a_name, PHONE_A)
    print(f"  user_a id={uid_a} phone={PHONE_A} session={sess_a[:8]}…")

    r1 = post("/users/me/delete", {"user_id": uid_a, "session_id": sess_a, "reason": "retest"})
    assertion("B3.first_delete.200", r1.status_code == 200, f"got {r1.status_code} {r1.text[:160]}")
    if r1.status_code == 200:
        assertion("B3.first_delete.ok_true", r1.json().get("ok") is True)
        assertion("B3.first_delete.no_already_pending_flag", not r1.json().get("already_pending"))

    # Second call with the same body
    r2 = post("/users/me/delete", {"user_id": uid_a, "session_id": sess_a, "reason": "retest"})
    assertion("B3.second_delete.200", r2.status_code == 200, f"got {r2.status_code} {r2.text[:200]}")
    if r2.status_code == 200:
        body2 = r2.json()
        assertion("B3.second_delete.ok_true", body2.get("ok") is True)
        assertion("B3.second_delete.already_pending_true", body2.get("already_pending") is True,
                  f"got already_pending={body2.get('already_pending')}")
        assertion("B3.second_delete.grace_days_30", body2.get("grace_days") == 30,
                  f"got grace_days={body2.get('grace_days')}")
        assertion("B3.second_delete.has_deleted_at", isinstance(body2.get("deleted_at"), str) and bool(body2.get("deleted_at")))
        assertion("B3.second_delete.has_scheduled_purge_at", isinstance(body2.get("scheduled_purge_at"), str) and bool(body2.get("scheduled_purge_at")))
        msg = (body2.get("message") or "").lower()
        assertion("B3.second_delete.message_already_marked",
                  "already" in msg and ("deletion" in msg or "marked for deletion" in msg),
                  f"message={body2.get('message')}")

    # ─────────────────────────────────────────────────────────
    # A5 / D-list: GET /api/admin/users/deleted → 200 with items
    # ─────────────────────────────────────────────────────────
    print("\n[A5/D-list] GET /api/admin/users/deleted")
    rd = get("/admin/users/deleted", headers=admin_h)
    assertion("A5.list_deleted.200", rd.status_code == 200, f"got {rd.status_code} {rd.text[:200]}")
    if rd.status_code == 200:
        body = rd.json()
        assertion("A5.list_deleted.has_items_key", "items" in body)
        assertion("A5.list_deleted.has_count_key", "count" in body)
        assertion("A5.list_deleted.grace_days_30", body.get("grace_days") == 30,
                  f"got grace_days={body.get('grace_days')}")
        items = body.get("items") or []
        ids = {it.get("id") for it in items}
        assertion("A5.list_deleted.contains_user_a", uid_a in ids,
                  f"user_a={uid_a} not in {len(items)} returned items")
        # sort: deleted_at desc
        deleted_ats = [it.get("deleted_at") for it in items if it.get("deleted_at")]
        sorted_desc = deleted_ats == sorted(deleted_ats, reverse=True)
        assertion("A5.list_deleted.sorted_deleted_at_desc", sorted_desc,
                  f"first 3 deleted_at: {deleted_ats[:3]}")

    # ─────────────────────────────────────────────────────────
    # D1 re-check after restore: user disappears from deleted list
    # ─────────────────────────────────────────────────────────
    print("\n[D1] After admin restore → user not in /admin/users/deleted")
    rr = post(f"/admin/users/{uid_a}/restore", headers=admin_h)
    assertion("D1.restore.200", rr.status_code == 200, f"got {rr.status_code} {rr.text[:200]}")
    if rr.status_code == 200:
        assertion("D1.restore.ok_true", rr.json().get("ok") is True)

    rd2 = get("/admin/users/deleted", headers=admin_h)
    assertion("D1.list_deleted_after_restore.200", rd2.status_code == 200)
    if rd2.status_code == 200:
        ids2 = {it.get("id") for it in (rd2.json().get("items") or [])}
        assertion("D1.user_a_not_in_deleted_after_restore", uid_a not in ids2,
                  f"user_a={uid_a} still appears in deleted list after restore")
        # Also verify admin user-detail says is_deleted=False
        rdet = get(f"/admin/users/{uid_a}", headers=admin_h)
        if rdet.status_code == 200:
            data = rdet.json()
            assertion("D1.user_a.is_deleted_false_in_admin_detail",
                      data.get("is_deleted") in (False, None),
                      f"is_deleted={data.get('is_deleted')}")

    # ─────────────────────────────────────────────────────────
    # D2 / D3: Delete user A again, then purge, then list
    # ─────────────────────────────────────────────────────────
    print("\n[D2/D3] Purge after redelete + appears in /admin/users/deleted")

    # We need a fresh session_id (since restore doesn't restore session). Easiest:
    # send-otp + verify-otp again for the same phone (collapse logic returns same id).
    # Honour rate limit.
    time.sleep(15)
    for attempt in range(3):
        rs = post("/auth/send-otp", {"user_id": uid_a, "phone": PHONE_A})
        if rs.status_code == 200:
            break
        time.sleep(15)
    assertion("D2.prep.send_otp.200", rs.status_code == 200, f"got {rs.status_code} {rs.text[:200]}")
    rv = post("/auth/verify-otp", {"user_id": uid_a, "phone": PHONE_A, "code": "123456"})
    assertion("D2.prep.verify_otp.200", rv.status_code == 200, f"got {rv.status_code} {rv.text[:200]}")
    sess_a2 = rv.json().get("session_id") if rv.status_code == 200 else None
    real_uid = rv.json().get("id") if rv.status_code == 200 else uid_a

    if sess_a2:
        rd3 = post("/users/me/delete", {"user_id": real_uid, "session_id": sess_a2})
        assertion("D2.redelete.200", rd3.status_code == 200, f"got {rd3.status_code} {rd3.text[:200]}")

    # Now purge
    rp = post(f"/admin/users/{real_uid}/purge", headers=admin_h)
    assertion("D2.purge.200", rp.status_code == 200, f"got {rp.status_code} {rp.text[:200]}")
    if rp.status_code == 200:
        assertion("D2.purge.purged_true", rp.json().get("purged") is True)

    # List deleted — purged user should still be present with anonymised name
    rd4 = get("/admin/users/deleted", headers=admin_h)
    assertion("D3.list_deleted.200", rd4.status_code == 200, f"got {rd4.status_code} {rd4.text[:200]}")
    if rd4.status_code == 200:
        body4 = rd4.json()
        assertion("D3.count_ge_1", (body4.get("count") or 0) >= 1, f"count={body4.get('count')}")
        items4 = body4.get("items") or []
        purged_entry = next((it for it in items4 if it.get("id") == real_uid), None)
        assertion("D3.purged_user_present", purged_entry is not None,
                  f"purged uid {real_uid} not in deleted list")
        if purged_entry:
            name = purged_entry.get("name") or ""
            assertion("D3.purged.name_anonymised_format",
                      name.startswith("Deleted User (") and name.endswith(")"),
                      f"name={name!r}")
            assertion("D3.purged.name_contains_uid_suffix",
                      real_uid[-6:] in name,
                      f"name={name!r} expected suffix {real_uid[-6:]}")
            assertion("D3.purged.phone_is_null", purged_entry.get("phone") is None,
                      f"phone={purged_entry.get('phone')!r}")
            assertion("D3.purged.is_purged_true", purged_entry.get("is_purged") is True,
                      f"is_purged={purged_entry.get('is_purged')}")

    # ─────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────
    print("\n=== SUMMARY ===")
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"  {passed}/{total} assertions passed.")
    if failed:
        print("  Failed assertions:")
        for n, d in failed:
            print(f"    {FAIL} {n}: {d}")
    print()
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
