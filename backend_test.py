"""Phase C2 — Credits & Discounts backend test suite.

Run: python /app/backend_test.py
Reads EXPO_PUBLIC_BACKEND_URL from /app/frontend/.env, all calls under /api.
Admin credentials: super_admin from /app/memory/test_credentials.md.
"""
from __future__ import annotations

import sys
import time
import traceback
from typing import Any, Dict, List, Optional

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
SUPER_EMAIL = "[email protected]"
SUPER_PASS = "ChangeMe123!"
OTP = "123456"
TS = int(time.time())

PASSED: List[str] = []
FAILED: List[str] = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  PASS {label}")
        PASSED.append(label)
    else:
        print(f"  FAIL {label} :: {detail}")
        FAILED.append(f"{label} :: {detail}")


def post(path, json_body=None, token=None, expect=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(f"{BASE}{path}", json=json_body, headers=headers, timeout=30)
    if expect is not None and r.status_code != expect:
        print(f"    [DEBUG] POST {path} expected {expect} got {r.status_code} body={r.text[:300]}")
    return r


def get(path, token=None, expect=None, params=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(f"{BASE}{path}", headers=headers, params=params, timeout=30)
    if expect is not None and r.status_code != expect:
        print(f"    [DEBUG] GET {path} expected {expect} got {r.status_code} body={r.text[:300]}")
    return r


def delete(path, token=None, expect=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.delete(f"{BASE}{path}", headers=headers, timeout=30)
    if expect is not None and r.status_code != expect:
        print(f"    [DEBUG] DELETE {path} expected {expect} got {r.status_code} body={r.text[:300]}")
    return r


def admin_login(email, password):
    r = post("/admin/auth/login", {"email": email, "password": password})
    r.raise_for_status()
    return r.json()["token"]


def register_user(name, referral_code=None):
    body = {"name": name}
    if referral_code:
        body["referral_code"] = referral_code
    r = post("/auth/register", body)
    r.raise_for_status()
    return r.json()


def send_otp(uid, phone):
    r = post("/auth/send-otp", {"user_id": uid, "phone": phone})
    r.raise_for_status()


def verify_otp(uid, phone):
    r = post("/auth/verify-otp", {"user_id": uid, "phone": phone, "code": OTP})
    r.raise_for_status()
    return r.json()


def fresh_phone():
    n = int(time.time() * 1000) % 9999999
    return f"+1555{n:07d}"


def main():
    print("=== Phase C2 — Credits & Discounts Backend Tests ===")
    print(f"BASE: {BASE}")
    print(f"TS: {TS}")

    super_tok = admin_login(SUPER_EMAIL, SUPER_PASS)
    print(f"super_admin token acquired ({len(super_tok)} chars)")

    # ===== Register Tom =====
    tom = register_user(f"TomC2T{TS}")
    tom_id = tom["id"]
    tom_phone = fresh_phone()
    send_otp(tom_id, tom_phone)
    tom = verify_otp(tom_id, tom_phone)
    tom_id = tom["id"]
    print(f"Tom: id={tom_id} phone={tom_phone}")

    # ===== A) Migration idempotency =====
    print("\n[A] Migration idempotency")
    wallet = get(f"/users/{tom_id}/credits").json()
    pending_rows = [r for r in wallet["items"] if r.get("status") == "pending" and float(r.get("amount", 0)) > 0]
    check("A: no pending non-zero rows for fresh user", len(pending_rows) == 0,
          f"pending_rows={pending_rows}")

    # ===== B) Admin grant credit =====
    print("\n[B] Admin grant credit ($10)")
    r = post(f"/admin/users/{tom_id}/credits/grant", {"amount": 10, "note": "Welcome"}, token=super_tok)
    check("B: grant 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
    grant_row = r.json()
    check("B: row has status=active", grant_row.get("status") == "active",
          f"status={grant_row.get('status')}")
    check("B: row kind=admin_grant", grant_row.get("kind") == "admin_grant")

    wallet = get(f"/users/{tom_id}/credits").json()
    check("B: balance == 10.0", abs(wallet["balance"] - 10.0) < 0.001,
          f"balance={wallet['balance']}")
    items_active = [it for it in wallet["items"] if it["status"] == "active"]
    check("B: items[0].kind == admin_grant", bool(items_active) and items_active[0]["kind"] == "admin_grant")
    check("B: items[0].consumed_amount == 0",
          bool(items_active) and abs(items_active[0]["consumed_amount"]) < 0.001)

    # ===== C) Auto-apply at contribute (full) =====
    print("\n[C] Auto-apply at contribute — full")
    r = post(f"/admin/users/{tom_id}/lead-discount", {"enabled": False}, token=super_tok)
    check("C-pre: clear lead_auto_discount 200", r.status_code == 200)

    r = post("/groups", {
        "lead_id": tom_id, "title": f"C2-C-{TS}", "total_amount": 30,
        "split_mode": "fast", "tax": 0, "tip": 0, "items": [],
    })
    check("C: create group 200", r.status_code == 200, r.text[:200])
    g = r.json()
    gid_c = g["id"]
    check("C: group total_amount == 30", abs(g["total_amount"] - 30) < 0.01,
          f"total={g.get('total_amount')}")
    r = post(f"/groups/{gid_c}/contribute", {"user_id": tom_id, "amount": 30})
    check("C: contribute 200", r.status_code == 200, r.text[:200])
    g = r.json()
    contribs = g.get("contributions", [])
    check("C: 1 contribution", len(contribs) == 1, f"contribs={contribs}")
    if contribs:
        c0 = contribs[0]
        check("C: amount == 30", abs(float(c0["amount"]) - 30) < 0.01, f"amount={c0.get('amount')}")
        check("C: cash_paid == 20", abs(float(c0.get("cash_paid", 0)) - 20) < 0.01,
              f"cash_paid={c0.get('cash_paid')}")
        check("C: credit_applied == 10",
              abs(float(c0.get("credit_applied", 0)) - 10) < 0.01,
              f"credit_applied={c0.get('credit_applied')}")
    wallet = get(f"/users/{tom_id}/credits").json()
    check("C: balance == 0", abs(wallet["balance"]) < 0.01, f"balance={wallet['balance']}")
    grant_after = next((it for it in wallet["items"] if it["id"] == grant_row["id"]), None)
    check("C: grant row consumed_amount==10",
          grant_after is not None and abs(grant_after["consumed_amount"] - 10) < 0.01,
          f"row={grant_after}")
    check("C: grant row status == consumed",
          grant_after is not None and grant_after["status"] == "consumed",
          f"row.status={grant_after and grant_after['status']}")

    # ===== D) Partial credit =====
    print("\n[D] Partial credit ($5 then contribute $30)")
    r = post(f"/admin/users/{tom_id}/credits/grant", {"amount": 5, "note": "More"}, token=super_tok)
    check("D: grant 200", r.status_code == 200)
    r = post("/groups", {
        "lead_id": tom_id, "title": f"C2-D-{TS}", "total_amount": 30,
        "split_mode": "fast", "tax": 0, "tip": 0, "items": [],
    })
    gid_d = r.json()["id"]
    r = post(f"/groups/{gid_d}/contribute", {"user_id": tom_id, "amount": 30})
    check("D: contribute 200", r.status_code == 200, r.text[:200])
    contribs = r.json().get("contributions", [])
    if contribs:
        c0 = contribs[0]
        check("D: cash_paid == 25", abs(float(c0.get("cash_paid", 0)) - 25) < 0.01,
              f"cash_paid={c0.get('cash_paid')}")
        check("D: credit_applied == 5",
              abs(float(c0.get("credit_applied", 0)) - 5) < 0.01,
              f"credit_applied={c0.get('credit_applied')}")
    wallet = get(f"/users/{tom_id}/credits").json()
    check("D: balance == 0", abs(wallet["balance"]) < 0.01, f"balance={wallet['balance']}")

    # ===== E) FIFO order =====
    print("\n[E] FIFO order ($3 first, $5 second; consume $4)")
    r1 = post(f"/admin/users/{tom_id}/credits/grant", {"amount": 3, "note": "first"}, token=super_tok)
    grant_e1_id = r1.json()["id"]
    time.sleep(0.05)
    r2 = post(f"/admin/users/{tom_id}/credits/grant", {"amount": 5, "note": "second"}, token=super_tok)
    grant_e2_id = r2.json()["id"]
    r = post("/groups", {
        "lead_id": tom_id, "title": f"C2-E-{TS}", "total_amount": 4,
        "split_mode": "fast", "tax": 0, "tip": 0, "items": [],
    })
    check("E: create $4 group 200", r.status_code == 200, r.text[:200])
    gid_e = r.json()["id"]
    r = post(f"/groups/{gid_e}/contribute", {"user_id": tom_id, "amount": 4})
    check("E: contribute $4 200", r.status_code == 200, r.text[:200])
    contribs = r.json().get("contributions", [])
    if contribs:
        c0 = contribs[0]
        check("E: cash_paid == 0", abs(float(c0.get("cash_paid", 0)) - 0) < 0.01,
              f"cash_paid={c0.get('cash_paid')}")
        check("E: credit_applied == 4",
              abs(float(c0.get("credit_applied", 0)) - 4) < 0.01,
              f"credit_applied={c0.get('credit_applied')}")
    wallet = get(f"/users/{tom_id}/credits").json()
    e1 = next((it for it in wallet["items"] if it["id"] == grant_e1_id), None)
    e2 = next((it for it in wallet["items"] if it["id"] == grant_e2_id), None)
    check("E: first grant fully consumed",
          e1 is not None and abs(e1["consumed_amount"] - 3) < 0.01 and e1["status"] == "consumed",
          f"e1={e1}")
    check("E: second grant consumed_amount=1, active",
          e2 is not None and abs(e2["consumed_amount"] - 1) < 0.01 and e2["status"] == "active",
          f"e2={e2}")
    check("E: balance == 4", abs(wallet["balance"] - 4) < 0.01, f"balance={wallet['balance']}")

    # ===== F) Revoke =====
    print("\n[F] Revoke")
    r = post(f"/admin/users/{tom_id}/credits/{grant_e2_id}/revoke", token=super_tok)
    check("F: revoke 200", r.status_code == 200, r.text[:200])
    revoked = r.json()
    check("F: status == revoked", revoked.get("status") == "revoked",
          f"status={revoked.get('status')}")
    wallet = get(f"/users/{tom_id}/credits").json()
    check("F: balance excludes revoked (== 0)",
          abs(wallet["balance"]) < 0.01, f"balance={wallet['balance']}")
    audit_before = get("/admin/audit-log", token=super_tok,
                       params={"action": "admin.revoke_credit", "limit": 200}).json()
    n_before = len(audit_before.get("items", []))
    r = post(f"/admin/users/{tom_id}/credits/{grant_e2_id}/revoke", token=super_tok)
    check("F: re-revoke 200 (idempotent)", r.status_code == 200, r.text[:200])
    check("F: re-revoke still status=revoked",
          r.json().get("status") == "revoked", f"row={r.json()}")
    audit_after = get("/admin/audit-log", token=super_tok,
                      params={"action": "admin.revoke_credit", "limit": 200}).json()
    n_after = len(audit_after.get("items", []))
    check("F: re-revoke does NOT add new audit row",
          n_after == n_before, f"before={n_before} after={n_after}")

    # ===== G) Group discount flat =====
    print("\n[G] Group discount flat ($5 off $100)")
    r = post("/groups", {
        "lead_id": tom_id, "title": f"C2-G-{TS}", "total_amount": 100,
        "split_mode": "itemized", "tax": 0, "tip": 0,
        "items": [{"name": "BigItem", "price": 100, "quantity": 1}],
    })
    check("G: create group 200", r.status_code == 200, r.text[:200])
    gid_g = r.json()["id"]
    r = post(f"/admin/groups/{gid_g}/discount",
             {"type": "flat", "value": 5, "note": "promo"}, token=super_tok)
    check("G: set flat discount 200", r.status_code == 200, r.text[:200])
    body = r.json()
    check("G: total_amount == 95", abs(body["total_amount"] - 95) < 0.01,
          f"total_amount={body.get('total_amount')}")
    check("G: original_total_amount == 100",
          abs(body["original_total_amount"] - 100) < 0.01, f"orig={body.get('original_total_amount')}")
    check("G: discount.amount == 5",
          abs(body["discount"]["amount"] - 5) < 0.01, f"discount={body.get('discount')}")
    g_get = get(f"/groups/{gid_g}").json()
    check("G: GET group total_amount == 95",
          abs(g_get["total_amount"] - 95) < 0.01, f"got {g_get.get('total_amount')}")

    # ===== H) Group discount percent =====
    print("\n[H] Group discount percent (20%)")
    r = post("/groups", {
        "lead_id": tom_id, "title": f"C2-H-{TS}", "total_amount": 100,
        "split_mode": "itemized", "tax": 0, "tip": 0,
        "items": [{"name": "Pizza", "price": 100, "quantity": 1}],
    })
    gid_h = r.json()["id"]
    r = post(f"/admin/groups/{gid_h}/discount",
             {"type": "percent", "value": 20, "note": "20%"}, token=super_tok)
    check("H: set percent discount 200", r.status_code == 200, r.text[:200])
    body = r.json()
    check("H: total == 80", abs(body["total_amount"] - 80) < 0.01,
          f"total={body.get('total_amount')}")
    check("H: discount.amount == 20",
          abs(body["discount"]["amount"] - 20) < 0.01, f"discount={body.get('discount')}")

    # ===== I) Discount on settled group => 400 =====
    print("\n[I] Discount on settled group → 400")
    settled_gid = gid_d
    settled_get = get(f"/groups/{settled_gid}").json()
    if settled_get.get("status") == "open":
        settled_gid = gid_c
        settled_get = get(f"/groups/{settled_gid}").json()
    check("I: settled group status != open",
          settled_get.get("status") != "open",
          f"status={settled_get.get('status')}")
    r = post(f"/admin/groups/{settled_gid}/discount",
             {"type": "flat", "value": 5}, token=super_tok)
    check("I: discount on settled → 400", r.status_code == 400,
          f"got {r.status_code} {r.text[:200]}")

    # ===== J) Clear discount =====
    print("\n[J] Clear discount on group H")
    r = delete(f"/admin/groups/{gid_h}/discount", token=super_tok)
    check("J: DELETE 200", r.status_code == 200, r.text[:200])
    body = r.json()
    check("J: total restored to 100", abs(body["total_amount"] - 100) < 0.01,
          f"total={body.get('total_amount')}")
    check("J: discount is null", body.get("discount") is None,
          f"discount={body.get('discount')}")
    g_get = get(f"/groups/{gid_h}").json()
    check("J: GET shows total==100", abs(g_get["total_amount"] - 100) < 0.01,
          f"got {g_get.get('total_amount')}")
    check("J: GET discount is null", g_get.get("discount") is None)

    # ===== K) Lead auto-discount =====
    print("\n[K] Lead auto-discount")
    r = post(f"/admin/users/{tom_id}/lead-discount",
             {"type": "flat", "value": 5, "note": "VIP", "enabled": True}, token=super_tok)
    check("K: set lead_auto_discount 200", r.status_code == 200, r.text[:200])
    lad = r.json().get("lead_auto_discount")
    check("K: lead_auto_discount.type == flat", bool(lad) and lad.get("type") == "flat",
          f"lad={lad}")
    check("K: lead_auto_discount.value == 5", bool(lad) and abs(float(lad.get("value", 0)) - 5) < 0.01)
    r = post("/groups", {
        "lead_id": tom_id, "title": f"C2-K-{TS}", "total_amount": 50,
        "split_mode": "itemized", "tax": 0, "tip": 0,
        "items": [{"name": "Burger", "price": 50, "quantity": 1}],
    })
    check("K: create group 200", r.status_code == 200, r.text[:200])
    g = r.json()
    check("K: group total_amount == 45", abs(g["total_amount"] - 45) < 0.01,
          f"total={g.get('total_amount')}")
    check("K: original_total_amount == 50",
          abs(g.get("original_total_amount", 0) - 50) < 0.01,
          f"orig={g.get('original_total_amount')}")
    check("K: discount.source == lead_auto",
          (g.get("discount") or {}).get("source") == "lead_auto",
          f"discount={g.get('discount')}")
    check("K: discount.amount == 5",
          abs((g.get("discount") or {}).get("amount", 0) - 5) < 0.01,
          f"discount={g.get('discount')}")

    r = post(f"/admin/users/{tom_id}/lead-discount", {"enabled": False}, token=super_tok)
    check("K: clear lead_auto_discount 200", r.status_code == 200)
    check("K: response lead_auto_discount is null",
          r.json().get("lead_auto_discount") is None)
    r = post("/groups", {
        "lead_id": tom_id, "title": f"C2-K2-{TS}", "total_amount": 50,
        "split_mode": "itemized", "tax": 0, "tip": 0,
        "items": [{"name": "Salad", "price": 50, "quantity": 1}],
    })
    g2 = r.json()
    check("K: post-clear group total_amount == 50",
          abs(g2["total_amount"] - 50) < 0.01, f"total={g2.get('total_amount')}")
    check("K: post-clear group has no discount",
          g2.get("discount") is None, f"discount={g2.get('discount')}")

    # ===== L) Audit log destructive flag =====
    print("\n[L] Audit log destructive=true for C2 actions")
    needed_actions = [
        "admin.grant_credit",
        "admin.revoke_credit",
        "admin.set_group_discount",
        "admin.clear_group_discount",
        "admin.set_lead_discount",
        "admin.clear_lead_discount",
    ]
    audit = get("/admin/audit-log", token=super_tok, params={"limit": 200}).json()
    items = audit.get("items", [])
    seen_destructive = set()
    seen_any = set()
    for it in items:
        action = it.get("action")
        if action in needed_actions:
            seen_any.add(action)
            if it.get("destructive") is True:
                seen_destructive.add(action)
    for action in needed_actions:
        check(f"L: audit '{action}' present", action in seen_any,
              "missing in last 200 entries")
        check(f"L: audit '{action}' destructive=true", action in seen_destructive,
              "destructive flag missing or false")

    # ===== M) RBAC — support admin =====
    print("\n[M] RBAC — support admin")
    support_email = f"support_c2_{TS}@example.com"
    support_pass = "SupportPass123!"
    r = post("/admin/admins", {
        "email": support_email, "password": support_pass,
        "name": f"SupportC2{TS}", "role": "support",
    }, token=super_tok)
    if r.status_code != 200:
        print(f"    [info] /admin/admins create returned {r.status_code} {r.text[:200]}")
    support_tok = admin_login(support_email, support_pass)

    r = post(f"/admin/users/{tom_id}/credits/grant",
             {"amount": 1, "note": "x"}, token=support_tok)
    check("M: support grant → 403", r.status_code == 403,
          f"got {r.status_code} {r.text[:200]}")

    wallet = get(f"/users/{tom_id}/credits").json()
    active_id = None
    for it in wallet["items"]:
        if it["status"] == "active":
            active_id = it["id"]
            break
    if not active_id:
        r = post(f"/admin/users/{tom_id}/credits/grant",
                 {"amount": 2, "note": "rbac"}, token=super_tok)
        active_id = r.json()["id"]

    r = post(f"/admin/users/{tom_id}/credits/{active_id}/revoke", token=support_tok)
    check("M: support revoke → 403", r.status_code == 403,
          f"got {r.status_code} {r.text[:200]}")

    open_gid = g2["id"]
    r = post(f"/admin/groups/{open_gid}/discount",
             {"type": "flat", "value": 1}, token=support_tok)
    check("M: support set group discount → 403", r.status_code == 403,
          f"got {r.status_code} {r.text[:200]}")
    r = delete(f"/admin/groups/{open_gid}/discount", token=support_tok)
    check("M: support DELETE group discount → 403", r.status_code == 403,
          f"got {r.status_code} {r.text[:200]}")
    r = post(f"/admin/users/{tom_id}/lead-discount",
             {"type": "flat", "value": 5, "enabled": True}, token=support_tok)
    check("M: support set lead-discount → 403", r.status_code == 403,
          f"got {r.status_code} {r.text[:200]}")

    r = get(f"/admin/users/{tom_id}/credits", token=support_tok)
    check("M: support GET admin wallet → 200", r.status_code == 200,
          f"got {r.status_code} {r.text[:200]}")
    r = get(f"/users/{tom_id}/credits")
    check("M: public GET wallet → 200", r.status_code == 200,
          f"got {r.status_code} {r.text[:200]}")

    # ===== Z) Admin wallet auth =====
    r = get(f"/admin/users/{tom_id}/credits", token=super_tok)
    check("Z: admin GET wallet 200", r.status_code == 200, r.text[:200])
    awallet = r.json()
    check("Z: admin wallet has balance & items",
          "balance" in awallet and "items" in awallet)

    r = get(f"/admin/users/{tom_id}/credits")
    check("Z: admin wallet without bearer → 401", r.status_code == 401,
          f"got {r.status_code}")

    # ===== N) Cleanup =====
    print("\n[N] Cleanup")
    r = post(f"/admin/users/{tom_id}/lead-discount", {"enabled": False}, token=super_tok)
    check("N: clear Tom's lead-discount", r.status_code == 200)

    print()
    print("=" * 60)
    print(f"PASSED: {len(PASSED)}  FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFAILED items:")
        for f in FAILED:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if not FAILED else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        traceback.print_exc()
        sys.exit(2)
