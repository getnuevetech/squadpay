"""Focused retest of the 4 previously failing F2.1 assertions after the
1-line fix in /app/backend/issuing_reveal.py stripe_issuing_webhook
(the body is now re-parsed as a plain dict after signature verification).

Re-validates ONLY:
  1. issuing_authorization.created signed webhook -> db.issuing_events row
     has correct card_id, amount, merchant, approved, raw_id (not None).
  2. issuing_transaction.created signed webhook with valid card_id ->
     group.virtual_card.transactions has new row (merchant + amount).
  3. group.virtual_card.spent += 3.00 after the transaction event.
  4. With card_disable_mode='auto' and spent>=spend_cap, the card is
     auto-disabled (status='inactive' on Stripe + DB).

Regression spot-check (signature flow):
  - No Stripe-Signature header -> 400.
  - Wrong signature -> 400.
"""
import os
import sys
import time
import json
import hmac
import hashlib
import requests
from pathlib import Path

import pymongo
import stripe  # noqa: F401


# ---------- Config ----------
def _backend_url() -> str:
    env_path = Path("/app/frontend/.env")
    base = None
    for line in env_path.read_text().splitlines():
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            base = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not base:
        raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not found in /app/frontend/.env")
    return base.rstrip("/") + "/api"


def _mongo():
    env_path = Path("/app/backend/.env")
    data = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    client = pymongo.MongoClient(data["MONGO_URL"])
    return client[data["DB_NAME"]]


BASE = _backend_url()
DB = _mongo()
print(f"[config] BASE = {BASE}")
print(f"[config] DB   = {DB.name}")

ADMIN_EMAIL = "[email protected]"
ADMIN_PASSWORD = "ChangeMe123!"

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name} :: {detail}")


def http(method, path, **kw):
    url = path if path.startswith("http") else BASE + path
    kw.setdefault("timeout", 60)
    return requests.request(method, url, **kw)


