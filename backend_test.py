"""Backend tests — Stripe Phase-2 inbound webhooks.

Run against the live preview backend defined in
/app/frontend/.env (EXPO_PUBLIC_BACKEND_URL). Tests:

  1. Before secrets configured: 3 webhook POSTs → 501.
  2. Save 3 Phase-2 secrets via admin POST /api/admin/integrations/stripe.
  3. GET /api/admin/integrations returns the *_set booleans = true (no plaintext).
  4. Mongo persistence — webhook_secret_*_enc encrypted strings present.
  5. After secrets set, webhook POSTs (no Stripe-Signature) → 400 (not 501).
  6. Idempotency — duplicate {id: "evt_test_idemp_1"} inserts into payment_events
     fail on the second attempt because of the unique index on .id.
  7. Cleanup — $unset the encrypted secret fields + remove the test event doc.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError


BACKEND_URL = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


passes: list[str] = []
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        passes.append(name)
        print(f"  ✅ {name}")
    else:
        fails.append(f"{name} — {detail}")
        print(f"  ❌ {name} — {detail}")


def admin_login() -> str:
    r = requests.post(
        f"{BACKEND_URL}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in admin login response: {data}"
    return tok


async def db_handle():
    client = AsyncIOMotorClient(MONGO_URL)
    return client, client[DB_NAME]


async def precondition_clear_phase2_secrets():
    """Make sure the test starts fresh — phase-2 secrets must not be configured."""
    client, db = await db_handle()
    try:
        await db.app_settings.update_one(
            {"key": "integrations"},
            {"$unset": {
                "stripe.webhook_secret_payments_enc": "",
                "stripe.webhook_secret_refunds_enc": "",
                "stripe.webhook_secret_issuing_enc": "",
                "stripe.webhook_secret_payments": "",
                "stripe.webhook_secret_refunds": "",
                "stripe.webhook_secret_issuing": "",
            }},
        )
    finally:
        client.close()


def test_pre_state_501():
    print("\n=== Step 1 — Pre-state: all 3 webhooks return 501 (no secret) ===")
    for path in ("/webhook/stripe-payments", "/webhook/stripe-refunds", "/webhook/stripe-issuing"):
        r = requests.post(
            f"{BACKEND_URL}{path}",
            data=b"{}",
            headers={"content-type": "application/json"},
            timeout=15,
        )
        check(
            f"POST {path} → 501 before secret configured",
            r.status_code == 501,
            f"got status={r.status_code}, body={r.text[:200]}",
        )


def test_save_phase2_secrets(token: str):
    print("\n=== Step 2 — Save 3 Phase-2 secrets via admin ===")
    body = {
        "enabled": True,
        "mode": "test",
        "publishable_key": "pk_test_phase2",
        "webhook_secret_payments": "whsec_test_p",
        "webhook_secret_refunds": "whsec_test_r",
        "webhook_secret_issuing": "whsec_test_i",
    }
    r = requests.post(
        f"{BACKEND_URL}/admin/integrations/stripe",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        timeout=20,
    )
    check(
        "POST /admin/integrations/stripe with 3 phase-2 secrets → 200",
        r.status_code == 200,
        f"status={r.status_code}, body={r.text[:300]}",
    )
    try:
        rj = r.json()
    except Exception:
        rj = {}
    body_str = json.dumps(rj)
    check(
        "Response does NOT contain plaintext webhook secret values",
        "whsec_test_p" not in body_str and "whsec_test_r" not in body_str and "whsec_test_i" not in body_str,
        "response body contained one of the plaintext secret values",
    )


def test_admin_integrations_get_flags(token: str):
    print("\n=== Step 2b — GET /admin/integrations returns the *_set flags ===")
    r = requests.get(
        f"{BACKEND_URL}/admin/integrations",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    check("GET /admin/integrations → 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        return
    rj = r.json()
    s = (rj.get("stripe") or {})
    print(f"  stripe keys: {sorted(s.keys())}")
    check("stripe.webhook_secret_payments_set == true",
          s.get("webhook_secret_payments_set") is True,
          f"got {s.get('webhook_secret_payments_set')!r}")
    check("stripe.webhook_secret_refunds_set == true",
          s.get("webhook_secret_refunds_set") is True,
          f"got {s.get('webhook_secret_refunds_set')!r}")
    check("stripe.webhook_secret_issuing_set == true",
          s.get("webhook_secret_issuing_set") is True,
          f"got {s.get('webhook_secret_issuing_set')!r}")
    body_str = json.dumps(rj)
    check("GET /admin/integrations does NOT return plaintext secret values",
          "whsec_test_p" not in body_str and "whsec_test_r" not in body_str and "whsec_test_i" not in body_str,
          "plaintext secret leaked back through GET")


async def test_mongo_persistence():
    print("\n=== Step 3 — Mongo persistence of *_enc fields ===")
    client, db = await db_handle()
    try:
        doc = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0, "stripe": 1}) or {}
        s = doc.get("stripe") or {}
        for k in ("webhook_secret_payments_enc", "webhook_secret_refunds_enc", "webhook_secret_issuing_enc"):
            val = s.get(k)
            check(f"app_settings.stripe.{k} present (string)", isinstance(val, str) and len(val) > 10,
                  f"got value type={type(val).__name__}, len={(len(val) if isinstance(val, str) else 'n/a')}")
            check(f"app_settings.stripe.{k} is NOT plaintext",
                  isinstance(val, str) and not val.startswith("whsec_test_"),
                  f"value appears to be plaintext: {val!r}")
        # Also ensure NO plaintext copy stored alongside
        for k in ("webhook_secret_payments", "webhook_secret_refunds", "webhook_secret_issuing"):
            check(f"app_settings.stripe.{k} (plaintext) NOT persisted",
                  k not in s,
                  f"plaintext key persisted: {s.get(k)!r}")
    finally:
        client.close()


def test_post_state_400():
    print("\n=== Step 4 — After secrets configured, webhook POSTs (no signature) → 400, not 501 ===")
    for path in ("/webhook/stripe-payments", "/webhook/stripe-refunds", "/webhook/stripe-issuing"):
        r = requests.post(
            f"{BACKEND_URL}{path}",
            data=b"not-a-valid-stripe-event",
            headers={"content-type": "application/json"},
            timeout=15,
        )
        check(
            f"POST {path} (no signature) → 400 (signature verification path wired)",
            r.status_code == 400,
            f"got status={r.status_code}, body={r.text[:200]}",
        )
        check(
            f"POST {path} no longer returns 501 after secret configured",
            r.status_code != 501,
            "still returning 501 — secret lookup did not pick up new value",
        )


async def test_idempotency_index():
    print("\n=== Step 5 — payment_events.id unique index idempotency ===")
    client, db = await db_handle()
    try:
        await db.payment_events.delete_many({"id": "evt_test_idemp_1"})

        idx = await db.payment_events.index_information()
        has_id_unique = any(
            spec.get("unique") and spec.get("key") == [("id", 1)]
            for spec in idx.values()
        )
        check("payment_events has UNIQUE index on `id`", has_id_unique,
              f"index_information={idx}")

        await db.payment_events.insert_one({
            "id": "evt_test_idemp_1",
            "type": "test.idempotency",
            "kind_tag": "payments",
            "livemode": False,
            "received_at": "2026-05-16T00:00:00Z",
        })
        check("First insert {id: evt_test_idemp_1} succeeded", True)

        duplicate_raised = False
        try:
            await db.payment_events.insert_one({
                "id": "evt_test_idemp_1",
                "type": "test.idempotency.dup",
                "kind_tag": "payments",
            })
        except DuplicateKeyError:
            duplicate_raised = True
        except Exception as e:
            duplicate_raised = "E11000" in str(e) or "duplicate" in str(e).lower()
        check("Second insert with same id raises DuplicateKeyError", duplicate_raised,
              "duplicate not rejected — uniqueness not enforced")
    finally:
        client.close()


async def cleanup():
    print("\n=== Cleanup — drop encrypted phase-2 secrets + test event doc ===")
    client, db = await db_handle()
    try:
        await db.app_settings.update_one(
            {"key": "integrations"},
            {"$unset": {
                "stripe.webhook_secret_payments_enc": "",
                "stripe.webhook_secret_refunds_enc": "",
                "stripe.webhook_secret_issuing_enc": "",
                "stripe.webhook_secret_payments": "",
                "stripe.webhook_secret_refunds": "",
                "stripe.webhook_secret_issuing": "",
            }},
        )
        await db.payment_events.delete_many({"id": "evt_test_idemp_1"})
        doc = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0, "stripe": 1}) or {}
        s = doc.get("stripe") or {}
        leftover = [k for k in ("webhook_secret_payments_enc", "webhook_secret_refunds_enc", "webhook_secret_issuing_enc") if k in s]
        check("Cleanup unset phase-2 _enc fields", not leftover, f"still present: {leftover}")
        ev = await db.payment_events.find_one({"id": "evt_test_idemp_1"})
        check("Cleanup deleted evt_test_idemp_1", ev is None, f"still present: {ev}")
        print(f"  post-cleanup stripe keys: {sorted(s.keys())}")
    finally:
        client.close()


def test_post_cleanup_501():
    print("\n=== Post-cleanup sanity — webhook POSTs back to 501 ===")
    for path in ("/webhook/stripe-payments", "/webhook/stripe-refunds", "/webhook/stripe-issuing"):
        r = requests.post(
            f"{BACKEND_URL}{path}",
            data=b"{}",
            headers={"content-type": "application/json"},
            timeout=15,
        )
        check(
            f"POST {path} → 501 after cleanup (no secret again)",
            r.status_code == 501,
            f"got status={r.status_code}, body={r.text[:200]}",
        )


def main():
    print(f"Backend URL: {BACKEND_URL}")
    print(f"Mongo URL  : {MONGO_URL}  DB: {DB_NAME}")
    asyncio.run(precondition_clear_phase2_secrets())

    test_pre_state_501()

    token = admin_login()
    print(f"  admin token acquired (len={len(token)})")

    test_save_phase2_secrets(token)
    test_admin_integrations_get_flags(token)
    asyncio.run(test_mongo_persistence())
    test_post_state_400()
    asyncio.run(test_idempotency_index())
    asyncio.run(cleanup())
    test_post_cleanup_501()

    print("\n" + "=" * 70)
    print(f"PASS: {len(passes)}   FAIL: {len(fails)}")
    if fails:
        print("\nFAILURES:")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("All Phase-2 webhook checks passed.")


if __name__ == "__main__":
    main()
