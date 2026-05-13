"""Phase 7 — Native Apple/Google Pay PaymentSheet endpoint tests.

Covers:
  A) GET /api/stripe/publishable-key
  B) Happy path POST /api/groups/{gid}/contribute-payment-intent
  C) Eligibility 4xx coverage
  D) Credit full-coverage 400 branch
  E) Stripe Customer reuse
  F) Finalize before payment succeeded
  G) Finalize negative cases
  H) Finalize idempotency (manual db flag flip)
  R) Regression: legacy /contribute Checkout path still works
"""
from __future__ import annotations
import asyncio
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://joint-pay-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client[DB_NAME]

results: List[Tuple[str, bool, str]] = []


def record(name: str, ok: bool, info: str = ""):
    results.append((name, ok, info))
    status = "✅" if ok else "❌"
    print(f"  {status} {name} {('— ' + info) if info else ''}")


# ── helpers ─────────────────────────────────────────────────────────────
async def admin_login(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"{API}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    r.raise_for_status()
    return r.json()["token"]


async def ensure_sms_mock(client: httpx.AsyncClient, token: str):
    r = await client.post(
        f"{API}/admin/integrations/sms-mode",
        headers={"Authorization": f"Bearer {token}"},
        json={"mode": "mock"},
    )
    if r.status_code not in (200, 204):
        print(f"[warn] could not set sms mock: {r.status_code} {r.text[:200]}")


async def register_user(client: httpx.AsyncClient, name: str, phone: str, verify: bool = True) -> Dict[str, Any]:
    """Register via /auth/register, then directly mark the user verified in mongo to
    avoid the 5/minute send-otp rate limit. The verified state matches what
    /verify-otp would set: {verified: True, phone: <phone>}.
    """
    r = await client.post(f"{API}/auth/register", json={"name": name})
    r.raise_for_status()
    user = r.json()
    if not verify:
        return user
    # Direct-DB shortcut (test-only) to avoid 5/min rate limit on /send-otp.
    from datetime import datetime, timezone
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "phone": phone,
            "verified": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    user["phone"] = phone
    user["verified"] = True
    return user


async def send_otp_only(client: httpx.AsyncClient, user_id: str, phone: str):
    r = await client.post(f"{API}/auth/send-otp", json={"user_id": user_id, "phone": phone})
    r.raise_for_status()


def fresh_phone() -> str:
    """Generate a random-looking 10-digit US phone."""
    return f"+1832{int(time.time() * 1000) % 10000000:07d}"


async def create_group(client: httpx.AsyncClient, lead: Dict[str, Any], total: float, title: str = "Pizza Night") -> Dict[str, Any]:
    r = await client.post(
        f"{API}/groups",
        json={
            "lead_id": lead["id"],
            "title": title,
            "total_amount": total,
            "split_mode": "fast",
            "tax": 0.0,
            "tip": 0.0,
            "items": [],
        },
    )
    r.raise_for_status()
    return r.json()


async def join_group(client: httpx.AsyncClient, code: str, user_id: str) -> Dict[str, Any]:
    # Resolve group_id from code
    r = await client.get(f"{API}/groups/by-code/{code}")
    r.raise_for_status()
    gid = r.json()["id"]
    r = await client.post(f"{API}/groups/{gid}/join", json={"user_id": user_id, "joined_via": "code"})
    r.raise_for_status()
    return r.json()


async def get_group(client: httpx.AsyncClient, gid: str) -> Dict[str, Any]:
    r = await client.get(f"{API}/groups/{gid}")
    r.raise_for_status()
    return r.json()


async def admin_grant_credit(client: httpx.AsyncClient, token: str, user_id: str, amount: float) -> Dict[str, Any]:
    r = await client.post(
        f"{API}/admin/users/{user_id}/credits/grant",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": amount, "note": "phase7 test"},
    )
    r.raise_for_status()
    return r.json()


async def admin_revoke_credit(client: httpx.AsyncClient, token: str, user_id: str, credit_id: str):
    r = await client.post(
        f"{API}/admin/users/{user_id}/credits/{credit_id}/revoke",
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()


# ── tests ───────────────────────────────────────────────────────────────
async def test_A_publishable_key(client: httpx.AsyncClient):
    print("\n[A] GET /api/stripe/publishable-key")
    r = await client.get(f"{API}/stripe/publishable-key")
    record("A.status_200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code != 200:
        return
    body = r.json()
    record("A.merchant_identifier", body.get("merchant_identifier") == "merchant.us.squadpay", body.get("merchant_identifier"))
    record("A.configured_true", body.get("configured") is True, str(body.get("configured")))
    record("A.publishable_key_present", bool(body.get("publishable_key")), str(bool(body.get("publishable_key"))))


async def test_B_happy_path(client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    print("\n[B] HAPPY PATH — create group + create PI")
    ts = int(time.time())
    tom = await register_user(client, f"Tom Phase7 {ts}", f"+1832{(ts % 10000000):07d}1")
    alice = await register_user(client, f"Alice Phase7 {ts}", f"+1713{(ts % 10000000):07d}2")
    bob = await register_user(client, f"Bob Phase7 {ts}", f"+1281{(ts % 10000000):07d}3")
    record("B.users_registered", all([tom.get("verified"), alice.get("verified"), bob.get("verified")]),
           f"tom={tom.get('verified')} alice={alice.get('verified')} bob={bob.get('verified')}")

    group = await create_group(client, tom, total=30.0, title="Tom's Pizza")
    gid = group["id"]
    code = group["code"]
    await join_group(client, code, alice["id"])
    await join_group(client, code, bob["id"])

    enriched = await get_group(client, gid)
    tom_share = next(p["total"] for p in enriched["per_user"] if p["user_id"] == tom["id"])
    record("B.tom_share_positive", tom_share > 0, f"tom_share={tom_share}")

    r = await client.post(
        f"{API}/groups/{gid}/contribute-payment-intent",
        json={"user_id": tom["id"], "amount": tom_share, "notify_on_settled": True},
    )
    record("B.pi_status_200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
    if r.status_code != 200:
        return None
    body = r.json()
    record("B.client_secret_pi_prefix", body.get("client_secret", "").startswith("pi_"), body.get("client_secret", "")[:30])
    record("B.client_secret_has_secret", "_secret_" in (body.get("client_secret") or ""), "")
    record("B.payment_intent_id_pi", body.get("payment_intent_id", "").startswith("pi_"), body.get("payment_intent_id", "")[:30])
    record("B.ephemeral_key_ek", body.get("ephemeral_key_secret", "").startswith("ek_"), body.get("ephemeral_key_secret", "")[:30])
    record("B.customer_id_cus", body.get("customer_id", "").startswith("cus_"), body.get("customer_id", "")[:30])
    record("B.publishable_key_present_or_null", body.get("publishable_key") is None or isinstance(body.get("publishable_key"), str), str(type(body.get("publishable_key"))))
    record("B.txn_id_chg", body.get("txn_id", "").startswith("chg_"), body.get("txn_id", "")[:30])
    record("B.cash_owed_positive", float(body.get("cash_owed") or 0) > 0, str(body.get("cash_owed")))
    record("B.credit_planned_zero", abs(float(body.get("credit_planned") or 0)) < 0.01, str(body.get("credit_planned")))
    record("B.currency_usd", body.get("currency") == "usd", str(body.get("currency")))
    record("B.merchant_display_name", body.get("merchant_display_name") == "SquadPay", str(body.get("merchant_display_name")))

    # DB inspection
    pi_id = body.get("payment_intent_id")
    tx = await db.payment_transactions.find_one({"payment_intent_id": pi_id}, {"_id": 0})
    record("B.db_tx_exists", tx is not None, "row present" if tx else "missing")
    if tx:
        record("B.db_tx_status_initiated", tx.get("status") == "initiated", str(tx.get("status")))
        record("B.db_tx_applied_false", tx.get("applied") is False, str(tx.get("applied")))
        record("B.db_tx_ledger_posted_false", tx.get("ledger_posted") is False, str(tx.get("ledger_posted")))
        record("B.db_tx_kind_native", (tx.get("metadata") or {}).get("kind") == "group_member_contribute_native",
               str((tx.get("metadata") or {}).get("kind")))

    return {"tom": tom, "alice": alice, "bob": bob, "group": group, "pi_body": body, "gid": gid, "tom_share": tom_share}


async def test_C_eligibility(client: httpx.AsyncClient, admin_token: str, ctx: Dict[str, Any]):
    print("\n[C] ELIGIBILITY 4xx COVERAGE")
    tom = ctx["tom"]
    alice = ctx["alice"]
    gid = ctx["gid"]
    share = ctx["tom_share"]

    # Unknown group id
    r = await client.post(f"{API}/groups/grp_DOESNOTEXIST/contribute-payment-intent",
                         json={"user_id": tom["id"], "amount": 5.0})
    record("C.unknown_group_404", r.status_code == 404, f"{r.status_code}: {r.text[:100]}")

    # Wrong format
    r = await client.post(f"{API}/groups/!!!INVALID/contribute-payment-intent",
                         json={"user_id": tom["id"], "amount": 5.0})
    record("C.bad_format_404", r.status_code == 404, f"{r.status_code}: {r.text[:100]}")

    # Non-member
    ts = int(time.time())
    outsider = await register_user(client, f"Outsider {ts}", f"+1469{(ts % 10000000):07d}9")
    r = await client.post(f"{API}/groups/{gid}/contribute-payment-intent",
                         json={"user_id": outsider["id"], "amount": 5.0})
    record("C.non_member_403", r.status_code == 403, f"{r.status_code}: {r.text[:120]}")
    record("C.non_member_msg", r.status_code == 403 and "Not a member" in r.text, r.text[:120])

    # Unverified user (skip verify-otp)
    r = await client.post(f"{API}/auth/register", json={"name": f"Unv {ts}"})
    unv = r.json()
    # add unv to a fresh group as a member via join? They need to be a member to bypass non-member check.
    # The route checks: 404 group, then 403 group_blocked, then 404 user-not-found, then 403 user-blocked,
    # then 403 if not user.verified, then 403 if not a member.
    # So the verified check fires BEFORE the member check ✓
    r = await client.post(f"{API}/groups/{gid}/contribute-payment-intent",
                         json={"user_id": unv["id"], "amount": 5.0})
    record("C.unverified_403", r.status_code == 403, f"{r.status_code}: {r.text[:160]}")
    record("C.unverified_msg", r.status_code == 403 and "Phone verification" in r.text, r.text[:160])

    # Group with <2 members
    solo_lead = await register_user(client, f"Solo {ts}", f"+1832{(ts % 10000000):07d}5")
    solo_group = await create_group(client, solo_lead, total=20.0, title="Solo bill")
    r = await client.post(f"{API}/groups/{solo_group['id']}/contribute-payment-intent",
                         json={"user_id": solo_lead["id"], "amount": 10.0})
    record("C.lt2_members_400", r.status_code == 400, f"{r.status_code}: {r.text[:160]}")
    record("C.lt2_members_msg", r.status_code == 400 and "at least 2 members" in r.text, r.text[:160])

    # amount=0
    r = await client.post(f"{API}/groups/{gid}/contribute-payment-intent",
                         json={"user_id": alice["id"], "amount": 0})
    record("C.amount_zero_400", r.status_code == 400, f"{r.status_code}: {r.text[:160]}")
    record("C.amount_zero_msg", r.status_code == 400 and "Nothing left" in r.text, r.text[:160])

    # Force group status='paid' via direct db write — use a fresh group
    paid_lead = await register_user(client, f"PaidLead {ts}", f"+1832{(ts % 10000000):07d}6")
    paid_m2 = await register_user(client, f"PaidM2 {ts}", f"+1713{(ts % 10000000):07d}7")
    paid_group = await create_group(client, paid_lead, total=15.0, title="Already paid")
    await join_group(client, paid_group["code"], paid_m2["id"])
    await db.groups.update_one({"id": paid_group["id"]}, {"$set": {"status": "paid"}})
    r = await client.post(f"{API}/groups/{paid_group['id']}/contribute-payment-intent",
                         json={"user_id": paid_lead["id"], "amount": 5.0})
    record("C.bill_paid_400", r.status_code == 400, f"{r.status_code}: {r.text[:160]}")
    record("C.bill_paid_msg", r.status_code == 400 and "Bill already paid" in r.text, r.text[:160])

    # Force is_blocked=true on a group
    blocked_lead = await register_user(client, f"BLead {ts}", f"+1832{(ts % 10000000):07d}8")
    blocked_m2 = await register_user(client, f"BM2 {ts}", f"+1713{(ts % 10000000):07d}9")
    blocked_group = await create_group(client, blocked_lead, total=15.0, title="Blocked group")
    await join_group(client, blocked_group["code"], blocked_m2["id"])
    await db.groups.update_one({"id": blocked_group["id"]}, {"$set": {"is_blocked": True}})
    r = await client.post(f"{API}/groups/{blocked_group['id']}/contribute-payment-intent",
                         json={"user_id": blocked_lead["id"], "amount": 5.0})
    record("C.blocked_group_403", r.status_code == 403, f"{r.status_code}: {r.text[:160]}")


async def test_D_credit_full_coverage(client: httpx.AsyncClient, admin_token: str, ctx: Dict[str, Any]):
    print("\n[D] CREDIT FULL-COVERAGE BRANCH")
    tom = ctx["tom"]
    gid = ctx["gid"]
    share = ctx["tom_share"]

    grant = await admin_grant_credit(client, admin_token, tom["id"], 1000.0)
    credit_id = grant["id"]
    record("D.credit_granted", credit_id.startswith("cr_"), credit_id)

    r = await client.post(
        f"{API}/groups/{gid}/contribute-payment-intent",
        json={"user_id": tom["id"], "amount": share},
    )
    record("D.fully_covered_400", r.status_code == 400, f"{r.status_code}: {r.text[:200]}")
    record("D.fully_covered_msg",
           r.status_code == 400 and "fully covered" in r.text.lower(),
           r.text[:200])

    # cleanup
    await admin_revoke_credit(client, admin_token, tom["id"], credit_id)
    record("D.credit_revoked", True, "revoked")


async def test_E_customer_reuse(client: httpx.AsyncClient, ctx: Dict[str, Any]):
    print("\n[E] STRIPE CUSTOMER REUSE")
    tom = ctx["tom"]
    gid = ctx["gid"]
    first_cust = ctx["pi_body"]["customer_id"]

    # second call with a DIFFERENT amount
    r = await client.post(
        f"{API}/groups/{gid}/contribute-payment-intent",
        json={"user_id": tom["id"], "amount": 1.50},
    )
    record("E.second_call_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return
    body = r.json()
    second_cust = body.get("customer_id")
    record("E.same_customer_returned", first_cust == second_cust, f"first={first_cust} second={second_cust}")

    user_doc = await db.users.find_one({"id": tom["id"]}, {"_id": 0, "stripe_customer_id": 1})
    record("E.db_user_stripe_customer_id_matches",
           user_doc and user_doc.get("stripe_customer_id") == first_cust,
           f"db={user_doc and user_doc.get('stripe_customer_id')}")

    ctx["second_pi_body"] = body


async def test_F_finalize_before_pay(client: httpx.AsyncClient, ctx: Dict[str, Any]):
    print("\n[F] FINALIZE BEFORE PAYMENT")
    gid = ctx["gid"]
    pi_id = ctx["pi_body"]["payment_intent_id"]

    # capture contributions count BEFORE
    g_before = await get_group(client, gid)
    contribs_before = len(g_before.get("contributions") or [])

    r = await client.post(
        f"{API}/groups/{gid}/contribute-payment-intent/finalize",
        json={"payment_intent_id": pi_id},
    )
    record("F.finalize_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return
    body = r.json()
    record("F.applied_false", body.get("applied") is False, str(body.get("applied")))
    record("F.payment_status_requires_pm",
           body.get("payment_status") in ("requires_payment_method", "requires_confirmation", "requires_action"),
           str(body.get("payment_status")))

    # DB inspections
    tx = await db.payment_transactions.find_one({"payment_intent_id": pi_id}, {"_id": 0})
    record("F.db_tx_applied_still_false", tx and tx.get("applied") is False, str(tx and tx.get("applied")))
    record("F.db_tx_status_updated", tx and tx.get("payment_status") in ("requires_payment_method", "requires_confirmation", "requires_action"),
           str(tx and tx.get("payment_status")))

    g_after = await get_group(client, gid)
    contribs_after = len(g_after.get("contributions") or [])
    record("F.contributions_unchanged", contribs_before == contribs_after, f"before={contribs_before} after={contribs_after}")


async def test_G_finalize_negative(client: httpx.AsyncClient, ctx: Dict[str, Any]):
    print("\n[G] FINALIZE NEGATIVE CASES")
    pi_id = ctx["pi_body"]["payment_intent_id"]

    # 1) wrong group_id with valid pi_id
    r = await client.post(
        f"{API}/groups/grp_OTHER_NOPE/contribute-payment-intent/finalize",
        json={"payment_intent_id": pi_id},
    )
    record("G.wrong_group_400", r.status_code == 400, f"{r.status_code}: {r.text[:200]}")
    record("G.wrong_group_msg",
           r.status_code == 400 and "does not belong to this group" in r.text,
           r.text[:200])

    # 2) non-existent PI
    gid = ctx["gid"]
    r = await client.post(
        f"{API}/groups/{gid}/contribute-payment-intent/finalize",
        json={"payment_intent_id": "pi_DOES_NOT_EXIST"},
    )
    record("G.unknown_pi_404", r.status_code == 404, f"{r.status_code}: {r.text[:200]}")
    record("G.unknown_pi_msg",
           r.status_code == 404 and "not found in our records" in r.text,
           r.text[:200])


async def test_H_finalize_idempotency(client: httpx.AsyncClient, ctx: Dict[str, Any]):
    print("\n[H] FINALIZE IDEMPOTENCY (simulated)")
    # Use the second_pi_body from E (so we don't disturb the one used in F)
    second = ctx.get("second_pi_body")
    if not second:
        record("H.precondition_skip", False, "no second PI from step E")
        return
    pi_id = second["payment_intent_id"]
    gid = ctx["gid"]

    # Flip applied=true directly in mongo
    await db.payment_transactions.update_one(
        {"payment_intent_id": pi_id},
        {"$set": {"applied": True, "status": "complete", "payment_status": "succeeded"}},
    )

    g_before = await get_group(client, gid)
    contribs_before = len(g_before.get("contributions") or [])

    r = await client.post(
        f"{API}/groups/{gid}/contribute-payment-intent/finalize",
        json={"payment_intent_id": pi_id},
    )
    record("H.idempotent_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        record("H.applied_true_in_response", r.json().get("applied") is True, str(r.json().get("applied")))

    g_after = await get_group(client, gid)
    contribs_after = len(g_after.get("contributions") or [])
    record("H.no_new_contribution", contribs_before == contribs_after, f"before={contribs_before} after={contribs_after}")


async def test_R_regression_legacy_contribute(client: httpx.AsyncClient):
    print("\n[R] REGRESSION — legacy /contribute (Stripe Checkout) still works")
    ts = int(time.time())
    tom = await register_user(client, f"RegTom {ts}", f"+1832{(ts % 10000000):07d}A")
    alice = await register_user(client, f"RegAlice {ts}", f"+1713{(ts % 10000000):07d}B")
    g = await create_group(client, tom, total=24.0, title="Regression bill")
    await join_group(client, g["code"], alice["id"])

    enriched = await get_group(client, g["id"])
    tom_share = next(p["total"] for p in enriched["per_user"] if p["user_id"] == tom["id"])

    r = await client.post(
        f"{API}/groups/{g['id']}/contribute",
        json={
            "user_id": tom["id"],
            "amount": tom_share,
            "origin_url": "http://localhost:3000",
            "app_return_url": "http://localhost:3000",
        },
    )
    record("R.legacy_contribute_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return
    body = r.json()
    # Legacy returns either checkout_url (Stripe checkout) or credit_only path
    has_checkout = bool(body.get("checkout_url")) or bool(body.get("url")) or bool(body.get("session_id"))
    record("R.legacy_has_session_or_url",
           has_checkout or body.get("status") == "credit_only" or body.get("settled") is True,
           f"keys={list(body.keys())[:10]}")


async def main():
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        token = await admin_login(client)
        await ensure_sms_mock(client, token)

        await test_A_publishable_key(client)

        ctx = await test_B_happy_path(client)
        if not ctx:
            print("\n[!] Happy path failed; aborting dependent tests.")
        else:
            await test_C_eligibility(client, token, ctx)
            await test_D_credit_full_coverage(client, token, ctx)
            await test_E_customer_reuse(client, ctx)
            await test_F_finalize_before_pay(client, ctx)
            await test_G_finalize_negative(client, ctx)
            await test_H_finalize_idempotency(client, ctx)

        await test_R_regression_legacy_contribute(client)

    # Summary
    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"SUMMARY: {passed}/{total} assertions passed")
    fails = [r for r in results if not r[1]]
    if fails:
        print(f"\n{len(fails)} FAILURES:")
        for name, _, info in fails:
            print(f"  ❌ {name}: {info[:300]}")
    else:
        print("ALL PASSED.")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
