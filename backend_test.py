"""Batch B regression test — validates server.py refactor (routes/ + core.py)
maintains 100% behavior parity across all public API endpoints.

Covers A..G sections per review request (34 tests).
"""
import os
import time
import uuid
import requests

BASE = os.environ.get(
    "BACKEND_URL", "https://joint-pay-1.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE}/api"

ADMIN_EMAIL = "[email protected]"
ADMIN_PASSWORD = "ChangeMe123!"

TS = int(time.time())
results = []  # list of (ok, name, details)


def log(ok, name, details=""):
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f"  :: {details}" if details else ""))
    results.append((ok, name, details))


def req(method, path, **kw):
    url = f"{API}{path}" if path.startswith("/") else path
    r = requests.request(method, url, timeout=30, **kw)
    return r


def fresh_phone():
    # +1 555 followed by 7 digits from ts+uid
    u = uuid.uuid4().int % 10_000_000
    return f"+1555{TS%1000:03d}{u:07d}"[:12]


# ============================================================
# Helpers
# ============================================================
def register(name, referral_code=None):
    body = {"name": name}
    if referral_code:
        body["referral_code"] = referral_code
    return req("POST", "/auth/register", json=body)


def send_otp(user_id, phone):
    return req("POST", "/auth/send-otp", json={"user_id": user_id, "phone": phone})


def verify_otp(user_id, phone, code="123456"):
    return req(
        "POST", "/auth/verify-otp",
        json={"user_id": user_id, "phone": phone, "code": code},
    )


def full_signup(name, referral_code=None):
    r = register(name, referral_code=referral_code)
    assert r.status_code == 200, f"register {r.status_code}: {r.text}"
    user = r.json()
    ph = fresh_phone()
    r2 = send_otp(user["id"], ph)
    assert r2.status_code == 200, f"send-otp {r2.status_code}: {r2.text}"
    r3 = verify_otp(user["id"], ph, "123456")
    assert r3.status_code == 200, f"verify-otp {r3.status_code}: {r3.text}"
    verified = r3.json()
    verified["phone_used"] = ph
    return verified


# ============================================================
# ===== A) Auth =====
# ============================================================
print("\n== A) Auth ==")

# 1. register basic
r = register(f"Alice-{TS}")
ok = r.status_code == 200 and set(["id", "name", "referral_code"]).issubset(r.json().keys())
rc = r.json().get("referral_code") if ok else None
ok = ok and rc and len(rc) == 6 and rc.isupper()
log(ok, "A1 register {name} → 200 with 6-char uppercase referral_code",
    f"code={rc}" if ok else r.text)
alice = r.json() if ok else None

# 2. register invalid referral_code → 400
r = register(f"Bob-{TS}", referral_code="INVALID")
ok = r.status_code == 400 and "Invalid referral code" in r.text
log(ok, "A2 register bad referral_code → 400", f"{r.status_code}: {r.text[:120]}")

# 3. register with valid referral_code → 200 referred_by_user_id set
r = register(f"Cara-{TS}", referral_code=rc)
ok = r.status_code == 200 and r.json().get("referred_by_user_id") == alice["id"]
log(ok, "A3 register with valid ref code → 200 referred_by_user_id set",
    f"ref={r.json().get('referred_by_user_id')}" if r.status_code == 200 else r.text)

# 4. send-otp
lead_reg = register(f"Lead-{TS}")
assert lead_reg.status_code == 200, lead_reg.text
lead_placeholder_id = lead_reg.json()["id"]
lead_phone = fresh_phone()
r = send_otp(lead_placeholder_id, lead_phone)
ok = r.status_code == 200 and r.json().get("mocked") is True
log(ok, "A4 send-otp → 200 mocked=true", f"{r.status_code}: {r.json()}" if r.status_code == 200 else r.text)

# 5. verify-otp 123456
r = verify_otp(lead_placeholder_id, lead_phone, "123456")
ok = r.status_code == 200 and r.json().get("verified") is True
log(ok, "A5 verify-otp correct → 200 verified user",
    f"id={r.json().get('id')}" if r.status_code == 200 else r.text)
lead = r.json() if ok else None

# 6. verify-otp bad code → 400
m2 = register(f"Member2-{TS}")
m2_id = m2.json()["id"]
m2_phone = fresh_phone()
send_otp(m2_id, m2_phone)
r = verify_otp(m2_id, m2_phone, "000000")
ok = r.status_code == 400
log(ok, "A6 verify-otp bad code → 400", f"{r.status_code}: {r.text[:120]}")

# fix for future - actually verify m2 now
r = verify_otp(m2_id, m2_phone, "123456")
assert r.status_code == 200
member2 = r.json()

