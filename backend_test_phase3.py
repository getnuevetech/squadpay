"""Phase 3 — Immutable Ledger + Txn ID System (June 2025) — backend tests.

Tests L1..L12 from the review request. Runs against local backend at
http://localhost:8001/api. Uses real admin credentials from
/app/memory/test_credentials.md.

Direct mongo access used for the L9 writer test and for verifying side effects
(payment_transactions, ledger_entries) — uses MONGO_URL / DB_NAME from
backend/.env. Cleanup after each test run.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

# Ensure we can import backend modules (ledger.py lives there).
sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

import ledger  # noqa: E402

BASE = "http://localhost:8001/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PWD = "Letmein@2007#ForReal"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "test_database")

results: List[Dict[str, Any]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    icon = "✅" if ok else "❌"
    print(f"{icon} {name} — {detail}" if detail else f"{icon} {name}")
    results.append({"name": name, "ok": ok, "detail": detail})


def admin_login(email: str, password: str) -> Optional[str]:
    r = requests.post(
        f"{BASE}/admin/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    if r.status_code != 200:
        return None
    return r.json().get("token")


def hdr(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


async def find_or_create_open_group(db) -> Dict[str, Any]:
    """Return an open group with total_amount > 0. Create one via API if needed."""
    g = await db.groups.find_one(
        {"status": "open", "total_amount": {"$gt": 0}, "is_blocked": {"$ne": True}},
        {"_id": 0},
    )
    if g:
        return g

    # Register a fresh lead + verify, then create a group via API.
    ts = int(time.time())
    name = f"LedgerLead{ts}"
    r = requests.post(f"{BASE}/auth/register", json={"name": name}, timeout=10)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    lead_id = r.json()["id"]

    phone = f"+1555{ts % 10000000:07d}"
    r = requests.post(
        f"{BASE}/auth/send-otp", json={"user_id": lead_id, "phone": phone}, timeout=10
    )
    assert r.status_code == 200, f"send-otp: {r.status_code} {r.text}"
    r = requests.post(
        f"{BASE}/auth/verify-otp",
        json={"user_id": lead_id, "phone": phone, "code": "123456"},
        timeout=10,
    )
    assert r.status_code == 200, f"verify-otp: {r.status_code} {r.text}"
    lead_id = r.json().get("id") or lead_id

    body = {
        "lead_id": lead_id,
        "title": "Phase3 Ledger Test Bill",
        "total_amount": 42.50,
        "tax": 0,
        "tip": 0,
        "split_mode": "fast",
        "items": [{"name": "Phase3 Item", "price": 42.50, "quantity": 1}],
    }
    r = requests.post(f"{BASE}/groups", json=body, timeout=10)
    assert r.status_code == 200, f"create group: {r.status_code} {r.text}"
    return r.json()


async def main() -> int:
    print(f"=== Phase 3 Ledger Tests — {BASE} ===\n")

    # ---- Prerequisite: admin login (also sanity per L1) ----
    tok = admin_login(ADMIN_EMAIL, ADMIN_PWD)
    if not tok:
        record("PREREQ admin login", False, "could not log in")
        print("FATAL: admin login failed. Stop.")
        return 2
    record("PREREQ admin login", True, "token acquired")

    # L1 — sanity on a previously-existing admin endpoint (audit-log).
    r = requests.get(f"{BASE}/admin/audit-log?limit=1", headers=hdr(tok), timeout=10)
    record(
        "L1 admin token works on existing endpoint (audit-log)",
        r.status_code == 200,
        f"status={r.status_code}",
    )

    # L2 — GET /admin/ledger/summary → 200, has `accounts` key.
    r = requests.get(f"{BASE}/admin/ledger/summary", headers=hdr(tok), timeout=10)
    ok = r.status_code == 200 and isinstance(r.json().get("accounts"), dict)
    record(
        "L2 GET /admin/ledger/summary",
        ok,
        f"status={r.status_code} body_keys={list(r.json().keys()) if r.ok else r.text[:200]}",
    )

    # L3 — GET /admin/ledger → 200; shape {total, skip, limit, items}.
    r = requests.get(f"{BASE}/admin/ledger", headers=hdr(tok), timeout=10)
    body = r.json() if r.ok else {}
    shape_ok = (
        r.status_code == 200
        and isinstance(body.get("total"), int)
        and isinstance(body.get("skip"), int)
        and isinstance(body.get("limit"), int)
        and isinstance(body.get("items"), list)
    )
    record(
        "L3 GET /admin/ledger shape", shape_ok,
        f"status={r.status_code} keys={list(body.keys()) if r.ok else r.text[:200]}",
    )

    # L4 — limit/skip echoed.
    r = requests.get(
        f"{BASE}/admin/ledger?limit=5&skip=0", headers=hdr(tok), timeout=10
    )
    body = r.json() if r.ok else {}
    record(
        "L4 limit/skip echoed",
        r.status_code == 200 and body.get("limit") == 5 and body.get("skip") == 0,
        f"status={r.status_code} limit={body.get('limit')} skip={body.get('skip')}",
    )

    # L5 — GET /admin/ledger/txn/<bogus> → 404.
    r = requests.get(
        f"{BASE}/admin/ledger/txn/tx_charge_doesnotexist",
        headers=hdr(tok),
        timeout=10,
    )
    record(
        "L5 unknown txn → 404", r.status_code == 404,
        f"status={r.status_code} body={r.text[:200]}",
    )

    # L6 — Negative auth tests.
    r = requests.get(f"{BASE}/admin/ledger", timeout=10)
    record(
        "L6a GET /admin/ledger without auth → 401",
        r.status_code == 401,
        f"status={r.status_code}",
    )
    r = requests.get(f"{BASE}/admin/ledger/summary", timeout=10)
    record(
        "L6b GET /admin/ledger/summary without auth → 401",
        r.status_code == 401,
        f"status={r.status_code}",
    )
    r = requests.get(
        f"{BASE}/admin/ledger?category=bogus.value", headers=hdr(tok), timeout=10
    )
    record(
        "L6c invalid category → 400",
        r.status_code == 400,
        f"status={r.status_code} body={r.text[:200]}",
    )

    # L7 — Valid category filter accepts charge.gross.
    r = requests.get(
        f"{BASE}/admin/ledger?category=charge.gross", headers=hdr(tok), timeout=10
    )
    record(
        "L7 category=charge.gross → 200",
        r.status_code == 200,
        f"status={r.status_code}",
    )

    # ---- L8 — Stripe checkout-session writes payment_transactions row ----
    mongo = AsyncIOMotorClient(MONGO_URL)
    db = mongo[DB_NAME]

    group = await find_or_create_open_group(db)
    gid = group["id"]
    print(f"\n[L8] using group {gid} total={group.get('total_amount')}")

    r = requests.post(
        f"{BASE}/groups/{gid}/checkout-session",
        json={"origin_url": "http://localhost:3000"},
        timeout=20,
    )
    if r.status_code != 200:
        record("L8a POST /checkout-session → 200", False,
               f"status={r.status_code} body={r.text[:400]}")
    else:
        cbody = r.json()
        keys_present = all(k in cbody for k in ("url", "session_id", "amount", "txn_id"))
        record("L8a POST /checkout-session → 200", keys_present,
               f"status=200 keys={list(cbody.keys())}")
        txn_id = cbody.get("txn_id", "")
        record(
            "L8b txn_id starts with 'tx_charge_'",
            isinstance(txn_id, str) and txn_id.startswith("tx_charge_"),
            f"txn_id={txn_id}",
        )

        # Verify payment_transactions row.
        sess_id = cbody.get("session_id")
        pt = await db.payment_transactions.find_one({"session_id": sess_id}, {"_id": 0})
        record(
            "L8c payment_transactions row created",
            pt is not None,
            f"row keys={list(pt.keys()) if pt else 'None'}",
        )
        if pt:
            record(
                "L8d payment_transactions.txn_id matches",
                pt.get("txn_id") == txn_id,
                f"db.txn_id={pt.get('txn_id')}",
            )
            record(
                "L8e payment_transactions.ledger_posted == False",
                pt.get("ledger_posted") is False,
                f"ledger_posted={pt.get('ledger_posted')}",
            )

    # ---- L9 — Direct ledger writer test (mirrors finalization) ----
    test_txn_id = ledger.make_txn_id("charge")
    test_bill_id = "test_bill_phase3"
    test_user_id = "u_test_ledger"
    gross_cents = 10000

    record(
        "L9a make_txn_id format",
        test_txn_id.startswith("tx_charge_") and len(test_txn_id) > 12,
        f"txn_id={test_txn_id}",
    )

    rows1 = await ledger.record_charge_event(
        db,
        txn_id=test_txn_id,
        bill_id=test_bill_id,
        user_id=test_user_id,
        gross_cents=gross_cents,
        currency="usd",
        reference={"test": "phase3"},
    )
    record(
        "L9b record_charge_event returns 4 rows",
        len(rows1) == 4,
        f"len={len(rows1)} cats={[r['category'] for r in rows1]}",
    )

    # Idempotency: re-run with same txn_id.
    rows2 = await ledger.record_charge_event(
        db,
        txn_id=test_txn_id,
        bill_id=test_bill_id,
        user_id=test_user_id,
        gross_cents=gross_cents,
        currency="usd",
        reference={"test": "phase3"},
    )
    db_count = await db.ledger_entries.count_documents({"txn_id": test_txn_id})
    record(
        "L9c idempotent re-run: still 4 db rows",
        db_count == 4,
        f"db_count={db_count} returned_len={len(rows2)}",
    )

    found = await ledger.find_entries_by_txn(db, test_txn_id)
    record(
        "L9d find_entries_by_txn returns 4 rows",
        len(found) == 4,
        f"len={len(found)}",
    )

    by_cat = {r["category"]: int(r["amount_cents"]) for r in found}
    invariant_ok = (
        by_cat.get("charge.gross", 0)
        - by_cat.get("charge.processor_fee", 0)
        - by_cat.get("charge.tax", 0)
        == by_cat.get("charge.net_payable", -1)
    )
    record(
        "L9e math invariant gross - fee - tax == net_payable",
        invariant_ok,
        f"gross={by_cat.get('charge.gross')} fee={by_cat.get('charge.processor_fee')} "
        f"tax={by_cat.get('charge.tax')} net={by_cat.get('charge.net_payable')}",
    )

    # L10 — Hit admin endpoint BEFORE cleanup.
    r = requests.get(
        f"{BASE}/admin/ledger/txn/{test_txn_id}", headers=hdr(tok), timeout=10
    )
    body = r.json() if r.ok else {}
    record(
        "L10 GET /admin/ledger/txn/{txn_id} → 200, 4 entries",
        r.status_code == 200
        and isinstance(body.get("entries"), list)
        and len(body["entries"]) == 4,
        f"status={r.status_code} entries_len={len(body.get('entries', []))}",
    )

    # ---- Cleanup L9 test rows ----
    del_res = await db.ledger_entries.delete_many({"txn_id": test_txn_id})
    print(f"\n[L9-cleanup] deleted {del_res.deleted_count} test ledger rows")
    remaining = await db.ledger_entries.count_documents({"txn_id": test_txn_id})
    record(
        "L9-cleanup all test rows removed",
        remaining == 0,
        f"remaining={remaining}",
    )

    # L11 — After cleanup, summary still works.
    r = requests.get(f"{BASE}/admin/ledger/summary", headers=hdr(tok), timeout=10)
    record(
        "L11 summary still works after cleanup",
        r.status_code == 200 and isinstance(r.json().get("accounts"), dict),
        f"status={r.status_code}",
    )

    # ---- L12 — RBAC ----
    ts = int(time.time())
    role_slug = f"phase3test{ts}"  # to_slug normalises
    role_name = f"Phase3Test {ts}"
    role_id = f"role_{role_slug}"

    # Create role WITHOUT income_fees module.
    r = requests.post(
        f"{BASE}/admin/access/roles",
        json={"name": role_name, "description": "rbac test", "modules": ["dashboard"]},
        headers=hdr(tok),
        timeout=10,
    )
    role_create_ok = r.status_code in (200, 201)
    record(
        "L12a create role without income_fees",
        role_create_ok,
        f"status={r.status_code} body={r.text[:200]}",
    )
    if role_create_ok:
        rb = r.json()
        role_slug = rb.get("slug") or role_slug
        role_id = rb.get("id") or f"role_{role_slug}"

    test_admin_email = f"phase3test{ts}@squadpay.us"
    test_admin_pwd = "Phase3Test#2026!"
    admin_id = None

    if role_create_ok:
        # Create admin in that role.
        r = requests.post(
            f"{BASE}/admin/admins",
            json={
                "email": test_admin_email,
                "password": test_admin_pwd,
                "name": "Phase3 Test Admin",
                "role": role_slug,
            },
            headers=hdr(tok),
            timeout=10,
        )
        record(
            "L12b create test admin in restricted role",
            r.status_code == 200,
            f"status={r.status_code} body={r.text[:200]}",
        )
        if r.status_code == 200:
            admin_id = r.json().get("id")

            # Log in as that admin.
            r2 = requests.post(
                f"{BASE}/admin/auth/login",
                json={"email": test_admin_email, "password": test_admin_pwd},
                timeout=10,
            )
            restricted_tok = r2.json().get("token") if r2.status_code == 200 else None
            record(
                "L12c restricted admin login",
                bool(restricted_tok),
                f"status={r2.status_code}",
            )

            if restricted_tok:
                # Hit /admin/ledger → expect 403 (module gate).
                r3 = requests.get(
                    f"{BASE}/admin/ledger", headers=hdr(restricted_tok), timeout=10
                )
                record(
                    "L12d restricted admin → /admin/ledger → 403",
                    r3.status_code == 403,
                    f"status={r3.status_code} body={r3.text[:200]}",
                )

                # Now add income_fees to role via PUT.
                r4 = requests.put(
                    f"{BASE}/admin/access/roles/{role_id}",
                    json={"modules": ["dashboard", "income_fees"]},
                    headers=hdr(tok),
                    timeout=10,
                )
                record(
                    "L12e PUT role to add income_fees",
                    r4.status_code == 200,
                    f"status={r4.status_code} body={r4.text[:200]}",
                )

                # Re-hit /admin/ledger → expect 200.
                r5 = requests.get(
                    f"{BASE}/admin/ledger", headers=hdr(restricted_tok), timeout=10
                )
                record(
                    "L12f restricted admin (now with income_fees) → 200",
                    r5.status_code == 200,
                    f"status={r5.status_code}",
                )

    # ---- Cleanup admin + role ----
    if admin_id:
        d = requests.delete(
            f"{BASE}/admin/admins/{admin_id}", headers=hdr(tok), timeout=10
        )
        print(f"[L12-cleanup] delete admin status={d.status_code}")
    if role_create_ok:
        d = requests.delete(
            f"{BASE}/admin/access/roles/{role_id}", headers=hdr(tok), timeout=10
        )
        print(f"[L12-cleanup] delete role status={d.status_code}")

    mongo.close()

    # ---- Summary ----
    print("\n=== Phase 3 Ledger Summary ===")
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    failed = [r for r in results if not r["ok"]]
    print(f"Passed {passed}/{total}")
    if failed:
        print("\nFAILED:")
        for r in failed:
            print(f"  ❌ {r['name']} — {r['detail']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
