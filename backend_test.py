"""Phase F2.1 + Feature Toggles backend test.

Covers:
  1. GET /api/app-features — public
  2. GET/POST /api/admin/features (super_admin)
  3. POST /api/admin/integrations/issuing with webhook_secret
     (masked response, encrypted persistence, no raw blob in response)
  4. POST /api/webhook/stripe/issuing — signature verification +
     issuing_authorization.created + issuing_transaction.created
  5. Regression: sensitive OTP, ephemeral-key auth chain, disable-card,
     old issuing fields round-trip

Base URL is read from /app/frontend/.env: EXPO_PUBLIC_BACKEND_URL + '/api'.
"""
import os
import re
import sys
import time
import json
import hmac
import hashlib
import requests
from pathlib import Path

import pymongo
import stripe


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


# ---------- Stripe signature helper ----------
def sign_stripe_payload(payload_bytes: bytes, secret: str, ts: int = None) -> str:
    ts = ts or int(time.time())
    signed_payload = f"{ts}.".encode() + payload_bytes
    v1 = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


# ========================================================================
# TEST 1 — Feature toggles
# ========================================================================
def test_feature_toggles(tok: str):
    print("\n=== TEST 1: Feature toggles ===")

    # Clean slate — set both to true
    r = http("POST", "/admin/features", headers=auth_hdr(tok),
             json={"credits_enabled": True, "invite_friends_enabled": True})
    record("1.setup reset features -> 200", r.status_code == 200, f"status={r.status_code}")

    # Public endpoint
    r = http("GET", "/app-features")
    body = r.json() if r.status_code == 200 else {}
    record("1a.GET /app-features -> 200", r.status_code == 200, f"status={r.status_code}")
    record("1a.public has credits_enabled=true", body.get("credits_enabled") is True, f"body={body}")
    record("1a.public has invite_friends_enabled=true",
           body.get("invite_friends_enabled") is True, f"body={body}")

    # Admin GET
    r = http("GET", "/admin/features", headers=auth_hdr(tok))
    body = r.json() if r.status_code == 200 else {}
    record("1b.admin GET /admin/features -> 200", r.status_code == 200, f"status={r.status_code}")
    record("1b.admin reports credits_enabled=true", body.get("credits_enabled") is True, f"body={body}")
    record("1b.admin reports invite_friends_enabled=true",
           body.get("invite_friends_enabled") is True, f"body={body}")

    # No auth -> 401
    r = http("GET", "/admin/features")
    record("1c.admin GET no-auth -> 401", r.status_code == 401, f"status={r.status_code}")

    # Disable credits
    r = http("POST", "/admin/features", headers=auth_hdr(tok),
             json={"credits_enabled": False})
    record("1d.POST credits_enabled=false -> 200", r.status_code == 200, f"status={r.status_code}")
    r = http("GET", "/admin/features", headers=auth_hdr(tok))
    b = r.json()
    record("1d.admin GET reflects credits_enabled=false",
           b.get("credits_enabled") is False and b.get("invite_friends_enabled") is True,
           f"body={b}")
    r = http("GET", "/app-features")
    b = r.json()
    record("1d.public reflects credits_enabled=false",
           b.get("credits_enabled") is False and b.get("invite_friends_enabled") is True,
           f"body={b}")

    # Disable invite_friends
    r = http("POST", "/admin/features", headers=auth_hdr(tok),
             json={"invite_friends_enabled": False})
    record("1e.POST invite_friends_enabled=false -> 200", r.status_code == 200, f"status={r.status_code}")
    r = http("GET", "/app-features")
    b = r.json()
    record("1e.public reflects both=false",
           b.get("credits_enabled") is False and b.get("invite_friends_enabled") is False,
           f"body={b}")

    # Reset both to true (cleanup)
    r = http("POST", "/admin/features", headers=auth_hdr(tok),
             json={"credits_enabled": True, "invite_friends_enabled": True})
    record("1f.cleanup reset to both=true -> 200", r.status_code == 200, f"status={r.status_code}")
    r = http("GET", "/app-features")
    b = r.json()
    record("1f.public both true after reset",
           b.get("credits_enabled") is True and b.get("invite_friends_enabled") is True,
           f"body={b}")


