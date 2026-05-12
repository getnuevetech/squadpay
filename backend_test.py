#!/usr/bin/env python3
"""Test F1-F5 for: Sensitive admin routes migrated to require_module() (June 2025)."""
import sys
import requests

BASE = "http://localhost:8001/api"
SUPER_EMAIL = "admin@squadpay.us"
SUPER_PASS = "Letmein@2007#ForReal"
MGR_EMAIL = "g1mgr1778059029@kwiktech.net"
MGR_PASS = "ManagerTemp!2026Aa"


def hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def login(email, pwd):
    r = requests.post(
        f"{BASE}/admin/auth/login",
        json={"email": email, "password": pwd},
        timeout=20,
    )
    print(f"  login {email}: {r.status_code}")
    if r.status_code != 200:
        print(f"  body: {r.text}")
        return None
    return r.json().get("token") or r.json().get("access_token")


def has_module_text(resp):
    try:
        body = resp.json()
        detail = body.get("detail", "")
        return "module" in detail.lower(), detail
    except Exception:
        return False, resp.text[:200]


def main():
    results = []

    print("\n==== AUTH ====")
    super_tok = login(SUPER_EMAIL, SUPER_PASS)
    if not super_tok:
        print("CRITICAL: super_admin login failed")
        sys.exit(1)
    mgr_tok = login(MGR_EMAIL, MGR_PASS)
    if not mgr_tok:
        print("CRITICAL: manager login failed")
        sys.exit(1)

    r = requests.get(f"{BASE}/admin/access/admins", headers=hdr(super_tok), timeout=20)
    print(f"  GET /admin/access/admins → {r.status_code}")
    mgr_id = None
    for it in (r.json().get("items") or []):
        if (it.get("email") or "").lower() == MGR_EMAIL.lower():
            mgr_id = it.get("id")
            break
    if not mgr_id:
        print("CRITICAL: manager id not found")
        sys.exit(1)
    print(f"  manager id: {mgr_id}")

    rr = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=hdr(super_tok),
        json={"module_overrides": {}},
        timeout=20,
    )
    print(f"  reset overrides at start → {rr.status_code}")

    print("\n==== F1: super_admin sees all 19 modules ====")
    r = requests.get(f"{BASE}/admin/me/modules", headers=hdr(super_tok), timeout=20)
    print(f"  GET /admin/me/modules → {r.status_code}")
    body = r.json() if r.status_code == 200 else {}
    mods = body.get("modules") or []
    keys = [m["key"] for m in mods]
    print(f"  module count: {len(mods)}; keys: {keys}")
    results.append(("F1 status 200", r.status_code == 200))
    results.append(("F1 count==19", len(mods) == 19))
    results.append(("F1 is_super_admin true", body.get("is_super_admin") is True))

    print("\n==== F2: manager (no overrides) gets 403 on all sensitive endpoints ====")
    f2_endpoints = [
        ("GET", "/admin/platform-fees", None),
        ("GET", "/admin/master-card", None),
        ("GET", "/admin/income-fees", None),
        ("GET", "/admin/admins", None),
        ("GET", "/admin/security/kms-status", None),
        ("POST", "/admin/integrations/twilio", {"enabled": False}),
    ]
    for method, path, body in f2_endpoints:
        url = f"{BASE}{path}"
        if method == "GET":
            r = requests.get(url, headers=hdr(mgr_tok), timeout=20)
        else:
            r = requests.post(url, headers=hdr(mgr_tok), json=body, timeout=20)
        has_mod, detail = has_module_text(r)
        ok_status = (r.status_code == 403)
        sym1 = "✅" if ok_status else "❌"
        sym2 = "✅" if has_mod else "❌"
        print(f"  {sym1} {method} {path} → {r.status_code} {sym2} body has 'module': detail='{detail[:140]}'")
        results.append((f"F2 {method} {path} 403", ok_status))
        results.append((f"F2 {method} {path} body has module", has_mod))

    print("\n==== F3: grant manager platform_fees ====")
    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=hdr(super_tok),
        json={"module_overrides": {"platform_fees": "grant"}},
        timeout=20,
    )
    print(f"  PUT grant platform_fees → {r.status_code}")
    results.append(("F3 PUT grant 200", r.status_code == 200))

    r = requests.get(f"{BASE}/admin/platform-fees", headers=hdr(mgr_tok), timeout=20)
    print(f"  GET /admin/platform-fees as manager → {r.status_code}")
    results.append(("F3 GET /admin/platform-fees → 200", r.status_code == 200))

    r = requests.get(f"{BASE}/admin/master-card", headers=hdr(mgr_tok), timeout=20)
    print(f"  GET /admin/master-card as manager → {r.status_code}")
    _, detail = has_module_text(r)
    print(f"    detail: {detail[:140]}")
    results.append(("F3 GET /admin/master-card → 403", r.status_code == 403))

    print("\n==== F4: informational — users deny + platform_fees grant ====")
    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=hdr(super_tok),
        json={"module_overrides": {"users": "deny", "platform_fees": "grant"}},
        timeout=20,
    )
    print(f"  PUT deny users + grant platform_fees → {r.status_code}")
    results.append(("F4 PUT 200", r.status_code == 200))

    r = requests.get(f"{BASE}/admin/users", headers=hdr(mgr_tok), timeout=20)
    print(f"  GET /admin/users as manager → {r.status_code} (informational; admin_users_groups still on require_role)")
    f4_users_status = r.status_code

    print("\n==== F5: reconciliations (default access for manager) ====")
    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=hdr(super_tok),
        json={"module_overrides": {}},
        timeout=20,
    )
    print(f"  PUT clear overrides → {r.status_code}")
    results.append(("F5 PUT clear 200", r.status_code == 200))

    r = requests.get(f"{BASE}/admin/reconciliations", headers=hdr(mgr_tok), timeout=20)
    print(f"  GET /admin/reconciliations (no override, manager has default access) → {r.status_code}")
    results.append(("F5 GET /admin/reconciliations default → 200", r.status_code == 200))

    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=hdr(super_tok),
        json={"module_overrides": {"reconciliations": "deny"}},
        timeout=20,
    )
    print(f"  PUT deny reconciliations → {r.status_code}")
    results.append(("F5 PUT deny 200", r.status_code == 200))

    r = requests.get(f"{BASE}/admin/reconciliations", headers=hdr(mgr_tok), timeout=20)
    print(f"  GET /admin/reconciliations (deny override) → {r.status_code}")
    _, detail = has_module_text(r)
    print(f"    detail: {detail[:140]}")
    results.append(("F5 GET /admin/reconciliations after deny → 403", r.status_code == 403))

    print("\n==== CLEANUP: clear manager overrides ====")
    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=hdr(super_tok),
        json={"module_overrides": {}},
        timeout=20,
    )
    print(f"  PUT clear overrides → {r.status_code}")

    print("\n==== SUMMARY ====")
    n_pass = sum(1 for _, ok in results if ok)
    n_total = len(results)
    for label, ok in results:
        sym = "✅" if ok else "❌"
        print(f"  {sym} {label}")
    print(f"\nINFO F4: GET /admin/users with users=deny → status {f4_users_status} (expected still 200 since users module not migrated)")
    print(f"\n{n_pass}/{n_total} assertions PASS")
    sys.exit(0 if n_pass == n_total else 1)


if __name__ == "__main__":
    main()
