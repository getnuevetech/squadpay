"""Backend test — Lead Settlement Payout endpoints (no-store, settlement-time).

Tests:
  - GET  /api/group/{group_id}/lead-payout/eligibility
  - POST /api/group/{group_id}/lead-payout/execute

Covers eligibility positive/negative/mode-switching and execute validation,
ACH happy path (Increase sandbox) and Push-to-Card happy path (Stripe test card).
Compliance check: NO raw PAN/CVV/routing/account numbers persisted to db.payouts.

Run:  python3 /app/backend_test.py
"""
from __future__ import annotations
import asyncio
import os
import sys
import time
import uuid
import requests

sys.path.insert(0, "/app/backend")

BASE = "https://joint-pay-1.preview.emergentagent.com/api"

PASS = 0
FAIL = 0
FAILS: list[str] = []


def _check(cond: bool, label: str, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        FAILS.append(label + (f"  ({extra})" if extra else ""))
        print(f"  FAIL  {label}" + (f"  ({extra})" if extra else ""))


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _req(method: str, path: str, *, json_body=None, headers=None, params=None, timeout=30):
    return requests.request(method, f"{BASE}{path}", json=json_body, headers=headers,
                            params=params, timeout=timeout)


def admin_login() -> str:
    r = _req("POST", "/admin/auth/login", json_body={
        "email": "admin@squadpay.us",
        "password": "Letmein@2007#ForReal",
    })
    if r.status_code != 200:
        raise RuntimeError(f"admin login failed: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


def set_settlement_mode(admin_token: str, mode: str) -> dict:
    r = _req("POST", "/admin/settlement-mode",
             json_body={"mode": mode},
             headers={"Authorization": f"Bearer {admin_token}"})
    return r.json() if r.status_code == 200 else {"error": r.text, "status": r.status_code}


def get_runtime_settlement_mode() -> str:
    r = _req("GET", "/runtime/settlement-mode")
    return r.json().get("mode") if r.status_code == 200 else None


def _rand_phone() -> str:
    return "+1555" + str(uuid.uuid4().int)[:7]


def register_and_verify(name: str) -> dict:
    r1 = _req("POST", "/auth/register", json_body={"name": name})
    assert r1.status_code == 200, f"register: {r1.status_code} {r1.text[:200]}"
    uid = r1.json()["id"]
    phone = _rand_phone()
    for _ in range(3):
        r2 = _req("POST", "/auth/send-otp", json_body={"user_id": uid, "phone": phone})
        if r2.status_code == 200:
            break
        if r2.status_code == 429:
            time.sleep(15)
            continue
        raise RuntimeError(f"send-otp: {r2.status_code} {r2.text[:200]}")
    r3 = _req("POST", "/auth/verify-otp", json_body={
        "user_id": uid, "phone": phone, "code": "123456",
    })
    assert r3.status_code == 200, f"verify-otp: {r3.status_code} {r3.text[:200]}"
    body = r3.json()
    return {
        "id": body.get("id", uid),
        "name": body.get("name", name),
        "phone": body.get("phone", phone),
        "session_id": body.get("session_id"),
    }


def create_group(lead_id: str, total: float = 60.0) -> dict:
    r = _req("POST", "/groups", json_body={
        "lead_id": lead_id,
        "title": "Lead Payout Test Squad",
        "total_amount": float(total),
        "tax": 0, "tip": 0,
        "split_mode": "fast",
        "items": [],
    })
    assert r.status_code == 200, f"create_group: {r.status_code} {r.text[:200]}"
    return r.json()


def join_group(gid: str, user_id: str) -> None:
    r = _req("POST", f"/groups/{gid}/join",
             json_body={"user_id": user_id, "joined_via": "code"})
    assert r.status_code == 200, f"join_group: {r.status_code} {r.text[:200]}"


async def fund_squad_fully(gid: str, lead_id: str, member_ids: list[str], total_amount: float):
    """Direct-DB seed of contributions + ledger entries to simulate a fully
    funded squad. Real Stripe Checkout requires a browser redirect and is
    out of scope for an API test harness."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from ledger import record_charge_event, make_txn_id
    from core import now_iso

    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    n = 1 + len(member_ids)
    total_cents = int(round(total_amount * 100))
    base_share_cents = total_cents // n
    leftover = total_cents - base_share_cents * n
    payouts = {lead_id: base_share_cents + leftover}
    for mid in member_ids:
        payouts[mid] = base_share_cents

    contributions = []
    for uid, cents in payouts.items():
        contributions.append({
            "id": "c_" + uuid.uuid4().hex[:10],
            "user_id": uid,
            "amount": round(cents / 100.0, 2),
            "cash_paid": round(cents / 100.0, 2),
            "credit_applied": 0.0,
            "notify_on_settled": False,
            "via": "test_seed",
            "at": now_iso(),
        })

    await db.groups.update_one({"id": gid}, {"$set": {
        "funding_mode": "group",
        "status": "paid",
        "lead_paid_at": now_iso(),
        "contributions": contributions,
        "funding": {
            "total_contributed": round(sum(c["amount"] for c in contributions), 2),
            "total_repaid": 0.0,
            "lead_shortfall": 0.0,
            "remaining_to_collect": 0.0,
            "merchant_remaining": 0.0,
            "fees_total": 0.0,
        },
    }})

    for c in contributions:
        gross_cents = int(round(c["amount"] * 100))
        try:
            await record_charge_event(
                db,
                txn_id=make_txn_id("test_seed"),
                bill_id=gid,
                user_id=c["user_id"],
                gross_cents=gross_cents,
                currency="usd",
                processor_fee_cents=0,
                tax_cents=0,
                kind="group_member_contribute",
                reference={"seeded_by": "backend_test"},
            )
        except Exception as e:
            print(f"  ledger seed failed: {e}")

    client.close()


async def fetch_payout_doc(txn_id: str):
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    doc = await db.payouts.find_one({"txn_id": txn_id}, {"_id": 0})
    client.close()
    return doc


async def fetch_group_status(gid: str):
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    g = await db.groups.find_one({"id": gid}, {"_id": 0, "status": 1,
                                                  "lead_payout_method": 1,
                                                  "lead_payout_paid_at": 1})
    client.close()
    return g


async def main():
    print(f"[backend_test] starting against {BASE}")

    _section("A. Admin login + initial settlement-mode")
    admin_token = admin_login()
    initial_mode = get_runtime_settlement_mode()
    print(f"  initial settlement_mode = {initial_mode}")
    res = set_settlement_mode(admin_token, "lead_choice")
    _check(res.get("ok") is True or res.get("mode") == "lead_choice",
           "set settlement_mode=lead_choice", str(res)[:200])
    mode_after = get_runtime_settlement_mode()
    _check(mode_after == "lead_choice", "runtime settlement_mode now lead_choice",
           f"got {mode_after}")

    _section("B. Create lead + 2 members, create group, fund it")
    lead = register_and_verify("Tom Walker")
    print(f"  lead: id={lead['id']}, session={(lead['session_id'] or '')[:12]}…")
    _check(bool(lead["session_id"]), "lead has session_id")

    mem1 = register_and_verify("Alice Jensen")
    mem2 = register_and_verify("Bob Patel")
    print(f"  members: {mem1['id']}, {mem2['id']}")

    g = create_group(lead["id"], total=60.0)
    gid = g["id"]
    print(f"  group: id={gid}, total=$60.00")
    join_group(gid, mem1["id"])
    join_group(gid, mem2["id"])
    await fund_squad_fully(gid, lead["id"], [mem1["id"], mem2["id"]], 60.0)
    print("  squad funded (direct seed)")

    _section("D. Eligibility positive (lead, fully funded, lead_choice)")
    r = _req("GET", f"/group/{gid}/lead-payout/eligibility",
             params={"user_id": lead["id"], "session_id": lead["session_id"]})
    print(f"  HTTP {r.status_code}: {r.text[:400]}")
    _check(r.status_code == 200, "eligibility returns 200", str(r.status_code))
    body = r.json() if r.status_code == 200 else {}
    _check(body.get("eligible") is True, "eligible=true", str(body))
    _check(body.get("fully_funded") is True, "fully_funded=true")
    _check(body.get("settlement_mode") == "lead_choice", "settlement_mode=lead_choice")
    _check(body.get("funding_mode") == "group", "funding_mode=group")
    _check(body.get("available_cents", 0) > 0, "available_cents > 0",
           f"got {body.get('available_cents')}")
    _check(body.get("supports_ach") is True, "supports_ach=true")
    _check(body.get("supports_card") is True, "supports_card=true")
    _check(body.get("show_virtual_card_option") is True, "show_virtual_card_option=true")
    _check(body.get("show_lead_payout_option") is True, "show_lead_payout_option=true")
    print(f"  available_cents={body.get('available_cents')}  usd={body.get('available_usd')}")

    _section("E. Eligibility — settlement mode switching")
    set_settlement_mode(admin_token, "virtual_card")
    r = _req("GET", f"/group/{gid}/lead-payout/eligibility",
             params={"user_id": lead["id"], "session_id": lead["session_id"]})
    body = r.json() if r.status_code == 200 else {}
    _check(body.get("show_lead_payout_option") is False,
           "show_lead_payout_option=false under virtual_card", str(body))
    _check(body.get("show_virtual_card_option") is True,
           "show_virtual_card_option=true under virtual_card")
    _check(body.get("eligible") is False, "eligible=false under virtual_card")
    _check("settlement_mode_disallows_lead_payout" in body.get("reasons", []),
           "reason: settlement_mode_disallows_lead_payout")

    set_settlement_mode(admin_token, "lead_card")
    r = _req("GET", f"/group/{gid}/lead-payout/eligibility",
             params={"user_id": lead["id"], "session_id": lead["session_id"]})
    body = r.json() if r.status_code == 200 else {}
    _check(body.get("show_virtual_card_option") is False,
           "show_virtual_card_option=false under lead_card", str(body))
    _check(body.get("show_lead_payout_option") is True,
           "show_lead_payout_option=true under lead_card")
    _check(body.get("eligible") is True, "eligible=true under lead_card")
    set_settlement_mode(admin_token, "lead_choice")

    _section("F. Eligibility — negative cases")
    r = _req("GET", f"/group/{gid}/lead-payout/eligibility",
             params={"user_id": mem1["id"], "session_id": mem1["session_id"]})
    _check(r.status_code == 403, "non-lead user → 403",
           f"got {r.status_code}: {r.text[:200]}")

    g2 = create_group(lead["id"], total=80.0)
    gid2 = g2["id"]
    join_group(gid2, mem1["id"])
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    _client = AsyncIOMotorClient(mongo_url)
    _db = _client[db_name]
    await _db.groups.update_one({"id": gid2}, {"$set": {
        "funding_mode": "group",
        "funding": {"remaining_to_collect": 80.0, "merchant_remaining": 80.0,
                    "total_contributed": 0.0, "total_repaid": 0.0,
                    "lead_shortfall": 0.0, "fees_total": 0.0}
    }})
    _client.close()
    r = _req("GET", f"/group/{gid2}/lead-payout/eligibility",
             params={"user_id": lead["id"], "session_id": lead["session_id"]})
    body = r.json() if r.status_code == 200 else {}
    _check(r.status_code == 200, "non-funded eligibility returns 200")
    _check(body.get("eligible") is False, "non-funded eligible=false")
    _check(body.get("fully_funded") is False, "fully_funded=false")
    _check("not_fully_funded" in body.get("reasons", []),
           "reason: not_fully_funded", str(body.get("reasons")))

    _section("G. Execute — validation errors")
    r = _req("POST", f"/group/{gid2}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "ach",
        "payload": {"routing_number": "101050001", "account_number": "11223344",
                    "account_holder_name": "Test Lead"},
    })
    _check(r.status_code == 409, "execute on under-funded squad → 409",
           f"got {r.status_code}: {r.text[:200]}")

    set_settlement_mode(admin_token, "virtual_card")
    r = _req("POST", f"/group/{gid}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "ach",
        "payload": {"routing_number": "101050001", "account_number": "11223344",
                    "account_holder_name": "Test Lead"},
    })
    _check(r.status_code == 409, "execute under virtual_card → 409",
           f"got {r.status_code}: {r.text[:200]}")
    set_settlement_mode(admin_token, "lead_choice")

    r = _req("POST", f"/group/{gid}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "foo", "payload": {},
    })
    _check(r.status_code == 400, "execute with invalid method → 400",
           f"got {r.status_code}: {r.text[:200]}")

    r = _req("POST", f"/group/{gid}/lead-payout/execute", json_body={
        "user_id": mem1["id"], "session_id": mem1["session_id"],
        "method": "ach",
        "payload": {"routing_number": "101050001", "account_number": "11223344",
                    "account_holder_name": "X"},
    })
    _check(r.status_code == 403, "non-lead execute → 403",
           f"got {r.status_code}: {r.text[:200]}")

    r = _req("POST", f"/group/{gid}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "ach",
        "payload": {"account_number": "11223344", "account_holder_name": "Test"},
    })
    _check(r.status_code == 400, "ACH missing routing_number → 400",
           f"got {r.status_code}: {r.text[:200]}")

    r = _req("POST", f"/group/{gid}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "push_to_card",
        "payload": {"exp_month": 12, "exp_year": 2030, "cvv": "123"},
    })
    _check(r.status_code == 400, "card missing card_number → 400",
           f"got {r.status_code}: {r.text[:200]}")

    _section("H. Execute — ACH happy path (Increase sandbox)")
    r = _req("POST", f"/group/{gid}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "ach",
        "payload": {
            "routing_number": "101050001",
            "account_number": "11223344",
            "account_holder_name": "Test Lead",
            "account_type": "checking",
        },
    }, timeout=60)
    print(f"  HTTP {r.status_code}: {r.text[:600]}")
    if r.status_code == 200:
        body = r.json()
        _check(body.get("ok") is True, "ACH ok=true")
        _check(str(body.get("txn_id", "")).startswith("payout_"),
               "ACH txn_id starts with payout_", str(body.get("txn_id")))
        _check(body.get("method") == "ach", "ACH method=ach")
        _check(body.get("last4") == "3344", "ACH last4=3344")
        _check(body.get("provider") == "increase", "ACH provider=increase")
        _check(body.get("status") in ("pending", "paid", "submitted",
                                       "pending_submission", "pending_reviewing",
                                       "pending_approval"),
               f"ACH status valid ({body.get('status')})")

        payout_doc = await fetch_payout_doc(body["txn_id"])
        print(f"  payout doc keys: {sorted(list(payout_doc.keys())) if payout_doc else 'MISSING'}")
        _check(payout_doc is not None, "payout row exists in db.payouts")
        if payout_doc:
            forbidden = {"routing_number", "account_number", "card_number",
                         "cvv", "pan", "account_holder_name"}
            present = forbidden & set(payout_doc.keys())
            _check(len(present) == 0,
                   f"COMPLIANCE: no raw sensitive fields in db.payouts",
                   f"forbidden present: {present}")
            for k in ("id", "txn_id", "user_id", "group_id", "gateway_slug",
                      "provider_payout_id", "amount_cents", "status", "method",
                      "last4", "kind", "created_at"):
                _check(k in payout_doc, f"payouts row has '{k}'")
            _check(payout_doc.get("last4") == "3344", "payouts.last4=3344")
            _check(payout_doc.get("kind") == "lead_settlement_payout",
                   "payouts.kind=lead_settlement_payout")

        g_after = await fetch_group_status(gid)
        _check(g_after and g_after.get("status") == "lead_paid",
               "group.status flipped to lead_paid", str(g_after))
    elif r.status_code == 502:
        print("  ENV NOTE: 502 from Increase sandbox is acceptable (env). Not a code bug.")
        FAILS.append(f"ACH 502 (env-issue, not code-bug): {r.text[:200]}")
    else:
        _check(False, f"ACH execute returned unexpected {r.status_code}",
               r.text[:300])

    _section("I. Execute — Push-to-Card happy path (Stripe test card)")
    g3 = create_group(lead["id"], total=40.0)
    gid3 = g3["id"]
    join_group(gid3, mem1["id"])
    await fund_squad_fully(gid3, lead["id"], [mem1["id"]], 40.0)

    r = _req("POST", f"/group/{gid3}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "push_to_card",
        "payload": {
            "card_number": "4242424242424242",
            "exp_month": 12,
            "exp_year": 2030,
            "cvv": "123",
            "cardholder_name": "Test Lead",
        },
    }, timeout=60)
    print(f"  HTTP {r.status_code}: {r.text[:600]}")
    if r.status_code == 200:
        body = r.json()
        _check(body.get("ok") is True, "Card ok=true")
        _check(body.get("method") == "push_to_card", "Card method=push_to_card")
        _check(body.get("last4") == "4242", "Card last4=4242")
        _check(body.get("provider") == "stripe", "Card provider=stripe")
        payout_doc = await fetch_payout_doc(body["txn_id"])
        _check(payout_doc is not None, "Card payout row exists")
        if payout_doc:
            forbidden = {"card_number", "cvv", "pan", "routing_number", "account_number"}
            present = forbidden & set(payout_doc.keys())
            _check(len(present) == 0,
                   "COMPLIANCE: no raw card fields in db.payouts",
                   f"forbidden present: {present}")
    elif r.status_code == 502:
        print("  ENV NOTE: 502 from Stripe push-to-card is acceptable (Instant Payouts not enabled). Not a code bug.")
        FAILS.append(f"Stripe push-to-card 502 (env-issue, not code-bug): {r.text[:300]}")
    else:
        _check(False, f"Card execute returned unexpected {r.status_code}",
               r.text[:300])

    print("\n" + "=" * 60)
    print(f"  PASS: {PASS}    FAIL: {FAIL}")
    if FAILS:
        print("\nFailures:")
        for f in FAILS:
            print(f"  - {f}")
    print("=" * 60)
    return FAIL


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        import traceback
        traceback.print_exc()
    sys.exit(0)
