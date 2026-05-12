"""
Focused re-test (R1-R5) for "Sensitive admin routes migrated to require_module()" task.

Verifies fixes for:
  R1 — F2 kms-status fix
  R2 — F5 reconciliations deny override fix
  R3 — Integrations GETs now gated
  R4 — Master account GET is now its own module
  R5 — Super admin still has full access

Endpoint: http://localhost:8001/api
Super admin: admin@squadpay.us / Letmein@2007#ForReal
Manager: g1mgr1778059029@kwiktech.net / ManagerTemp!2026Aa
"""
import json
import sys
import requests

BASE = "http://localhost:8001/api"
SUPER_EMAIL = "admin@squadpay.us"
SUPER_PASS = "Letmein@2007#ForReal"
MGR_EMAIL = "g1mgr1778059029@kwiktech.net"
MGR_PASS = "ManagerTemp!2026Aa"

results = []  # list of (label, ok, detail)


def record(label, ok, detail=""):
    results.append((label, ok, detail))
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {label} :: {detail}")


def admin_login(email, password):
    r = requests.post(f"{BASE}/admin/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    j = r.json()
    return j["token"], j["admin"]


def main():
    # ===== Login both admins =====
    super_token, super_admin = admin_login(SUPER_EMAIL, SUPER_PASS)
    print(f"super_admin id={super_admin.get('id')}")
    mgr_token, mgr_admin = admin_login(MGR_EMAIL, MGR_PASS)
    mgr_id = mgr_admin["id"]
    print(f"manager id={mgr_id} overrides={mgr_admin.get('module_overrides')}")

    super_h = {"Authorization": f"Bearer {super_token}"}
    mgr_h = {"Authorization": f"Bearer {mgr_token}"}

    # Confirm overrides are {}
    cur = mgr_admin.get("module_overrides") or {}
    record(
        "PRE: manager.module_overrides == {}",
        cur == {},
        f"got {cur!r}",
    )
    if cur != {}:
        # Force-clear
        r = requests.put(
            f"{BASE}/admin/access/admins/{mgr_id}",
            headers=super_h,
            json={"module_overrides": {}},
            timeout=15,
        )
        print("force-clear:", r.status_code, r.text[:200])

    # ===== R1 — F2 kms-status fix =====
    r = requests.get(f"{BASE}/admin/security/kms-status", headers=mgr_h, timeout=15)
    body = r.text
    try:
        body_j = r.json()
    except Exception:
        body_j = {}
    record(
        "R1: GET /admin/security/kms-status as manager → 403 with 'module' in body",
        r.status_code == 403 and "module" in body.lower(),
        f"status={r.status_code} body={body[:200]}",
    )

    # ===== R2 — F5 reconciliations deny override fix =====
    # 2a: Apply deny override
    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=super_h,
        json={"module_overrides": {"reconciliations": "deny"}},
        timeout=15,
    )
    record(
        "R2a: PUT mgr overrides {reconciliations:deny} → 200",
        r.status_code == 200,
        f"status={r.status_code} body={r.text[:200]}",
    )

    # 2b: GET /reconciliations as manager → 403
    r = requests.get(f"{BASE}/admin/reconciliations", headers=mgr_h, timeout=15)
    record(
        "R2b: GET /admin/reconciliations as manager (deny) → 403",
        r.status_code == 403 and "module" in r.text.lower(),
        f"status={r.status_code} body={r.text[:200]}",
    )

    # 2c: GET /reconciliations/anyid as manager → 403 (gate fires before 404)
    r = requests.get(f"{BASE}/admin/reconciliations/anyid", headers=mgr_h, timeout=15)
    record(
        "R2c: GET /admin/reconciliations/anyid as manager (deny) → 403 (gate before 404)",
        r.status_code == 403 and "module" in r.text.lower(),
        f"status={r.status_code} body={r.text[:200]}",
    )

    # 2d: GET /reconciliation-settings as manager → 403
    r = requests.get(f"{BASE}/admin/reconciliation-settings", headers=mgr_h, timeout=15)
    record(
        "R2d: GET /admin/reconciliation-settings as manager (deny) → 403",
        r.status_code == 403 and "module" in r.text.lower(),
        f"status={r.status_code} body={r.text[:200]}",
    )

    # 2e: Clear override
    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=super_h,
        json={"module_overrides": {}},
        timeout=15,
    )
    record(
        "R2e: PUT mgr overrides {} (clear) → 200",
        r.status_code == 200,
        f"status={r.status_code} body={r.text[:200]}",
    )

    # 2f: Re-GET /reconciliations as manager → 200 (default access restored)
    r = requests.get(f"{BASE}/admin/reconciliations", headers=mgr_h, timeout=15)
    record(
        "R2f: GET /admin/reconciliations as manager (cleared) → 200",
        r.status_code == 200,
        f"status={r.status_code} body={r.text[:200]}",
    )

    # ===== R3 — Integrations GETs now gated =====
    # overrides are currently {} (cleared in 2e)
    r = requests.get(f"{BASE}/admin/integrations", headers=mgr_h, timeout=15)
    record(
        "R3a: GET /admin/integrations as manager (no override) → 403 (integrations is super_admin only)",
        r.status_code == 403 and "module" in r.text.lower(),
        f"status={r.status_code} body={r.text[:200]}",
    )

    r = requests.get(f"{BASE}/admin/integrations/issuing", headers=mgr_h, timeout=15)
    record(
        "R3b: GET /admin/integrations/issuing as manager (no override) → 403",
        r.status_code == 403 and "module" in r.text.lower(),
        f"status={r.status_code} body={r.text[:200]}",
    )

    # Grant integrations
    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=super_h,
        json={"module_overrides": {"integrations": "grant"}},
        timeout=15,
    )
    record(
        "R3c: PUT mgr overrides {integrations:grant} → 200",
        r.status_code == 200,
        f"status={r.status_code} body={r.text[:200]}",
    )

    r = requests.get(f"{BASE}/admin/integrations", headers=mgr_h, timeout=15)
    record(
        "R3d: GET /admin/integrations as manager (granted) → 200",
        r.status_code == 200,
        f"status={r.status_code} body={r.text[:300]}",
    )

    r = requests.get(f"{BASE}/admin/integrations/issuing", headers=mgr_h, timeout=15)
    # Should be 200 OR 5xx (if Stripe key missing), just not 403
    record(
        "R3e: GET /admin/integrations/issuing as manager (granted) → 200 or 5xx (NOT 403)",
        r.status_code != 403,
        f"status={r.status_code} body={r.text[:200]}",
    )

    # ===== R4 — Master account GET is its own module =====
    # Clear overrides
    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=super_h,
        json={"module_overrides": {}},
        timeout=15,
    )
    record(
        "R4a: PUT mgr overrides {} (clear) → 200",
        r.status_code == 200,
        f"status={r.status_code} body={r.text[:200]}",
    )

    r = requests.get(f"{BASE}/admin/master-account", headers=mgr_h, timeout=15)
    record(
        "R4b: GET /admin/master-account as manager (no override) → 403 (master_account is super_admin only)",
        r.status_code == 403 and "module" in r.text.lower(),
        f"status={r.status_code} body={r.text[:200]}",
    )

    # Grant master_account
    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=super_h,
        json={"module_overrides": {"master_account": "grant"}},
        timeout=15,
    )
    record(
        "R4c: PUT mgr overrides {master_account:grant} → 200",
        r.status_code == 200,
        f"status={r.status_code} body={r.text[:200]}",
    )

    r = requests.get(f"{BASE}/admin/master-account", headers=mgr_h, timeout=15)
    record(
        "R4d: GET /admin/master-account as manager (granted) → 200",
        r.status_code == 200,
        f"status={r.status_code} body={r.text[:300]}",
    )

    # ===== R5 — Super admin still has full access =====
    endpoints = [
        ("GET", "/admin/security/kms-status"),
        ("GET", "/admin/reconciliations"),
        ("GET", "/admin/reconciliation-settings"),
        ("GET", "/admin/integrations"),
        ("GET", "/admin/integrations/issuing"),
        ("GET", "/admin/master-account"),
    ]
    for method, path in endpoints:
        r = requests.request(method, f"{BASE}{path}", headers=super_h, timeout=15)
        # 200 expected (or natural 5xx if upstream missing). NOT 403.
        ok = r.status_code != 403
        record(
            f"R5: {method} {path} as super_admin → not 403 (got {r.status_code})",
            ok,
            f"status={r.status_code} body={r.text[:150]}",
        )

    # The reconciliations/anyid 404 path for super_admin (gate must pass)
    r = requests.get(f"{BASE}/admin/reconciliations/anyid", headers=super_h, timeout=15)
    record(
        "R5: GET /admin/reconciliations/anyid as super_admin → 404 (gate passed)",
        r.status_code == 404,
        f"status={r.status_code} body={r.text[:150]}",
    )

    # ===== CLEANUP — restore manager overrides to {} =====
    r = requests.put(
        f"{BASE}/admin/access/admins/{mgr_id}",
        headers=super_h,
        json={"module_overrides": {}},
        timeout=15,
    )
    record(
        "CLEANUP: PUT mgr overrides {} → 200",
        r.status_code == 200,
        f"status={r.status_code}",
    )

    # ===== summary =====
    print("\n" + "=" * 70)
    fails = [(l, d) for (l, ok, d) in results if not ok]
    print(f"TOTAL {len(results)} | PASS {len(results) - len(fails)} | FAIL {len(fails)}")
    for l, d in fails:
        print(f"  ❌ {l}\n     {d}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
