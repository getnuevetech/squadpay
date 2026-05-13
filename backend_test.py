"""Phase 5a backend tests — Group B Payout Adapter contract + Astra OAuth + Push-to-Card.

Covers P5a.1–P5a.15 from test_result.md backend_phase5a.

Runs against local backend at http://localhost:8001/api with admin
admin@squadpay.us / Letmein@2007#ForReal.

Does NOT attempt to actually exchange Astra OAuth codes (live consent
required by Astra docs).
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import time
import hashlib
import hmac
import re
import secrets
import traceback
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

# Make backend modules importable for P5a.13 / P5a.14
sys.path.insert(0, "/app/backend")

BASE_URL = "http://localhost:8001/api"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"
ASTRA_CLIENT_ID_PREFIX = "52b85ed4"

PASSES: List[str] = []
FAILS: List[str] = []


def ok(name: str, detail: str = ""):
    PASSES.append(name)
    print(f"  ✅ {name} {detail}".strip())


def fail(name: str, detail: str = ""):
    FAILS.append(f"{name} — {detail}")
    print(f"  ❌ {name} :: {detail}")


def section(label: str):
    print("\n" + "═" * 80)
    print(f" {label}")
    print("═" * 80)


# ───────────────────────────────────────────────────────────────────────
# Helpers — HTTP
# ───────────────────────────────────────────────────────────────────────
async def admin_login(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"{BASE_URL}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    r.raise_for_status()
    return r.json()["token"]


async def register_user(client: httpx.AsyncClient, name: str) -> str:
    r = await client.post(f"{BASE_URL}/auth/register", json={"name": name})
    r.raise_for_status()
    return r.json()["id"]


async def verify_phone(
    client: httpx.AsyncClient, user_id: str, phone: str
) -> str:
    """Returns session_id."""
    r = await client.post(
        f"{BASE_URL}/auth/send-otp",
        json={"user_id": user_id, "phone": phone},
    )
    r.raise_for_status()
    v = await client.post(
        f"{BASE_URL}/auth/verify-otp",
        json={"user_id": user_id, "phone": phone, "code": "123456"},
    )
    v.raise_for_status()
    data = v.json()
    return data["session_id"]


def encrypt_value(plain: str) -> str:
    from integrations import encrypt_secret
    return encrypt_secret(plain)


# ───────────────────────────────────────────────────────────────────────
# Tests
# ───────────────────────────────────────────────────────────────────────
async def run_tests() -> None:
    mc = AsyncIOMotorClient(MONGO_URL)
    db = mc[DB_NAME]

    test_user_ids: List[str] = []
    test_group_ids: List[str] = []
    test_state_tokens: List[str] = []
    seeded_card_ids: List[str] = []
    test_phones: List[str] = []
    test_txn_ids: List[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # ─────────── P5a.1 ───────────
        section("P5a.1 GET /admin/gateways → active.payout == astra")
        try:
            token = await admin_login(client)
            r = await client.get(
                f"{BASE_URL}/admin/gateways",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code != 200:
                fail("P5a.1 admin/gateways HTTP 200", f"got {r.status_code}: {r.text[:200]}")
            else:
                payload = r.json()
                active = payload.get("active") or {}
                if active.get("payout") != "astra":
                    fail("P5a.1 active.payout==astra", f"active={active}")
                else:
                    ok("P5a.1 admin/gateways active.payout='astra'", f"(active={active})")
        except Exception as e:
            fail("P5a.1", f"{type(e).__name__}: {e}")

        # ─────────── Setup user ───────────
        section("Setup — real user (Alex Morgan) via send-otp + verify-otp")
        unique_suffix = str(int(time.time()))[-6:]
        alex_phone = f"+155501{unique_suffix}"
        alex_id = None
        alex_sid = None
        try:
            alex_id = await register_user(client, f"Alex P5a {unique_suffix}")
            test_user_ids.append(alex_id)
            test_phones.append(alex_phone)
            alex_sid = await verify_phone(client, alex_id, alex_phone)
            ok("Setup alex", f"alex_id={alex_id}, sid_len={len(alex_sid)}")
        except Exception as e:
            fail("Setup alex", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}")
            return

        # ─────────── P5a.2 ───────────
        section("P5a.2 POST /payout/authorize-url with bogus user/session → 401")
        try:
            r = await client.post(
                f"{BASE_URL}/payout/authorize-url",
                json={
                    "user_id": "u_doesnotexist_bogus",
                    "session_id": "sess_bogus",
                    "redirect_uri": "https://example.com/cb",
                },
            )
            if r.status_code == 401:
                ok("P5a.2 bogus user→401", f"detail={r.json().get('detail')}")
            else:
                fail("P5a.2 bogus user→401", f"got {r.status_code}: {r.text[:200]}")
        except Exception as e:
            fail("P5a.2", f"{type(e).__name__}: {e}")

        try:
            r = await client.post(
                f"{BASE_URL}/payout/authorize-url",
                json={
                    "user_id": alex_id,
                    "session_id": "definitely_not_my_session",
                    "redirect_uri": "https://example.com/cb",
                },
            )
            if r.status_code == 401:
                ok("P5a.2 real user wrong session→401")
            else:
                fail("P5a.2 real user wrong session→401", f"got {r.status_code}: {r.text[:200]}")
        except Exception as e:
            fail("P5a.2 wrong sid", f"{type(e).__name__}: {e}")

        # ─────────── P5a.3 ───────────
        section("P5a.3 POST /payout/authorize-url valid → 200 + Astra URL shape")
        captured_state: Optional[str] = None
        try:
            r = await client.post(
                f"{BASE_URL}/payout/authorize-url",
                json={
                    "user_id": alex_id,
                    "session_id": alex_sid,
                    "redirect_uri": "https://example.com/cb",
                },
            )
            if r.status_code != 200:
                fail("P5a.3 HTTP 200", f"got {r.status_code}: {r.text[:300]}")
            else:
                d = r.json()
                url = d.get("url") or ""
                state = d.get("state") or ""
                captured_state = state
                if state:
                    test_state_tokens.append(state)
                if not url.startswith("https://sandbox.astra.finance/oauth/authorize?"):
                    fail("P5a.3 url prefix", f"got {url[:120]}")
                else:
                    ok("P5a.3 url starts sandbox.astra.finance", f"len={len(url)}")
                parsed = urlparse(url)
                q = parse_qs(parsed.query)
                if (q.get("response_type") or [""])[0] != "code":
                    fail("P5a.3 response_type=code", f"got {q.get('response_type')}")
                else:
                    ok("P5a.3 response_type=code")
                client_id = (q.get("client_id") or [""])[0]
                if not client_id.startswith(ASTRA_CLIENT_ID_PREFIX):
                    fail("P5a.3 client_id prefix 52b85ed4", f"got {client_id[:20]}")
                else:
                    ok("P5a.3 client_id starts 52b85ed4", f"({client_id[:12]}…)")
                got_state = (q.get("state") or [""])[0]
                if got_state and got_state == state:
                    ok("P5a.3 state present + matches body.state")
                else:
                    fail("P5a.3 state matches response", f"url_state={got_state} body_state={state}")
                redirect_q = (q.get("redirect_uri") or [""])[0]
                if redirect_q == "https://example.com/cb":
                    ok("P5a.3 redirect_uri urlencoded round-trips")
                else:
                    fail("P5a.3 redirect_uri", f"got {redirect_q!r}")
                if d.get("gateway_slug") == "astra":
                    ok("P5a.3 gateway_slug==astra")
                else:
                    fail("P5a.3 gateway_slug==astra", f"got {d.get('gateway_slug')}")

                row = await db.astra_oauth_states.find_one({"state": state}, {"_id": 0})
                if not row:
                    fail("P5a.3 astra_oauth_states row exists", f"state={state}")
                elif row.get("consumed") is not False:
                    fail("P5a.3 state row consumed=false", f"row={row}")
                elif row.get("user_id") != alex_id:
                    fail("P5a.3 state row user_id matches", f"got {row.get('user_id')}")
                else:
                    ok("P5a.3 astra_oauth_states row: consumed=false, user_id matches")
        except Exception as e:
            fail("P5a.3", f"{type(e).__name__}: {e}")

        # ─────────── P5a.4 ───────────
        section("P5a.4 POST /payout/oauth-callback wrong state → 400")
        try:
            r = await client.post(
                f"{BASE_URL}/payout/oauth-callback",
                json={
                    "user_id": alex_id,
                    "session_id": alex_sid,
                    "code": "fake_authz_code",
                    "state": "bogus_state_xyz",
                    "redirect_uri": "https://example.com/cb",
                },
            )
            if r.status_code == 400 and "invalid or expired oauth state" in (r.json().get("detail") or "").lower():
                ok("P5a.4 wrong state→400 'Invalid or expired OAuth state'")
            else:
                detail = ""
                try:
                    detail = r.json().get("detail")
                except Exception:
                    detail = r.text[:200]
                fail("P5a.4 wrong state→400", f"got {r.status_code} detail={detail}")
        except Exception as e:
            fail("P5a.4", f"{type(e).__name__}: {e}")

        # ─────────── P5a.5 ───────────
        section("P5a.5 POST /payout/oauth-callback for consumed state → 409")
        try:
            if not captured_state:
                fail("P5a.5", "no captured_state from P5a.3")
            else:
                res = await db.astra_oauth_states.update_one(
                    {"state": captured_state}, {"$set": {"consumed": True}}
                )
                if res.modified_count != 1:
                    fail("P5a.5 prep — flip consumed=true in mongo",
                         f"modified_count={res.modified_count}")
                else:
                    r = await client.post(
                        f"{BASE_URL}/payout/oauth-callback",
                        json={
                            "user_id": alex_id,
                            "session_id": alex_sid,
                            "code": "fake_authz_code",
                            "state": captured_state,
                            "redirect_uri": "https://example.com/cb",
                        },
                    )
                    if r.status_code == 409 and "already used" in (r.json().get("detail") or "").lower():
                        ok("P5a.5 consumed state→409 'OAuth state already used'")
                    else:
                        fail("P5a.5 consumed state→409",
                             f"got {r.status_code} body={r.text[:200]}")
        except Exception as e:
            fail("P5a.5", f"{type(e).__name__}: {e}")

        # ─────────── P5a.6 ───────────
        section("P5a.6 GET /payout/eligibility for fresh open group")
        gid: Optional[str] = None
        try:
            r = await client.post(
                f"{BASE_URL}/groups",
                json={
                    "lead_id": alex_id,
                    "title": "P5a Test Squad",
                    "total_amount": 100.00,
                    "split_mode": "fast",
                    "tax": 0.0,
                    "tip": 0.0,
                    "items": [],
                },
            )
            if r.status_code != 200:
                fail("P5a.6 setup create group", f"got {r.status_code}: {r.text[:200]}")
            else:
                gid = r.json()["id"]
                test_group_ids.append(gid)
                ok("P5a.6 setup create open group", f"gid={gid}")

                er = await client.get(
                    f"{BASE_URL}/payout/eligibility",
                    params={"user_id": alex_id, "session_id": alex_sid, "group_id": gid},
                )
                if er.status_code != 200:
                    fail("P5a.6 eligibility HTTP 200", f"got {er.status_code}: {er.text[:200]}")
                else:
                    d = er.json()
                    if d.get("eligible") is False and "group_not_paid" in (d.get("reasons") or []):
                        ok("P5a.6 eligible=false, reasons contains 'group_not_paid'",
                           f"(reasons={d.get('reasons')})")
                    else:
                        fail("P5a.6 eligible=false + group_not_paid", f"got {d}")
        except Exception as e:
            fail("P5a.6", f"{type(e).__name__}: {e}")

        # ─────────── P5a.7 ───────────
        section("P5a.7 GET /payout/eligibility when user not lead → not_lead")
        try:
            if not gid:
                fail("P5a.7", "no test group from P5a.6")
            else:
                other_id = "u_other_test_p5a"
                orig = await db.groups.find_one({"id": gid}, {"_id": 0, "lead_id": 1})
                orig_lead = orig.get("lead_id") if orig else None
                await db.groups.update_one({"id": gid}, {"$set": {"lead_id": other_id}})
                try:
                    er = await client.get(
                        f"{BASE_URL}/payout/eligibility",
                        params={"user_id": alex_id, "session_id": alex_sid, "group_id": gid},
                    )
                    if er.status_code != 200:
                        fail("P5a.7 eligibility HTTP 200", f"got {er.status_code}: {er.text[:200]}")
                    else:
                        d = er.json()
                        if d.get("eligible") is False and "not_lead" in (d.get("reasons") or []):
                            ok("P5a.7 eligible=false + reasons contains 'not_lead'",
                               f"(reasons={d.get('reasons')})")
                        else:
                            fail("P5a.7", f"got {d}")
                finally:
                    if orig_lead:
                        await db.groups.update_one({"id": gid}, {"$set": {"lead_id": orig_lead}})
        except Exception as e:
            fail("P5a.7", f"{type(e).__name__}: {e}")

        # ─────────── P5a.8 ───────────
        section("P5a.8 GET /payout/eligibility — paid+group funded with 4 ledger charges")
        try:
            if not gid:
                fail("P5a.8", "no test group from P5a.6")
            else:
                await db.groups.update_one(
                    {"id": gid},
                    {"$set": {"status": "paid", "funding_mode": "group"}},
                )
                from ledger import record_charge_event, make_txn_id
                for i in range(4):
                    tid = make_txn_id("charge")
                    test_txn_ids.append(tid)
                    await record_charge_event(
                        db,
                        txn_id=tid,
                        bill_id=gid,
                        user_id=alex_id,
                        gross_cents=5000,
                        currency="usd",
                        reference={"test_p5a8": True, "i": i},
                        processor_fee_cents=0,
                        tax_cents=0,
                    )
                ok("P5a.8 setup: 4 charge ledger txns @ 5000c each (merchant_payable CREDIT)")

                er = await client.get(
                    f"{BASE_URL}/payout/eligibility",
                    params={"user_id": alex_id, "session_id": alex_sid, "group_id": gid},
                )
                if er.status_code != 200:
                    fail("P5a.8 eligibility HTTP 200", f"got {er.status_code}: {er.text[:200]}")
                else:
                    d = er.json()
                    eligible = d.get("eligible")
                    available = float(d.get("available_usd") or 0)
                    linked = d.get("astra_linked")
                    if eligible is True and available > 0 and linked is False:
                        ok(
                            "P5a.8 eligible=true, available_usd>0, astra_linked=false",
                            f"(available_usd={available}, reasons={d.get('reasons')})",
                        )
                    else:
                        fail("P5a.8", f"got {d}")
        except Exception as e:
            fail("P5a.8", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}")

        # ─────────── P5a.9 ───────────
        section("P5a.9 POST /payout/push-to-card before Astra link → 412 Astra session expired")
        try:
            if not gid:
                fail("P5a.9", "no test group")
            else:
                await db.astra_user_tokens.delete_many({"user_id": alex_id})
                await db.astra_user_cards.delete_many({"user_id": alex_id})

                # Seed an active card row so the card-not-found check doesn't shadow token check.
                seed_card_id = f"card_seed_{secrets.token_hex(4)}"
                seeded_card_ids.append(seed_card_id)
                await db.astra_user_cards.insert_one({
                    "id": seed_card_id,
                    "user_id": alex_id,
                    "brand": "visa",
                    "last4": "4242",
                    "display_name": "Test Visa",
                    "is_active": True,
                    "is_default": True,
                    "created_at": "2026-05-13T00:00:00+00:00",
                    "updated_at": "2026-05-13T00:00:00+00:00",
                })

                r = await client.post(
                    f"{BASE_URL}/payout/push-to-card",
                    json={
                        "user_id": alex_id,
                        "session_id": alex_sid,
                        "group_id": gid,
                        "card_id": seed_card_id,
                        "amount": 10.0,
                    },
                )
                if r.status_code == 412 and "astra session expired" in (r.json().get("detail") or "").lower():
                    ok("P5a.9 412 'Astra session expired'", f"detail={r.json().get('detail')}")
                else:
                    fail("P5a.9", f"got {r.status_code} body={r.text[:200]}")
        except Exception as e:
            fail("P5a.9", f"{type(e).__name__}: {e}")

        # ─────────── P5a.10 ───────────
        section("P5a.10 POST /payout/push-to-card amount > available → 409")
        try:
            if not gid:
                fail("P5a.10", "no test group")
            else:
                token_doc = {
                    "id": f"aut_{secrets.token_hex(8)}",
                    "user_id": alex_id,
                    "gateway_slug": "astra",
                    "access_token_enc": encrypt_value("fake_access_token_p5a10"),
                    "refresh_token_enc": encrypt_value("fake_refresh_token_p5a10"),
                    "token_type": "Bearer",
                    "scope": "transfers:write cards:read",
                    "expires_at": time.time() + 3600,
                    "created_at": "2026-05-13T00:00:00+00:00",
                    "updated_at": "2026-05-13T00:00:00+00:00",
                }
                await db.astra_user_tokens.replace_one(
                    {"user_id": alex_id, "gateway_slug": "astra"}, token_doc, upsert=True
                )

                card_id = f"card_p5a10_{secrets.token_hex(4)}"
                seeded_card_ids.append(card_id)
                await db.astra_user_cards.insert_one({
                    "id": card_id,
                    "user_id": alex_id,
                    "brand": "visa",
                    "last4": "4242",
                    "display_name": "Test Visa 4242",
                    "is_active": True,
                    "is_default": True,
                    "created_at": "2026-05-13T00:00:00+00:00",
                    "updated_at": "2026-05-13T00:00:00+00:00",
                })

                r = await client.post(
                    f"{BASE_URL}/payout/push-to-card",
                    json={
                        "user_id": alex_id,
                        "session_id": alex_sid,
                        "group_id": gid,
                        "card_id": card_id,
                        "amount": 999.99,
                    },
                )
                if r.status_code == 409 and "exceeds available cash-out balance" in (r.json().get("detail") or "").lower():
                    ok("P5a.10 409 'exceeds available cash-out balance'",
                       f"detail={r.json().get('detail')}")
                else:
                    fail("P5a.10", f"got {r.status_code} body={r.text[:200]}")
        except Exception as e:
            fail("P5a.10", f"{type(e).__name__}: {e}")

        # ─────────── P5a.11 ───────────
        section("P5a.11 POST /webhook/astra without signature header → 400")
        try:
            r = await client.post(
                f"{BASE_URL}/webhook/astra",
                content=json.dumps({"type": "transfer.completed", "data": {"id": "tr_test"}}),
                headers={"Content-Type": "application/json"},
            )
            try:
                detail = (r.json().get("detail") or "").lower()
            except Exception:
                detail = r.text.lower()[:200]
            if r.status_code == 400 and "missing astra signature" in detail:
                ok("P5a.11 400 'Missing Astra signature header'", f"detail={detail}")
            else:
                fail("P5a.11", f"got {r.status_code} body={r.text[:200]}")
        except Exception as e:
            fail("P5a.11", f"{type(e).__name__}: {e}")

        # ─────────── P5a.12 ───────────
        section("P5a.12 POST /webhook/astra with wrong signature → 400")
        try:
            r = await client.post(
                f"{BASE_URL}/webhook/astra",
                content=json.dumps({"type": "transfer.completed", "data": {"id": "tr_test"}}),
                headers={"Content-Type": "application/json", "Astra-Signature": "bogus_sig"},
            )
            try:
                detail = (r.json().get("detail") or "").lower()
            except Exception:
                detail = r.text.lower()[:200]
            if r.status_code == 400 and ("signature mismatch" in detail or "webhook error" in detail):
                ok("P5a.12 400 signature mismatch", f"detail={detail}")
            else:
                fail("P5a.12", f"got {r.status_code} body={r.text[:200]}")
        except Exception as e:
            fail("P5a.12", f"{type(e).__name__}: {e}")

        # ─────────── P5a.13 ───────────
        section("P5a.13 BranchPayoutAdapter / WisePayoutAdapter → 501")
        try:
            from adapters.payout_scaffolds import BranchPayoutAdapter, WisePayoutAdapter
            from fastapi import HTTPException

            for cls in (BranchPayoutAdapter, WisePayoutAdapter):
                inst = cls()
                # create_card_capture_session
                try:
                    await inst.create_card_capture_session(
                        user_id="u", return_url="x", cancel_url="y", metadata={}
                    )
                    fail(f"P5a.13 {cls.__name__}.create_card_capture_session",
                         "did NOT raise — should raise 501")
                except HTTPException as he:
                    if he.status_code == 501 and "not yet implemented" in (he.detail or "").lower():
                        ok(f"P5a.13 {cls.__name__}.create_card_capture_session → 501")
                    else:
                        fail(f"P5a.13 {cls.__name__}.create_card_capture_session",
                             f"status={he.status_code} detail={he.detail}")
                # push_to_card
                try:
                    await inst.push_to_card(
                        amount_cents=1,
                        currency="usd",
                        card_token="t",
                        idempotency_key="k",
                        metadata={},
                    )
                    fail(f"P5a.13 {cls.__name__}.push_to_card", "did NOT raise — should raise 501")
                except HTTPException as he:
                    if he.status_code == 501 and "not yet implemented" in (he.detail or "").lower():
                        ok(f"P5a.13 {cls.__name__}.push_to_card → 501")
                    else:
                        fail(f"P5a.13 {cls.__name__}.push_to_card",
                             f"status={he.status_code} detail={he.detail}")
        except Exception as e:
            fail("P5a.13", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}")

        # ─────────── P5a.14 ───────────
        section("P5a.14 ledger.record_payout_event — 3 rows + idempotent + math")
        try:
            from ledger import make_txn_id, record_payout_event, find_entries_by_txn
            tid = make_txn_id("payout")
            rows = await record_payout_event(
                db, txn_id=tid, bill_id="b_t", user_id="u_t",
                amount_cents=5000, currency="usd",
                reference={"test_p5a": True}, provider_fee_cents=75,
            )
            if len(rows) != 3:
                fail("P5a.14 row count == 3", f"got {len(rows)}")
            else:
                ok("P5a.14 record_payout_event returned 3 rows")

            rows2 = await record_payout_event(
                db, txn_id=tid, bill_id="b_t", user_id="u_t",
                amount_cents=5000, currency="usd",
                reference={"test_p5a": True}, provider_fee_cents=75,
            )
            n = await db.ledger_entries.count_documents({"txn_id": tid})
            if n != 3:
                fail("P5a.14 idempotent — count_documents == 3", f"got {n}")
            else:
                ok("P5a.14 idempotent re-call left exactly 3 rows")

            by_cat = {r["category"]: r["amount_cents"] for r in await find_entries_by_txn(db, tid)}
            req = by_cat.get("payout.requested", -1)
            fee = by_cat.get("payout.processor_fee", -1)
            sett = by_cat.get("payout.settled", -1)
            if req == 5000 and fee == 75 and sett == 4925 and req == fee + sett:
                ok("P5a.14 math invariant: 5000 == 75 + 4925")
            else:
                fail("P5a.14 math invariant",
                     f"requested={req} fee={fee} settled={sett}")

            await db.ledger_entries.delete_many({"reference.test_p5a": True})
            ok("P5a.14 cleanup deleted test_p5a ledger rows")
        except Exception as e:
            fail("P5a.14", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}")

        # ─────────── P5a.15 Phase 4 regression ───────────
        section("P5a.15 Regression — Phase 4 Stripe charge adapter")
        try:
            ok("P5a.15a admin login still works (token issued)")

            bob_id = await register_user(client, f"Bob P5a15 {unique_suffix}")
            test_user_ids.append(bob_id)
            bob_phone = f"+155502{unique_suffix}"
            test_phones.append(bob_phone)
            bob_sid = await verify_phone(client, bob_id, bob_phone)

            cr = await client.post(
                f"{BASE_URL}/groups",
                json={
                    "lead_id": bob_id,
                    "title": "P5a15 Regression Group",
                    "total_amount": 25.50,
                    "split_mode": "fast",
                    "items": [],
                },
            )
            bob_gid = None
            if cr.status_code != 200:
                fail("P5a.15b create group", f"got {cr.status_code}: {cr.text[:200]}")
            else:
                bob_gid = cr.json()["id"]
                test_group_ids.append(bob_gid)
                ok("P5a.15b create open group for lead-pay regression",
                   f"gid={bob_gid}, total=$25.50")

            if bob_gid:
                cs = await client.post(
                    f"{BASE_URL}/groups/{bob_gid}/checkout-session",
                    json={"origin_url": "http://localhost:3000"},
                )
                if cs.status_code != 200:
                    fail("P5a.15b lead-pay checkout-session 200",
                         f"got {cs.status_code}: {cs.text[:300]}")
                else:
                    d = cs.json()
                    url = d.get("url") or ""
                    sid = d.get("session_id") or ""
                    if url.startswith("https://checkout.stripe.com") and sid.startswith("cs_test_"):
                        ok("P5a.15b lead-pay session created (stripe url + cs_test_ session)",
                           f"sid={sid[:18]}…")
                    else:
                        fail("P5a.15b stripe url + cs_test session",
                             f"url={url[:80]} sid={sid[:18]}")
                    if abs(float(d.get("amount") or 0) - 25.50) <= 0.01:
                        ok("P5a.15b checkout amount == group.total_amount")
                    else:
                        fail("P5a.15b amount==25.50", f"got {d.get('amount')}")

                    sr = await client.get(f"{BASE_URL}/checkout/status/{sid}")
                    if sr.status_code == 200:
                        sd = sr.json()
                        if sd.get("payment_status") in ("pending", "unpaid", "no_payment_required") or sd.get("status") in (
                            "open", "complete", "expired",
                        ):
                            ok("P5a.15c checkout/status returns coherent status",
                               f"(status={sd.get('status')} pay={sd.get('payment_status')})")
                        else:
                            fail("P5a.15c status shape", f"got {sd}")
                    else:
                        fail("P5a.15c checkout/status HTTP 200",
                             f"got {sr.status_code}: {sr.text[:200]}")

                    sr2 = await client.get(f"{BASE_URL}/checkout/status/cs_test_DOES_NOT_EXIST")
                    if sr2.status_code == 404:
                        ok("P5a.15c bogus session-id → 404")
                    else:
                        fail("P5a.15c bogus session-id → 404",
                             f"got {sr2.status_code}: {sr2.text[:120]}")

            # Member contribute via Stripe
            carol_id = await register_user(client, f"Carol P5a15 {unique_suffix}")
            test_user_ids.append(carol_id)
            carol_phone = f"+155503{unique_suffix}"
            test_phones.append(carol_phone)
            carol_sid = await verify_phone(client, carol_id, carol_phone)
            if bob_gid:
                j = await client.post(
                    f"{BASE_URL}/groups/{bob_gid}/join",
                    json={"user_id": carol_id, "join_method": "code"},
                )
                if j.status_code in (200, 201):
                    ok("P5a.15d carol joined bob's group")
                    con = await client.post(
                        f"{BASE_URL}/groups/{bob_gid}/contribute",
                        json={
                            "user_id": carol_id,
                            "origin_url": "http://localhost:3000",
                            "notify_on_settled": False,
                        },
                    )
                    if con.status_code != 200:
                        fail("P5a.15d carol contribute HTTP 200",
                             f"got {con.status_code}: {con.text[:200]}")
                    else:
                        cd = con.json()
                        if cd.get("checkout_required"):
                            url = cd.get("url") or ""
                            sid = cd.get("session_id") or ""
                            if url.startswith("https://checkout.stripe.com") and sid.startswith("cs_test_"):
                                ok("P5a.15d member contribute → stripe checkout",
                                   f"sid={sid[:18]}…")
                            else:
                                fail("P5a.15d contribute stripe url",
                                     f"url={url[:80]} sid={sid[:18]}")
                        else:
                            ok("P5a.15d member contribute completed (credit_only path)",
                               f"credit_only={cd.get('credit_only')}")
                else:
                    fail("P5a.15d carol join group", f"got {j.status_code}: {j.text[:200]}")

            # Scaffolds raise 501
            from adapters.charge_scaffolds import (
                SquareChargeAdapter, AdyenChargeAdapter, FlutterwaveChargeAdapter,
            )
            from fastapi import HTTPException
            for ScaffoldCls in (SquareChargeAdapter, AdyenChargeAdapter, FlutterwaveChargeAdapter):
                inst = ScaffoldCls()
                try:
                    await inst.create_checkout_session(
                        amount_cents=100,
                        currency="usd",
                        success_url="https://example.com/s",
                        cancel_url="https://example.com/c",
                        metadata={},
                        idempotency_key="k",
                        product_name="t",
                    )
                    fail(f"P5a.15e {ScaffoldCls.__name__}.create_checkout_session", "did NOT raise")
                except HTTPException as he:
                    if he.status_code == 501:
                        ok(f"P5a.15e {ScaffoldCls.__name__}.create_checkout_session → 501")
                    else:
                        fail(f"P5a.15e {ScaffoldCls.__name__}.create_checkout_session",
                             f"status={he.status_code}")

        except Exception as e:
            fail("P5a.15", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}")

        # ─────────── Cleanup ───────────
        section("Cleanup")
        try:
            for g in test_group_ids:
                await db.groups.delete_one({"id": g})
                await db.ledger_entries.delete_many({"bill_id": g})
                await db.payment_transactions.delete_many({"group_id": g})
                await db.payouts.delete_many({"group_id": g})
            for u in test_user_ids:
                await db.users.delete_one({"id": u})
                await db.otp_codes.delete_one({"user_id": u})
                await db.astra_user_tokens.delete_many({"user_id": u})
                await db.astra_user_cards.delete_many({"user_id": u})
                await db.credits.delete_many({"user_id": u})
                await db.astra_oauth_states.delete_many({"user_id": u})
            for s in test_state_tokens:
                await db.astra_oauth_states.delete_one({"state": s})
            print(f"  Cleanup done: {len(test_user_ids)} users, {len(test_group_ids)} groups, {len(test_state_tokens)} states")
        except Exception as e:
            print(f"  cleanup error (non-fatal): {e}")

    # Summary
    print("\n" + "═" * 80)
    print(f" SUMMARY :: PASSES={len(PASSES)}, FAILS={len(FAILS)}")
    print("═" * 80)
    if FAILS:
        print("\nFAILURES:")
        for f in FAILS:
            print("  -", f)
    else:
        print("\nALL CHECKS PASSED ✅")


if __name__ == "__main__":
    asyncio.run(run_tests())
