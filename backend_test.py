"""Backend test harness for Account Deletion (App Store 5.1.1(v)).

Runs against the live preview backend.

Covers the 4 case groups from the review request:
  (A) Happy path
  (B) Auth guards
  (C) Phone-collision blocks new placeholder login
  (D) Admin endpoints (restore / purge / list deleted)

Notes:
  - send-otp endpoint is rate-limited to 5/minute per IP, so we space out
    OTP sends with explicit sleeps (~14s) to stay under the limit.
  - We use the exact phone from the spec (+15551237777) since SMS provider is
    forced to "mock" mode (OTP is always "123456").
"""
import json
import sys
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

TS = int(time.time())
SUFFIX = f"{TS % 100000:05d}"
PHONE = "+15551237777"  # spec phone — SMS mode is mock so number doesn't matter

OTP_BACKOFF_S = 14  # send-otp is 5/minute; 14s spacing keeps us safe

_passes = []
_fails = []


def ok(name, cond, detail=""):
    if cond:
        _passes.append(name)
        print(f"  ✅ {name}")
    else:
        _fails.append((name, detail))
        print(f"  ❌ {name} -- {detail}")


def post(path, json_body=None, headers=None):
    url = f"{BASE}{path}"
    try:
        r = requests.post(url, json=json_body or {}, headers=headers or {}, timeout=30)
    except Exception as e:
        return None, {"error": str(e)}
    try:
        data = r.json()
    except Exception:
        data = {"_raw": r.text}
    return r, data


def get(path, headers=None, params=None):
    url = f"{BASE}{path}"
    try:
        r = requests.get(url, headers=headers or {}, params=params or {}, timeout=30)
    except Exception as e:
        return None, {"error": str(e)}
    try:
        data = r.json()
    except Exception:
        data = {"_raw": r.text}
    return r, data


def _status(r):
    return r.status_code if r is not None else None


