"""Backend test harness — Access Role Management v2 (G1–G12).

Tests role-centric RBAC introduced in June 2025.
"""
import os
import sys
import json
import time
import requests

BASE_URL = "https://joint-pay-1.preview.emergentagent.com/api"
SUPER_EMAIL = "admin@squadpay.us"
SUPER_PASS = "Letmein@2007#ForReal"

MANAGER_EMAIL = "g1mgr1778059029@kwiktech.net"
MANAGER_PASS = "ManagerTemp!2026Aa"

OPSLEAD_EMAIL = "opslead@squadpay.us"
OPSLEAD_PASS = "Ops!2026Tst"

results = []  # (name, ok, detail)


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: {detail}")


def login(email, password):
    r = requests.post(f"{BASE_URL}/admin/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        return None, r
    return r.json()["token"], r


def H(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    print(f"=== Access Role Management v2 — G1..G12 ===")
    print(f"BASE_URL={BASE_URL}\n")

    # Login super_admin
    super_token, r = login(SUPER_EMAIL, SUPER_PASS)
    if not super_token:
        record("super_admin login", False, f"status={r.status_code} body={r.text[:200]}")
        return
    record("super_admin login", True, "token obtained")

    # Pre-cleanup BEFORE G1 so any leftover ops_lead from a prior failed run
    # doesn't pollute the "exactly 3 roles" assertion.
    pre = requests.get(f"{BASE_URL}/admin/access/roles", headers=H(super_token), timeout=30)
    if pre.status_code == 200:
        for r in pre.json().get("items", []):
            if not r.get("is_system"):
                # detach any admins
                ad_r = requests.get(f"{BASE_URL}/admin/admins", headers=H(super_token), timeout=30)
                for a in ad_r.json() if ad_r.ok else []:
                    if a.get("role") == r.get("slug"):
                        requests.patch(
                            f"{BASE_URL}/admin/admins/{a['id']}/role",
                            headers=H(super_token), json={"role": "support"}, timeout=30,
                        )
                requests.delete(f"{BASE_URL}/admin/access/roles/{r['id']}", headers=H(super_token), timeout=30)
                print(f"  (pre-cleanup before G1: removed leftover non-system role '{r.get('slug')}')")

    # ─────────────────────── G1: list roles ───────────────────────
    r = requests.get(f"{BASE_URL}/admin/access/roles", headers=H(super_token), timeout=30)
    ok = r.status_code == 200
    if not ok:
        record("G1 list roles status", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        data = r.json()
        items = data.get("items", [])
        record("G1 list roles status 200", True, f"count={len(items)}")
        record("G1 exactly 3 roles", len(items) == 3, f"got {len(items)} items")
        all_sys = all(it.get("is_system") is True for it in items)
        record("G1 all is_system=true", all_sys, "")
        sa = next((it for it in items if it.get("slug") == "super_admin"), None)
        if sa:
            mc = len(sa.get("modules") or [])
            record("G1 super_admin has 19 modules", mc == 19, f"modules.length={mc}")
        else:
            record("G1 super_admin doc present", False, "no super_admin in items")

    # ─────────────────────── G2: create ops_lead ───────────────────────
    # Pre-cleanup: if leftover ops_lead role exists from previous run, remove it
    rolelist = requests.get(f"{BASE_URL}/admin/access/roles", headers=H(super_token), timeout=30).json()
    existing_opslead = next((r for r in rolelist.get("items", []) if r.get("slug") == "ops_lead"), None)
    if existing_opslead:
        # detach any admins from it first
        admins_r = requests.get(f"{BASE_URL}/admin/admins", headers=H(super_token), timeout=30)
        for a in admins_r.json() if admins_r.ok else []:
            if a.get("role") == "ops_lead":
                requests.patch(
                    f"{BASE_URL}/admin/admins/{a['id']}/role",
                    headers=H(super_token), json={"role": "support"}, timeout=30,
                )
        requests.delete(f"{BASE_URL}/admin/access/roles/{existing_opslead['id']}", headers=H(super_token), timeout=30)
        print("(pre-cleanup: removed leftover ops_lead role)")

    body = {"name": "Ops Lead", "description": "Squad operations team lead",
            "modules": ["dashboard", "users", "squads"]}
    r = requests.post(f"{BASE_URL}/admin/access/roles", headers=H(super_token), json=body, timeout=30)
    record("G2 create role status 201", r.status_code == 201, f"status={r.status_code} body={r.text[:300]}")
    ops_lead_id = None
    if r.status_code == 201:
        d = r.json()
        ops_lead_id = d.get("id")
        record("G2 slug==ops_lead", d.get("slug") == "ops_lead", f"slug={d.get('slug')}")
        record("G2 assigned_admin_count==0", d.get("assigned_admin_count") == 0, f"got {d.get('assigned_admin_count')}")
        record("G2 modules.length==3", len(d.get("modules") or []) == 3, f"got {len(d.get('modules') or [])}")
    else:
        # If POST returned non-201 but role was actually persisted (e.g. 500
        # caused by response serialization), look it up so G3..G12 can proceed.
        list_r = requests.get(f"{BASE_URL}/admin/access/roles", headers=H(super_token), timeout=30)
        if list_r.status_code == 200:
            ol = next((r for r in list_r.json().get("items", []) if r.get("slug") == "ops_lead"), None)
            if ol:
                ops_lead_id = ol["id"]
                print(f"  (recovered ops_lead_id from list: {ops_lead_id} despite POST {r.status_code})")
                record("G2 role actually persisted despite error response",
                       len(ol.get("modules") or []) == 3,
                       f"persisted modules={ol.get('modules')}, assigned_admin_count={ol.get('assigned_admin_count')}")

    # ─────────────────────── G3: duplicate ───────────────────────
    r = requests.post(f"{BASE_URL}/admin/access/roles", headers=H(super_token), json=body, timeout=30)
    record("G3 duplicate -> 409", r.status_code == 409, f"status={r.status_code} body={r.text[:120]}")

    # ─────────────────────── G4: update modules ───────────────────────
    if ops_lead_id:
        r = requests.put(
            f"{BASE_URL}/admin/access/roles/{ops_lead_id}",
            headers=H(super_token),
            json={"modules": ["dashboard", "users", "squads", "analytics"]},
            timeout=30,
        )
        record("G4 update status 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        if r.status_code == 200:
            mlen = len(r.json().get("modules") or [])
            record("G4 modules.length==4", mlen == 4, f"got {mlen}")

    # ─────────────────────── G5: super_admin immutable ───────────────────────
    r = requests.put(
        f"{BASE_URL}/admin/access/roles/role_super_admin",
        headers=H(super_token),
        json={"modules": ["dashboard"]},
        timeout=30,
    )
    record("G5 super_admin immutable -> 400", r.status_code == 400, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 400:
        record("G5 detail mentions immutable", "immutable" in r.text.lower(), f"body={r.text[:200]}")

    # ─────────────────────── G6: create opslead admin ───────────────────────
    # Pre-cleanup: if user already exists, delete or reuse
    admins_list = requests.get(f"{BASE_URL}/admin/admins", headers=H(super_token), timeout=30).json()
    opslead_existing = next((a for a in admins_list if a.get("email") == OPSLEAD_EMAIL.lower()), None)
    opslead_id = None
    if opslead_existing:
        # Reset its state: set role=ops_lead, is_active=true, reset password
        opslead_id = opslead_existing["id"]
        # PATCH role to ops_lead
        rrole = requests.patch(
            f"{BASE_URL}/admin/admins/{opslead_id}/role",
            headers=H(super_token), json={"role": "ops_lead"}, timeout=30,
        )
        if rrole.status_code in (200, 201):
            record("G6 reused existing opslead admin (role=ops_lead)", True, f"id={opslead_id}")
        else:
            record("G6 reused existing opslead admin", False, f"role patch status={rrole.status_code} body={rrole.text[:200]}")
        # Activate
        requests.patch(
            f"{BASE_URL}/admin/admins/{opslead_id}/active",
            headers=H(super_token), json={"is_active": True}, timeout=30,
        )
        # Reset password via admin reset (try a few possible routes)
        # First try direct mongo-less: use admin-reset endpoint if exists
        rr = requests.post(
            f"{BASE_URL}/admin/admins/{opslead_id}/reset-password",
            headers=H(super_token), json={"new_password": OPSLEAD_PASS}, timeout=30,
        )
        if rr.status_code not in (200, 201, 204):
            # try alternative endpoints
            rr2 = requests.post(
                f"{BASE_URL}/admin/admins/{opslead_id}/password",
                headers=H(super_token), json={"new_password": OPSLEAD_PASS}, timeout=30,
            )
            print(f"  (note: reset-password fallback status={rr.status_code} alt={rr2.status_code if rr2 else 'NA'})")
    else:
        body = {"email": OPSLEAD_EMAIL, "password": OPSLEAD_PASS, "name": "Ops Lead", "role": "ops_lead"}
        r = requests.post(f"{BASE_URL}/admin/admins", headers=H(super_token), json=body, timeout=30)
        ok = r.status_code in (200, 201)
        record("G6 create opslead admin", ok, f"status={r.status_code} body={r.text[:300]}")
        if ok:
            d = r.json()
            opslead_id = d.get("id")
            record("G6 role==ops_lead", d.get("role") == "ops_lead", f"role={d.get('role')}")

    # ─────────────────────── G7: login ops_lead, check modules ───────────────────────
    ops_token = None
    if opslead_id:
        # Wait a brief moment if just created
        time.sleep(0.3)
        ops_token, r = login(OPSLEAD_EMAIL, OPSLEAD_PASS)
        if not ops_token:
            record("G7 login opslead", False, f"status={r.status_code} body={r.text[:300]}")
        else:
            record("G7 login opslead", True, "token obtained")
            rm = requests.get(f"{BASE_URL}/admin/me/modules", headers=H(ops_token), timeout=30)
            record("G7 /admin/me/modules status 200", rm.status_code == 200, f"status={rm.status_code} body={rm.text[:200]}")
            if rm.status_code == 200:
                d = rm.json()
                mods = d.get("modules") or []
                keys = sorted([m.get("key") for m in mods])
                exp = sorted(["dashboard", "users", "squads", "analytics"])
                record("G7 exactly 4 modules (dashboard,users,squads,analytics)", keys == exp, f"got {keys}")
                record("G7 is_super_admin==false", d.get("is_super_admin") is False, f"got {d.get('is_super_admin')}")
                record("G7 role==ops_lead", d.get("role") == "ops_lead", f"got {d.get('role')}")
                record("G7 role_name==Ops Lead", d.get("role_name") == "Ops Lead", f"got {d.get('role_name')}")
            # GET platform-fees -> 403
            rp = requests.get(f"{BASE_URL}/admin/platform-fees", headers=H(ops_token), timeout=30)
            record("G7 platform-fees forbidden -> 403", rp.status_code == 403, f"status={rp.status_code} body={rp.text[:200]}")

    # ─────────────────────── G8: invalid role on PATCH ───────────────────────
    if opslead_id:
        r = requests.patch(
            f"{BASE_URL}/admin/admins/{opslead_id}/role",
            headers=H(super_token), json={"role": "bogus_slug"}, timeout=30,
        )
        record("G8 invalid role -> 400", r.status_code == 400, f"status={r.status_code} body={r.text[:200]}")
        if r.status_code == 400:
            record("G8 detail mentions 'Unknown role'", "unknown role" in r.text.lower(), f"body={r.text[:200]}")

    # ─────────────────────── G9: delete protected role ───────────────────────
    if ops_lead_id:
        r = requests.delete(f"{BASE_URL}/admin/access/roles/{ops_lead_id}", headers=H(super_token), timeout=30)
        record("G9 delete protected -> 400", r.status_code == 400, f"status={r.status_code} body={r.text[:200]}")
        if r.status_code == 400:
            record("G9 mentions '1 admin'", "1 admin" in r.text, f"body={r.text[:200]}")

    # ─────────────────────── G10: reassign + delete ───────────────────────
    if opslead_id and ops_lead_id:
        r = requests.patch(
            f"{BASE_URL}/admin/admins/{opslead_id}/role",
            headers=H(super_token), json={"role": "support"}, timeout=30,
        )
        record("G10 PATCH role->support 200", r.status_code in (200, 201), f"status={r.status_code} body={r.text[:200]}")
        r = requests.delete(f"{BASE_URL}/admin/access/roles/{ops_lead_id}", headers=H(super_token), timeout=30)
        record("G10 DELETE role 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        if r.status_code == 200:
            j = r.json()
            record("G10 'deleted' field present", "deleted" in j, f"body={j}")
        # Re-GET roles list
        r = requests.get(f"{BASE_URL}/admin/access/roles", headers=H(super_token), timeout=30)
        if r.status_code == 200:
            items = r.json().get("items", [])
            record("G10 roles back to 3", len(items) == 3, f"count={len(items)}")
        # null ops_lead_id so subsequent tests can re-create
        ops_lead_id = None

    # ─────────────────────── G11: manager can't manage roles ───────────────────────
    mgr_token, r = login(MANAGER_EMAIL, MANAGER_PASS)
    if not mgr_token:
        record("G11 manager login", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        record("G11 manager login", True, "token obtained")
        rr = requests.get(f"{BASE_URL}/admin/access/roles", headers=H(mgr_token), timeout=30)
        record("G11 manager GET /admin/access/roles -> 403", rr.status_code == 403, f"status={rr.status_code} body={rr.text[:200]}")
        rl = requests.get(f"{BASE_URL}/admin/access/roles/lookup", headers=H(mgr_token), timeout=30)
        record("G11 manager GET /admin/access/roles/lookup -> 200", rl.status_code == 200, f"status={rl.status_code} body={rl.text[:200]}")

    # ─────────────────────── G12: add platform_fees mid-test ───────────────────────
    # Re-create ops_lead with dashboard + platform_fees
    body12 = {"name": "Ops Lead", "description": "Re-created for G12",
              "modules": ["dashboard", "platform_fees"]}
    r = requests.post(f"{BASE_URL}/admin/access/roles", headers=H(super_token), json=body12, timeout=30)
    record("G12 re-create ops_lead with platform_fees", r.status_code == 201, f"status={r.status_code} body={r.text[:300]}")
    new_role_id = None
    if r.status_code == 201:
        new_role_id = r.json()["id"]
    else:
        # Recovery again — look up from list (same ObjectId bug as G2)
        list_r = requests.get(f"{BASE_URL}/admin/access/roles", headers=H(super_token), timeout=30)
        if list_r.status_code == 200:
            ol = next((r for r in list_r.json().get("items", []) if r.get("slug") == "ops_lead"), None)
            if ol:
                new_role_id = ol["id"]
                print(f"  (G12 recovered new_role_id from list: {new_role_id})")
                record("G12 role actually persisted despite error",
                       set(ol.get("modules") or []) == {"dashboard", "platform_fees"},
                       f"persisted modules={ol.get('modules')}")

    # Patch opslead admin back to ops_lead
    if opslead_id and new_role_id:
        r = requests.patch(
            f"{BASE_URL}/admin/admins/{opslead_id}/role",
            headers=H(super_token), json={"role": "ops_lead"}, timeout=30,
        )
        record("G12 PATCH opslead -> ops_lead", r.status_code in (200, 201), f"status={r.status_code}")

        # Login (or reuse token? cache might be stale; new login should be safe)
        time.sleep(0.3)
        ops_token2, rr = login(OPSLEAD_EMAIL, OPSLEAD_PASS)
        if not ops_token2:
            record("G12 ops_lead re-login", False, f"status={rr.status_code} body={rr.text[:200]}")
        else:
            record("G12 ops_lead re-login", True, "token obtained")
            rp = requests.get(f"{BASE_URL}/admin/platform-fees", headers=H(ops_token2), timeout=30)
            record("G12 platform-fees -> 200 (granted)", rp.status_code == 200, f"status={rp.status_code} body={rp.text[:200]}")

            # PUT role to drop platform_fees
            r = requests.put(
                f"{BASE_URL}/admin/access/roles/{new_role_id}",
                headers=H(super_token),
                json={"modules": ["dashboard"]},
                timeout=30,
            )
            record("G12 PUT remove platform_fees -> 200", r.status_code == 200, f"status={r.status_code}")
            # SAME token → expect 403 (cache reload effective)
            rp2 = requests.get(f"{BASE_URL}/admin/platform-fees", headers=H(ops_token2), timeout=30)
            record("G12 platform-fees -> 403 (revoked)", rp2.status_code == 403, f"status={rp2.status_code} body={rp2.text[:200]}")

    # ─────────────────────── Cleanup ───────────────────────
    print("\n=== Cleanup ===")
    if opslead_id:
        # PATCH role back to support
        rc = requests.patch(
            f"{BASE_URL}/admin/admins/{opslead_id}/role",
            headers=H(super_token), json={"role": "support"}, timeout=30,
        )
        print(f"  cleanup PATCH role->support: {rc.status_code}")
    if new_role_id:
        rc = requests.delete(f"{BASE_URL}/admin/access/roles/{new_role_id}", headers=H(super_token), timeout=30)
        print(f"  cleanup DELETE ops_lead role: {rc.status_code}")
    if opslead_id:
        rc = requests.patch(
            f"{BASE_URL}/admin/admins/{opslead_id}/active",
            headers=H(super_token), json={"is_active": False}, timeout=30,
        )
        print(f"  cleanup deactivate opslead admin: {rc.status_code}")

    # ─────────────────────── Summary ───────────────────────
    print("\n=== Summary ===")
    n_pass = sum(1 for _, ok, _ in results if ok)
    n_fail = sum(1 for _, ok, _ in results if not ok)
    print(f"PASS: {n_pass}    FAIL: {n_fail}    Total: {len(results)}")
    if n_fail:
        print("\nFailures:")
        for name, ok, det in results:
            if not ok:
                print(f"  - {name}: {det}")


if __name__ == "__main__":
    main()
