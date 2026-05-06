"""
Phase H2 — Phone-already-registered confirmation + safe placeholder merge.

Tests the new POST /api/auth/verify-otp confirm_existing flow + GET /api/auth/lookup-phone.
Uses the live preview backend (EXPO_PUBLIC_BACKEND_URL).
"""
import os
import time
import random
import json
import sys
import requests
from pymongo import MongoClient

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"

PASS = 0
FAIL = 0
FAILS = []


def assert_eq(name, actual, expected):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  ✅ {name}: {actual}")
    else:
        FAIL += 1
        FAILS.append(f"{name}: expected {expected!r} got {actual!r}")
        print(f"  ❌ {name}: expected {expected!r} got {actual!r}")


def assert_true(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}{(' — ' + detail) if detail else ''}")
    else:
        FAIL += 1
        FAILS.append(f"{name}: {detail}")
        print(f"  ❌ {name}: {detail}")


def fresh_phone():
    return f"+1555{random.randint(100000, 999999)}"


def register(name, referral_code=None):
    body = {"name": name}
    if referral_code:
        body["referral_code"] = referral_code
    r = requests.post(f"{BASE}/auth/register", json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def send_otp(user_id, phone):
    r = requests.post(f"{BASE}/auth/send-otp", json={"user_id": user_id, "phone": phone}, timeout=30)
    r.raise_for_status()
    return r.json()


def verify_otp(user_id, phone, code="123456", confirm_existing=None):
    body = {"user_id": user_id, "phone": phone, "code": code}
    if confirm_existing is not None:
        body["confirm_existing"] = confirm_existing
    return requests.post(f"{BASE}/auth/verify-otp", json=body, timeout=30)


def main():
    ts = int(time.time())
    print(f"\n=== Phase H2 — phone-already-registered + safe merge — ts={ts} ===\n")
    print(f"BASE: {BASE}\n")

    # ─────────────────────────────────────────────
    # Step 1: Setup Bob (verified)
    # ─────────────────────────────────────────────
    print("STEP 1: Register + verify Bob.")
    bob_phone = fresh_phone()
    bob_reg = register(f"Bob{ts}")
    bob_id = bob_reg["id"]
    send_otp(bob_id, bob_phone)
    r = verify_otp(bob_id, bob_phone)
    assert_eq("Bob verify-otp status", r.status_code, 200)
    bob = r.json()
    assert_true("Bob.verified", bob.get("verified") is True)
    assert_eq("Bob.name", bob["name"], f"Bob{ts}")
    assert_eq("Bob.id stable", bob["id"], bob_id)
    print(f"  Bob id={bob_id} phone={bob_phone}\n")

    # ─────────────────────────────────────────────
    # Step 2-4: lookup-phone variants
    # ─────────────────────────────────────────────
    print("STEP 2: lookup-phone of Bob's phone (no exclude).")
    r = requests.get(f"{BASE}/auth/lookup-phone", params={"phone": bob_phone}, timeout=15)
    assert_eq("lookup status", r.status_code, 200)
    d = r.json()
    assert_eq("lookup exists", d.get("exists"), True)
    assert_eq("lookup name", d.get("name"), f"Bob{ts}")
    assert_eq("lookup blocked", d.get("blocked"), False)

    print("STEP 3: lookup-phone with exclude_user_id=Bob.id.")
    r = requests.get(
        f"{BASE}/auth/lookup-phone",
        params={"phone": bob_phone, "exclude_user_id": bob_id},
        timeout=15,
    )
    assert_eq("lookup self-excluded status", r.status_code, 200)
    d = r.json()
    assert_eq("lookup self-excluded exists", d.get("exists"), False)

    print("STEP 4: lookup-phone of unused number.")
    r = requests.get(f"{BASE}/auth/lookup-phone", params={"phone": "+19999999999"}, timeout=15)
    assert_eq("lookup unused status", r.status_code, 200)
    d = r.json()
    assert_eq("lookup unused exists", d.get("exists"), False)
    print()

    # ─────────────────────────────────────────────
    # Step 5-6: Setup Robert as a placeholder + create a group as a placeholder lead
    # ─────────────────────────────────────────────
    print("STEP 5: Register placeholder Robert.")
    robert_reg = register(f"Robert{ts}")
    robert_id = robert_reg["id"]
    print(f"  Robert id={robert_id} (placeholder)")
    assert_true("Robert is unverified", robert_reg.get("verified") is False)

    print("STEP 6: Insert a group with Robert as lead via direct Mongo seeding.")
    mongo = MongoClient(MONGO_URL)
    db = mongo[DB_NAME]
    group_id = f"g_h2_{ts}_{random.randint(1000, 9999)}"
    group_doc = {
        "id": group_id,
        "code": f"H2{ts % 100000:05d}",
        "title": "Robert's Lunch",
        "lead_id": robert_id,
        "members": [
            {"user_id": robert_id, "role": "lead", "joined_at": "2025-01-01T00:00:00Z"}
        ],
        "items": [],
        "assignments": [],
        "contributions": [],
        "repayments": [],
        "split_mode": "fast",
        "status": "open",
        "total_amount": 30.0,
        "tax": 0.0,
        "tip": 0.0,
        "created_at": "2025-01-01T00:00:00Z",
    }
    db.groups.insert_one(group_doc.copy())
    g = db.groups.find_one({"id": group_id}, {"_id": 0})
    assert_eq("seeded group lead_id", g.get("lead_id"), robert_id)
    assert_eq("seeded group members count", len(g.get("members", [])), 1)
    assert_eq("seeded group member user_id", g["members"][0]["user_id"], robert_id)
    print()

    # ─────────────────────────────────────────────
    # Step 7-8: Robert sends OTP to Bob's phone, then verify WITHOUT confirm_existing
    # ─────────────────────────────────────────────
    print("STEP 7: Robert send-otp to Bob's phone.")
    r = send_otp(robert_id, bob_phone)
    assert_true("send-otp ok", r.get("ok") is True)

    print("STEP 8: Robert verify-otp WITHOUT confirm_existing → expect 409.")
    r = verify_otp(robert_id, bob_phone, code="123456")
    assert_eq("verify-otp 409 status", r.status_code, 409)
    body = r.json()
    assert_eq("verify-otp 409 code", body.get("code"), "phone_already_registered")
    assert_eq("verify-otp 409 existing_name", body.get("existing_name"), f"Bob{ts}")
    assert_true(
        "verify-otp 409 message present",
        isinstance(body.get("message"), str) and len(body["message"]) > 0,
        detail=str(body.get("message"))[:80],
    )
    print()

    # Confirm Robert is still a placeholder, group still belongs to him
    rob = db.users.find_one({"id": robert_id}, {"_id": 0})
    assert_true("Robert NOT deleted yet (pre-confirm)", rob is not None)
    g = db.groups.find_one({"id": group_id}, {"_id": 0})
    assert_eq("group lead still Robert (pre-confirm)", g.get("lead_id"), robert_id)
    bob_check = db.users.find_one({"id": bob_id}, {"_id": 0})
    assert_eq("Bob.name unchanged after 409", bob_check.get("name"), f"Bob{ts}")
    print()

    # ─────────────────────────────────────────────
    # Step 9: Verify WITH confirm_existing=true → 200 (merge)
    # ─────────────────────────────────────────────
    print("STEP 9: Robert verify-otp WITH confirm_existing=true → expect 200.")
    r = verify_otp(robert_id, bob_phone, code="123456", confirm_existing=True)
    assert_eq("verify-otp 200 status", r.status_code, 200)
    out = r.json()
    assert_eq("merged user.id == Bob.id", out.get("id"), bob_id)
    assert_eq("merged user.name == Bob (name preserved)", out.get("name"), f"Bob{ts}")
    assert_eq("merged user.phone == Bob phone", out.get("phone"), bob_phone)
    assert_true("merged user.verified", out.get("verified") is True)
    print()

    # ─────────────────────────────────────────────
    # Step 10: Post-merge invariants
    # ─────────────────────────────────────────────
    print("STEP 10: Post-merge invariants via API.")
    r = requests.get(f"{BASE}/users/{robert_id}", timeout=15)
    assert_eq("GET Robert → 404 (placeholder deleted)", r.status_code, 404)

    r = requests.get(f"{BASE}/users/{bob_id}", timeout=15)
    assert_eq("GET Bob → 200", r.status_code, 200)
    bob_after = r.json()
    assert_eq("Bob.name STILL 'Bob' (NOT renamed to Robert)", bob_after["name"], f"Bob{ts}")

    r = requests.get(f"{BASE}/groups/{group_id}", timeout=15)
    assert_eq("GET group → 200", r.status_code, 200)
    g_after = r.json()
    assert_eq("group.lead_id == Bob.id", g_after.get("lead_id"), bob_id)
    members = g_after.get("members", [])
    assert_eq("group has 1 member", len(members), 1)
    if members:
        assert_eq("member.user_id == Bob.id", members[0].get("user_id"), bob_id)
        assert_eq("member.role == lead", members[0].get("role"), "lead")
    print()

    # Also re-verify directly in Mongo to be sure
    g_db = db.groups.find_one({"id": group_id}, {"_id": 0})
    assert_eq("DB: group.lead_id", g_db.get("lead_id"), bob_id)
    rob_db = db.users.find_one({"id": robert_id}, {"_id": 0})
    assert_true("DB: Robert deleted", rob_db is None)
    bob_db = db.users.find_one({"id": bob_id}, {"_id": 0})
    assert_eq("DB: Bob.name preserved", bob_db.get("name"), f"Bob{ts}")
    print()

    # ─────────────────────────────────────────────
    # Step 11: Regression — fresh placeholder + brand-new phone
    # ─────────────────────────────────────────────
    print("STEP 11: Regression — Charlie placeholder + fresh phone, NO confirm_existing.")
    charlie_phone = fresh_phone()
    charlie_reg = register(f"Charlie{ts}")
    charlie_id = charlie_reg["id"]
    send_otp(charlie_id, charlie_phone)
    r = verify_otp(charlie_id, charlie_phone, code="123456")
    assert_eq("Charlie verify-otp status (no 409)", r.status_code, 200)
    out = r.json()
    assert_eq("Charlie.id stable", out.get("id"), charlie_id)
    assert_eq("Charlie.name", out.get("name"), f"Charlie{ts}")
    assert_true("Charlie.verified", out.get("verified") is True)
    print()

    # ─────────────────────────────────────────────
    # Step 12: Regression spot — /users/{id}/groups + POST /groups
    # ─────────────────────────────────────────────
    print("STEP 12: Regression spot — /users/{id}/groups + POST /groups.")
    r = requests.get(f"{BASE}/users/{bob_id}/groups", timeout=15)
    assert_eq("GET Bob/groups status", r.status_code, 200)
    groups_list = r.json()
    assert_true(
        "Bob's groups includes the merged group",
        any(g.get("id") == group_id for g in (groups_list if isinstance(groups_list, list) else [])),
        detail=f"len={len(groups_list) if isinstance(groups_list, list) else 'NA'}",
    )

    new_group_payload = {
        "lead_id": charlie_id,
        "title": f"Charlie's Pizza {ts}",
        "items": [{"name": "Pizza", "price": 12.0, "quantity": 1}],
        "tax": 0.0,
        "tip": 0.0,
        "split_mode": "fast",
    }
    r = requests.post(f"{BASE}/groups", json=new_group_payload, timeout=30)
    assert_eq("POST /groups (Charlie) status", r.status_code, 200)
    if r.status_code == 200:
        new_g = r.json()
        assert_eq("new group lead_id", new_g.get("lead_id"), charlie_id)
    print()

    # Final
    print("=" * 60)
    print(f"TOTAL: {PASS} PASS, {FAIL} FAIL")
    if FAILS:
        print("\nFailures:")
        for f in FAILS:
            print("  -", f)
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