def admin_login() -> str:
    r = http("POST", "/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    r.raise_for_status()
    body = r.json()
    return body.get("token") or body.get("access_token")


def auth_hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def sign_stripe_payload(payload_bytes: bytes, secret: str, ts: int = None) -> str:
    ts = ts or int(time.time())
    signed = f"{ts}.".encode() + payload_bytes
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


def register_and_verify(name: str, phone: str) -> str:
    r = http("POST", "/auth/register", json={"name": name})
    r.raise_for_status()
    uid = r.json()["id"]
    http("POST", "/auth/send-otp", json={"user_id": uid, "phone": phone}).raise_for_status()
    http("POST", "/auth/verify-otp", json={"user_id": uid, "phone": phone, "code": "123456"}).raise_for_status()
    return uid


# ---------- Setup webhook secret ----------
def setup_webhook_secret(tok: str) -> str:
    secret = "whsec_test_phase_f21_v2"
    print("\n=== Setup: configure webhook_secret ===")
    r = http("POST", "/admin/integrations/issuing", headers=auth_hdr(tok),
             json={"webhook_secret": secret})
    print(f"[setup] POST /admin/integrations/issuing -> {r.status_code}")
    if r.status_code != 200:
        raise RuntimeError(f"Failed to set webhook_secret: {r.text}")
    # Confirm masked secret stored
    r = http("GET", "/admin/integrations/issuing", headers=auth_hdr(tok))
    body = r.json() if r.status_code == 200 else {}
    print(f"[setup] webhook_secret_masked={body.get('webhook_secret_masked')}")
    return secret


# ---------- Regression: signature flow ----------
def test_signature_regression(secret: str):
    print("\n=== Regression: signature verification ===")
    payload = {
        "id": "evt_retest_nosig",
        "type": "issuing_authorization.created",
        "data": {"object": {"id": "iauth_x", "card": {"id": "ic_fake"}, "amount": 100, "approved": True}},
    }
    body = json.dumps(payload).encode()
    # No signature -> 400
    r = http("POST", "/webhook/stripe/issuing", data=body,
             headers={"Content-Type": "application/json"})
    record("R1.no Stripe-Signature -> 400", r.status_code == 400,
           f"status={r.status_code} body={r.text[:120]}")
    # Wrong signature -> 400
    bad_sig = sign_stripe_payload(body, "whsec_bogus_not_the_secret")
    r = http("POST", "/webhook/stripe/issuing", data=body,
             headers={"Content-Type": "application/json", "Stripe-Signature": bad_sig})
    record("R2.wrong signature -> 400", r.status_code == 400,
           f"status={r.status_code} body={r.text[:120]}")


# ---------- Test 1: issuing_authorization.created fields populated ----------
def test_authorization_event(secret: str):
    print("\n=== TEST 1: issuing_authorization.created -> fields populated ===")
    ts = int(time.time())
    raw_id = f"iauth_retest_{ts}"
    auth_evt = {
        "id": f"evt_retest_auth_{ts}",
        "object": "event",
        "api_version": "2020-08-27",
        "created": ts,
        "type": "issuing_authorization.created",
        "data": {
            "object": {
                "id": raw_id,
                "object": "issuing.authorization",
                "amount": -1234,
                "approved": True,
                "card": {"id": "ic_test_for_auth_fields"},
                "merchant_data": {"name": "Bistro Retest", "category": "eating_places", "city": "Boston"},
            }
        },
    }
    body = json.dumps(auth_evt).encode()
    sig = sign_stripe_payload(body, secret)
    r = http("POST", "/webhook/stripe/issuing", data=body,
             headers={"Content-Type": "application/json", "Stripe-Signature": sig})
    print(f"[t1] webhook -> {r.status_code} body={r.text[:160]}")
    if r.status_code != 200:
        record("T1.webhook 200", False, f"status={r.status_code}")
        return
    record("T1.webhook 200", True, "")
    time.sleep(0.5)
    ev = DB.issuing_events.find_one({"raw_id": raw_id})
    if not ev:
        record("T1.issuing_events row exists with raw_id", False, "doc not found")
        return
    record("T1.raw_id stored (NOT None)", ev.get("raw_id") == raw_id, f"raw_id={ev.get('raw_id')}")
    record("T1.card_id correct (NOT None)",
           ev.get("card_id") == "ic_test_for_auth_fields",
           f"card_id={ev.get('card_id')}")
    record("T1.amount correct (NOT None)",
           ev.get("amount") == -1234, f"amount={ev.get('amount')}")
    record("T1.approved correct (NOT None)",
           ev.get("approved") is True, f"approved={ev.get('approved')}")
    md = ev.get("merchant") or {}
    record("T1.merchant captured (NOT None)",
           isinstance(md, dict) and md.get("name") == "Bistro Retest",
           f"merchant={md}")


# ---------- Tests 2,3,4: transaction.created flips card + spent + auto-disable ----------
def test_transaction_event(tok: str, secret: str):
    print("\n=== TEST 2/3/4: issuing_transaction.created -> txn row + spent + auto-disable ===")
    ts = int(time.time())

    # Set card_disable_mode=auto first
    r = http("POST", "/admin/integrations/issuing", headers=auth_hdr(tok),
             json={"card_disable_mode": "auto"})
    print(f"[setup] card_disable_mode=auto -> {r.status_code}")

    # Create a tiny fast-split group, fund via credit -> auto-issue real ic_ card
    lead_id = register_and_verify(f"F21Retest{ts}", f"+155547{ts % 100000:05d}")
    r = http("POST", "/groups", json={
        "lead_id": lead_id,
        "title": f"F21 Retest {ts}",
        "total_amount": 3.00,
        "split_mode": "fast",
        "tax": 0,
        "tip": 0,
        "items": [],
    })
    if r.status_code != 200:
        record("setup.create group", False, f"status={r.status_code} body={r.text[:200]}")
        return
    gid = r.json()["id"]
    print(f"[setup] gid={gid}")

    r = http("POST", f"/admin/users/{lead_id}/credits/grant", headers=auth_hdr(tok),
             json={"amount": 5.0, "note": "F21 retest"})
    if r.status_code != 200:
        record("setup.grant credit", False, f"status={r.status_code} body={r.text[:200]}")
        return

    r = http("POST", f"/groups/{gid}/contribute", json={"user_id": lead_id})
    if r.status_code != 200:
        record("setup.contribute", False, f"status={r.status_code} body={r.text[:200]}")
        return

    time.sleep(1.5)
    group = DB.groups.find_one({"id": gid})
    vc = (group or {}).get("virtual_card") or {}
    card_id = vc.get("stripe_card_id")
    if not card_id:
        record("setup.card auto-issued", False, f"vc={vc}")
        return
    record("setup.card auto-issued",
           True, f"card_id={card_id} status={vc.get('status')} spend_cap={vc.get('spend_cap')}")

    # Send signed issuing_transaction.created with amount=-300 ($3.00)
    txn_evt = {
        "id": f"evt_retest_txn_{ts}",
        "object": "event",
        "api_version": "2020-08-27",
        "created": int(time.time()),
        "type": "issuing_transaction.created",
        "data": {
            "object": {
                "id": f"ipi_retest_{ts}",
                "object": "issuing.transaction",
                "amount": -300,
                "currency": "usd",
                "card": card_id,
                "type": "capture",
                "merchant_data": {"name": "Cafe Retest", "category": "eating_places", "city": "Seattle"},
            }
        },
    }
    body = json.dumps(txn_evt).encode()
    sig = sign_stripe_payload(body, secret)
    r = http("POST", "/webhook/stripe/issuing", data=body,
             headers={"Content-Type": "application/json", "Stripe-Signature": sig})
    print(f"[t2] webhook -> {r.status_code} body={r.text[:200]}")
    record("T2.webhook 200", r.status_code == 200, f"status={r.status_code}")

    time.sleep(2.0)
    group = DB.groups.find_one({"id": gid})
    vc = (group or {}).get("virtual_card") or {}
    txns = vc.get("transactions") or []
    spent = float(vc.get("spent") or 0.0)

    # Test 2: virtual_card.transactions has new row with merchant + amount
    record("T2.transactions[] has >=1 row",
           len(txns) >= 1, f"txns_len={len(txns)}")
    if txns:
        last = txns[-1]
        record("T2.last txn amount = 3.00",
               abs(float(last.get("amount") or 0) - 3.00) < 0.01,
               f"amount={last.get('amount')}")
        m = last.get("merchant") or {}
        record("T2.last txn merchant captured",
               isinstance(m, dict) and m.get("name") == "Cafe Retest",
               f"merchant={m}")

    # Test 3: spent += 3.00
    record("T3.virtual_card.spent == 3.00",
           abs(spent - 3.00) < 0.01, f"spent={spent}")

    # Test 4: card auto-disabled (DB)
    record("T4.card auto-disabled in DB (status=inactive)",
           vc.get("status") == "inactive",
           f"status={vc.get('status')} disabled_by={vc.get('disabled_by')}")

    # Test 4 (Stripe): retrieve card from Stripe and confirm status
    try:
        sk = None
        for line in Path("/app/backend/.env").read_text().splitlines():
            if line.startswith("STRIPE_API_KEY="):
                sk = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
        if sk:
            stripe.api_key = sk
            card = stripe.issuing.Card.retrieve(card_id)
            record("T4.card auto-disabled on Stripe (status=inactive)",
                   getattr(card, "status", None) == "inactive",
                   f"stripe_status={getattr(card, 'status', None)}")
        else:
            record("T4.card auto-disabled on Stripe (status=inactive)", False, "no STRIPE_API_KEY")
    except Exception as e:
        record("T4.card auto-disabled on Stripe (status=inactive)", False, f"err={e}")


def main():
    tok = admin_login()
    print(f"[login] admin token len={len(tok)}")
    secret = setup_webhook_secret(tok)
    test_signature_regression(secret)
    test_authorization_event(secret)
    test_transaction_event(tok, secret)

    print("\n========== SUMMARY ==========")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    for name, ok, detail in RESULTS:
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {name}  ::  {detail}")
    print(f"\nTOTAL: {passed} pass / {failed} fail / {len(RESULTS)} total")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