def admin_login() -> Optional[str]:
    r, data = post("/admin/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if _status(r) != 200:
        print(f"  !! admin login failed: {_status(r)} {data}")
        return None
    return data.get("token") or data.get("access_token")


def ensure_mock_mode(token: str):
    r, _ = post("/admin/integrations/sms-mode", {"mode": "mock"},
                headers={"Authorization": f"Bearer {token}"})
    print(f"  [setup] sms-mode=mock -> status={_status(r)}")


def register(name: str) -> Optional[str]:
    r, data = post("/auth/register", {"name": name})
    if _status(r) != 200:
        print(f"  !! register failed: {_status(r)} {data}")
        return None
    return data.get("id")


def send_otp_with_retry(user_id: str, phone: str, max_wait_s: int = 75) -> Tuple[int, dict]:
    """Sends OTP; on 429 sleeps and retries up to max_wait_s seconds."""
    start = time.time()
    while True:
        r, data = post("/auth/send-otp", {"user_id": user_id, "phone": phone})
        st = _status(r)
        if st != 429:
            return st, data
        if time.time() - start > max_wait_s:
            return st, data
        print(f"  [rate-limited; sleeping {OTP_BACKOFF_S}s]")
        time.sleep(OTP_BACKOFF_S)


def verify_otp(user_id: str, phone: str, code: str = "123456",
               confirm_existing: bool = False) -> Tuple[int, dict]:
    body = {"user_id": user_id, "phone": phone, "code": code}
    if confirm_existing:
        body["confirm_existing"] = True
    r, data = post("/auth/verify-otp", body)
    return _status(r), data


def main():
    print(f"BASE = {BASE}")
    print(f"PHONE = {PHONE}")

    print("\n[setup] admin login & SMS mock mode")
    admin_token = admin_login()
    if not admin_token:
        print("FATAL: cannot get admin token; aborting")
        sys.exit(2)
    ok("admin.login", bool(admin_token))
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    ensure_mock_mode(admin_token)

    # Pre-clean: if PHONE is owned by a previously-deleted user, purge them
    # so we can reuse it. Some side effects from earlier test runs may persist.
    r, data = get("/admin/users/deleted", headers=admin_headers)
    pre_clean_blocked = False
    if _status(r) == 200 and isinstance(data, dict):
        for it in (data.get("items") or []):
            if it.get("phone") == PHONE and not it.get("is_purged"):
                # Purge it to free up the phone slot.
                pr, _ = post(f"/admin/users/{it['id']}/purge", headers=admin_headers)
                print(f"  [pre-clean] purged stale deleted user {it['id']} -> {_status(pr)}")
    else:
        # admin/users/deleted endpoint hit the route-shadow bug; can't pre-clean.
        # Continue regardless — we'll surface the bug in the actual test.
        pre_clean_blocked = True
        print(f"  [pre-clean] admin/users/deleted not reachable yet: {_status(r)} {data}")

    # ────────────────────────────────────────────────────────────
    # (A) HAPPY PATH
    # ────────────────────────────────────────────────────────────
    print("\n[A] Happy path")
    uid = register(f"DelTest_{SUFFIX}")
    ok("A1.register.200", bool(uid), f"got {uid}")
    ok("A1.user_id_prefix", (uid or "").startswith("u_"))

    status, data = send_otp_with_retry(uid, PHONE)
    ok("A2.send_otp.200", status == 200, f"status={status} body={data}")
    msg = (data.get("message") or "").lower() if isinstance(data, dict) else ""
    ok("A2.mock_code_hint", "123456" in msg or data.get("mocked") is True,
       f"body={data}")

    status, data = verify_otp(uid, PHONE, "123456")
    # If there's a leftover verified user with this phone (from earlier runs),
    # we may get a 409 collision — confirm and retry.
    if status == 409:
        status, data = verify_otp(uid, PHONE, "123456", confirm_existing=True)
    ok("A3.verify_otp.200", status == 200, f"status={status} body={data}")
    session_id = data.get("session_id")
    ok("A3.session_id_present", bool(session_id))
    # uid may have been collapsed if the phone was already verified earlier
    uid = data.get("id") or uid

    r, data = post("/users/me/delete", {
        "user_id": uid, "session_id": session_id, "reason": "qa run",
    })
    status = _status(r)
    ok("A4.delete.200", status == 200, f"status={status} body={data}")
    ok("A4.delete.ok_true", data.get("ok") is True, f"body={data}")
    spa = data.get("scheduled_purge_at")
    ok("A4.scheduled_purge_at_present", bool(spa))
    ok("A4.grace_days_30", data.get("grace_days") == 30)
    if spa:
        try:
            spa_dt = datetime.fromisoformat(spa.replace("Z", "+00:00"))
            delta_days = (spa_dt - datetime.now(timezone.utc)).total_seconds() / 86400.0
            ok("A4.purge_in_~30d", 29.5 < delta_days < 30.5, f"delta={delta_days:.2f}d")
        except Exception as e:
            ok("A4.purge_iso_parse", False, f"err={e} spa={spa}")

    # A5: confirm soft-delete state. Admin /admin/users/deleted (CRITICAL — may be
    # shadowed by /admin/users/{user_id} route). Also confirm GET /users/{uid}
    # still returns during grace (PII preserved).
    r, data = get("/admin/users/deleted", headers=admin_headers)
    if _status(r) == 200:
        items = data.get("items") or []
        found_in_deleted = any(it.get("id") == uid for it in items)
        ok("A5.user_appears_in_admin_deleted_list", found_in_deleted,
           f"uid={uid} item_count={len(items)}")
    else:
        ok("A5.user_appears_in_admin_deleted_list", False,
           f"endpoint returned {_status(r)} {data} -- "
           f"CRITICAL: /admin/users/deleted is shadowed by /admin/users/{{user_id}}")

    r, data = get(f"/users/{uid}")
    ok("A5b.get_user_returns_during_grace", _status(r) == 200, f"status={_status(r)}")
    if _status(r) == 200:
        ok("A5b.name_preserved_during_grace",
           isinstance(data.get("name"), str) and data["name"].startswith("DelTest_"),
           f"name={data.get('name')}")

    # A6: send_otp on deleted user → 403
    # NOTE: we have just sent an OTP earlier so we may hit rate limit. Use retry.
    status, data = send_otp_with_retry(uid, PHONE)
    detail_raw = data.get("detail") if isinstance(data, dict) else ""
    detail = json.dumps(detail_raw) if isinstance(detail_raw, dict) else str(detail_raw or "")
    ok("A6.send_otp_blocked.403", status == 403, f"status={status} body={data}")
    ok("A6.msg_contains_deleted", "deleted" in detail.lower(), f"detail={detail}")
    ok("A6.msg_contains_help_email", "help@squadpay.us" in detail.lower(), f"detail={detail}")

    # ────────────────────────────────────────────────────────────
    # (B) AUTH GUARDS
    # ────────────────────────────────────────────────────────────
    print("\n[B] Auth guards")

    # Restore via admin so we can get a fresh session id and run B1/B2/B3.
    r, data = post(f"/admin/users/{uid}/restore", headers=admin_headers)
    ok("B.setup.admin_restore.200", _status(r) == 200, f"status={_status(r)} body={data}")

    # Wait a bit to let any OTP rate-limit window expire before the next send
    time.sleep(OTP_BACKOFF_S)
    status, data = send_otp_with_retry(uid, PHONE)
    ok("B.setup.send_otp.200", status == 200, f"status={status} body={data}")
    status, data = verify_otp(uid, PHONE, "123456")
    if status == 409:
        status, data = verify_otp(uid, PHONE, "123456", confirm_existing=True)
    ok("B.setup.verify_otp.200", status == 200, f"status={status} body={data}")
    real_sid = data.get("session_id")
    uid = data.get("id") or uid

    # B1: bogus session_id → 401 Invalid session
    r, data = post("/users/me/delete", {
        "user_id": uid, "session_id": "totally-bogus-session-xyz", "reason": "qa B1",
    })
    ok("B1.bogus_session.401", _status(r) == 401, f"status={_status(r)} body={data}")
    ok("B1.detail_invalid_session",
       "invalid session" in str(data.get("detail") or "").lower(),
       f"detail={data.get('detail')}")

    # B2: unknown user_id → 404 User not found
    r, data = post("/users/me/delete", {
        "user_id": "u_doesnotexist_999", "session_id": "x", "reason": "qa B2",
    })
    ok("B2.unknown_user.404", _status(r) == 404, f"status={_status(r)} body={data}")
    ok("B2.detail_user_not_found",
       "user not found" in str(data.get("detail") or "").lower(),
       f"detail={data.get('detail')}")

    # B3: happy-path delete called twice (without restoring in between).
    # Spec: 2nd call should still return 200 with already_pending:true.
    r, data = post("/users/me/delete", {
        "user_id": uid, "session_id": real_sid, "reason": "qa B3.1",
    })
    ok("B3.first_delete.200", _status(r) == 200, f"status={_status(r)} body={data}")
    ok("B3.first.not_already_pending",
       data.get("ok") is True and not data.get("already_pending"),
       f"body={data}")

    # Second call with the SAME session_id. Server clears current_session_id on
    # delete, so _verify_session will see (current=None) != session_id and 401.
    # Spec expects 200 already_pending:true — this exposes an ordering bug
    # where idempotency check happens AFTER session-equality check.
    r, data = post("/users/me/delete", {
        "user_id": uid, "session_id": real_sid, "reason": "qa B3.2",
    })
    ok("B3.second_delete.200_already_pending",
       _status(r) == 200 and data.get("already_pending") is True,
       f"status={_status(r)} body={data} -- expected 200 already_pending:true per spec")

    # B4: admin restore without Bearer → 401 or 403
    r, data = post(f"/admin/users/{uid}/restore")  # no admin headers
    ok("B4.admin_restore_no_token.401_or_403", _status(r) in (401, 403),
       f"status={_status(r)} body={data}")

    # ────────────────────────────────────────────────────────────
    # (C) PHONE COLLISION
    # ────────────────────────────────────────────────────────────
    print("\n[C] Phone collision blocks new placeholder login")
    new_uid = register(f"CollideTest_{SUFFIX}")
    ok("C.register_new_placeholder.200", bool(new_uid))

    # uid is still soft-deleted (B3 deleted it). Send OTP from NEW placeholder
    # for the SAME phone → expect 403 collision message. Backoff first.
    time.sleep(OTP_BACKOFF_S)
    status, data = send_otp_with_retry(new_uid, PHONE)
    detail_raw = data.get("detail") if isinstance(data, dict) else ""
    detail = json.dumps(detail_raw) if isinstance(detail_raw, dict) else str(detail_raw or "")
    ok("C.collision.403", status == 403, f"status={status} body={data}")
    ok("C.msg_mentions_deleted_phone",
       "deleted" in detail.lower() and "phone" in detail.lower(),
       f"detail={detail}")

    # ────────────────────────────────────────────────────────────
    # (D) ADMIN ENDPOINTS
    # ────────────────────────────────────────────────────────────
    print("\n[D] Admin endpoints (restore / purge / list deleted)")

    # D1: admin restore the user
    r, data = post(f"/admin/users/{uid}/restore", headers=admin_headers)
    ok("D1.admin_restore.200", _status(r) == 200, f"status={_status(r)} body={data}")
    ok("D1.restored_true", data.get("restored") is True or data.get("already_active") is True,
       f"body={data}")

    # confirm via admin/users/deleted no longer contains user
    r, data = get("/admin/users/deleted", headers=admin_headers)
    if _status(r) == 200:
        items = data.get("items") or []
        ok("D1.user_not_in_deleted_list_after_restore",
           not any(it.get("id") == uid for it in items),
           f"items count={len(items)}")
    else:
        ok("D1.user_not_in_deleted_list_after_restore", False,
           f"endpoint shadowed: {_status(r)} {data}")

    # D2: soft-delete again, then purge
    time.sleep(OTP_BACKOFF_S)
    status, data = send_otp_with_retry(uid, PHONE)
    ok("D2.setup.send_otp.200", status == 200, f"status={status} body={data}")
    status, data = verify_otp(uid, PHONE, "123456")
    if status == 409:
        status, data = verify_otp(uid, PHONE, "123456", confirm_existing=True)
    ok("D2.setup.verify_otp.200", status == 200, f"status={status} body={data}")
    sid2 = data.get("session_id")
    uid = data.get("id") or uid

    r, data = post("/users/me/delete", {
        "user_id": uid, "session_id": sid2, "reason": "qa D2",
    })
    ok("D2.soft_delete_again.200", _status(r) == 200, f"status={_status(r)} body={data}")

    r, data = post(f"/admin/users/{uid}/purge", headers=admin_headers)
    ok("D2.admin_purge.200", _status(r) == 200, f"status={_status(r)} body={data}")
    ok("D2.purged_true", data.get("purged") is True, f"body={data}")

    r, data = get(f"/users/{uid}")
    ok("D2.get_user_after_purge.200", _status(r) == 200, f"status={_status(r)} body={data}")
    if _status(r) == 200:
        name = data.get("name") or ""
        ok("D2.name_starts_with_Deleted_User", name.startswith("Deleted User"),
           f"name={name!r}")
        ok("D2.phone_is_null", data.get("phone") in (None, ""),
           f"phone={data.get('phone')!r}")

    # D3: admin/users/deleted
    r, data = get("/admin/users/deleted", headers=admin_headers)
    status = _status(r)
    ok("D3.admin_list_deleted.200", status == 200, f"status={status} body={data}")
    if status == 200 and isinstance(data, dict):
        items = data.get("items") or []
        ok("D3.purged_user_in_list", any(it.get("id") == uid for it in items),
           f"uid={uid}; ids={[it.get('id') for it in items[:10]]}")
        ok("D3.grace_days_30", data.get("grace_days") == 30, f"keys={list(data.keys())}")
        ok("D3.has_items_array", isinstance(items, list), f"type={type(items).__name__}")

    # ────────────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print(f"PASSED: {len(_passes)}    FAILED: {len(_fails)}")
    if _fails:
        print("\nFailures:")
        for n, d in _fails:
            print(f"  ❌ {n}\n     {d}")
    print("=" * 64)
    return 0 if not _fails else 1


if __name__ == "__main__":
    sys.exit(main())