# ========================================================================
# TEST 2 — Issuing webhook_secret persistence
# ========================================================================
def test_issuing_webhook_secret(tok: str):
    print("\n=== TEST 2: Issuing webhook_secret ===")
    secret = f"whsec_test_phase_f21_{int(time.time())}"

    r = http("POST", "/admin/integrations/issuing", headers=auth_hdr(tok),
             json={"webhook_secret": secret})
    record("2a.POST webhook_secret -> 200", r.status_code == 200, f"status={r.status_code}")
    body = r.json()
    # Masked present, enc absent
    mask = body.get("webhook_secret_masked")
    record("2a.response has webhook_secret_masked",
           isinstance(mask, str) and len(mask) > 0 and mask.endswith(secret[-4:]),
           f"masked={mask}")
    record("2a.response DOES NOT include webhook_secret_enc",
           "webhook_secret_enc" not in body, f"keys={list(body.keys())}")
    record("2a.response DOES NOT include raw webhook_secret",
           body.get("webhook_secret") is None and secret not in json.dumps(body),
           f"body keys={list(body.keys())}")

    # Re-GET confirms masked value persisted
    r = http("GET", "/admin/integrations/issuing", headers=auth_hdr(tok))
    body2 = r.json()
    record("2b.GET reflects masked secret", body2.get("webhook_secret_masked") == mask,
           f"masked_get={body2.get('webhook_secret_masked')} expected={mask}")
    record("2b.GET does not expose webhook_secret_enc",
           "webhook_secret_enc" not in body2,
           f"keys={list(body2.keys())}")

    # Inspect DB record
    rec = DB.app_settings.find_one({"key": "integrations"})
    iss = (rec or {}).get("issuing", {})
    enc = iss.get("webhook_secret_enc")
    record("2c.DB app_settings.integrations.issuing.webhook_secret_enc present",
           isinstance(enc, str) and len(enc) > 10, f"enc_len={len(enc or '')}")
    record("2c.DB enc is NOT plaintext",
           enc != secret and secret not in (enc or ""), f"enc_prefix={(enc or '')[:10]}…")

    # Decrypt it via admin module — note: Fernet key is derived from backend's
    # JWT_SECRET env var. We load backend/.env to prove round-trip works.
    try:
        backend_env = {}
        for line in Path("/app/backend/.env").read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                backend_env[k.strip()] = v.strip().strip('"').strip("'")
        if backend_env.get("JWT_SECRET"):
            os.environ["JWT_SECRET"] = backend_env["JWT_SECRET"]
        if backend_env.get("SECRETS_KEY"):
            os.environ["SECRETS_KEY"] = backend_env["SECRETS_KEY"]
        sys.path.insert(0, "/app/backend")
        # Clear cached module if it was already imported with wrong env
        for mod in ("admin",):
            if mod in sys.modules:
                del sys.modules[mod]
        from admin import decrypt_secret  # type: ignore
        decrypted = decrypt_secret(enc)
        record("2c.DB encrypted blob decrypts back to secret",
               decrypted == secret,
               f"match={decrypted == secret}")
    except Exception as e:
        record("2c.DB encrypted blob decrypts back to secret", False, f"err={e}")

    return secret