# 7. GET /users/{id}
r = req("GET", f"/users/{lead['id']}")
j = r.json() if r.status_code == 200 else {}
ok = r.status_code == 200 and set(["id", "name", "verified"]).issubset(j.keys())
log(ok, "A7 GET /users/{id} → 200 UserOut shape", f"{r.status_code}: {list(j.keys())[:8]}")


# ============================================================
# ===== B) Groups =====
# ============================================================
print("\n== B) Groups ==")

# 8. POST /groups  (itemized, with items + lead)
grp_body = {
    "lead_id": lead["id"],
    "title": "Dinner at Luigi's",
    "total_amount": 60.0,
    "split_mode": "itemized",
    "tax": 5.0,
    "tip": 7.0,
    "items": [
        {"name": "Pasta", "price": 18.0, "quantity": 2},
        {"name": "Salad", "price": 12.0, "quantity": 1},
    ],
}
r = req("POST", "/groups", json=grp_body)
ok = r.status_code == 200
g = r.json() if ok else {}
ok = ok and g.get("id") and g.get("code") and len(g.get("members", [])) == 1
log(ok, "B8 POST /groups → 200 with id, code, members[1]",
    f"id={g.get('id')} code={g.get('code')} members={len(g.get('members', []))}")
group_id = g.get("id")
group_code = g.get("code")

# 9. GET /groups/{id} enriched
r = req("GET", f"/groups/{group_id}")
j = r.json() if r.status_code == 200 else {}
ok = r.status_code == 200 and "per_user" in j and "derived_status" in j and "funding" in j
log(ok, "B9 GET /groups/{id} → 200 enriched",
    f"derived={j.get('derived_status')} keys={sorted(list(j.keys()))[:6]}")

# 10. GET /groups/by-code/{code}
r = req("GET", f"/groups/by-code/{group_code}")
ok = r.status_code == 200 and r.json().get("id") == group_id
log(ok, "B10 GET /groups/by-code/{code} → 200",
    f"{r.status_code}: id={r.json().get('id') if r.status_code == 200 else '?'}")

# 11. POST /groups/{id}/join — member2 joins
r = req("POST", f"/groups/{group_id}/join", json={"user_id": member2["id"]})
ok = r.status_code == 200 and len(r.json().get("members", [])) == 2
log(ok, "B11 POST /groups/{id}/join → 200, members grew",
    f"members={len(r.json().get('members', [])) if r.status_code == 200 else r.text[:120]}")

# 12. PATCH /groups/{id} (lead-only) title
r = req("PATCH", f"/groups/{group_id}", json={"user_id": lead["id"], "title": "New Title"})
ok = r.status_code == 200 and r.json().get("title") == "New Title"
log(ok, "B12 PATCH /groups/{id} (lead) → 200 title updated",
    f"title={r.json().get('title') if r.status_code == 200 else r.text[:120]}")

# 13. PATCH /groups/{id} (not lead) → 403
r = req("PATCH", f"/groups/{group_id}", json={"user_id": member2["id"], "title": "x"})
ok = r.status_code == 403
log(ok, "B13 PATCH /groups/{id} (not lead) → 403", f"{r.status_code}: {r.text[:120]}")

# 14. PUT /groups/{id}/items — replaces (no contributions)
new_items = [
    {"name": "Pizza", "price": 20.0, "quantity": 2},
    {"name": "Coke", "price": 5.0, "quantity": 2},
]
r = req("PUT", f"/groups/{group_id}/items", json={"items": new_items})
ok = r.status_code == 200 and len(r.json().get("items", [])) == 2
log(ok, "B14 PUT /groups/{id}/items → 200 (replaces)",
    f"items={len(r.json().get('items', [])) if r.status_code == 200 else r.text[:120]}")

# 15. POST /groups/{id}/items/append
r = req(
    "POST",
    f"/groups/{group_id}/items/append",
    json={"user_id": lead["id"], "items": [{"name": "Dessert", "price": 8.0, "quantity": 1}]},
)
ok = r.status_code == 200 and len(r.json().get("items", [])) == 3
log(ok, "B15 POST /groups/{id}/items/append → 200",
    f"items={len(r.json().get('items', [])) if r.status_code == 200 else r.text[:120]}")
# capture an item id
items_after = r.json().get("items", [])
target_item_id = items_after[0]["id"] if items_after else None

