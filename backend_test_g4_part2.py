"""Phase G4 — Part 2: seed a virtual_card directly in Mongo to unlock
scenarios 7 (non-lead 403) and 9 (OTP-gate 401). These require a card
to be present on the group, else the code hits 400 'no issued card'
first."""
import os
import sys
import time
import json
import requests
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "[email protected]"
ADMIN_PASSWORD = "ChangeMe123!"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

PASS = 0
FAIL = 0
FAILS = []


def log(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        FAILS.append((label, detail))
        print(f"  ❌ {label}  →  {detail}")


def main():
    print(f"BASE = {BASE}")
    print(f"MONGO = {MONGO_URL}  DB = {DB_NAME}")

    # Login admin
    r = requests.post(f"{BASE}/admin/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    token = r.json().get("token") or r.json().get("access_token")
    A = {"Authorization": f"Bearer {token}"}

    # Enable apple + google
    requests.post(f"{BASE}/admin/integrations/issuing",
                  json={"apple_pay_enrolled": True, "google_pay_enrolled": True},
                  headers=A, timeout=30)

    # Register a lead and verify
    ts = int(time.time())
    u1 = requests.post(f"{BASE}/auth/register", json={"name": f"LeadG4 {ts}"}, timeout=30).json()
    phone1 = f"+1558{ts%10000000:07d}"
    requests.post(f"{BASE}/auth/send-otp", json={"user_id": u1["id"], "phone": phone1}, timeout=30)
    vr = requests.post(f"{BASE}/auth/verify-otp",
                       json={"user_id": u1["id"], "phone": phone1, "code": "123456"},
                       timeout=30).json()
    lead_id = vr.get("id") or u1["id"]
    print(f"lead_id = {lead_id}")

    # Register a 2nd user (non-lead) and verify
    u2 = requests.post(f"{BASE}/auth/register", json={"name": f"NonLeadG4 {ts}"}, timeout=30).json()
    phone2 = f"+1559{(ts+1)%10000000:07d}"
    requests.post(f"{BASE}/auth/send-otp", json={"user_id": u2["id"], "phone": phone2}, timeout=30)
    vr2 = requests.post(f"{BASE}/auth/verify-otp",
                        json={"user_id": u2["id"], "phone": phone2, "code": "123456"},
                        timeout=30).json()
    nonlead_id = vr2.get("id") or u2["id"]
    print(f"nonlead_id = {nonlead_id}")

    # Create group
    g = requests.post(f"{BASE}/groups", json={
        "lead_id": lead_id, "title": f"G4-Card {ts}", "total_amount": 25.0,
    }, timeout=30).json()
    gid = g["id"]
    print(f"group_id = {gid}")

    # Have nonlead join
    r = requests.post(f"{BASE}/groups/{gid}/join", json={"user_id": nonlead_id}, timeout=30)
    print(f"nonlead join status: {r.status_code}")

    # DIRECT DB — seed a fake virtual_card on the group
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    fake_card = {
        "stripe_card_id": f"ic_FAKE_g4_{ts}",
        "cardholder_id": "ich_test",
        "nickname": f"SquadPay - G4-Test",
        "status": "active",
        "last4": "4242",
        "brand": "Visa",
        "exp_month": 12,
        "exp_year": 2030,
        "spend_cap": 2500,
        "spent": 0,
    }
    db.groups.update_one({"id": gid}, {"$set": {"virtual_card": fake_card}})
    # Verify
    g_after = db.groups.find_one({"id": gid}, {"_id": 0, "virtual_card": 1})
    log("seeded virtual_card in Mongo", bool(g_after and g_after.get("virtual_card", {}).get("stripe_card_id")),
        f"got {g_after}")

    # ---------- Scenario 7 (real) ----------
    print("\n=== 7 (real) Non-lead with seeded card → 403 ===")
    r = requests.post(f"{BASE}/groups/{gid}/card/push-provisioning/apple",
                      json={"user_id": nonlead_id}, timeout=30)
    detail = ""
    try:
        detail = str(r.json().get("detail") or "")
    except Exception:
        pass
    log("7.non-lead status==403", r.status_code == 403,
        f"status={r.status_code} body={r.text[:300]}")
    log("7.non-lead detail 'Only the group lead'",
        "only the group lead" in detail.lower(),
        f"detail={detail[:200]}")

    # ---------- Scenario 9 (real) ----------
    print("\n=== 9 (real) Lead without reveal_token → 401 ===")
    r = requests.post(f"{BASE}/groups/{gid}/card/push-provisioning/apple",
                      json={"user_id": lead_id}, timeout=30)
    detail = ""
    try:
        detail = str(r.json().get("detail") or "")
    except Exception:
        pass
    log("9.OTP gate status==401", r.status_code == 401,
        f"status={r.status_code} body={r.text[:300]}")
    log("9.OTP gate detail 'reveal_token required'",
        "reveal_token required" in detail.lower(),
        f"detail={detail[:200]}")

    # ---------- Scenario 8 (real) — validation 400s ----------
    print("\n=== 8 (real) Validation 400s — nonce/certificates ===")
    # Get reveal_token
    requests.post(f"{BASE}/auth/sensitive/send-otp", json={"user_id": lead_id}, timeout=30)
    vr = requests.post(f"{BASE}/auth/sensitive/verify-otp",
                       json={"user_id": lead_id, "code": "123456", "purpose": "card_reveal"},
                       timeout=30).json()
    rtok = vr.get("reveal_token")

    # 8a) No nonce, no certificates
    r = requests.post(f"{BASE}/groups/{gid}/card/push-provisioning/apple",
                      json={"user_id": lead_id, "reveal_token": rtok}, timeout=30)
    detail = ""
    try:
        detail = str(r.json().get("detail") or "")
    except Exception:
        pass
    log("8a.apple no-nonce status==400", r.status_code == 400,
        f"status={r.status_code} body={r.text[:300]}")
    log("8a.apple detail mentions 'nonce'", "nonce" in detail.lower(),
        f"detail={detail[:200]}")

    # 8b) Nonce but no certificates (need fresh token)
    requests.post(f"{BASE}/auth/sensitive/send-otp", json={"user_id": lead_id}, timeout=30)
    vr = requests.post(f"{BASE}/auth/sensitive/verify-otp",
                       json={"user_id": lead_id, "code": "123456", "purpose": "card_reveal"},
                       timeout=30).json()
    rtok2 = vr.get("reveal_token")
    r = requests.post(f"{BASE}/groups/{gid}/card/push-provisioning/apple",
                      json={"user_id": lead_id, "reveal_token": rtok2,
                            "nonce": "nonce_test_value_12345"},
                      timeout=30)
    detail = ""
    try:
        detail = str(r.json().get("detail") or "")
    except Exception:
        pass
    log("8b.apple nonce-no-cert status==400", r.status_code == 400,
        f"status={r.status_code} body={r.text[:300]}")
    log("8b.apple detail mentions 'certificates'", "certificates" in detail.lower(),
        f"detail={detail[:200]}")

    # google validation too
    print("\n=== 8 (real) Validation 400s — google wallet_account_id ===")
    requests.post(f"{BASE}/auth/sensitive/send-otp", json={"user_id": lead_id}, timeout=30)
    vr = requests.post(f"{BASE}/auth/sensitive/verify-otp",
                       json={"user_id": lead_id, "code": "123456", "purpose": "card_reveal"},
                       timeout=30).json()
    rtok3 = vr.get("reveal_token")
    r = requests.post(f"{BASE}/groups/{gid}/card/push-provisioning/google",
                      json={"user_id": lead_id, "reveal_token": rtok3}, timeout=30)
    detail = ""
    try:
        detail = str(r.json().get("detail") or "")
    except Exception:
        pass
    log("8c.google no-wallet status==400", r.status_code == 400,
        f"status={r.status_code} body={r.text[:300]}")
    log("8c.google detail mentions 'wallet_account_id'",
        "wallet_account_id" in detail.lower(), f"detail={detail[:200]}")

    # RESET
    requests.post(f"{BASE}/admin/integrations/issuing",
                  json={"apple_pay_enrolled": False, "google_pay_enrolled": False},
                  headers=A, timeout=30)

    # Cleanup seeded card - remove the group (optional, but keep group for history; just unset card)
    db.groups.update_one({"id": gid}, {"$unset": {"virtual_card": ""}})

    print("\n" + "=" * 60)
    print(f"PART 2 TOTAL PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("\nFAILURES:")
        for lbl, det in FAILS:
            print(f"  ❌ {lbl}\n     {det}")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
