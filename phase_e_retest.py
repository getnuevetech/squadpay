"""Phase E status endpoint retest after fix."""
import os
import sys
import time
import requests

BASE = os.environ.get("BACKEND_URL", "https://joint-pay-1.preview.emergentagent.com") + "/api"

ts = int(time.time())
results = []

def log(name, ok, info=""):
    results.append((name, ok, info))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name} :: {info}")

def post(path, **kwargs):
    return requests.post(BASE + path, timeout=30, **kwargs)
def get(path, **kwargs):
    return requests.get(BASE + path, timeout=30, **kwargs)

# 1. Register fresh user
name = f"RetestE{ts}"
phone = f"+1555200{ts % 10000:04d}"
r = post("/auth/register", json={"name": name})
assert r.status_code == 200, r.text
uid = r.json()["id"]
print("user:", uid, name, phone)

# Send + verify OTP
r = post("/auth/send-otp", json={"user_id": uid, "phone": phone})
assert r.status_code == 200, r.text
r = post("/auth/verify-otp", json={"user_id": uid, "phone": phone, "code": "123456"})
assert r.status_code == 200, r.text
uid = r.json()["id"]  # may collapse

# 2. Create fast-split group total $12.34, 1 item @ $12.34
r = post("/groups", json={
    "lead_id": uid,
    "title": f"E-Retest {ts}",
    "total_amount": 12.34,
    "split_type": "equal",
    "items": [{"name": "TestItem", "price": 12.34, "quantity": 1}],
})
assert r.status_code == 200, r.text
group = r.json()
gid = group["id"]
print("group:", gid, "total:", group.get("total_amount"))

# 3. POST checkout-session
r = post(f"/groups/{gid}/checkout-session", json={"origin_url": "http://localhost:3000"})
assert r.status_code == 200, f"checkout-session: {r.status_code} {r.text}"
sj = r.json()
session_id = sj["session_id"]
print("session_id:", session_id, "url:", sj.get("url")[:60])
assert session_id.startswith("cs_test_"), session_id

# A) GET status — expect 200, not 502
r = get(f"/checkout/status/{session_id}")
log("A.status_200", r.status_code == 200, f"code={r.status_code} body={r.text[:300]}")
if r.status_code == 200:
    body = r.json()
    expected_keys = {"session_id", "status", "payment_status", "amount_total", "currency", "applied", "group_id"}
    log("A.shape", expected_keys.issubset(body.keys()), f"keys={sorted(body.keys())}")
    log("A.session_id_match", body.get("session_id") == session_id, f"got={body.get('session_id')}")
    log("A.status_open_or_complete", body.get("status") in ("open", "complete"), f"status={body.get('status')}")
    log("A.payment_status_unpaid", body.get("payment_status") == "unpaid", f"payment_status={body.get('payment_status')}")
    log("A.amount_total_1234", body.get("amount_total") == 1234, f"amount_total={body.get('amount_total')}")
    log("A.currency_usd", body.get("currency") == "usd", f"currency={body.get('currency')}")
    log("A.applied_false", body.get("applied") is False, f"applied={body.get('applied')}")
    log("A.group_id_match", body.get("group_id") == gid, f"group_id={body.get('group_id')}")

# B) Idempotency — poll twice
r2 = get(f"/checkout/status/{session_id}")
log("B.poll2_200", r2.status_code == 200, f"code={r2.status_code} body={r2.text[:200]}")
if r2.status_code == 200:
    b2 = r2.json()
    log("B.poll2_applied_false", b2.get("applied") is False, f"applied={b2.get('applied')}")
    log("B.poll2_same_session", b2.get("session_id") == session_id, "")
    log("B.poll2_amount_1234", b2.get("amount_total") == 1234, f"amount_total={b2.get('amount_total')}")

# C) Spot-check non-status assertions
# C1: bad origin_url → 400
r = post(f"/groups/{gid}/checkout-session", json={"origin_url": "localhost:3000"})
log("C1.bad_origin_400", r.status_code == 400, f"code={r.status_code} body={r.text[:200]}")

# C2: GET status with non-existent session → 404
r = get("/checkout/status/cs_test_DOES_NOT_EXIST")
log("C2.bad_session_404", r.status_code == 404, f"code={r.status_code} body={r.text[:200]}")

# Summary
print("\n=== SUMMARY ===")
fails = [r for r in results if not r[1]]
print(f"PASS: {len(results) - len(fails)} / {len(results)}")
if fails:
    print("FAILURES:")
    for n, _, info in fails:
        print(f"  - {n}: {info}")
    sys.exit(1)
print("ALL PASS")