# 16. PATCH /groups/{id}/items/{item_id} quantity_delta=1
r = req(
    "PATCH",
    f"/groups/{group_id}/items/{target_item_id}",
    json={"user_id": lead["id"], "quantity_delta": 1},
)
ok = r.status_code == 200
log(ok, "B16 PATCH /groups/{id}/items/{item_id} quantity_delta=+1 → 200",
    f"{r.status_code}: {r.text[:120]}")

# 17. DELETE /groups/{id}/items/{item_id}
# Target the dessert we just appended to not disrupt
dessert_id = items_after[-1]["id"] if items_after else None
r = req("DELETE", f"/groups/{group_id}/items/{dessert_id}", params={"user_id": lead["id"]})
ok = r.status_code == 200 and all(it["id"] != dessert_id for it in r.json().get("items", []))
log(ok, "B17 DELETE /groups/{id}/items/{item_id} → 200",
    f"{r.status_code}, items_after={len(r.json().get('items', []))}" if r.status_code == 200 else r.text[:120])

# 18. POST /groups/{id}/assign
# Use first remaining item_id
remaining_items = r.json().get("items", []) if r.status_code == 200 else []
assign_item_id = remaining_items[0]["id"] if remaining_items else target_item_id
r = req(
    "POST",
    f"/groups/{group_id}/assign",
    json={"user_id": lead["id"], "item_id": assign_item_id, "quantity": 1},
)
ok = r.status_code == 200
log(ok, "B18 POST /groups/{id}/assign → 200", f"{r.status_code}: {r.text[:120]}")


# ============================================================
# ===== C) Contribute =====
# Create a fresh FAST-split group so contributions work predictably.
# ============================================================
print("\n== C) Contribute ==")

cgroup_body = {
    "lead_id": lead["id"],
    "title": "Brunch Fast Split",
    "total_amount": 60.0,
    "split_mode": "fast",
    "tax": 0.0,
    "tip": 0.0,
    "items": [],
}
r = req("POST", "/groups", json=cgroup_body)
assert r.status_code == 200, r.text
cgrp = r.json()
cgroup_id = cgrp["id"]
# member2 joins
r = req("POST", f"/groups/{cgroup_id}/join", json={"user_id": member2["id"]})
assert r.status_code == 200
# add a 3rd member for split
member3 = full_signup(f"Mem3-{TS}")
r = req("POST", f"/groups/{cgroup_id}/join", json={"user_id": member3["id"]})
assert r.status_code == 200
print(f"  (setup) fast-split group {cgroup_id} with lead + 2 members")

# 19. POST /contribute with origin_url → Stripe URL
r = req(
    "POST",
    f"/groups/{cgroup_id}/contribute",
    json={"user_id": member2["id"], "origin_url": "http://localhost:3000"},
)
j = r.json() if r.status_code == 200 else {}
ok = (
    r.status_code == 200
    and j.get("checkout_required") is True
    and isinstance(j.get("url"), str)
    and "stripe.com" in j["url"]
    and isinstance(j.get("session_id"), str)
    and j["session_id"].startswith("cs_test_")
)
log(ok, "C19 POST /contribute w/ origin_url → 200 checkout_required + Stripe URL",
    f"status={r.status_code} checkout={j.get('checkout_required')} url_ok={('stripe.com' in (j.get('url') or ''))} sid={(j.get('session_id') or '')[:16]}")
contrib_sid = j.get("session_id") if ok else None

