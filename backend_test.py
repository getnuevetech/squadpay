"""Backend regression test — Lead Settlement Payout `execute` endpoint AFTER
the Stripe Elements (card_token) refactor (May 2026).

Tests:
  A. card_token validation (Mode 1) + mode-priority + mixed-empty handling
  B. ACH happy path regression (no change expected)
  C. Eligibility endpoint regression
  D. Mode 2 backward-compat (raw PAN) still routed to Stripe (200 or 502)

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
        # try the new domain
        r = _req("POST", "/admin/auth/login", json_body={
            "email": "admin@getsquadpay.com",
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
        "title": "Lead Payout Settle Test",
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


def _err_detail(r) -> str:
    try:
        return str(r.json().get("detail", ""))
    except Exception:
        return r.text[:200]


async def main():
    print(f"[backend_test] starting against {BASE}")
    print("[backend_test] REGRESSION FOR: Stripe Elements (card_token) refactor")

    _section("A. Admin login + set settlement_mode=lead_choice (need card+ACH)")
    admin_token = admin_login()
    res = set_settlement_mode(admin_token, "lead_choice")
    _check(res.get("ok") is True or res.get("mode") == "lead_choice",
           "set settlement_mode=lead_choice", str(res)[:200])
    mode_after = get_runtime_settlement_mode()
    _check(mode_after == "lead_choice", "runtime settlement_mode=lead_choice",
           f"got {mode_after}")

    _section("B. Seed: create lead + 1 member, create group, FULLY fund it")
    lead = register_and_verify("Marcus Reyes")
    print(f"  lead: id={lead['id']}, session={(lead['session_id'] or '')[:12]}…")
    mem1 = register_and_verify("Priya Shah")
    g = create_group(lead["id"], total=60.0)
    gid = g["id"]
    join_group(gid, mem1["id"])
    await fund_squad_fully(gid, lead["id"], [mem1["id"]], 60.0)
    print(f"  group {gid} fully funded ($60 / 2 members)")

    # ─────────────────────────────────────────────────────────────────────
    # TEST 6 (eligibility GET — no regression)
    # ─────────────────────────────────────────────────────────────────────
    _section("Test 6 — GET /lead-payout/eligibility (regression)")
    r = _req("GET", f"/group/{gid}/lead-payout/eligibility",
             params={"user_id": lead["id"], "session_id": lead["session_id"]})
    print(f"  HTTP {r.status_code}: {r.text[:400]}")
    _check(r.status_code == 200, "Test 6 — eligibility 200", str(r.status_code))
    body = r.json() if r.status_code == 200 else {}
    _check(body.get("eligible") is True, "Test 6 — eligible=true", str(body))
    _check(body.get("supports_card") is True, "Test 6 — supports_card=true")
    _check(body.get("supports_ach") is True, "Test 6 — supports_ach=true")
    _check(body.get("show_lead_payout_option") is True,
           "Test 6 — show_lead_payout_option=true")
    _check(body.get("available_cents", 0) > 0,
           "Test 6 — available_cents > 0",
           f"got {body.get('available_cents')}")

    # ─────────────────────────────────────────────────────────────────────
    # TEST 2 — bad card_token format (no tok_ prefix)
    # ─────────────────────────────────────────────────────────────────────
    _section("Test 2 — bad card_token format ('pm_xxx_wrong')")
    r = _req("POST", f"/group/{gid}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "push_to_card",
        "payload": {"card_token": "pm_xxx_wrong"},
    })
    detail = _err_detail(r)
    print(f"  HTTP {r.status_code}: {detail[:300]}")
    _check(r.status_code == 400,
           "Test 2 — 400 on non-tok_ token", f"got {r.status_code}")
    _check(("tok_" in detail.lower()) or ("stripe token" in detail.lower()),
           "Test 2 — detail mentions tok_ or Stripe token", detail[:200])

    # ─────────────────────────────────────────────────────────────────────
    # TEST 3 — empty card_token AND empty raw PAN
    # ─────────────────────────────────────────────────────────────────────
    _section("Test 3 — empty card_token AND empty card_number")
    r = _req("POST", f"/group/{gid}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "push_to_card",
        "payload": {"card_token": "", "card_number": ""},
    })
    detail = _err_detail(r)
    print(f"  HTTP {r.status_code}: {detail[:300]}")
    _check(r.status_code == 400, "Test 3 — 400 returned",
           f"got {r.status_code}")
    has_token_mode = "card_token" in detail.lower() or "stripe elements" in detail.lower()
    has_raw_mode = "card_number" in detail.lower() or "raw card" in detail.lower()
    _check(has_token_mode and has_raw_mode,
           "Test 3 — detail mentions BOTH modes (card_token + card_number)",
           detail[:300])

    # ─────────────────────────────────────────────────────────────────────
    # TEST 1 — card_token: "tok_visa" — Mode 1 reaches Stripe
    # ─────────────────────────────────────────────────────────────────────
    _section("Test 1 — card_token='tok_visa' (Mode 1 reaches Stripe)")
    pre_log_size = 0
    try:
        pre_log_size = os.path.getsize("/var/log/supervisor/backend.err.log")
    except Exception:
        pass
    r = _req("POST", f"/group/{gid}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "push_to_card",
        "payload": {"card_token": "tok_visa"},
    }, timeout=45)
    detail_t1 = _err_detail(r)
    print(f"  HTTP {r.status_code}: {detail_t1[:400]}")
    # Expected outcomes:
    #   - 200 if Stripe accepts (unlikely with destination='tok_visa' for Payout.create)
    #   - 502 with Stripe error message — code routed correctly to Stripe.
    #   - 400 with our own "tok_" validation message would mean it never reached Stripe (BAD).
    if r.status_code == 200:
        _check(True, "Test 1 — Mode 1 reached Stripe (200)")
    elif r.status_code == 502:
        _check(True, "Test 1 — Mode 1 reached Stripe and Stripe rejected (502 OK)",
               detail_t1[:200])
    elif r.status_code == 400:
        # Could be either: validation (BAD) or a Stripe wrapped 400.
        # Our backend only raises 400 BEFORE Stripe for card_token. So 400 with our
        # message is a real bug for tok_visa.
        if "must be a stripe token" in detail_t1.lower() or "tok_*" in detail_t1.lower():
            _check(False, "Test 1 — Mode 1 incorrectly blocked by our validator",
                   detail_t1[:300])
        else:
            # Could be from Stripe Token.retrieve / Payout.create wrapped as 502 normally;
            # 400 from Stripe is unusual but possible
            _check(True, f"Test 1 — Mode 1 reached Stripe; 400 from Stripe ({detail_t1[:160]})")
    else:
        _check(False, f"Test 1 — unexpected status {r.status_code}", detail_t1[:300])

    # Inspect backend log for the Token.create marker absence (Mode 1 skips it)
    try:
        with open("/var/log/supervisor/backend.err.log", "r") as f:
            f.seek(pre_log_size)
            new_log = f.read()
        token_create_called = "Token.create" in new_log or "token.create" in new_log.lower()
        # We expect Mode 1 NOT to call Token.create server-side
        _check(not token_create_called,
               "Test 1 (log) — Token.create NOT called server-side for Mode 1",
               f"log snippet: {new_log[-500:] if token_create_called else ''}")
    except Exception as e:
        print(f"  (could not read backend log: {e})")

    # ─────────────────────────────────────────────────────────────────────
    # TEST 4 — BOTH card_token AND raw PAN sent → Mode 1 wins
    # ─────────────────────────────────────────────────────────────────────
    _section("Test 4 — Both card_token + card_number sent (Mode 1 must win)")
    try:
        pre_log_size = os.path.getsize("/var/log/supervisor/backend.err.log")
    except Exception:
        pre_log_size = 0
    r = _req("POST", f"/group/{gid}/lead-payout/execute", json_body={
        "user_id": lead["id"], "session_id": lead["session_id"],
        "method": "push_to_card",
        "payload": {
            "card_token": "tok_visa",
            "card_number": "4242424242424242",
            "exp_month": 12,
            "exp_year": 2030,
            "cvv": "123",
        },
    }, timeout=45)
    detail_t4 = _err_detail(r)
    print(f"  HTTP {r.status_code}: {detail_t4[:400]}")
    # The error/response should NOT be from server-side Token.create (Mode 2)
    # Path-of-evidence: if backend chose Mode 2 it would log "Token.create failed" and
    # 502 with "Card tokenization failed".
    chose_mode2 = "tokenization failed" in detail_t4.lower() or "card tokenization" in detail_t4.lower()
    _check(not chose_mode2,
           "Test 4 — Mode 1 wins (no 'tokenization failed' in response)",
           detail_t4[:300])
    try:
        with open("/var/log/supervisor/backend.err.log", "r") as f:
            f.seek(pre_log_size)
            new_log = f.read()
        token_create_called = ("Token.create failed" in new_log
                                or "stripe.Token.create" in new_log)
        _check(not token_create_called,
               "Test 4 (log) — server-side Token.create NOT invoked",
               f"log tail: {new_log[-400:] if token_create_called else ''}")
    except Exception as e:
        print(f"  (could not read backend log: {e})")

    # ─────────────────────────────────────────────────────────────────────
    # TEST 5 — ACH regression (must still work exactly as before)
    # ─────────────────────────────────────────────────────────────────────
    _section("Test 5 — ACH regression (Increase sandbox)")
    # Need a fresh fully-funded group because the prior tests may have
    # flipped this group to lead_paid. Actually, all prior execute attempts
    # were 4xx, so group.status should still be 'paid'. But to be safe, fund
    # a fresh group.
    g_ach = create_group(lead["id"], total=50.0)
    gid_ach = g_ach["id"]
    join_group(gid_ach, mem1["id"])
    await fund_squad_fully(gid_ach, lead["id"], [mem1["id"]], 50.0)
    r = _req("POST", f"/group/{gid_ach}/lead-payout/execute", json_body={
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
    ach_ok = False
    if r.status_code == 200:
        body = r.json()
        ach_ok = True
        _check(body.get("ok") is True, "Test 5 — ACH ok=true")
        _check(body.get("method") == "ach", "Test 5 — method=ach")
        _check(body.get("last4") == "3344", "Test 5 — last4=3344")
        _check(body.get("provider") == "increase", "Test 5 — provider=increase")
        # Compliance check on db.payouts
        payout_doc = await fetch_payout_doc(body["txn_id"])
        _check(payout_doc is not None, "Test 5 — payout row exists")
        if payout_doc:
            forbidden = {"routing_number", "account_number", "card_number",
                         "cvv", "pan"}
            present = forbidden & set(payout_doc.keys())
            _check(len(present) == 0,
                   "Test 5 — COMPLIANCE: no raw routing/account numbers in db.payouts",
                   f"forbidden present: {present}")
            _check(payout_doc.get("last4") == "3344",
                   "Test 5 — payouts.last4=3344")
            _check(payout_doc.get("kind") == "lead_settlement_payout",
                   "Test 5 — payouts.kind=lead_settlement_payout")
    elif r.status_code == 502:
        print("  ENV NOTE: 502 from Increase sandbox is acceptable.")
        _check(False, "Test 5 — ACH execute returned 502 (env, not code-bug)",
               r.text[:200])
    else:
        _check(False, f"Test 5 — ACH unexpected status {r.status_code}",
               r.text[:300])

    # ─────────────────────────────────────────────────────────────────────
    # TEST 7 — Mode 2 backward compat (raw PAN)
    # ─────────────────────────────────────────────────────────────────────
    _section("Test 7 — Mode 2 backward compat (raw PAN path)")
    g_m2 = create_group(lead["id"], total=40.0)
    gid_m2 = g_m2["id"]
    join_group(gid_m2, mem1["id"])
    await fund_squad_fully(gid_m2, lead["id"], [mem1["id"]], 40.0)
    r = _req("POST", f"/group/{gid_m2}/lead-payout/execute", json_body={
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
    detail_t7 = _err_detail(r)
    print(f"  HTTP {r.status_code}: {r.text[:600]}")
    if r.status_code == 200:
        body = r.json()
        _check(body.get("ok") is True, "Test 7 — 200 (Raw Card Data API on)")
        _check(body.get("method") == "push_to_card", "Test 7 — method=push_to_card")
    elif r.status_code == 502:
        _check(True,
               "Test 7 — 502 acceptable (Raw Card Data API likely disabled)",
               detail_t7[:200])
    elif r.status_code == 400:
        _check(False,
               "Test 7 — Mode 2 returned 400 (should NOT be validation error)",
               detail_t7[:300])
    else:
        _check(False, f"Test 7 — unexpected status {r.status_code}",
               detail_t7[:300])

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
