"""
Phase O retest — only the two flagged bugs.
"""
import os
import time
import requests

# Load EXPO_PUBLIC_BACKEND_URL from /app/frontend/.env
BASE = None
with open("/app/frontend/.env") as f:
    for line in f:
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
            break
assert BASE, "EXPO_PUBLIC_BACKEND_URL missing"
API = BASE.rstrip("/") + "/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

print(f"BASE: {API}")

# ─── Admin login ───
r = requests.post(f"{API}/admin/auth/login",
                  json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                  timeout=30)
print(f"admin login → {r.status_code}")
assert r.status_code == 200, r.text
admin_token = r.json().get("token") or r.json().get("access_token")
H = {"Authorization": f"Bearer {admin_token}"}

results = {"bug1": None, "bug2": None}

# ────────────────────────────────────────────────────────────────
# BUG 1 — provision card_not_issued branch when virtual_card is None
# ────────────────────────────────────────────────────────────────
print("\n=== BUG 1: provision card_not_issued branch ===")
ts = int(time.time())
phone = f"+155555{ts % 100000:05d}"
name = f"PhaseORetest{ts}"

# Register lead
rr = requests.post(f"{API}/auth/register", json={"name": name}, timeout=30)
print(f"register → {rr.status_code}")
assert rr.status_code == 200, rr.text
lead_id = rr.json()["id"]

# Send OTP + verify
rr = requests.post(f"{API}/auth/send-otp",
                   json={"user_id": lead_id, "phone": phone}, timeout=30)
print(f"send-otp → {rr.status_code}")
assert rr.status_code == 200, rr.text

rr = requests.post(f"{API}/auth/verify-otp",
                   json={"user_id": lead_id, "phone": phone, "code": "123456"},
                   timeout=30)
print(f"verify-otp → {rr.status_code}")
assert rr.status_code == 200, rr.text
lead_id = rr.json()["id"]  # may have collapsed

# Create fast-split group with virtual_card=None at create-time
rr = requests.post(f"{API}/groups",
                   json={"lead_id": lead_id, "title": "Bug1 retest",
                         "total_amount": 20.0, "split_mode": "fast_split"},
                   timeout=30)
print(f"create group → {rr.status_code}")
assert rr.status_code == 200, rr.text
group = rr.json()
group_id = group["id"]
print(f"group virtual_card: {group.get('virtual_card')!r}")

# Call /cards/{group_id}/provision with platform=apple
rr = requests.post(
    f"{API}/cards/{group_id}/provision",
    json={"user_id": lead_id, "platform": "apple"},
    timeout=30,
)
print(f"provision → {rr.status_code}")
print(f"body: {rr.text[:400]}")
ok = (rr.status_code == 200)
body = rr.json() if rr.status_code == 200 else {}
status_val = body.get("status")
results["bug1_status"] = rr.status_code
results["bug1_body"] = body

# Expected: 200, status='card_not_issued', ok=False
if rr.status_code == 200 and status_val == "card_not_issued" and body.get("ok") is False:
    results["bug1"] = "PASS"
    print("✅ BUG 1 FIX VERIFIED — card_not_issued branch reached, no 500")
else:
    results["bug1"] = "FAIL"
    print(f"❌ BUG 1 STILL FAILING: status_code={rr.status_code}, status={status_val}, ok={body.get('ok')}")

# ────────────────────────────────────────────────────────────────
# BUG 2 — legacy PUT mirrors into extra_fees for new app-config
# ────────────────────────────────────────────────────────────────
print("\n=== BUG 2: legacy → new mirror ===")

put_payload = {
    "fees": [
        {"id": "extra_1", "name": "Mirror Test", "type": "flat", "value": 1.23, "enabled": True},
        {"id": "extra_2", "name": "Other", "type": "flat", "value": 0, "enabled": False},
    ]
}
rr = requests.put(f"{API}/admin/platform-fees", json=put_payload, headers=H, timeout=30)
print(f"PUT /admin/platform-fees → {rr.status_code}")
print(f"body: {rr.text[:300]}")
assert rr.status_code == 200, rr.text

# Now GET /admin/app-config
rr = requests.get(f"{API}/admin/app-config", headers=H, timeout=30)
print(f"GET /admin/app-config → {rr.status_code}")
assert rr.status_code == 200, rr.text
cfg = rr.json()
extras = cfg.get("extra_fees") or []
print(f"extra_fees: {extras}")
results["bug2_extras"] = extras

bug2_pass = (
    len(extras) >= 1
    and extras[0].get("name") == "Mirror Test"
    and abs(float(extras[0].get("value", 0)) - 1.23) < 1e-6
    and extras[0].get("enabled") is True
)
if bug2_pass:
    results["bug2"] = "PASS"
    print("✅ BUG 2 FIX VERIFIED — legacy PUT mirrors to extra_fees")
else:
    results["bug2"] = "FAIL"
    print(f"❌ BUG 2 STILL FAILING: extras[0]={extras[0] if extras else None}")

# ─── Cleanup: restore defaults (both disabled, value 0) ───
print("\n=== Cleanup ===")
restore_payload = {
    "fees": [
        {"id": "extra_1", "name": "Extra Fee 1", "type": "flat", "value": 0, "enabled": False},
        {"id": "extra_2", "name": "Extra Fee 2", "type": "flat", "value": 0, "enabled": False},
    ]
}
rr = requests.put(f"{API}/admin/platform-fees", json=restore_payload, headers=H, timeout=30)
print(f"restore extras → {rr.status_code}")
assert rr.status_code == 200, rr.text

# Verify restore in new endpoint too
rr = requests.get(f"{API}/admin/app-config", headers=H, timeout=30)
cfg = rr.json()
print(f"post-restore extra_fees: {cfg.get('extra_fees')}")

# ─── Summary ───
print("\n" + "=" * 60)
print("FINAL RESULTS")
print("=" * 60)
print(f"  BUG 1 (provision card_not_issued): {results['bug1']}")
print(f"  BUG 2 (legacy → new mirror):       {results['bug2']}")