# 20. POST /contribute credit_only path (need credits ≥ amount).
# Grant member3 admin credits covering their share.
# First login admin.
al = req("POST", "/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
assert al.status_code == 200, f"admin login failed: {al.text}"
admin_token = al.json().get("access_token") or al.json().get("token")
admin_headers = {"Authorization": f"Bearer {admin_token}"}

# figure out member3's remaining share
gstate = req("GET", f"/groups/{cgroup_id}").json()
mem3_per = next((p for p in gstate["per_user"] if p["user_id"] == member3["id"]), None)
share_needed = (mem3_per["total"] - mem3_per.get("contributed", 0)) if mem3_per else 25.0
grant_amount = round(share_needed + 5.0, 2)

gr = req(
    "POST",
    f"/admin/users/{member3['id']}/credits/grant",
    headers=admin_headers,
    json={"amount": grant_amount, "note": "batch-b regression test"},
)
if gr.status_code != 200:
    log(False, "C20 admin grant credit (setup) failed", f"{gr.status_code}: {gr.text[:160]}")
else:
    # contribute WITHOUT origin_url (credit-only branch)
    r = req(
        "POST",
        f"/groups/{cgroup_id}/contribute",
        json={"user_id": member3["id"]},
    )
    j = r.json() if r.status_code == 200 else {}
    ok = (
        r.status_code == 200
        and j.get("checkout_required") is False
        and j.get("credit_only") is True
    )
    log(ok, "C20 POST /contribute (no origin_url, credit ≥ share) → 200 credit_only=true",
        f"status={r.status_code} credit_applied={j.get('credit_applied')}")

# 21. GET /contribute/status/{session_id} — use the sid from step 19
if contrib_sid:
    r = req("GET", f"/contribute/status/{contrib_sid}")
    j = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and "applied" in j
    log(ok, "C21 GET /contribute/status/{sid} → 200 with applied flag",
        f"status={r.status_code} applied={j.get('applied')} payment_status={j.get('payment_status')}")
else:
    log(False, "C21 skipped — no contrib_sid from step 19", "")


# ============================================================
# ===== D) Pay / Repay =====
# Create a new fast-split group so we can test shortfall path deterministically.
# ============================================================
print("\n== D) Pay / Repay ==")

# Fresh fast group with lead + 2 members, total $60
payg = req(
    "POST", "/groups",
    json={
        "lead_id": lead["id"],
        "title": "Short Bill",
        "total_amount": 60.0,
        "split_mode": "fast",
        "items": [],
    },
).json()
pay_gid = payg["id"]
# add member2 and member3
req("POST", f"/groups/{pay_gid}/join", json={"user_id": member2["id"]})
# reuse member3 (new signup to avoid credit-balance issues)
member4 = full_signup(f"Mem4-{TS}")
req("POST", f"/groups/{pay_gid}/join", json={"user_id": member4["id"]})

# Grant lead enough credits to pay own share via credit_only path
gstate = req("GET", f"/groups/{pay_gid}").json()
lead_per = next((p for p in gstate["per_user"] if p["user_id"] == lead["id"]), None)
lead_share = lead_per["total"] if lead_per else 21.0
gr = req(
    "POST", f"/admin/users/{lead['id']}/credits/grant",
    headers=admin_headers, json={"amount": round(lead_share + 1.0, 2), "note": "pay test"},
)
assert gr.status_code == 200, gr.text
# lead pays own share (credit-only)
r = req("POST", f"/groups/{pay_gid}/contribute", json={"user_id": lead["id"]})
assert r.status_code == 200, r.text

# 22. POST /pay without mode when funds short → 400
r = req("POST", f"/groups/{pay_gid}/pay", json={"user_id": lead["id"]})
ok = r.status_code == 400 and ("short" in r.text.lower() or "shortfall" in r.text.lower())
log(ok, "D22 POST /pay when short (no mode) → 400 with shortfall message",
    f"{r.status_code}: {r.text[:160]}")

# 23. POST /pay with shortfall_mode=lead, is_loan=true → 200 paid
r = req(
    "POST", f"/groups/{pay_gid}/pay",
    json={"user_id": lead["id"], "shortfall_mode": "lead", "is_loan": True},
)
ok = r.status_code == 200 and r.json().get("status") == "paid"
log(ok, "D23 POST /pay shortfall_mode=lead is_loan=true → 200 group paid",
    f"{r.status_code}: status={r.json().get('status') if r.status_code == 200 else r.text[:160]}")

# 24. POST /repay — member repays some of their outstanding
gstate = req("GET", f"/groups/{pay_gid}").json()
m2_per = next((p for p in gstate["per_user"] if p["user_id"] == member2["id"]), None)
outst = m2_per.get("outstanding", 0) if m2_per else 0
if outst > 0.01:
    pay_amt = round(outst / 2.0, 2)
    r = req(
        "POST", f"/groups/{pay_gid}/repay",
        json={"user_id": member2["id"], "amount": pay_amt},
    )
    ok = r.status_code == 200
    # check outstanding decreased
    new_m2 = next((p for p in r.json().get("per_user", []) if p["user_id"] == member2["id"]), None)
    new_out = new_m2.get("outstanding", 0) if new_m2 else None
    ok = ok and new_out is not None and new_out < outst
    log(ok, "D24 POST /repay → 200 outstanding decreased",
        f"{r.status_code} before={outst} after={new_out}")
else:
    log(False, "D24 setup — member2 has no outstanding; can't exercise repay",
        f"outstanding={outst}")

# 25. GET /users/{id}/groups
r = req("GET", f"/users/{lead['id']}/groups")
j = r.json() if r.status_code == 200 else []
ok = (
    r.status_code == 200
    and isinstance(j, list)
    and len(j) >= 1
    and all("status" in row and "derived_status" in row for row in j)
)
log(ok, "D25 GET /users/{id}/groups → 200 array with status + derived_status",
    f"count={len(j) if isinstance(j, list) else '?'}")


# ============================================================
# ===== E) Referrals + Credits (misc_routes) =====
# ============================================================
print("\n== E) Referrals + Credits ==")

# 26. GET /users/{id}/referrals
r = req("GET", f"/users/{alice['id']}/referrals")
j = r.json() if r.status_code == 200 else {}
ok = (
    r.status_code == 200
    and j.get("referral_code") == alice["referral_code"]
    and "referees" in j
    and "settings" in j
)
log(ok, "E26 GET /users/{id}/referrals → 200 with code/referees/settings",
    f"{r.status_code}: code={j.get('referral_code')} referees_count={j.get('referees_count')}")

# 27. GET /referrals/lookup/{code}
r = req("GET", f"/referrals/lookup/{alice['referral_code']}")
j = r.json() if r.status_code == 200 else {}
ok = (
    r.status_code == 200
    and j.get("referrer_name") == alice["name"]
    and j.get("referrer_code") == alice["referral_code"]
)
log(ok, "E27 GET /referrals/lookup/{code} → 200 with referrer_name",
    f"{r.status_code}: {j}")

# 28. GET /referrals/lookup/INVALIDX → 404
r = req("GET", "/referrals/lookup/ZZZZZZ99")
ok = r.status_code == 404
log(ok, "E28 GET /referrals/lookup/INVALID → 404", f"{r.status_code}: {r.text[:120]}")

# 29. GET /users/{id}/credits
r = req("GET", f"/users/{lead['id']}/credits")
j = r.json() if r.status_code == 200 else {}
ok = (
    r.status_code == 200
    and "balance" in j
    and isinstance(j.get("items"), list)
)
log(ok, "E29 GET /users/{id}/credits → 200 balance + items[]",
    f"{r.status_code}: balance={j.get('balance')} items={len(j.get('items', []))}")


# ============================================================
# ===== F) Misc =====
# ============================================================
print("\n== F) Misc ==")

# 30. GET /
r = req("GET", "/")
ok = r.status_code == 200 and r.json() == {"message": "GroupPay API", "ok": True}
log(ok, "F30 GET /api/ → 200 GroupPay API", f"{r.status_code}: {r.text[:120]}")

# 31. GET /app-features
r = req("GET", "/app-features")
j = r.json() if r.status_code == 200 else {}
ok = r.status_code == 200 and "credits_enabled" in j and "invite_friends_enabled" in j
log(ok, "F31 GET /api/app-features → 200 with expected flags",
    f"{r.status_code}: {j}")

# 32. GET /checkout/native-bridge
r = req(
    "GET", "/checkout/native-bridge",
    params={"session_id": "cs_test_FAKE123", "dest": "exp://localhost:19000/--/pay"},
)
ok = r.status_code == 200 and "html" in r.headers.get("content-type", "").lower() and "kwikpay" in r.text.lower()
log(ok, "F32 GET /api/checkout/native-bridge → 200 HTML",
    f"{r.status_code} ct={r.headers.get('content-type')}")


# ============================================================
# ===== G) Admin =====
# ============================================================
print("\n== G) Admin ==")

# 33. Admin login already done above; verify returned token
ok = bool(admin_token)
log(ok, "G33 POST /admin/auth/login → 200 with token",
    f"token_present={bool(admin_token)}")

# 34. GET /admin/metrics
r = req("GET", "/admin/metrics", headers=admin_headers)
j = r.json() if r.status_code == 200 else {}
ok = r.status_code == 200 and isinstance(j, dict) and len(j) > 0
log(ok, "G34 GET /admin/metrics → 200",
    f"{r.status_code}: keys={sorted(list(j.keys()))[:8]}")

# 35. GET /admin/integrations
r = req("GET", "/admin/integrations", headers=admin_headers)
j = r.json() if r.status_code == 200 else {}
keys = set(j.keys()) if isinstance(j, dict) else set()
ok = r.status_code == 200 and {"stripe", "twilio"}.issubset(keys)
# signalwire & sms_routing may not exist in this build; accept if at least stripe+twilio
log(ok, "G35 GET /admin/integrations → 200 with stripe/twilio",
    f"{r.status_code}: keys={sorted(keys)}")


# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 60)
passed = sum(1 for ok, _, _ in results if ok)
failed = [r for r in results if not r[0]]
print(f"PASSED: {passed}/{len(results)}")
print(f"FAILED: {len(failed)}")
if failed:
    print("\nFAILURES:")
    for ok, name, details in failed:
        print(f"  ✗ {name}")
        if details:
            print(f"      {details[:240]}")

import sys as _sys
_sys.exit(0 if not failed else 1)
