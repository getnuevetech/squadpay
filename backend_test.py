"""Module Registry + RBAC backend (June 2025) end-to-end test.

Covers E1–E7 from the review request.

Uses LOCAL backend at http://localhost:8001/api.
"""
from __future__ import annotations
import os
import re
import sys
import uuid
import requests

BASE = os.environ.get("BACKEND_URL", "http://localhost:8001/api")
SUPER_EMAIL = "admin@squadpay.us"
SUPER_PASSWORD = "Letmein@2007#ForReal"

passed = 0
failed = 0
issues: list[str] = []

def assert_eq(label, got, want):
    global passed, failed
    if got == want:
        print(f"  ✅ {label}")
        passed += 1
        return True
    else:
        msg = f"  ❌ {label}  got={got!r} want={want!r}"
        print(msg)
        issues.append(msg)
        failed += 1
        return False

def assert_true(label, cond, extra=""):
    global passed, failed
    if cond:
        print(f"  ✅ {label}")
        passed += 1
        return True
    else:
        msg = f"  ❌ {label}  {extra}"
        print(msg)
        issues.append(msg)
        failed += 1
        return False

def login(email, password):
    r = requests.post(f"{BASE}/admin/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        return None, r
    return r.json()["token"], r

def H(tok):
    return {"Authorization": f"Bearer {tok}"}

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Setup: login as super admin ===")
super_token, r = login(SUPER_EMAIL, SUPER_PASSWORD)
assert_true("super admin login 200", super_token is not None,
            f"status={r.status_code} body={r.text[:200]}")
if not super_token:
    print("FATAL: cannot proceed without super admin token")
    sys.exit(1)
SH = H(super_token)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== E1: Super admin sees all 19 modules ===")
r = requests.get(f"{BASE}/admin/me/modules", headers=SH, timeout=20)
assert_eq("E1 GET /admin/me/modules → 200", r.status_code, 200)
if r.status_code == 200:
    body = r.json()
    assert_eq("E1 is_super_admin == true", body.get("is_super_admin"), True)
    assert_eq("E1 modules.length == 19", len(body.get("modules") or []), 19)
    assert_eq("E1 group_order matches",
              body.get("group_order"),
              ["Overview", "Operations", "Marketing", "Finance", "System"])
    keys = [m["key"] for m in body.get("modules") or []]
    for k in ("dashboard", "platform_fees", "access", "integrations"):
        assert_true(f"E1 super has '{k}'", k in keys)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== E2 setup: locate a manager admin ===")
r = requests.get(f"{BASE}/admin/access/admins", headers=SH, timeout=20)
assert_eq("E2 GET /admin/access/admins → 200", r.status_code, 200)
admins_list = (r.json() or {}).get("items") or []
print(f"  → admins.count = {len(admins_list)}")

manager = next((a for a in admins_list
                if (a.get("role") == "manager" and a.get("is_active", True))),
               None)
created_manager = False
NEW_MGR_PASSWORD = "ManagerTemp!2026Aa"
if not manager:
    print("  (no existing manager — creating one)")
    new_mgr_email = f"e2.mgr.{uuid.uuid4().hex[:6]}@squadpay.us"
    r2 = requests.post(
        f"{BASE}/admin/admins", headers=SH, timeout=20,
        json={"email": new_mgr_email,
              "password": NEW_MGR_PASSWORD,
              "name": "E2 Test Manager",
              "role": "manager"}
    )
    assert_eq("E2 create manager admin → 200", r2.status_code, 200)
    manager = r2.json()
    created_manager = True

manager_id = manager["id"]
manager_email = manager["email"]
print(f"  → manager_id={manager_id}  email={manager_email}  (newly_created={created_manager})")

# Reset password to a known value via:
#   POST /admin/admins/{id}/send-password-reset {return_link:true} → reset URL with token
#   POST /admin/auth/reset-password {token, new_password} → applies the new password
# NOTE: review spec calls for /admin/admins/{id}/reset returning a fresh password directly.
# That endpoint does NOT exist in this codebase; the available admin password-reset flow
# is two-step (send-link + apply). We use that and report it.
if not created_manager:
    rr = requests.post(
        f"{BASE}/admin/admins/{manager_id}/send-password-reset",
        headers=SH, timeout=20,
        json={"return_link": True}
    )
    assert_true(
        "E2 send-password-reset (super) → 200",
        rr.status_code == 200,
        f"status={rr.status_code} body={rr.text[:200]}",
    )
    if rr.status_code == 200:
        reset_url = rr.json().get("reset_url") or ""
        m = re.search(r"token=([^&\s]+)", reset_url)
        assert_true("E2 reset_url contains token", bool(m), f"reset_url={reset_url}")
        if m:
            tok = m.group(1)
            rrp = requests.post(
                f"{BASE}/admin/auth/reset-password",
                json={"token": tok, "new_password": NEW_MGR_PASSWORD},
                timeout=20,
            )
            assert_eq("E2 reset-password apply → 200", rrp.status_code, 200)

mgr_token, mr = login(manager_email, NEW_MGR_PASSWORD)
assert_true(
    "E2 manager login 200", mgr_token is not None,
    f"status={getattr(mr,'status_code',None)} body={getattr(mr,'text','')[:200]}",
)
MH = H(mgr_token) if mgr_token else {}

# ─────────────────────────────────────────────────────────────────────────────
if mgr_token:
    print("\n=== E2: Manager sees only their defaults ===")
    r = requests.get(f"{BASE}/admin/me/modules", headers=MH, timeout=20)
    assert_eq("E2 GET /admin/me/modules (manager) → 200", r.status_code, 200)
    if r.status_code == 200:
        body = r.json()
        assert_eq("E2 is_super_admin == false", body.get("is_super_admin"), False)
        keys = [m["key"] for m in body.get("modules") or []]
        print(f"  → manager modules: {keys}")

        SHOULD_NOT_HAVE = ["platform_fees", "income_fees", "master_account",
                           "integrations", "security", "admins", "legal_pages",
                           "access"]
        for k in SHOULD_NOT_HAVE:
            assert_true(f"E2 manager DOES NOT have '{k}'", k not in keys)

        SHOULD_HAVE = ["dashboard", "analytics", "users", "squads",
                       "customer_service", "notifications", "bulk_sms",
                       "credit_rules", "referrals", "reconciliations", "audit"]
        for k in SHOULD_HAVE:
            assert_true(f"E2 manager HAS '{k}'", k in keys)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== E3: Grant override flows through ===")
r = requests.put(
    f"{BASE}/admin/access/admins/{manager_id}",
    headers=SH, timeout=20,
    json={"module_overrides": {"platform_fees": "grant"}},
)
assert_eq("E3 PUT grant platform_fees → 200", r.status_code, 200)
if r.status_code == 200:
    body = r.json()
    acc_mods = ((body.get("admin") or {}).get("accessible_modules")) or []
    assert_true("E3 response admin.accessible_modules contains platform_fees",
                "platform_fees" in acc_mods,
                f"got={acc_mods}")

if mgr_token:
    r2 = requests.get(f"{BASE}/admin/me/modules", headers=MH, timeout=20)
    assert_eq("E3 GET /admin/me/modules (manager re-check) → 200", r2.status_code, 200)
    if r2.status_code == 200:
        keys2 = [m["key"] for m in (r2.json().get("modules") or [])]
        assert_true("E3 manager now sees platform_fees", "platform_fees" in keys2)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== E4: Invalid module key / value rejected ===")
r = requests.put(
    f"{BASE}/admin/access/admins/{manager_id}",
    headers=SH, timeout=20,
    json={"module_overrides": {"bogus_key": "grant"}},
)
assert_eq("E4 unknown key → 400", r.status_code, 400)
detail = ""
try:
    detail = (r.json() or {}).get("detail") or ""
except Exception:
    detail = r.text
assert_true("E4 detail contains 'Unknown module key'",
            "Unknown module key" in str(detail),
            f"detail={detail}")

# Invalid value: Pydantic Literal['grant','deny'] would 422, route's manual check would 400.
r = requests.put(
    f"{BASE}/admin/access/admins/{manager_id}",
    headers=SH, timeout=20,
    json={"module_overrides": {"platform_fees": "kinda"}},
)
assert_true("E4 invalid value rejected (400 or 422)",
            r.status_code in (400, 422),
            f"status={r.status_code} body={r.text[:200]}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== E5: Cannot demote the last super admin ===")
r = requests.get(f"{BASE}/admin/access/admins", headers=SH, timeout=20)
admins_list = (r.json() or {}).get("items") or []
active_supers = [a for a in admins_list
                 if a.get("role") == "super_admin" and a.get("is_active", True)]
print(f"  → active super_admins count: {len(active_supers)}")

actor_super_id = next((a["id"] for a in active_supers
                       if a["email"] == SUPER_EMAIL.lower()), None)
print(f"  → actor super_admin id (self) = {actor_super_id}")

# Spec: create a throwaway super_admin, demote it (succeeds since actor remains super),
# then attempt to demote the actor (last remaining) — should 400.
throwaway_email = f"e5.throwaway.{uuid.uuid4().hex[:6]}@squadpay.us"
r_create = requests.post(
    f"{BASE}/admin/admins", headers=SH, timeout=20,
    json={"email": throwaway_email,
          "password": "ThrowawaySuperPass!2026",
          "name": "E5 Throwaway Super",
          "role": "super_admin"}
)
assert_eq("E5 create throwaway super_admin → 200", r_create.status_code, 200)
throwaway_id = r_create.json().get("id") if r_create.status_code == 200 else None

r = requests.get(f"{BASE}/admin/access/admins", headers=SH, timeout=20)
admins_list = (r.json() or {}).get("items") or []
active_supers = [a for a in admins_list
                 if a.get("role") == "super_admin" and a.get("is_active", True)]
print(f"  → active super_admins after creating throwaway: {len(active_supers)}")

# Pre-existing "other" super_admins (not actor, not throwaway) must be demoted to managers
# so that only actor + throwaway remain super (to make the next demote of throwaway → 1 super left).
others = [a for a in active_supers
          if a["id"] not in (actor_super_id, throwaway_id)]
print(f"  → other pre-existing super_admins (not actor, not throwaway): {len(others)}")

restored = []
for o in others:
    r_dem = requests.put(
        f"{BASE}/admin/access/admins/{o['id']}",
        headers=SH, timeout=20,
        json={"role": "manager"},
    )
    print(f"  → demoted pre-existing super {o['email']} → status={r_dem.status_code}")
    assert_true(f"E5 pre-cleanup demote {o['email']} → 200",
                r_dem.status_code == 200,
                f"body={r_dem.text[:200]}")
    if r_dem.status_code == 200:
        restored.append(o["id"])

# Demote throwaway → should succeed (actor still super, ≥1 super remains).
r_t = requests.put(
    f"{BASE}/admin/access/admins/{throwaway_id}",
    headers=SH, timeout=20,
    json={"role": "manager"},
)
assert_eq("E5 demote throwaway super (succeeds, actor still super) → 200",
          r_t.status_code, 200)

# Try to demote the actor (the only remaining super) → expect 400.
# Route enforces BOTH self-demote and last-super guards. Both produce 400; the
# self-demote check fires first in the current code path.
r_self = requests.put(
    f"{BASE}/admin/access/admins/{actor_super_id}",
    headers=SH, timeout=20,
    json={"role": "manager"},
)
assert_eq("E5 demote remaining last super → 400", r_self.status_code, 400)
detail = ""
try:
    detail = (r_self.json() or {}).get("detail") or ""
except Exception:
    detail = r_self.text
ok_msg = ("Cannot demote the last active super_admin" in str(detail) or
          "cannot demote your own" in str(detail).lower())
assert_true("E5 detail explains protected demotion",
            ok_msg, f"detail={detail}")

# Cleanup: restore pre-existing super_admins back to super_admin role.
for oid in restored:
    r_rest = requests.put(
        f"{BASE}/admin/access/admins/{oid}",
        headers=SH, timeout=20,
        json={"role": "super_admin"},
    )
    print(f"  → restored {oid} → super_admin status={r_rest.status_code}")

# ─────────────────────────────────────────────────────────────────────────────
if mgr_token:
    print("\n=== E6: Non-super blocked from access mgmt ===")
    r = requests.get(f"{BASE}/admin/access/admins", headers=MH, timeout=20)
    assert_eq("E6 GET /admin/access/admins (manager) → 403", r.status_code, 403)
    r = requests.get(f"{BASE}/admin/access/registry", headers=MH, timeout=20)
    assert_eq("E6 GET /admin/access/registry (manager) → 403", r.status_code, 403)
    r = requests.put(
        f"{BASE}/admin/access/admins/{manager_id}",
        headers=MH, timeout=20,
        json={"module_overrides": {"audit": "deny"}},
    )
    assert_eq("E6 PUT /admin/access/admins (manager) → 403", r.status_code, 403)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== E7: Idempotency — PUT {} ===")
r = requests.put(
    f"{BASE}/admin/access/admins/{manager_id}",
    headers=SH, timeout=20,
    json={},
)
assert_eq("E7 PUT {} → 200", r.status_code, 200)
if r.status_code == 200:
    body = r.json()
    ok = body.get("ok") in (True, "true")
    unchanged = body.get("unchanged") in (True, "true")
    assert_true("E7 body.ok true (unchanged true or admin echoed)",
                ok and (unchanged or body.get("admin") is not None),
                f"body={body}")

r = requests.put(
    f"{BASE}/admin/access/admins/{manager_id}",
    headers=SH, timeout=20,
    json={"role": "manager",
          "module_overrides": {"platform_fees": "grant"}},
)
assert_eq("E7 PUT same values → 200 (no 500)", r.status_code, 200)

# Final cleanup: clear platform_fees override
r = requests.put(
    f"{BASE}/admin/access/admins/{manager_id}",
    headers=SH, timeout=20,
    json={"module_overrides": {}},
)
print(f"  → cleared overrides status={r.status_code}")

print(f"\n=== TOTAL: {passed} passed, {failed} failed ===")
if failed:
    print("\nIssues encountered:")
    for x in issues:
        print("  -", x)
sys.exit(0 if failed == 0 else 1)