# ========================================================================
# TEST 3 — Webhook signature verification
# ========================================================================
def test_webhook_sig(secret: str):
    print("\n=== TEST 3: Webhook signature verification ===")

    # 3a. No signature -> 400
    payload = {
        "id": "evt_test_nosig",
        "type": "issuing_authorization.created",
        "data": {"object": {"id": "iauth_x", "card": {"id": "ic_fake"}, "amount": 500, "approved": True}},
    }
    body = json.dumps(payload).encode()
    r = http("POST", "/webhook/stripe/issuing", data=body,
             headers={"Content-Type": "application/json"})
    record("3a.webhook no signature -> 400", r.status_code == 400, f"status={r.status_code} body={r.text[:200]}")

    # 3b. Wrong signature -> 400
    bad_sig = sign_stripe_payload(body, "whsec_bogus_not_the_secret")
    r = http("POST", "/webhook/stripe/issuing", data=body,
             headers={"Content-Type": "application/json", "Stripe-Signature": bad_sig})
    record("3b.webhook wrong signature -> 400", r.status_code == 400, f"status={r.status_code} body={r.text[:200]}")

    # 3c. Correct signature -> 200 (issuing_authorization.created -> db.issuing_events)
    before = DB.issuing_events.count_documents({})
    auth_evt = {
        "id": f"evt_test_auth_{int(time.time())}",
        "object": "event",
        "api_version": "2020-08-27",
        "created": int(time.time()),
        "type": "issuing_authorization.created",
        "data": {
            "object": {
                "id": f"iauth_test_{int(time.time())}",
                "object": "issuing.authorization",
                "amount": -500,
                "approved": True,
                "card": {"id": "ic_test_fake_for_auth_log"},
                "merchant_data": {"name": "Test Coffee", "category": "eating_places", "city": "Seattle"},
            }
        },
    }
    body = json.dumps(auth_evt).encode()
    sig = sign_stripe_payload(body, secret)
    r = http("POST", "/webhook/stripe/issuing", data=body,
             headers={"Content-Type": "application/json", "Stripe-Signature": sig})
    record("3c.webhook correct sig issuing_authorization.created -> 200",
           r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    after = DB.issuing_events.count_documents({})
    record("3c.db.issuing_events received new entry",
           after >= before + 1, f"before={before} after={after}")
    # Ensure the entry matches
    ev = DB.issuing_events.find_one({"raw_id": auth_evt["data"]["object"]["id"]})
    record("3c.issuing_events has our raw_id",
           ev is not None and ev.get("kind") == "authorization",
           f"doc={'found' if ev else 'missing'}")


# ========================================================================
# TEST 4 — issuing_transaction.created settles a real group card
# ========================================================================
def register_and_verify(name: str, phone: str) -> str:
    r = http("POST", "/auth/register", json={"name": name})
    r.raise_for_status()
    uid = r.json()["id"]
    http("POST", "/auth/send-otp", json={"user_id": uid, "phone": phone}).raise_for_status()
    http("POST", "/auth/verify-otp", json={"user_id": uid, "phone": phone, "code": "123456"}).raise_for_status()
    return uid


def test_issuing_transaction(tok: str, secret: str):
    print("\n=== TEST 4: Issuing transaction.created -> group card + auto-disable ===")

    ts = int(time.time())
    # Register a lead user and create a tiny fast-split group so total=$3.00.
    lead_id = register_and_verify(f"F21Lead{ts}", f"+155599{ts % 100000:05d}")
    r = http("POST", "/groups", json={
        "lead_id": lead_id,
        "title": f"F21 Tiny Bill {ts}",
        "total_amount": 3.00,
        "split_mode": "fast",
        "tax": 0,
        "tip": 0,
        "items": [],
    })
    if r.status_code != 200:
        record("4.setup create group", False, f"status={r.status_code} body={r.text[:200]}")
        return
    gid = r.json()["id"]
    record("4.setup group created", True, f"gid={gid}")

    # Grant lead enough credit to cover share + fees
    r = http("POST", f"/admin/users/{lead_id}/credits/grant", headers=auth_hdr(tok),
             json={"amount": 5.0, "note": "F21 test"})
    record("4.setup grant credit", r.status_code == 200, f"status={r.status_code}")

    # Lead contributes (credit-only path) -> fully funds -> auto-issue card
    r = http("POST", f"/groups/{gid}/contribute",
             json={"user_id": lead_id})
    if r.status_code != 200:
        record("4.setup contribute", False, f"status={r.status_code} body={r.text[:200]}")
        return
    record("4.setup contribute credit-only", True, f"status={r.status_code}")

    # Give backend a moment to create card (sync call, but just in case)
    time.sleep(1.0)
    group = DB.groups.find_one({"id": gid})
    vc = (group or {}).get("virtual_card") or {}
    card_id = vc.get("stripe_card_id")
    if not card_id:
        record("4.card auto-issued", False, f"vc={vc}")
        return
    record("4.card auto-issued with stripe_card_id", True, f"card_id={card_id}")
    record("4.card status active & spend_cap set",
           vc.get("status") == "active" and abs(float(vc.get("spend_cap") or 0) - 3.00) < 0.01,
           f"status={vc.get('status')} spend_cap={vc.get('spend_cap')}")

    # Ensure card_disable_mode=auto
    r = http("POST", "/admin/integrations/issuing", headers=auth_hdr(tok),
             json={"card_disable_mode": "auto"})
    record("4.setup card_disable_mode=auto", r.status_code == 200, f"status={r.status_code}")

    # Compose a signed issuing_transaction.created event with amount=-300 (i.e. $3.00)
    txn_evt = {
        "id": f"evt_test_txn_{ts}",
        "object": "event",
        "api_version": "2020-08-27",
        "created": int(time.time()),
        "type": "issuing_transaction.created",
        "data": {
            "object": {
                "id": f"ipi_test_{ts}",
                "object": "issuing.transaction",
                "amount": -300,
                "currency": "usd",
                "card": card_id,
                "type": "capture",
                "merchant_data": {"name": "Merchant Co", "category": "eating_places", "city": "Seattle"},
            }
        },
    }
    body = json.dumps(txn_evt).encode()
    sig = sign_stripe_payload(body, secret)
    r = http("POST", "/webhook/stripe/issuing", data=body,
             headers={"Content-Type": "application/json", "Stripe-Signature": sig})
    record("4.webhook issuing_transaction.created signed -> 200",
           r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    # Verify DB state
    time.sleep(1.5)
    group = DB.groups.find_one({"id": gid})
    vc = (group or {}).get("virtual_card") or {}
    txns = vc.get("transactions") or []
    spent = float(vc.get("spent") or 0.0)
    record("4.virtual_card.transactions has new row",
           len(txns) >= 1, f"txns_len={len(txns)}")
    if txns:
        record("4.new txn amount=3.00",
               abs(float(txns[-1].get("amount") or 0) - 3.00) < 0.01,
               f"amount={txns[-1].get('amount')}")
    record("4.virtual_card.spent += 3.00",
           abs(spent - 3.00) < 0.01, f"spent={spent}")
    record("4.card auto-disabled (status=inactive)",
           vc.get("status") == "inactive",
           f"status={vc.get('status')} disabled_by={vc.get('disabled_by')} reason={vc.get('disabled_reason')}")


# ========================================================================
# TEST 5 — F2/F1 regression
# ========================================================================
def test_regression(tok: str):
    print("\n=== TEST 5: Phase F2 + F1 regression ===")
    ts = int(time.time())
    lead_id = register_and_verify(f"F21Reg{ts}", f"+155566{ts % 100000:05d}")

    # 5a. sensitive OTP send + verify
    r = http("POST", "/auth/sensitive/send-otp", json={"user_id": lead_id})
    record("5a.sensitive send-otp -> 200", r.status_code == 200, f"status={r.status_code}")
    r = http("POST", "/auth/sensitive/verify-otp",
             json={"user_id": lead_id, "code": "123456", "purpose": "card_reveal"})
    body = r.json() if r.status_code == 200 else {}
    record("5a.sensitive verify-otp -> 200", r.status_code == 200, f"status={r.status_code} body={str(body)[:200]}")
    reveal_token = body.get("reveal_token")
    record("5a.reveal_token returned",
           isinstance(reveal_token, str) and len(reveal_token) > 10,
           f"token_len={len(reveal_token or '')}")

    # 5b. ephemeral-key auth chain — create a tiny fully-funded group to get a card
    r = http("POST", "/groups", json={
        "lead_id": lead_id,
        "title": f"F21 RegCard {ts}",
        "total_amount": 3.00,
        "split_mode": "fast",
        "tax": 0, "tip": 0, "items": [],
    })
    gid = r.json().get("id") if r.status_code == 200 else None
    record("5b.create group", bool(gid), f"status={r.status_code}")
    r = http("POST", f"/admin/users/{lead_id}/credits/grant", headers=auth_hdr(tok),
             json={"amount": 5.0, "note": "regression"})
    record("5b.grant credit", r.status_code == 200, f"status={r.status_code}")
    r = http("POST", f"/groups/{gid}/contribute", json={"user_id": lead_id})
    record("5b.contribute credit-only", r.status_code == 200, f"status={r.status_code}")
    time.sleep(0.8)

    # Now call ephemeral-key. With a valid reveal_token, nonce, and stripe_version,
    # it may hit Stripe (which could fail since ephemeral key creation requires
    # real Stripe context). We accept 200 OR 502 (Stripe error) as "auth chain OK".
    # But we reject 400/401/403/404 since those would be backend auth failures.
    r = http("POST", f"/groups/{gid}/card/ephemeral-key",
             json={
                 "user_id": lead_id,
                 "reveal_token": reveal_token,
                 "nonce": "nonce_test_12345abcdef",
                 "stripe_version": "2024-06-20",
             })
    auth_ok = r.status_code in (200, 502)
    record("5b.ephemeral-key auth chain OK (200 or 502 Stripe)",
           auth_ok, f"status={r.status_code} body={r.text[:200]}")

    # 5c. admin disable-card — create yet another group with a card, then disable
    r = http("POST", "/groups", json={
        "lead_id": lead_id,
        "title": f"F21 RegDisable {ts}",
        "total_amount": 3.00,
        "split_mode": "fast",
        "tax": 0, "tip": 0, "items": [],
    })
    gid2 = r.json().get("id") if r.status_code == 200 else None
    record("5c.create 2nd group", bool(gid2), f"status={r.status_code}")
    r = http("POST", f"/admin/users/{lead_id}/credits/grant", headers=auth_hdr(tok),
             json={"amount": 5.0, "note": "regression2"})
    record("5c.grant credit #2", r.status_code == 200, f"status={r.status_code}")
    r = http("POST", f"/groups/{gid2}/contribute", json={"user_id": lead_id})
    record("5c.contribute credit-only #2", r.status_code == 200, f"status={r.status_code}")
    time.sleep(1.0)
    r = http("POST", f"/admin/groups/{gid2}/disable-card", headers=auth_hdr(tok))
    record("5c.admin disable-card -> 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        vc = r.json().get("virtual_card") or {}
        record("5c.card now inactive", vc.get("status") == "inactive", f"status={vc.get('status')}")

    # 5d. Old issuing fields round-trip
    r = http("POST", "/admin/integrations/issuing", headers=auth_hdr(tok),
             json={
                 "require_otp_for_card_reveal": False,
                 "reveal_ttl_seconds": 120,
                 "card_disable_mode": "manual",
             })
    record("5d.POST old fields -> 200", r.status_code == 200, f"status={r.status_code}")
    r = http("GET", "/admin/integrations/issuing", headers=auth_hdr(tok))
    b = r.json() if r.status_code == 200 else {}
    record("5d.GET reflects require_otp_for_card_reveal=false",
           b.get("require_otp_for_card_reveal") is False, f"val={b.get('require_otp_for_card_reveal')}")
    record("5d.GET reflects reveal_ttl_seconds=120",
           b.get("reveal_ttl_seconds") == 120, f"val={b.get('reveal_ttl_seconds')}")
    record("5d.GET reflects card_disable_mode=manual",
           b.get("card_disable_mode") == "manual", f"val={b.get('card_disable_mode')}")

    # Restore defaults
    r = http("POST", "/admin/integrations/issuing", headers=auth_hdr(tok),
             json={
                 "require_otp_for_card_reveal": True,
                 "reveal_ttl_seconds": 60,
                 "card_disable_mode": "auto",
             })
    record("5d.cleanup restore defaults -> 200", r.status_code == 200, f"status={r.status_code}")


# ========================================================================
# Runner
# ========================================================================
def main():
    print(f"[run] {time.strftime('%Y-%m-%d %H:%M:%S')}")
    tok = admin_login()
    print(f"[auth] admin token acquired ({len(tok)} chars)")

    test_feature_toggles(tok)
    secret = test_issuing_webhook_secret(tok)
    test_webhook_sig(secret)
    test_issuing_transaction(tok, secret)
    test_regression(tok)

    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    failed = sum(1 for _n, ok, _d in RESULTS if not ok)
    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed}/{passed+failed} passed, {failed} failed")
    print("=" * 60)
    if failed:
        print("\nFAILURES:")
        for n, ok, d in RESULTS:
            if not ok:
                print(f"  - {n} :: {d}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
