"""
Phase O — Unified Admin App-Config (Batch A) backend test suite.

Tests:
  1) GET/PUT /api/admin/app-config — shape, defaults, RBAC, round-trip.
  2) core_fees.transaction_fee_pct propagates to bill math live.
  3) Wallet provisioning admin gate on POST /api/cards/{group_id}/provision.
  4) Legacy /api/admin/platform-fees still works and mirrors into app-config.
  5) Auth / RBAC.
"""
import os
import sys
import time
import json
import re
import requests
from pathlib import Path

# --- Load backend URL from frontend .env (NEVER hardcode) -------------------
FRONTEND_ENV = Path("/app/frontend/.env")
BACKEND_URL = None
for line in FRONTEND_ENV.read_text().splitlines():
    if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
        BACKEND_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
        break
if not BACKEND_URL:
    print("FATAL: EXPO_PUBLIC_BACKEND_URL not found in /app/frontend/.env")
    sys.exit(1)

API = f"{BACKEND_URL}/api"
print(f"BASE: {API}")

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

# ----------------------------------------------------------------------------

results = []          # list of (name, ok, detail)
failures = []         # list of (name, detail)


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    status = "✅" if ok else "❌"
    print(f"  {status} {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append((name, detail))


def post(path, json_body=None, headers=None, expected=None):
    url = f"{API}{path}"
    r = requests.post(url, json=json_body, headers=headers or {}, timeout=30)
    return r


def get(path, headers=None):
    url = f"{API}{path}"
    return requests.get(url, headers=headers or {}, timeout=30)


def put(path, json_body=None, headers=None):
    url = f"{API}{path}"
    return requests.put(url, json=json_body, headers=headers or {}, timeout=30)


def admin_login(email, password):
    r = post("/admin/auth/login", {"email": email, "password": password})
    if r.status_code != 200:
        return None, r
    return r.json().get("token"), r


# ----------------------------------------------------------------------------
# Test sections
# ----------------------------------------------------------------------------

def section(name):
    print(f"\n=== {name} ===")


def main():
    section("0) Admin login")
    token, r = admin_login(ADMIN_EMAIL, ADMIN_PASSWORD)
    record("admin login 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if not token:
        print("Cannot proceed without admin token. Aborting.")
        return
    admin_h = {"Authorization": f"Bearer {token}"}

    # ============================================================
    # 1) GET/PUT /api/admin/app-config
    # ============================================================
    section("1A) GET /admin/app-config — auth required")
    r = get("/admin/app-config")
    record("GET /admin/app-config without auth -> 401", r.status_code == 401, f"got {r.status_code}")

    section("1B) GET /admin/app-config — happy path + shape")
    r = get("/admin/app-config", headers=admin_h)
    record("GET 200 with admin token", r.status_code == 200, f"got {r.status_code}")
    cfg = r.json() if r.status_code == 200 else {}
    required = ["core_fees", "extra_fees", "wallet", "limits", "otp", "card", "reminders", "ocr", "brand", "ops"]
    for k in required:
        record(f"section '{k}' present", k in cfg)

    # Capture original values so we restore them at the end.
    original = json.loads(json.dumps(cfg))  # deep copy

    section("1C) Default values verification (note: PUT may have run previously)")
    # We can't strictly assert defaults if a prior PUT changed them, but if
    # a fresh install these should all match. Just record observed values.
    cf = cfg.get("core_fees", {})
    wal = cfg.get("wallet", {})
    lim = cfg.get("limits", {})
    otp = cfg.get("otp", {})
    ocr = cfg.get("ocr", {})

    # core_fees defaults are 3.0 / 0.03 — but they may have been edited.
    # We'll verify them after restoring at end. For now, just check types.
    record("core_fees.transaction_fee_pct is number", isinstance(cf.get("transaction_fee_pct"), (int, float)))
    record("core_fees.platform_fee_flat is number", isinstance(cf.get("platform_fee_flat"), (int, float)))
    record("wallet.enabled is bool", isinstance(wal.get("enabled"), bool))
    record("wallet.apple_enabled is bool", isinstance(wal.get("apple_enabled"), bool))
    record("wallet.google_enabled is bool", isinstance(wal.get("google_enabled"), bool))
    record("limits.min_members_per_bill is int", isinstance(lim.get("min_members_per_bill"), int))
    record("otp.code_length == 6 (default)", otp.get("code_length") == 6, f"got {otp.get('code_length')}")
    record("otp.expiry_seconds == 300 (default)", otp.get("expiry_seconds") == 300, f"got {otp.get('expiry_seconds')}")
    record("ocr.provider == 'openai'", ocr.get("provider") == "openai", f"got {ocr.get('provider')}")
    record("ocr.model == 'gpt-4o'", ocr.get("model") == "gpt-4o", f"got {ocr.get('model')}")

    section("1D) PUT /admin/app-config — auth required")
    r = put("/admin/app-config", json_body={"core_fees": {"transaction_fee_pct": 2.5, "platform_fee_flat": 0.03}})
    record("PUT without auth -> 401", r.status_code == 401, f"got {r.status_code}")

    section("1E) PUT round-trip — change fees, wallet, limits, ops")
    payload = json.loads(json.dumps(cfg))  # start from current full doc
    payload["core_fees"]["transaction_fee_pct"] = 2.5
    payload["wallet"]["enabled"] = True
    payload["limits"]["min_members_per_bill"] = 3
    payload["ops"]["maintenance_mode"] = True
    r = put("/admin/app-config", json_body=payload, headers=admin_h)
    record("PUT 200", r.status_code == 200, f"got {r.status_code} body={r.text[:300]}")

    # Subsequent GET reflects changes
    r2 = get("/admin/app-config", headers=admin_h)
    record("GET after PUT -> 200", r2.status_code == 200)
    cfg2 = r2.json() if r2.status_code == 200 else {}
    record("core_fees.transaction_fee_pct == 2.5",
           abs(cfg2.get("core_fees", {}).get("transaction_fee_pct", 0) - 2.5) < 1e-6,
           f"got {cfg2.get('core_fees', {}).get('transaction_fee_pct')}")
    record("wallet.enabled == True", cfg2.get("wallet", {}).get("enabled") is True,
           f"got {cfg2.get('wallet', {}).get('enabled')}")
    record("limits.min_members_per_bill == 3",
           cfg2.get("limits", {}).get("min_members_per_bill") == 3,
           f"got {cfg2.get('limits', {}).get('min_members_per_bill')}")
    record("ops.maintenance_mode == True", cfg2.get("ops", {}).get("maintenance_mode") is True)

    # ============================================================
    # 2) Live fee propagation — transaction_fee_pct=5% → bill math
    # ============================================================
    section("2) Live fee propagation to bill math")

    # Set transaction_fee_pct to 5
    payload2 = json.loads(json.dumps(cfg2))
    payload2["core_fees"]["transaction_fee_pct"] = 5.0
    # Also reset wallet/limits/ops to defaults during this test so they don't
    # interfere; but core_fees is the focus.
    payload2["wallet"]["enabled"] = False
    payload2["limits"]["min_members_per_bill"] = 2
    payload2["ops"]["maintenance_mode"] = False
    r = put("/admin/app-config", json_body=payload2, headers=admin_h)
    record("PUT transaction_fee_pct=5.0 -> 200", r.status_code == 200, f"got {r.status_code}")

    # Register two test users
    ts = int(time.time())
    lead_phone = f"+1832500{ts % 10000:04d}"
    member_phone = f"+1832501{ts % 10000:04d}"

    def register_and_verify(name, phone):
        rr = post("/auth/register", {"name": name})
        if rr.status_code not in (200, 201):
            return None, f"register failed {rr.status_code} {rr.text[:200]}"
        uid = rr.json().get("id") or rr.json().get("user_id") or rr.json().get("user", {}).get("id")
        rr2 = post("/auth/send-otp", {"user_id": uid, "phone": phone})
        if rr2.status_code != 200:
            return None, f"send-otp failed {rr2.status_code} {rr2.text[:200]}"
        rr3 = post("/auth/verify-otp", {"user_id": uid, "phone": phone, "code": "123456"})
        if rr3.status_code != 200:
            return None, f"verify-otp failed {rr3.status_code} {rr3.text[:200]}"
        body = rr3.json()
        return body.get("id") or body.get("user_id") or uid, None

    lead_id, err = register_and_verify(f"FeeLead{ts}", lead_phone)
    record("register+verify lead", err is None, err or f"id={lead_id}")
    member_id, err2 = register_and_verify(f"FeeMember{ts}", member_phone)
    record("register+verify member", err2 is None, err2 or f"id={member_id}")

    if lead_id and member_id:
        # Create group via fast-split, total=10, two members, tax/tip=0
        body = {
            "lead_id": lead_id,
            "title": f"FeeTest {ts}",
            "total_amount": 10.0,
            "split_mode": "fast",
            "tax": 0.0,
            "tip": 0.0,
            "items": [{"name": "X", "price": 10.0, "quantity": 1}],
        }
        rg = post("/groups", body)
        record("POST /groups -> 200", rg.status_code == 200, f"got {rg.status_code} body={rg.text[:200]}")
        if rg.status_code == 200:
            grp = rg.json()
            gid = grp.get("id")
            # Member joins
            rj = post(f"/groups/{gid}/join", {"user_id": member_id})
            record("member join -> 200", rj.status_code == 200, f"got {rj.status_code} body={rj.text[:200]}")
            # Reload enriched
            rget = get(f"/groups/{gid}")
            record("GET /groups/{id} -> 200", rget.status_code == 200)
            grp = rget.json()
            per_user = grp.get("per_user", [])
            # Each member: merchant_share=5 (10/2), transaction_fee at 5% = 0.25
            ok_all = len(per_user) == 2
            record("per_user has 2 entries", ok_all, f"got {len(per_user)}")
            for p in per_user:
                ms = p.get("merchant_share")
                tf = p.get("transaction_fee")
                expected = round(float(ms) * 0.05, 2)
                ok = abs(float(tf) - expected) < 0.011
                record(f"user {p.get('user_id')[-6:]}: tx_fee={tf} == 5% of merchant_share={ms} (expected {expected})", ok,
                       f"got tf={tf}, expected ~{expected}")

    # Restore transaction_fee_pct to 3.0
    payload3 = json.loads(json.dumps(payload2))
    payload3["core_fees"]["transaction_fee_pct"] = 3.0
    r = put("/admin/app-config", json_body=payload3, headers=admin_h)
    record("Restore transaction_fee_pct=3.0 -> 200", r.status_code == 200)

    # ============================================================
    # 3) Wallet provisioning admin gate
    # ============================================================
    section("3) Wallet provisioning admin gate")

    # Need a test group with a lead. Reuse lead_id/gid from above, or create one.
    # For status branches, we need: a group, a virtual_card to test the
    # gate path. The current code requires virtual_card.stripe_card_id to be
    # set before reaching the admin gate. If no card → status='card_not_issued'.
    # So testing the wallet gate (master/per-platform off) requires a group
    # WITH an issued virtual_card.
    #
    # We'll attempt the gate test with the gid above (no card) — which should
    # return 'card_not_issued'. Then we'll directly inject a virtual_card via
    # admin API... but there isn't one for that. Workaround: we'll use the DB
    # via direct manipulation? No — let's stick to API only and:
    #   a) Verify card_not_issued path (no virtual card on the group).
    #   b) Verify not_lead path (call with a non-lead user_id).
    #   c) Verify unsupported_platform (Pydantic rejection).
    #
    # The admin-gate-with-issued-card test requires injecting virtual_card.
    # The current backend has no admin route to forge a virtual_card directly,
    # so for the gate-toggle scenarios we will monkey-patch via DB if
    # available. Since this is a test environment, we'll use the requests
    # API exclusively — and if no card exists we'll note this branch as not
    # exercised end-to-end but verify the gate logic where possible.

    if lead_id and 'gid' in dir():
        # 3a) unsupported_platform → Pydantic rejection (422)
        r = post(f"/cards/{gid}/provision", {"user_id": lead_id, "platform": "banana"})
        record("unsupported_platform -> 422 from Pydantic", r.status_code == 422,
               f"got {r.status_code} body={r.text[:200]}")

        # 3b) not_lead → call with member_id
        r = post(f"/cards/{gid}/provision", {"user_id": member_id, "platform": "apple"})
        ok = r.status_code == 200 and r.json().get("status") == "not_lead"
        record("not_lead branch (member calls)", ok, f"got {r.status_code} body={r.text[:200]}")

        # 3c) card_not_issued (no virtual_card on group)
        r = post(f"/cards/{gid}/provision", {"user_id": lead_id, "platform": "apple"})
        ok = r.status_code == 200 and r.json().get("status") == "card_not_issued"
        record("card_not_issued branch (no virtual_card)", ok, f"got {r.status_code} body={r.text[:200]}")

    # 3d) For admin gate tests (master/per-platform toggles), we MUST inject a
    # virtual_card into the group document. Use a direct Mongo update via the
    # admin API if available, OR use motor directly (test env).
    section("3d) Wallet admin gate — inject virtual_card via motor")
    try:
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        client = AsyncIOMotorClient(mongo_url)
        # Detect DB name from backend/.env
        dbname = "test_database"
        be_env = Path("/app/backend/.env").read_text()
        m = re.search(r'DB_NAME="?([^"\n]+)"?', be_env)
        if m:
            dbname = m.group(1)
        db = client[dbname]

        async def set_vc():
            await db.groups.update_one(
                {"id": gid},
                {"$set": {"virtual_card": {"stripe_card_id": "ic_test_fakecard123", "last4": "4242"}}},
            )

        asyncio.get_event_loop().run_until_complete(set_vc())
        record("Inject virtual_card into group via motor", True)
    except Exception as e:
        record("Inject virtual_card into group via motor", False, str(e))
        return

    # Helper to set wallet config quickly
    def set_wallet(enabled, apple, google):
        p = json.loads(json.dumps(payload3))
        p["wallet"]["enabled"] = enabled
        p["wallet"]["apple_enabled"] = apple
        p["wallet"]["google_enabled"] = google
        rr = put("/admin/app-config", json_body=p, headers=admin_h)
        return rr.status_code == 200

    # 3e) wallet.enabled=false (default): pending_psp_approval
    record("set wallet.enabled=false", set_wallet(False, True, True))
    r = post(f"/cards/{gid}/provision", {"user_id": lead_id, "platform": "apple"})
    ok = r.status_code == 200 and r.json().get("ok") is True and r.json().get("status") == "pending_psp_approval"
    record("wallet OFF + apple => pending_psp_approval", ok, f"got {r.status_code} body={r.text[:200]}")

    # 3f) wallet.enabled=true, apple_enabled=true → still pending (stub branch)
    record("set wallet.enabled=true, apple=true", set_wallet(True, True, True))
    r = post(f"/cards/{gid}/provision", {"user_id": lead_id, "platform": "apple"})
    ok = r.status_code == 200 and r.json().get("status") == "pending_psp_approval"
    record("wallet ON + apple ON => pending_psp_approval (stub)", ok, f"got {r.status_code} body={r.text[:200]}")

    # 3g) wallet.enabled=true, apple_enabled=false → pending (per-platform off)
    record("set wallet.enabled=true, apple=false, google=true", set_wallet(True, False, True))
    r = post(f"/cards/{gid}/provision", {"user_id": lead_id, "platform": "apple"})
    ok = r.status_code == 200 and r.json().get("status") == "pending_psp_approval"
    record("wallet ON + apple OFF => pending_psp_approval", ok, f"got {r.status_code} body={r.text[:200]}")

    # 3h) wallet.enabled=true, google_enabled=false → pending (per-platform off)
    record("set wallet.enabled=true, apple=true, google=false", set_wallet(True, True, False))
    r = post(f"/cards/{gid}/provision", {"user_id": lead_id, "platform": "google"})
    ok = r.status_code == 200 and r.json().get("status") == "pending_psp_approval"
    record("wallet ON + google OFF => pending_psp_approval", ok, f"got {r.status_code} body={r.text[:200]}")

    # Restore wallet OFF
    record("set wallet.enabled=false at end", set_wallet(False, True, True))

    # ============================================================
    # 4) Legacy /api/admin/platform-fees still works
    # ============================================================
    section("4) Legacy /admin/platform-fees compatibility")
    r = get("/admin/platform-fees", headers=admin_h)
    ok = r.status_code == 200 and "fees" in r.json()
    record("GET /admin/platform-fees -> 200 with {fees: [...]}", ok, f"got {r.status_code} body={r.text[:200]}")
    if ok:
        fees = r.json()["fees"]
        record("GET legacy returns 2 extra-fee slots", len(fees) == 2, f"got {len(fees)} slots")

    # PUT legacy: change extra_1 to enabled flat $1
    legacy_payload = {
        "fees": [
            {"id": "extra_1", "name": "Test legacy fee", "type": "flat", "value": 1.0, "enabled": True},
            {"id": "extra_2", "name": "Extra Fee 2", "type": "flat", "value": 0.0, "enabled": False},
        ]
    }
    r = put("/admin/platform-fees", json_body=legacy_payload, headers=admin_h)
    record("PUT /admin/platform-fees -> 200", r.status_code == 200, f"got {r.status_code} body={r.text[:200]}")

    # GET new /admin/app-config reflects extra_fees update
    r = get("/admin/app-config", headers=admin_h)
    cfg3 = r.json() if r.status_code == 200 else {}
    extras = cfg3.get("extra_fees", [])
    extra_1 = next((e for e in extras if e.get("id") == "extra_1"), None)
    ok = bool(extra_1) and extra_1.get("enabled") is True and abs(extra_1.get("value", 0) - 1.0) < 1e-6
    record("New /admin/app-config reflects legacy PUT (extra_1 enabled=true value=1.0)", ok,
           f"got extra_1={extra_1}")

    # Restore legacy fees
    restore_payload = {
        "fees": [
            {"id": "extra_1", "name": "Extra Fee 1", "type": "flat", "value": 0.0, "enabled": False},
            {"id": "extra_2", "name": "Extra Fee 2", "type": "flat", "value": 0.0, "enabled": False},
        ]
    }
    r = put("/admin/platform-fees", json_body=restore_payload, headers=admin_h)
    record("Restore legacy fees", r.status_code == 200)

    # ============================================================
    # 5) Auth / RBAC
    # ============================================================
    section("5) Auth / RBAC")
    r = get("/admin/app-config")
    record("No auth header -> 401", r.status_code == 401, f"got {r.status_code}")
    r = put("/admin/app-config", json_body={})
    record("PUT no auth -> 401", r.status_code == 401, f"got {r.status_code}")

    # Try with a non-admin user token (use a regular user_id as Bearer — should be rejected)
    r = get("/admin/app-config", headers={"Authorization": f"Bearer not_a_real_admin_token_12345"})
    record("Non-admin token -> 401/403", r.status_code in (401, 403),
           f"got {r.status_code} body={r.text[:200]}")

    # ============================================================
    # FINAL RESTORE — set everything back to defaults
    # ============================================================
    section("FINAL: Restore defaults")
    final = json.loads(json.dumps(cfg3))
    final["core_fees"]["transaction_fee_pct"] = 3.0
    final["core_fees"]["platform_fee_flat"] = 0.03
    final["wallet"]["enabled"] = False
    final["wallet"]["apple_enabled"] = True
    final["wallet"]["google_enabled"] = True
    final["limits"]["min_members_per_bill"] = 2
    final["ops"]["maintenance_mode"] = False
    r = put("/admin/app-config", json_body=final, headers=admin_h)
    record("Restore defaults -> 200", r.status_code == 200, f"got {r.status_code}")

    rfin = get("/admin/app-config", headers=admin_h)
    cfin = rfin.json() if rfin.status_code == 200 else {}
    record("Final: transaction_fee_pct == 3.0",
           abs(cfin.get("core_fees", {}).get("transaction_fee_pct", 0) - 3.0) < 1e-6,
           f"got {cfin.get('core_fees', {}).get('transaction_fee_pct')}")
    record("Final: wallet.enabled == False", cfin.get("wallet", {}).get("enabled") is False)
    record("Final: min_members_per_bill == 2", cfin.get("limits", {}).get("min_members_per_bill") == 2)
    record("Final: maintenance_mode == False", cfin.get("ops", {}).get("maintenance_mode") is False)

    # Summary
    section("SUMMARY")
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"PASSED: {passed}/{total}")
    if failures:
        print(f"FAILURES ({len(failures)}):")
        for name, det in failures:
            print(f"  ❌ {name} — {det}")
    else:
        print("ALL GREEN ✅")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(2)
