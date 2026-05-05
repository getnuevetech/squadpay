"""Phase C1 — Referrals backend test suite.

Run: python /app/backend_test.py
Reads EXPO_PUBLIC_BACKEND_URL from /app/frontend/.env, all calls under /api.
Admin credentials: super_admin from /app/memory/test_credentials.md.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from typing import Any, Dict, Optional, Tuple

import requests

# ----- Config -----
def _load_backend_url() -> str:
    env_path = "/app/frontend/.env"
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not found in /app/frontend/.env")


BASE = _load_backend_url().rstrip("/") + "/api"
ADMIN_EMAIL = "[email protected]"
ADMIN_PASSWORD = "ChangeMe123!"

REFERRAL_ALPHABET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")

# ----- Test runner -----
RESULTS = []  # list of (name, ok, msg)


def record(name: str, ok: bool, msg: str = ""):
    RESULTS.append((name, ok, msg))
    sym = "PASS" if ok else "FAIL"
    print(f"[{sym}] {name}: {msg}")


def expect(cond: bool, name: str, msg: str = ""):
    record(name, bool(cond), msg)
    return bool(cond)


def http(method: str, path: str, **kw) -> requests.Response:
    url = f"{BASE}{path}"
    return requests.request(method, url, timeout=30, **kw)


def jdump(r: requests.Response) -> str:
    try:
        return json.dumps(r.json())[:300]
    except Exception:
        return r.text[:300]


# ----- Auth helpers -----
def admin_login(email: str = ADMIN_EMAIL, pw: str = ADMIN_PASSWORD) -> str:
    r = http("POST", "/admin/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, f"admin login failed {r.status_code} {r.text}"
    return r.json()["token"]


def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_user(name: str, referral_code: Optional[str] = None) -> requests.Response:
    payload: Dict[str, Any] = {"name": name}
    if referral_code is not None:
        payload["referral_code"] = referral_code
    return http("POST", "/auth/register", json=payload)


def send_otp(user_id: str, phone: str) -> requests.Response:
    return http("POST", "/auth/send-otp", json={"user_id": user_id, "phone": phone})


def verify_otp(user_id: str, phone: str, code: str = "123456") -> requests.Response:
    return http("POST", "/auth/verify-otp", json={"user_id": user_id, "phone": phone, "code": code})


def fresh_phone(seq: int = 0) -> str:
    # +1555 + 7 digits
    base = int(time.time())
    return f"+1555{(base + seq) % 10000000:07d}"


# ----- Scenarios -----
def main():
    print(f"BASE = {BASE}")
    ts = int(time.time())

    # Admin login (used throughout)
    token = admin_login()
    H = auth_headers(token)
    expect(bool(token), "admin_login", "got token")

    # Get current settings (and remember to restore at cleanup)
    r = http("GET", "/admin/referrals/settings", headers=H)
    expect(r.status_code == 200, "settings.get_initial", f"{r.status_code} {jdump(r)}")
    initial_settings = r.json() if r.status_code == 200 else {}

    # Reset to default disabled state to start
    r = http("POST", "/admin/referrals/settings",
             headers=H, json={"enabled": False, "referrer_credit": 0, "referee_credit": 0})
    expect(r.status_code == 200, "settings.reset_disabled", f"{r.status_code}")

    # ----- A) Code generation -----
    r1 = register_user(f"AliceC1{ts}")
    r2 = register_user(f"BobC1{ts}")
    expect(r1.status_code == 200, "A.register_alice", f"{r1.status_code} {jdump(r1)}")
    expect(r2.status_code == 200, "A.register_bob", f"{r2.status_code} {jdump(r2)}")
    alice = r1.json()
    bob = r2.json()
    alice_code = alice.get("referral_code")
    bob_code = bob.get("referral_code")
    expect(isinstance(alice_code, str) and len(alice_code) == 6,
           "A.alice_code_len6", f"code={alice_code}")
    expect(isinstance(bob_code, str) and len(bob_code) == 6,
           "A.bob_code_len6", f"code={bob_code}")
    expect(all(c in REFERRAL_ALPHABET for c in (alice_code or "")),
           "A.alice_code_alphabet", f"code={alice_code}")
    expect(all(c in REFERRAL_ALPHABET for c in (bob_code or "")),
           "A.bob_code_alphabet", f"code={bob_code}")
    expect(alice_code != bob_code, "A.codes_distinct",
           f"alice={alice_code} bob={bob_code}")

    # ----- B) Public lookup -----
    r = http("GET", f"/referrals/lookup/{alice_code}")
    ok = r.status_code == 200 and r.json().get("valid") is True \
        and r.json().get("referrer_name") == alice["name"] \
        and r.json().get("referrer_code") == alice_code
    expect(ok, "B.lookup_valid", f"{r.status_code} {jdump(r)}")

    r = http("GET", "/referrals/lookup/NOPE99")
    ok = r.status_code == 404 and "Referral code not found" in (r.json().get("detail", "") or "")
    expect(ok, "B.lookup_unknown_404", f"{r.status_code} {jdump(r)}")

    # ----- C) Register-with-code -----
    r = register_user(f"BobBob{ts}", alice_code)
    expect(r.status_code == 200, "C.register_with_code_status", f"{r.status_code} {jdump(r)}")
    bb = r.json() if r.status_code == 200 else {}
    expect(bb.get("referred_by_user_id") == alice["id"],
           "C.referred_by_set", f"got={bb.get('referred_by_user_id')} expect={alice['id']}")
    expect(isinstance(bb.get("referral_code"), str)
           and bb.get("referral_code") != alice_code,
           "C.own_code_distinct", f"own={bb.get('referral_code')} alice={alice_code}")

    r = register_user(f"BogusRef{ts}", "XXXX99")
    ok = r.status_code == 400 and "Invalid referral code" in (r.json().get("detail", "") or "")
    expect(ok, "C.invalid_code_400", f"{r.status_code} {jdump(r)}")

    # ----- D) Reward DISABLED -----
    # Already disabled above. Register Dan with Alice's code.
    rd = register_user(f"DanD{ts}", alice_code)
    expect(rd.status_code == 200, "D.register_dan", f"{rd.status_code}")
    dan = rd.json()
    dan_phone = fresh_phone(seq=1)
    s = send_otp(dan["id"], dan_phone)
    expect(s.status_code == 200, "D.send_otp_dan", f"{s.status_code}")
    v = verify_otp(dan["id"], dan_phone)
    expect(v.status_code == 200, "D.verify_otp_dan", f"{v.status_code} {jdump(v)}")
    dan_real = v.json() if v.status_code == 200 else {}

    # Capture Alice's pending_credits BEFORE checking via the user-facing endpoint:
    r = http("GET", f"/users/{alice['id']}/referrals")
    alice_pc_after_dan = r.json().get("pending_credits", -1) if r.status_code == 200 else -1
    expect(r.status_code == 200, "D.alice_referrals_get", f"{r.status_code}")
    expect(alice_pc_after_dan == 0, "D.no_pending_credits_when_disabled",
           f"alice.pending_credits={alice_pc_after_dan} (expected 0)")

    # Idempotency: re-send + re-verify same Dan phone — should not create credits
    s2 = send_otp(dan_real["id"], dan_phone)
    v2 = verify_otp(dan_real["id"], dan_phone)
    expect(v2.status_code == 200, "D.reverify_dan", f"{v2.status_code}")
    r = http("GET", f"/users/{alice['id']}/referrals")
    alice_pc_after_dan2 = r.json().get("pending_credits", -1) if r.status_code == 200 else -1
    expect(alice_pc_after_dan2 == 0, "D.idempotent_disabled",
           f"alice.pending_credits={alice_pc_after_dan2}")

    # ----- E) Reward ENABLED -----
    r = http("POST", "/admin/referrals/settings",
             headers=H, json={"enabled": True, "referrer_credit": 5, "referee_credit": 2})
    expect(r.status_code == 200, "E.enable_settings", f"{r.status_code} {jdump(r)}")

    # Get baseline
    r = http("GET", f"/users/{alice['id']}/referrals")
    alice_pc_before_eva = r.json().get("pending_credits", 0) if r.status_code == 200 else 0

    re_ = register_user(f"EvaE{ts}", alice_code)
    expect(re_.status_code == 200, "E.register_eva", f"{re_.status_code}")
    eva = re_.json()
    eva_phone = fresh_phone(seq=2)
    s = send_otp(eva["id"], eva_phone)
    v = verify_otp(eva["id"], eva_phone)
    expect(v.status_code == 200, "E.verify_eva", f"{v.status_code} {jdump(v)}")
    eva_real = v.json() if v.status_code == 200 else {}

    r = http("GET", f"/users/{alice['id']}/referrals")
    alice_pc_after_eva = r.json().get("pending_credits", 0) if r.status_code == 200 else 0
    expect(alice_pc_after_eva >= alice_pc_before_eva + 1,
           "E.alice_pending_increased",
           f"before={alice_pc_before_eva} after={alice_pc_after_eva}")

    r = http("GET", f"/users/{eva_real.get('id')}/referrals")
    expect(r.status_code == 200, "E.eva_referrals_get", f"{r.status_code}")
    eva_pc = r.json().get("pending_credits", 0) if r.status_code == 200 else 0
    expect(eva_pc >= 1, "E.eva_pending_credit", f"eva.pending_credits={eva_pc}")

    # Idempotency: re-verify Eva — pending should NOT increase
    s = send_otp(eva_real["id"], eva_phone)
    v = verify_otp(eva_real["id"], eva_phone)
    expect(v.status_code == 200, "E.reverify_eva", f"{v.status_code}")
    r = http("GET", f"/users/{alice['id']}/referrals")
    alice_pc_after_eva2 = r.json().get("pending_credits", 0) if r.status_code == 200 else 0
    expect(alice_pc_after_eva2 == alice_pc_after_eva,
           "E.idempotent_enabled",
           f"after_eva={alice_pc_after_eva} after_re={alice_pc_after_eva2}")

    # ----- F) Persistent collapse referral transfer -----
    # 1. OldUser, no code, verified with phone Y.
    ro = register_user(f"OldUser{ts}")
    expect(ro.status_code == 200, "F.register_old", f"{ro.status_code}")
    old = ro.json()
    phone_y = fresh_phone(seq=3)
    s = send_otp(old["id"], phone_y)
    v = verify_otp(old["id"], phone_y)
    expect(v.status_code == 200, "F.verify_old", f"{v.status_code}")
    old_real = v.json() if v.status_code == 200 else {}
    expect(not old_real.get("referred_by_user_id"),
           "F.old_no_initial_referrer", f"{old_real.get('referred_by_user_id')}")

    # 2. Fresh placeholder with Alice's code, verify with phone Y → collapses; transfer.
    rp = register_user(f"FreshPlaceholder{ts}", alice_code)
    expect(rp.status_code == 200, "F.register_placeholder", f"{rp.status_code}")
    ph = rp.json()
    expect(ph.get("referred_by_user_id") == alice["id"],
           "F.placeholder_set", f"{ph.get('referred_by_user_id')}")
    s = send_otp(ph["id"], phone_y)
    v = verify_otp(ph["id"], phone_y)
    expect(v.status_code == 200, "F.collapse_to_old", f"{v.status_code} {jdump(v)}")
    collapsed = v.json() if v.status_code == 200 else {}
    expect(collapsed.get("id") == old_real.get("id"),
           "F.collapse_same_id",
           f"got={collapsed.get('id')} old={old_real.get('id')}")
    expect(collapsed.get("referred_by_user_id") == alice["id"],
           "F.referrer_transferred",
           f"collapsed.referred_by={collapsed.get('referred_by_user_id')}")

    # 3. Re-register with Bob's code, verify Y again — referred_by should NOT change.
    rp2 = register_user(f"FreshPlaceholder2{ts}", bob_code)
    ph2 = rp2.json() if rp2.status_code == 200 else {}
    s = send_otp(ph2["id"], phone_y)
    v = verify_otp(ph2["id"], phone_y)
    expect(v.status_code == 200, "F.collapse_again", f"{v.status_code}")
    collapsed2 = v.json() if v.status_code == 200 else {}
    expect(collapsed2.get("referred_by_user_id") == alice["id"],
           "F.referrer_unchanged_on_recollapse",
           f"got={collapsed2.get('referred_by_user_id')}")

    # ----- G) Self-refer guard -----
    rs = register_user(f"Self{ts}")
    expect(rs.status_code == 200, "G.register_self", f"{rs.status_code}")
    self_user = rs.json()
    self_phone = fresh_phone(seq=4)
    s = send_otp(self_user["id"], self_phone)
    v = verify_otp(self_user["id"], self_phone)
    expect(v.status_code == 200, "G.verify_self", f"{v.status_code}")
    self_real = v.json() if v.status_code == 200 else {}
    self_code = self_real.get("referral_code") or self_user.get("referral_code")

    # Now register a placeholder using self's own code, then verify with same phone
    rsp = register_user(f"SelfPlaceholder{ts}", self_code)
    sph = rsp.json() if rsp.status_code == 200 else {}
    expect(sph.get("referred_by_user_id") == self_real.get("id"),
           "G.placeholder_self_set", f"{sph.get('referred_by_user_id')}")
    s = send_otp(sph["id"], self_phone)
    v = verify_otp(sph["id"], self_phone)
    expect(v.status_code == 200, "G.verify_self_collapse", f"{v.status_code}")
    sc = v.json() if v.status_code == 200 else {}
    expect(sc.get("id") == self_real.get("id"),
           "G.collapsed_to_self", f"got={sc.get('id')} self={self_real.get('id')}")
    expect(not sc.get("referred_by_user_id"),
           "G.self_refer_blocked",
           f"referred_by={sc.get('referred_by_user_id')} (must be None)")

    # ----- H) Phone masking -----
    r = http("GET", f"/users/{alice['id']}/referrals")
    expect(r.status_code == 200, "H.alice_referrals", f"{r.status_code}")
    body = r.json() if r.status_code == 200 else {}
    referees = body.get("referees", [])
    referees_with_phone = [x for x in referees if x.get("phone")]
    if not referees_with_phone:
        record("H.has_phone_referees", False, f"no referees with phone — referees={referees}")
    else:
        all_masked = True
        for ree in referees_with_phone:
            ph_str = ree.get("phone") or ""
            ok_mask = "*" in ph_str and re.search(r"\d{4}$", ph_str) is not None
            if not ok_mask:
                all_masked = False
                break
        expect(all_masked, "H.phones_masked",
               f"sample={referees_with_phone[0].get('phone')}")

    # ----- I) Admin auth/RBAC -----
    r = http("GET", "/admin/referrals")
    expect(r.status_code == 401, "I.no_bearer_401", f"{r.status_code} {jdump(r)}")

    # Create support admin (super_admin only)
    support_email = f"support_c1_{ts}@example.com"
    support_pw = "SupportPass123!"
    r = http("POST", "/admin/admins", headers=H,
             json={"email": support_email, "password": support_pw,
                   "name": "C1 Support", "role": "support"})
    expect(r.status_code == 200, "I.create_support", f"{r.status_code} {jdump(r)}")

    # Login as support
    r = http("POST", "/admin/auth/login",
             json={"email": support_email, "password": support_pw})
    expect(r.status_code == 200, "I.support_login", f"{r.status_code}")
    support_token = r.json().get("token") if r.status_code == 200 else None
    SH = auth_headers(support_token) if support_token else {}

    # Support POST settings → 403
    r = http("POST", "/admin/referrals/settings", headers=SH,
             json={"enabled": False, "referrer_credit": 0, "referee_credit": 0})
    ok = r.status_code == 403 and "Requires one of roles" in (r.json().get("detail", "") or "")
    expect(ok, "I.support_post_settings_403",
           f"{r.status_code} {jdump(r)}")

    # Support GET leaderboard → 200
    r = http("GET", "/admin/referrals", headers=SH)
    expect(r.status_code == 200, "I.support_get_leaderboard_200",
           f"{r.status_code} {jdump(r)}")

    # ----- J) Admin leaderboard + stats -----
    r = http("GET", "/admin/referrals", params={"q": "alice"}, headers=H)
    expect(r.status_code == 200, "J.leaderboard_status", f"{r.status_code}")
    payload = r.json() if r.status_code == 200 else {}
    items = payload.get("items", [])
    alice_row = next((x for x in items if x.get("user_id") == alice["id"]), None)
    expect(alice_row is not None, "J.alice_in_leaderboard",
           f"items_count={len(items)}; user_ids={[x.get('user_id') for x in items[:5]]}")
    if alice_row:
        expect(alice_row.get("referral_code") == alice_code,
               "J.alice_code_matches",
               f"row.code={alice_row.get('referral_code')} alice_code={alice_code}")
        expect((alice_row.get("total_referrals") or 0) >= 2,
               "J.alice_total_ge_2",
               f"total={alice_row.get('total_referrals')}")
        # verified_referrals reflects actual verified referees from /users/{id}/referrals
        ru = http("GET", f"/users/{alice['id']}/referrals")
        actual_verified = ru.json().get("verified_referees_count", -1) if ru.status_code == 200 else -1
        expect(alice_row.get("verified_referrals") == actual_verified,
               "J.verified_matches",
               f"row.verified={alice_row.get('verified_referrals')} actual={actual_verified}")
    stats = payload.get("stats", {}) or {}
    if stats.get("total_referred", 0) > 0:
        expected_cr = round(stats["verified_referred"] / stats["total_referred"] * 100, 1)
        expect(stats.get("conversion_rate") == expected_cr,
               "J.conversion_rate_correct",
               f"got={stats.get('conversion_rate')} expected={expected_cr}")

    # ----- K) Audit log -----
    r = http("GET", "/admin/audit-log", params={"limit": 20}, headers=H)
    expect(r.status_code == 200, "K.audit_log_status", f"{r.status_code}")
    entries = r.json().get("items", []) if r.status_code == 200 else []
    upd_entries = [e for e in entries if e.get("action") == "admin.update_referral_settings"]
    expect(len(upd_entries) >= 1, "K.audit_has_update",
           f"count={len(upd_entries)}")
    if upd_entries:
        e0 = upd_entries[0]
        expect(e0.get("destructive") is True, "K.destructive_true",
               f"destructive={e0.get('destructive')}")
        expect(e0.get("target_type") == "settings",
               "K.target_type_settings", f"target_type={e0.get('target_type')}")
        expect(e0.get("target_id") == "referrals",
               "K.target_id_referrals", f"target_id={e0.get('target_id')}")

    # ----- L) Cleanup -----
    r = http("POST", "/admin/referrals/settings", headers=H,
             json={"enabled": False, "referrer_credit": 0, "referee_credit": 0})
    expect(r.status_code == 200, "L.cleanup_disable", f"{r.status_code}")

    # ----- Summary -----
    print("\n========== SUMMARY ==========")
    fails = [r for r in RESULTS if not r[1]]
    print(f"Total: {len(RESULTS)}, Pass: {len(RESULTS) - len(fails)}, Fail: {len(fails)}")
    if fails:
        print("\nFailing tests:")
        for name, _ok, msg in fails:
            print(f"  - {name}: {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        traceback.print_exc()
        print(f"\nFATAL: {e}")
        sys.exit(2)
