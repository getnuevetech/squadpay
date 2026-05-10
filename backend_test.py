"""Backend test for single-active-session enforcement endpoints.

Targets:
  POST /api/auth/verify-otp        (now returns session_id)
  POST /api/auth/check-session     (NEW)
  POST /api/auth/logout            (NEW)

Plus regression on:
  POST /api/auth/register
  POST /api/auth/send-otp
  GET  /api/auth/lookup-phone
  GET  /api/users/{id}
"""
from __future__ import annotations
import os
import sys
import time
import requests

BASE = os.environ.get("BACKEND_URL", "https://joint-pay-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    badge = "PASS" if ok else "FAIL"
    print(f"[{badge}] {name}  {detail}")


def post(path: str, payload: dict, expected: int | None = None):
    r = requests.post(f"{API}{path}", json=payload, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = r.text
    if expected is not None and r.status_code != expected:
        print(f"  -> POST {path} status={r.status_code} expected={expected} body={body}")
    return r.status_code, body


def get(path: str, params: dict | None = None):
    r = requests.get(f"{API}{path}", params=params or {}, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


def unique_phone() -> str:
    n = int(time.time() * 1000) % 10000000
    return f"555{n:07d}"[:10]


def main() -> int:
    print(f"\n=== Single-Session Auth Backend Tests ===\nAPI: {API}\n")

    code = "123456"

    # ---- Pre-flight: confirm SMS mode is mock ----
    s, b = post("/auth/register", {"name": "PreflightProbe"})
    if s != 200:
        record("preflight.register", False, f"status={s} body={b}")
        return 1
    pre_uid = b["id"]
    s, b = post("/auth/send-otp", {"user_id": pre_uid, "phone": unique_phone()})
    if s != 200:
        record("preflight.send_otp", False, f"status={s} body={b}")
        return 1
    is_mock = bool(b.get("mocked"))
    record("preflight.sms_mode_mock", is_mock,
           f"mocked={b.get('mocked')} live={b.get('live')}")
    if not is_mock:
        print("\nSMS mode is LIVE — cannot proceed without real OTP.")
        return 1

    # =========================================================
    # Setup — register the actual session test user
    # =========================================================
    s, body = post("/auth/register", {"name": "SessionTester"})
    record("setup.register_user",
           s == 200 and body.get("verified") is False,
           f"status={s} id={body.get('id')}")
    if s != 200:
        return 1
    user_id = body["id"]
    phone = unique_phone()

    def login() -> str:
        s, b = post("/auth/send-otp", {"user_id": user_id, "phone": phone})
        assert s == 200, f"send-otp failed: {s} {b}"
        s, b = post("/auth/verify-otp",
                    {"user_id": user_id, "phone": phone, "code": code})
        assert s == 200, f"verify-otp failed: {s} {b}"
        sid = b.get("session_id")
        assert sid, f"verify-otp response missing session_id: {b}"
        return sid

    # =========================================================
    # Scenario A — Verify-OTP issues session_id
    # =========================================================
    s, b = post("/auth/send-otp", {"user_id": user_id, "phone": phone})
    record("A.send_otp", s == 200, f"status={s}")

    s, b = post("/auth/verify-otp",
                {"user_id": user_id, "phone": phone, "code": code})
    ok = (
        s == 200
        and isinstance(b, dict)
        and b.get("id") == user_id
        and b.get("name") == "SessionTester"
        and b.get("phone") == phone
        and b.get("verified") is True
        and isinstance(b.get("session_id"), str)
    )
    sid = b.get("session_id") if isinstance(b, dict) else None
    record("A.verify_otp_returns_session_id", ok,
           f"status={s} sid={sid!r}")

    sid_format_ok = bool(sid) and len(sid) == 32 and all(c in "0123456789abcdef" for c in sid)
    record("A.session_id_is_32_hex", sid_format_ok,
           f"len={len(sid) if sid else None}")
    session_id_A = sid

    # =========================================================
    # Scenario B — check-session valid
    # =========================================================
    s, b = post("/auth/check-session", {"user_id": user_id, "session_id": session_id_A})
    record("B.check_valid", s == 200 and b == {"valid": True}, f"status={s} body={b}")

    # =========================================================
    # Scenario C — Second device login invalidates first
    # =========================================================
    session_id_B = login()
    record("C.second_login_new_session", session_id_B != session_id_A,
           f"A={session_id_A[:8]}... B={session_id_B[:8]}...")

    s, b = post("/auth/check-session", {"user_id": user_id, "session_id": session_id_A})
    ok = s == 200 and b == {"valid": False, "reason": "session_superseded"}
    record("C.old_session_superseded", ok, f"status={s} body={b}")

    s, b = post("/auth/check-session", {"user_id": user_id, "session_id": session_id_B})
    record("C.new_session_valid", s == 200 and b == {"valid": True},
           f"status={s} body={b}")

    # =========================================================
    # Scenario D — Logout with matching session_id
    # =========================================================
    s, b = post("/auth/logout", {"user_id": user_id, "session_id": session_id_B})
    record("D.logout_match", s == 200 and b == {"ok": True, "cleared": True},
           f"status={s} body={b}")

    s, b = post("/auth/check-session", {"user_id": user_id, "session_id": session_id_B})
    ok = s == 200 and b == {"valid": False, "reason": "no_active_session"}
    record("D.after_logout_no_active", ok, f"status={s} body={b}")

    # =========================================================
    # Scenario E — Logout with stale session_id (loser device)
    # =========================================================
    session_id_C = login()
    session_id_D = login()
    record("E.precondition_C_neq_D", session_id_C != session_id_D,
           f"C={session_id_C[:8]}... D={session_id_D[:8]}...")

    s, b = post("/auth/logout", {"user_id": user_id, "session_id": session_id_C})
    record("E.stale_logout_no_clear",
           s == 200 and b == {"ok": True, "cleared": False},
           f"status={s} body={b}")

    s, b = post("/auth/check-session", {"user_id": user_id, "session_id": session_id_D})
    record("E.D_still_valid", s == 200 and b == {"valid": True}, f"status={s} body={b}")

    # =========================================================
    # Scenario F — Logout without session_id (force-clear)
    # =========================================================
    s, b = post("/auth/logout", {"user_id": user_id})
    record("F.logout_no_sid", s == 200 and b == {"ok": True, "cleared": True},
           f"status={s} body={b}")

    s, b = post("/auth/check-session", {"user_id": user_id, "session_id": session_id_D})
    ok = s == 200 and b == {"valid": False, "reason": "no_active_session"}
    record("F.after_force_clear_no_active", ok, f"status={s} body={b}")

    # =========================================================
    # Scenario G — Invalid user
    # =========================================================
    s, b = post("/auth/check-session", {"user_id": "u_nonexistent_xyz", "session_id": "abc"})
    ok = s == 200 and b == {"valid": False, "reason": "user_not_found"}
    record("G.user_not_found", ok, f"status={s} body={b}")

    # =========================================================
    # Regression
    # =========================================================
    s, b = get("/auth/lookup-phone", {"phone": phone})
    ok = s == 200 and b.get("exists") is True and b.get("name") == "SessionTester"
    record("R.lookup_phone_existing", ok, f"status={s} body={b}")

    s, b = get("/auth/lookup-phone", {"phone": "9999999999"})
    record("R.lookup_phone_unknown", s == 200 and b == {"exists": False},
           f"status={s} body={b}")

    s, b = get(f"/users/{user_id}")
    ok = (
        s == 200
        and b.get("id") == user_id
        and b.get("name") == "SessionTester"
        and b.get("phone") == phone
        and b.get("verified") is True
        and "referral_code" in b
    )
    record("R.get_user_shape", ok,
           f"status={s} keys={list(b.keys()) if isinstance(b, dict) else b}")

    session_id_E = login()
    s, b = post("/auth/check-session", {"user_id": user_id, "session_id": session_id_E})
    record("R.relogin_after_force_clear", s == 200 and b == {"valid": True},
           f"status={s} body={b}")

    s, b = post("/auth/send-otp", {"user_id": user_id, "phone": phone})
    ok = s == 200 and b.get("mocked") is True and b.get("live") is False and "message" in b
    record("R.send_otp_shape", ok, f"status={s} body={b}")

    post("/auth/logout", {"user_id": user_id})

    passed = sum(1 for _, ok, _ in results if ok)
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n=== Summary: {passed}/{len(results)} passed ===")
    if failed:
        print("Failures:")
        for f in failed:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
