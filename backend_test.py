"""Backend test — Phase 5a Stripe Connect Express payout adapter (P5b-be.1–10).

Runs against the live preview backend. Cleans up after itself.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
import asyncio
import requests
from typing import Any, Dict, Optional

BACKEND = os.environ.get("BACKEND_URL", "https://joint-pay-1.preview.emergentagent.com").rstrip("/")
API = f"{BACKEND}/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"

_results: list = []
_failures: list = []
_cleanup_user_ids: list = []
_cleanup_group_ids: list = []
_cleanup_payout_card_ids: list = []
_cleanup_connect_account_user_ids: list = []
_cleanup_ledger_txn_ids: list = []


def _log(name: str, ok: bool, detail: str = "") -> None:
    tag = "✅" if ok else "❌"
    print(f"{tag} {name} {('— ' + detail) if detail else ''}".rstrip())
    _results.append((name, ok, detail))
    if not ok:
        _failures.append((name, detail))


def _assert(name: str, cond: bool, detail: str = "") -> bool:
    _log(name, cond, detail)
    return cond


def _post(path: str, **kwargs) -> requests.Response:
    return requests.post(f"{API}{path}", timeout=60, **kwargs)


def _get(path: str, **kwargs) -> requests.Response:
    return requests.get(f"{API}{path}", timeout=60, **kwargs)


def admin_login() -> str:
    r = _post("/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        raise RuntimeError(f"Admin login failed: {r.status_code} {r.text}")
    j = r.json()
    token = j.get("access_token") or j.get("token")
    if not token:
        raise RuntimeError(f"No access_token in login response: {r.text}")
    return token


def make_user_session(name: str) -> Dict[str, str]:
    phone = f"+1555{int(time.time() * 1000) % 10000000:07d}"
    r = _post("/auth/register", json={"name": name})
    if r.status_code != 200:
        raise RuntimeError(f"Register failed: {r.status_code} {r.text}")
    uid = r.json()["id"]
    _cleanup_user_ids.append(uid)

    r = _post("/auth/send-otp", json={"user_id": uid, "phone": phone})
    if r.status_code != 200:
        raise RuntimeError(f"send-otp failed: {r.status_code} {r.text}")
    r = _post("/auth/verify-otp", json={"user_id": uid, "phone": phone, "code": "123456"})
    if r.status_code != 200:
        raise RuntimeError(f"verify-otp failed: {r.status_code} {r.text}")
    payload = r.json()
    return {"id": payload["id"], "session_id": payload["session_id"], "phone": phone}


def gateways_state(token: str) -> Dict[str, Any]:
    r = _get("/admin/gateways", headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


def activate_provider(token: str, group: str, slug: str) -> requests.Response:
    return _post(
        f"/admin/gateways/{group}/activate",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider_slug": slug},
    )


def p1(token: str) -> None:
    print("\n── P5b-be.1 — admin/gateways shows stripe_connect active ──")
    s = gateways_state(token)
    active = (s.get("active") or {})
    _assert(
        "P1.active.payout==stripe_connect",
        active.get("payout") == "stripe_connect",
        detail=f"active={active}",
    )


def p2(user: Dict[str, str]) -> Optional[str]:
    print("\n── P5b-be.2 — /payout/authorize-url (Stripe Connect) ──")
    body = {
        "user_id": user["id"],
        "session_id": user["session_id"],
        "return_url": "https://example.com/return",
        "refresh_url": "https://example.com/refresh",
    }
    r = _post("/payout/authorize-url", json=body)
    if not _assert("P2.status==200", r.status_code == 200, detail=f"{r.status_code} {r.text[:300]}"):
        return None
    j = r.json()
    _assert("P2.gateway_slug==stripe_connect", j.get("gateway_slug") == "stripe_connect", str(j))
    _assert("P2.kind==account_onboarding", j.get("kind") == "account_onboarding", str(j))
    url = j.get("url") or ""
    _assert(
        "P2.url starts with https://connect.stripe.com/setup/e/",
        url.startswith("https://connect.stripe.com/setup/e/"),
        detail=url[:120],
    )
    acct = j.get("account_id") or ""
    _assert("P2.account_id starts with acct_", acct.startswith("acct_"), detail=acct)
    _cleanup_connect_account_user_ids.append(user["id"])

    async def _check_db():
        cli = AsyncIOMotorClient(MONGO_URL)
        try:
            db = cli[DB_NAME]
            row = await db.connect_user_accounts.find_one(
                {"user_id": user["id"], "gateway_slug": "stripe_connect"},
                {"_id": 0},
            )
            return row
        finally:
            cli.close()

    row = asyncio.get_event_loop().run_until_complete(_check_db())
    _assert("P2.db.connect_user_accounts row exists", bool(row), str(row))
    if row:
        _assert("P2.db.account_id matches", row.get("account_id") == acct, f"{row.get('account_id')} vs {acct}")

    r2 = _post("/payout/authorize-url", json=body)
    if _assert("P2.idem.status==200", r2.status_code == 200, detail=f"{r2.status_code} {r2.text[:200]}"):
        j2 = r2.json()
        _assert(
            "P2.idem.same account_id (no duplicate Express account)",
            j2.get("account_id") == acct,
            detail=f"first={acct} second={j2.get('account_id')}",
        )
        url2 = j2.get("url") or ""
        _assert(
            "P2.idem.url is fresh https://connect.stripe.com/setup/e/...",
            url2.startswith("https://connect.stripe.com/setup/e/"),
            detail=url2[:120],
        )
    return acct


def p3(user: Dict[str, str]) -> None:
    print("\n── P5b-be.3 — /payout/sync-after-onboarding ──")
    r = _post(
        "/payout/sync-after-onboarding",
        json={"user_id": user["id"], "session_id": user["session_id"]},
    )
    if not _assert("P3.status==200", r.status_code == 200, detail=f"{r.status_code} {r.text[:300]}"):
        return
    j = r.json()
    _assert("P3.details_submitted==false", j.get("details_submitted") is False, detail=str(j))
    _assert("P3.payouts_enabled==false", j.get("payouts_enabled") is False, detail=str(j))
    _assert(
        "P3.requirements_due is list",
        isinstance(j.get("requirements_due"), list),
        detail=str(j.get("requirements_due"))[:200],
    )
    _assert("P3.cards == []", j.get("cards") == [], detail=str(j.get("cards"))[:200])

    async def _check_db():
        cli = AsyncIOMotorClient(MONGO_URL)
        try:
            db = cli[DB_NAME]
            return await db.connect_user_accounts.find_one(
                {"user_id": user["id"], "gateway_slug": "stripe_connect"}, {"_id": 0}
            )
        finally:
            cli.close()

    row = asyncio.get_event_loop().run_until_complete(_check_db())
    if row:
        _assert("P3.db.details_submitted==false", row.get("details_submitted") is False, str(row))
        _assert("P3.db.payouts_enabled==false", row.get("payouts_enabled") is False, str(row))


def p4(user: Dict[str, str]) -> None:
    print("\n── P5b-be.4 — GET /payout/cards ──")
    r = _get(
        "/payout/cards",
        params={"user_id": user["id"], "session_id": user["session_id"]},
    )
    if not _assert("P4.status==200", r.status_code == 200, detail=f"{r.status_code} {r.text[:300]}"):
        return
    j = r.json()
    _assert("P4.items==[]", j.get("items") == [], detail=str(j.get("items"))[:200])
    _assert("P4.gateway_slug==stripe_connect", j.get("gateway_slug") == "stripe_connect", str(j))


async def _setup_paid_group_with_balance(user_id: str) -> str:
    from ledger import make_txn_id, record_charge_event  # type: ignore

    cli = AsyncIOMotorClient(MONGO_URL)
    try:
        db = cli[DB_NAME]
        gid = f"g_test_{uuid.uuid4().hex[:12]}"
        group = {
            "id": gid,
            "code": f"TEST{uuid.uuid4().hex[:6].upper()}",
            "lead_id": user_id,
            "title": "P5b-be test group",
            "total_amount": 50.0,
            "original_total_amount": 50.0,
            "tax": 0.0,
            "tip": 0.0,
            "split_mode": "fast",
            "status": "paid",
            "funding_mode": "group",
            "items": [],
            "members": [{"user_id": user_id, "role": "lead", "joined_at": "2025-06-01T00:00:00Z"}],
            "assignments": [],
            "contributions": [],
            "repayments": [],
            "created_at": "2025-06-01T00:00:00Z",
        }
        await db.groups.insert_one(group)

        txn = make_txn_id("charge")
        await record_charge_event(
            db,
            txn_id=txn,
            bill_id=gid,
            user_id=user_id,
            gross_cents=5000,
            currency="usd",
            reference={"test": "P5b-be setup"},
        )
        _cleanup_ledger_txn_ids.append(txn)
        _cleanup_group_ids.append(gid)
        return gid
    finally:
        cli.close()


def p5_p6(user: Dict[str, str]) -> None:
    print("\n── P5b-be.5 — push-to-card before onboarding → 412 ──")
    loop = asyncio.get_event_loop()
    gid = loop.run_until_complete(_setup_paid_group_with_balance(user["id"]))

    card_id = "card_fake"

    async def _ensure_card_row():
        cli = AsyncIOMotorClient(MONGO_URL)
        try:
            db = cli[DB_NAME]
            await db.payout_user_cards.delete_many({"id": card_id, "user_id": user["id"]})
            await db.payout_user_cards.insert_one({
                "id": card_id,
                "user_id": user["id"],
                "gateway_slug": "stripe_connect",
                "brand": "visa",
                "last4": "4242",
                "is_active": True,
                "is_default": True,
                "created_at": "2025-06-01T00:00:00Z",
                "updated_at": "2025-06-01T00:00:00Z",
            })
            _cleanup_payout_card_ids.append(card_id)
        finally:
            cli.close()

    loop.run_until_complete(_ensure_card_row())

    r = _post(
        "/payout/push-to-card",
        json={
            "user_id": user["id"],
            "session_id": user["session_id"],
            "group_id": gid,
            "card_id": card_id,
            "amount": 10.00,
        },
    )
    _assert(
        "P5.status==412 with 'Stripe Connect onboarding incomplete'",
        r.status_code == 412 and "Stripe Connect onboarding incomplete" in (r.text or ""),
        detail=f"{r.status_code} {r.text[:300]}",
    )

    print("\n── P5b-be.6 — push-to-card amount > available → 409 ──")

    async def _force_enabled():
        cli = AsyncIOMotorClient(MONGO_URL)
        try:
            db = cli[DB_NAME]
            await db.connect_user_accounts.update_one(
                {"user_id": user["id"], "gateway_slug": "stripe_connect"},
                {"$set": {"payouts_enabled": True, "details_submitted": True}},
            )
        finally:
            cli.close()

    loop.run_until_complete(_force_enabled())

    r = _post(
        "/payout/push-to-card",
        json={
            "user_id": user["id"],
            "session_id": user["session_id"],
            "group_id": gid,
            "card_id": card_id,
            "amount": 9999.99,
        },
    )
    _assert(
        "P6.status==409 with 'exceeds available cash-out balance'",
        r.status_code == 409 and "exceeds available cash-out balance" in (r.text or ""),
        detail=f"{r.status_code} {r.text[:300]}",
    )


def p7(token: str) -> None:
    print("\n── P5b-be.7 — /webhook/stripe-connect missing signature ──")
    # The adapter checks `webhook_secret` BEFORE `signature`. If admin hasn't
    # configured a webhook secret, the no-secret 503 branch fires first and the
    # outer route wraps it as 400 "Webhook error: 503: ... not configured".
    # That's misleading — the real test target is the missing-signature path.
    # We seed a dummy webhook_secret via the existing PUT endpoint so we can
    # exercise the actual missing-signature branch the review request targets.
    seed = _post(
        "/admin/gateways/payout/stripe_connect",
        headers={"Authorization": f"Bearer {token}"},
        json={"credentials": {"webhook_secret": "whsec_test_dummy_for_unit_test"}},
    )
    print(f"   [seed webhook_secret] {seed.status_code} {seed.text[:200]}")
    if seed.status_code != 200:
        # PUT not allowed via POST? Try PUT.
        import json as _json
        seed = requests.put(
            f"{API}/admin/gateways/payout/stripe_connect",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            data=_json.dumps({"credentials": {"webhook_secret": "whsec_test_dummy_for_unit_test"}}),
            timeout=30,
        )
        print(f"   [seed webhook_secret PUT] {seed.status_code} {seed.text[:200]}")
    # ACTUAL HTTP-request to the webhook endpoint with NO Stripe-Signature header.
    r = _post("/webhook/stripe-connect", data=b'{"id":"evt_test"}')
    _assert(
        "P7.status==400 with 'Missing Stripe-Signature header'",
        r.status_code == 400 and "Missing Stripe-Signature header" in (r.text or ""),
        detail=f"{r.status_code} {r.text[:300]}",
    )
    # Best-effort: clear the dummy secret to leave state as we found it.
    _post(
        "/admin/gateways/payout/stripe_connect",
        headers={"Authorization": f"Bearer {token}"},
        json={"credentials": {"webhook_secret": ""}},
    )


def p8() -> None:
    print("\n── P5b-be.8 — Branch/Wise scaffolds raise HTTPException(501) ──")
    from adapters.payout_scaffolds import BranchPayoutAdapter, WisePayoutAdapter  # type: ignore
    from fastapi import HTTPException

    for name, cls in (("Branch", BranchPayoutAdapter), ("Wise", WisePayoutAdapter)):
        a = cls()
        try:
            asyncio.get_event_loop().run_until_complete(
                a.push_to_card(
                    amount_cents=100, currency="usd", card_token="x|y",
                    idempotency_key="x", metadata={},
                )
            )
            _assert(f"P8.{name} push_to_card raised 501", False, "did NOT raise")
        except HTTPException as e:
            _assert(f"P8.{name} push_to_card raised 501", e.status_code == 501, f"status={e.status_code}")
        except Exception as e:
            _assert(f"P8.{name} push_to_card raised 501", False, f"raised {type(e).__name__}: {e}")


def p9(token: str, user: Dict[str, str]) -> None:
    print("\n── P5b-be.9 — switch payout provider stripe_connect ↔ astra ──")
    r = activate_provider(token, "payout", "astra")
    if not _assert("P9.activate astra==200", r.status_code == 200, detail=f"{r.status_code} {r.text[:300]}"):
        return
    s = gateways_state(token)
    _assert("P9.active.payout==astra", (s.get("active") or {}).get("payout") == "astra", str(s.get("active")))

    r = _post(
        "/payout/authorize-url",
        json={
            "user_id": user["id"],
            "session_id": user["session_id"],
            "return_url": "https://example.com/return",
        },
    )
    if _assert("P9.astra authorize-url status==200", r.status_code == 200, detail=f"{r.status_code} {r.text[:300]}"):
        j = r.json()
        _assert("P9.astra gateway_slug==astra", j.get("gateway_slug") == "astra", str(j))
        _assert("P9.astra kind==oauth_authorize", j.get("kind") == "oauth_authorize", str(j))
        url = j.get("url") or ""
        _assert(
            "P9.astra url starts https://sandbox.astra.finance/oauth/authorize?",
            url.startswith("https://sandbox.astra.finance/oauth/authorize?"),
            detail=url[:120],
        )

    r = activate_provider(token, "payout", "stripe_connect")
    _assert("P9.activate stripe_connect==200", r.status_code == 200, detail=f"{r.status_code} {r.text[:300]}")
    s = gateways_state(token)
    _assert(
        "P9.active.payout==stripe_connect (after switch back)",
        (s.get("active") or {}).get("payout") == "stripe_connect",
        str(s.get("active")),
    )

    r = _post(
        "/payout/authorize-url",
        json={
            "user_id": user["id"],
            "session_id": user["session_id"],
            "return_url": "https://example.com/return",
            "refresh_url": "https://example.com/refresh",
        },
    )
    if _assert("P9.back authorize-url status==200", r.status_code == 200, detail=f"{r.status_code} {r.text[:300]}"):
        j = r.json()
        _assert("P9.back gateway_slug==stripe_connect", j.get("gateway_slug") == "stripe_connect", str(j))
        _assert("P9.back kind==account_onboarding", j.get("kind") == "account_onboarding", str(j))


def p10(user: Dict[str, str]) -> None:
    print("\n── P5b-be.10 — Phase 3 + Phase 4 regression ──")

    async def _ledger_test():
        from ledger import make_txn_id, record_charge_event, find_entries_by_txn  # type: ignore
        cli = AsyncIOMotorClient(MONGO_URL)
        try:
            db = cli[DB_NAME]
            txn = make_txn_id("charge")
            _cleanup_ledger_txn_ids.append(txn)
            rows1 = await record_charge_event(
                db,
                txn_id=txn,
                bill_id="g_regression_test",
                user_id=user["id"],
                gross_cents=5000,
                currency="usd",
                reference={"regression": True},
            )
            assert len(rows1) == 4, f"expected 4 rows got {len(rows1)}"
            cats = sorted(r["category"] for r in rows1)
            assert cats == [
                "charge.gross", "charge.net_payable", "charge.processor_fee", "charge.tax",
            ], f"unexpected categories: {cats}"
            by = {r["category"]: r["amount_cents"] for r in rows1}
            assert by["charge.gross"] - by["charge.processor_fee"] - by["charge.tax"] == by["charge.net_payable"]
            rows2 = await record_charge_event(
                db, txn_id=txn, bill_id="g_regression_test", user_id=user["id"],
                gross_cents=5000, currency="usd",
            )
            total_for_txn = await find_entries_by_txn(db, txn)
            assert len(total_for_txn) == 4, f"idem expected 4 rows still got {len(total_for_txn)}"
            return True
        finally:
            cli.close()

    try:
        ok = asyncio.get_event_loop().run_until_complete(_ledger_test())
        _assert("P10.A ledger.record_charge_event 4 rows + idem + math invariant", bool(ok))
    except Exception as e:
        _assert("P10.A ledger.record_charge_event 4 rows + idem + math invariant", False, f"{type(e).__name__}: {e}")

    name = f"P10Lead{int(time.time())}"
    lead = make_user_session(name)
    r = _post("/groups", json={
        "lead_id": lead["id"],
        "title": "Regression checkout test",
        "total_amount": 25.0,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    })
    if not _assert("P10.B create group==200", r.status_code == 200, detail=f"{r.status_code} {r.text[:300]}"):
        return
    gid = r.json()["id"]
    _cleanup_group_ids.append(gid)

    r = _post(f"/groups/{gid}/checkout-session", json={
        "origin_url": "http://localhost:3000",
    })
    if _assert("P10.B checkout-session==200", r.status_code == 200, detail=f"{r.status_code} {r.text[:400]}"):
        j = r.json()
        url = j.get("url") or ""
        sid = j.get("session_id") or ""
        _assert("P10.B Stripe url returned", "stripe.com" in url, detail=url[:120])
        _assert("P10.B session_id starts cs_", sid.startswith("cs_"), detail=sid)


async def _cleanup() -> None:
    cli = AsyncIOMotorClient(MONGO_URL)
    try:
        db = cli[DB_NAME]
        if _cleanup_user_ids:
            await db.users.delete_many({"id": {"$in": _cleanup_user_ids}})
            await db.otp_codes.delete_many({"user_id": {"$in": _cleanup_user_ids}})
        if _cleanup_group_ids:
            await db.groups.delete_many({"id": {"$in": _cleanup_group_ids}})
            await db.ledger_entries.delete_many({"bill_id": {"$in": _cleanup_group_ids}})
        if _cleanup_payout_card_ids:
            await db.payout_user_cards.delete_many({"id": {"$in": _cleanup_payout_card_ids}})
        if _cleanup_connect_account_user_ids:
            await db.connect_user_accounts.delete_many(
                {"user_id": {"$in": _cleanup_connect_account_user_ids}}
            )
        if _cleanup_ledger_txn_ids:
            await db.ledger_entries.delete_many({"txn_id": {"$in": _cleanup_ledger_txn_ids}})
        await db.ledger_entries.delete_many({"bill_id": "g_regression_test"})
    finally:
        cli.close()


def main() -> int:
    print(f"BACKEND={BACKEND}")
    token = admin_login()
    print(f"Admin logged in OK (token len={len(token)})")

    p1(token)

    user = make_user_session(f"P5bLead{int(time.time())}")
    print(f"Created user {user['id']} session={user['session_id'][:8]}...")

    p2(user)
    p3(user)
    p4(user)
    p5_p6(user)
    p7(token)
    p8()
    user2 = make_user_session(f"P9User{int(time.time())}")
    p9(token, user2)
    activate_provider(token, "payout", "stripe_connect")
    p10(user)

    print("\n── Cleaning up test data ──")
    try:
        asyncio.get_event_loop().run_until_complete(_cleanup())
        print("Cleanup OK")
    except Exception as e:
        print(f"Cleanup error (non-fatal): {e}")

    print("\n" + "═" * 80)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = len(_results) - passed
    print(f"RESULTS: {passed}/{len(_results)} passed, {failed} failed")
    if _failures:
        print("\nFAILURES:")
        for n, d in _failures:
            print(f"  ❌ {n}: {d}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
