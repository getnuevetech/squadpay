"""Phase 4 — Group A Charge Adapter Contract end-to-end tests.

Run: python3 /app/backend_test.py

Targets local backend at http://localhost:8001/api with super_admin creds.
"""
from __future__ import annotations
import asyncio
import os
import sys
import json
import traceback

import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

BASE = "http://localhost:8001/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

PASS = []
FAIL = []


def record(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append((name, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))


def admin_login() -> str:
    r = requests.post(f"{BASE}/admin/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=20)
    r.raise_for_status()
    return r.json()["token"]


# ---------------------------------------------------------------------------
async def get_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return c[os.environ.get("DB_NAME", "test_database")]


# ---------------------------------------------------------------------------
async def find_open_group(db, *, min_members: int = 1, exclude_ids=None):
    exclude_ids = set(exclude_ids or [])
    cursor = db.groups.find({"status": "open", "total_amount": {"$gt": 0}}).limit(60)
    async for g in cursor:
        if g.get("is_blocked"):
            continue
        if g.get("id") in exclude_ids:
            continue
        members = g.get("members") or []
        if len(members) < min_members:
            continue
        return g
    return None


# ---------------------------------------------------------------------------
def p4_1(token: str):
    print("\n--- P4.1 GET /api/admin/gateways ---")
    r = requests.get(f"{BASE}/admin/gateways", headers={"Authorization": f"Bearer {token}"}, timeout=15)
    record("P4.1 GET /admin/gateways → 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        print(r.text[:500])
        return
    body = r.json()
    active = body.get("active") or {}
    record("P4.1 active.charge == 'stripe'", active.get("charge") == "stripe", f"active={active}")


def p4_2(token: str, db_get, group_id_holder: dict) -> str:
    print("\n--- P4.2 POST /api/groups/{gid}/checkout-session ---")
    # Find an open group with total > 0
    db = asyncio.get_event_loop().run_until_complete(db_get())
    g = asyncio.get_event_loop().run_until_complete(find_open_group(db, min_members=1))
    if not g:
        record("P4.2 setup — open group found", False, "no eligible group")
        return ""
    gid = g["id"]
    group_id_holder["p42_group"] = gid
    record("P4.2 setup — open group found", True, f"gid={gid} total={g.get('total_amount')}")

    r = requests.post(f"{BASE}/groups/{gid}/checkout-session",
                      json={"origin_url": "http://localhost:3000"},
                      timeout=30)
    record("P4.2 checkout-session → 200", r.status_code == 200,
           f"status={r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        return ""
    body = r.json()
    txn_id = body.get("txn_id") or ""
    sid = body.get("session_id") or ""
    record("P4.2 response.txn_id starts with 'tx_charge_'", txn_id.startswith("tx_charge_"),
           f"txn_id={txn_id}")
    record("P4.2 response.session_id starts with 'cs_'", sid.startswith("cs_"),
           f"session_id={sid}")
    record("P4.2 response.url present (Stripe)", "stripe.com" in (body.get("url") or ""),
           f"url={(body.get('url') or '')[:80]}")

    # Verify db.payment_transactions row has gateway_slug='stripe' AND matching txn_id.
    async def _check():
        row = await db.payment_transactions.find_one({"session_id": sid}, {"_id": 0})
        return row
    row = asyncio.get_event_loop().run_until_complete(_check())
    record("P4.2 db row exists for session", bool(row), f"row keys={list((row or {}).keys())}")
    if row:
        record("P4.2 db row.gateway_slug == 'stripe'",
               row.get("gateway_slug") == "stripe",
               f"gateway_slug={row.get('gateway_slug')}")
        record("P4.2 db row.txn_id matches response",
               row.get("txn_id") == txn_id,
               f"db.txn_id={row.get('txn_id')} resp.txn_id={txn_id}")
    return sid


def p4_3(db_get, group_id_holder: dict) -> str:
    """Member contribute Path B → must route through Stripe with gateway_slug stamped."""
    print("\n--- P4.3 POST /api/groups/{gid}/contribute (cash Path B) ---")
    db = asyncio.get_event_loop().run_until_complete(db_get())

    # Find a group with >= 2 members + a verified, non-blocked member who hasn't fully paid
    # AND has zero active credits (so Path B kicks in).
    async def _find():
        cur = db.groups.find({"status": "open", "total_amount": {"$gt": 0}}).limit(80)
        async for g in cur:
            if g.get("is_blocked"):
                continue
            if g.get("id") == group_id_holder.get("p42_group"):
                # avoid the group we just hit (no real conflict but cleaner)
                pass
            members = g.get("members") or []
            if len(members) < 2:
                continue
            for m in members:
                u = await db.users.find_one({"id": m["user_id"]}, {"_id": 0})
                if not u or not u.get("verified") or u.get("is_blocked"):
                    continue
                # check no active credits with remaining balance
                rows = await db.credits.find({"user_id": u["id"], "status": "active"}, {"_id": 0}).to_list(None)
                bal = 0.0
                for r in rows:
                    bal += round(float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0), 2)
                if bal > 0.01:
                    continue
                # check this user has not already paid in full for this group
                # quickly check by per-user share via enrichment? Easiest: see if there's
                # at least one member who hasn't contributed.
                contribs = g.get("contributions") or []
                already = sum(float(c.get("amount") or 0) for c in contribs if c.get("user_id") == u["id"])
                per_share = float(g.get("total_amount") or 0) / max(1, len(members))
                if already + 0.01 >= per_share:
                    continue
                return g, u
        return None, None

    g, u = asyncio.get_event_loop().run_until_complete(_find())
    record("P4.3 setup — group+member found", bool(g and u),
           f"gid={g.get('id') if g else None} uid={u.get('id') if u else None}")
    if not (g and u):
        return ""
    gid = g["id"]

    r = requests.post(f"{BASE}/groups/{gid}/contribute",
                      json={
                          "user_id": u["id"],
                          # let backend compute remaining share (so we don't overpay)
                          "origin_url": "http://localhost:3000",
                      },
                      timeout=30)
    record("P4.3 contribute → 200", r.status_code == 200,
           f"status={r.status_code} body={r.text[:300]}")
    if r.status_code != 200:
        return ""
    body = r.json()
    if not body.get("checkout_required"):
        record("P4.3 routed to Path B (checkout_required=true)", False,
               f"body={json.dumps(body)[:200]}")
        return ""
    record("P4.3 routed to Path B (checkout_required=true)", True, "")
    txn_id = body.get("txn_id") or ""
    sid = body.get("session_id") or ""
    record("P4.3 response.txn_id starts with 'tx_charge_'", txn_id.startswith("tx_charge_"),
           f"txn_id={txn_id}")

    async def _check():
        row = await db.payment_transactions.find_one({"session_id": sid}, {"_id": 0})
        return row
    row = asyncio.get_event_loop().run_until_complete(_check())
    record("P4.3 db row exists", bool(row), f"row={list((row or {}).keys())}")
    if row:
        record("P4.3 db row.gateway_slug == 'stripe'",
               row.get("gateway_slug") == "stripe",
               f"gateway_slug={row.get('gateway_slug')}")
        record("P4.3 db row.txn_id matches response",
               row.get("txn_id") == txn_id, f"db.txn_id={row.get('txn_id')}")
    return sid


def p4_4(sid: str):
    print("\n--- P4.4 GET /api/checkout/status/{session_id} ---")
    if not sid:
        record("P4.4 status endpoint", False, "no session_id from prior step")
        return
    r = requests.get(f"{BASE}/checkout/status/{sid}", timeout=30)
    record("P4.4 status → 200 (adapter-mediated retrieve)",
           r.status_code == 200, f"status={r.status_code} body={r.text[:300]}")
    if r.status_code != 200:
        return
    body = r.json()
    record("P4.4 payment_status present", "payment_status" in body,
           f"payment_status={body.get('payment_status')}")


def p4_5():
    print("\n--- P4.5 Scaffold defence-in-depth ---")
    try:
        # Run async method synchronously
        from fastapi import HTTPException
        from adapters.charge_scaffolds import SquareChargeAdapter, AdyenChargeAdapter, FlutterwaveChargeAdapter
        # SquareChargeAdapter.create_checkout_session — explicit call from review
        sq = SquareChargeAdapter()
        try:
            asyncio.new_event_loop().run_until_complete(sq.create_checkout_session(
                amount_cents=100, currency="usd",
                success_url="x", cancel_url="y", metadata={}, idempotency_key="k"))
            record("P4.5 Square create_checkout_session raises HTTPException", False,
                   "no exception raised")
        except HTTPException as e:
            ok = e.status_code == 501 and "Square" in (e.detail or "") and "not yet implemented" in (e.detail or "")
            record("P4.5 Square.create_checkout_session → 501 'Square not yet implemented'",
                   ok, f"status={e.status_code} detail={e.detail}")
        except Exception as e:
            record("P4.5 Square.create_checkout_session raises HTTPException", False,
                   f"wrong exception {type(e).__name__}: {e}")

        # bonus — check retrieve_session and verify_webhook also raise 501
        for name, coro in [
            ("Square.retrieve_session", sq.retrieve_session("abc")),
            ("Square.verify_webhook",   sq.verify_webhook(b"{}", "sig")),
        ]:
            try:
                asyncio.new_event_loop().run_until_complete(coro)
                record(f"P4.5 {name} raises 501", False, "no exception")
            except HTTPException as e:
                ok = e.status_code == 501
                record(f"P4.5 {name} raises 501", ok, f"status={e.status_code}")
            except Exception as e:
                record(f"P4.5 {name} raises 501", False, f"wrong type {type(e).__name__}")

        # And verify the other two scaffold classes also raise on create_checkout_session
        for cls in (AdyenChargeAdapter, FlutterwaveChargeAdapter):
            inst = cls()
            try:
                asyncio.new_event_loop().run_until_complete(inst.create_checkout_session(
                    amount_cents=100, currency="usd", success_url="x", cancel_url="y",
                    metadata={}, idempotency_key="k"))
                record(f"P4.5 {cls.__name__}.create_checkout_session raises 501", False,
                       "no exception")
            except HTTPException as e:
                ok = e.status_code == 501 and ("not yet implemented" in (e.detail or ""))
                record(f"P4.5 {cls.__name__}.create_checkout_session → 501",
                       ok, f"status={e.status_code} detail={(e.detail or '')[:80]}")
            except Exception as e:
                record(f"P4.5 {cls.__name__}.create_checkout_session raises 501", False,
                       f"wrong type {type(e).__name__}")
    except Exception:
        record("P4.5 scaffold defence-in-depth", False, traceback.format_exc()[-500:])


def p4_6(token: str):
    print("\n--- P4.6 Activation guard regression ---")
    r = requests.post(f"{BASE}/admin/gateways/charge/activate",
                      json={"provider_slug": "square"},
                      headers={"Authorization": f"Bearer {token}"},
                      timeout=20)
    ok = r.status_code == 400 and "adapter is not yet implemented in code" in (r.text or "")
    record("P4.6 activate square → 400 'adapter is not yet implemented in code'",
           ok, f"status={r.status_code} body={r.text[:300]}")


def p4_7():
    """Phase 3 ledger regression — direct ledger.make_txn_id + record_charge_event."""
    print("\n--- P4.7 Phase 3 ledger regression ---")

    async def run():
        from motor.motor_asyncio import AsyncIOMotorClient
        from ledger import make_txn_id, record_charge_event, find_entries_by_txn
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ.get("DB_NAME", "test_database")]
        txn_id = make_txn_id("charge")
        ok_fmt = txn_id.startswith("tx_charge_") and len(txn_id) > len("tx_charge_") + 20
        record("P4.7 make_txn_id format", ok_fmt, f"txn_id={txn_id}")

        rows1 = await record_charge_event(
            db, txn_id=txn_id, bill_id="test_bill_phase4",
            user_id="u_test_phase4", gross_cents=10000, currency="usd",
            reference={"test": "phase4"},
        )
        record("P4.7 first call → 4 rows returned", len(rows1) == 4, f"rows={len(rows1)}")
        cats = sorted([r["category"] for r in rows1])
        record("P4.7 categories include 4 expected",
               cats == sorted(["charge.gross", "charge.processor_fee", "charge.tax", "charge.net_payable"]),
               f"cats={cats}")

        # Idempotency
        rows2 = await record_charge_event(
            db, txn_id=txn_id, bill_id="test_bill_phase4",
            user_id="u_test_phase4", gross_cents=10000, currency="usd",
            reference={"test": "phase4-replay"},
        )
        cnt = await db.ledger_entries.count_documents({"txn_id": txn_id})
        record("P4.7 idempotency → still 4 rows in DB", cnt == 4, f"cnt={cnt}")

        # Math invariant: gross == fee + tax + net_payable. With fee=0 tax=0 → net == gross.
        rows = await find_entries_by_txn(db, txn_id)
        by_cat = {r["category"]: r for r in rows}

        def _amt(cat: str, want_dir: str) -> int:
            r = by_cat.get(cat) or {}
            if (r.get("direction") or "") == want_dir:
                return int(r.get("amount_cents") or 0)
            return 0

        gross = _amt("charge.gross", "credit")
        fee   = _amt("charge.processor_fee", "debit")
        tax   = _amt("charge.tax", "debit")
        net   = _amt("charge.net_payable", "credit")
        record("P4.7 math invariant gross - fee - tax == net_payable",
               gross - fee - tax == net,
               f"gross={gross} fee={fee} tax={tax} net={net}")

        # Cleanup
        del_res = await db.ledger_entries.delete_many({"txn_id": txn_id})
        record("P4.7 cleanup removed test rows",
               del_res.deleted_count == 4, f"deleted={del_res.deleted_count}")

    asyncio.new_event_loop().run_until_complete(run())


# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("Phase 4 — Charge Adapter Contract — backend test")
    print("=" * 70)
    token = admin_login()
    print(f"super_admin token acquired (len={len(token)})")

    async def _db():
        return await get_db()

    p4_1(token)

    group_id_holder = {}
    sid_p42 = p4_2(token, _db, group_id_holder)
    sid_p43 = p4_3(_db, group_id_holder)

    # P4.4 — exercise checkout/status on the lead-pay session from P4.2.
    p4_4(sid_p42)
    # Also exercise contribute/status on the P4.3 session as additional adapter coverage.
    if sid_p43:
        print("\n--- P4.4-bonus GET /api/contribute/status/{session_id} ---")
        r = requests.get(f"{BASE}/contribute/status/{sid_p43}", timeout=30)
        record("P4.4-bonus contribute/status → 200", r.status_code == 200,
               f"status={r.status_code} body={r.text[:200]}")

    p4_5()
    p4_6(token)
    p4_7()

    # Summary
    print("\n" + "=" * 70)
    print(f"RESULTS: PASS={len(PASS)}  FAIL={len(FAIL)}")
    if FAIL:
        print("\nFAILED ASSERTIONS:")
        for n, d in FAIL:
            print(f"  ❌ {n}\n     {d}")
    print("=" * 70)


if __name__ == "__main__":
    main()
