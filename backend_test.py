"""SquadPay backend test harness — June 2025 Item 6/7/8 batch.

Focus areas (per current review request):
  1. Item 8 — Contribution math in itemized mode: members with no items
     should show $0 contribution (no fees either).
  2. Items 6/7 — Public GET /api/runtime/wallet-config endpoint + admin
     PUT round-trip via /api/admin/wallet-config.
  3. Regression smoke — /api/, POST /groups, repay 404, public wallet config.

Bypasses /auth/send-otp 5/min IP rate limit by registering users via
/auth/register then flipping `verified=true` directly in MongoDB.
Recurring routes are intentionally NOT exercised — that feature was
deleted in this session.

Run:  python /app/backend_test.py
"""
import os
import sys
import time
import asyncio
from typing import Optional, List

import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env", override=False)

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL",
                     "https://joint-pay-1.preview.emergentagent.com").rstrip("/") + "/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

passes: List[str] = []
failures: List[str] = []


def record(ok: bool, label: str, detail: str = ""):
    if ok:
        passes.append(label)
        print(f"  PASS  {label}")
    else:
        failures.append(f"{label} -- {detail}")
        print(f"  FAIL  {label} -- {detail}")


def section(title: str):
    print(f"\n=== {title} ===")


# ---------- Mongo helpers (verify-shortcut) ----------
from motor.motor_asyncio import AsyncIOMotorClient
_client = AsyncIOMotorClient(MONGO_URL)
_db = _client[DB_NAME]


async def _mark_verified(user_id: str, phone: str):
    await _db.users.update_one(
        {"id": user_id},
        {"$set": {"phone": phone, "verified": True}},
    )


# ---------- HTTP helpers ----------
def http(method: str, path: str, **kw):
    url = f"{BASE}{path}"
    return requests.request(method, url, timeout=30, **kw)


def admin_login() -> Optional[str]:
    r = http("POST", "/admin/auth/login",
             json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code == 200:
        tok = r.json().get("token")
        record(bool(tok), "admin login → token",
               "no token in body" if not tok else "")
        return tok
    record(False, "admin login → token", f"{r.status_code}: {r.text[:200]}")
    return None


# ---------- User factory (rate-limit safe via direct DB verify) ----------
async def make_user(name_prefix: str) -> dict:
    ts = int(time.time() * 1000)
    phone = f"+1832{ts % 10000000:07d}"
    name = f"{name_prefix}{ts % 100000}"
    r = http("POST", "/auth/register", json={"name": name})
    if r.status_code != 200:
        raise RuntimeError(f"register failed: {r.status_code} {r.text[:200]}")
    user = r.json()
    await _mark_verified(user["id"], phone)
    user["phone"] = phone
    user["verified"] = True
    time.sleep(0.02)
    return user


# ============================================================
# 1) Item 8 — Itemized contribution math
# ============================================================
async def test_item8_itemized_contribution_math():
    section("1. Item 8 — Itemized mode: no-items members must see $0 total/fees")

    lead = await make_user("LeadIM")
    alice = await make_user("AliceIM")
    bob = await make_user("BobIM")

    body = {
        "lead_id": lead["id"],
        "title": "Itemized Math Test",
        "total_amount": 30.0,
        "split_mode": "itemized",
        "tax": 0.0,
        "tip": 0.0,
        "items": [
            {"name": "Burger", "price": 12.0, "quantity": 1},
            {"name": "Fries",  "price": 6.0,  "quantity": 1},
            {"name": "Drink",  "price": 12.0, "quantity": 1},
        ],
    }
    r = http("POST", "/groups", json=body)
    record(r.status_code == 200, "create itemized squad",
           f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return None
    g = r.json()
    gid = g["id"]
    items = g["items"]

    for u, via in [(alice, "code"), (bob, "qr")]:
        rj = http("POST", f"/groups/{gid}/join",
                  json={"user_id": u["id"], "joined_via": via})
        record(rj.status_code == 200,
               f"{u['name']} joins squad",
               f"{rj.status_code}: {rj.text[:120]}")

    rg = http("GET", f"/groups/{gid}")
    record(rg.status_code == 200, "GET /groups/{gid} (initial)",
           f"{rg.status_code}: {rg.text[:200]}")
    eg = rg.json()
    per_user = {p["user_id"]: p for p in eg.get("per_user", [])}

    for uid, label in [(lead["id"], "lead"), (alice["id"], "alice"), (bob["id"], "bob")]:
        p = per_user.get(uid)
        if not p:
            record(False, f"per_user has {label}", "missing")
            continue
        ok = (
            abs(p.get("food", 0)) < 0.001
            and abs(p.get("total", 0)) < 0.001
            and abs(p.get("transaction_fee", 0)) < 0.001
            and abs(p.get("platform_fee", 0)) < 0.001
            and abs(p.get("extra_fees_total", 0)) < 0.001
        )
        record(ok,
               f"{label} (no items) → total=0, all fees=0 in itemized",
               f"food={p.get('food')} total={p.get('total')} "
               f"tx_fee={p.get('transaction_fee')} pf={p.get('platform_fee')} "
               f"extras={p.get('extra_fees_total')}")

    # Assign Burger ($12) → Alice
    burger_id = items[0]["id"]
    ra = http("POST", f"/groups/{gid}/assign",
              json={"user_id": alice["id"], "item_id": burger_id, "quantity": 1})
    record(ra.status_code == 200, "assign Burger → Alice",
           f"{ra.status_code}: {ra.text[:200]}")

    rg2 = http("GET", f"/groups/{gid}")
    eg2 = rg2.json()
    pu2 = {p["user_id"]: p for p in eg2.get("per_user", [])}

    p_alice = pu2[alice["id"]]
    record(p_alice["food"] > 0 and p_alice["total"] > 0,
           "after assign — alice.total > 0",
           f"food={p_alice['food']} total={p_alice['total']}")
    record(p_alice["transaction_fee"] >= 0 and p_alice["total"] > p_alice["food"] - 0.001,
           "after assign — alice has fee math applied",
           f"food={p_alice['food']} tx_fee={p_alice['transaction_fee']} "
           f"pf={p_alice['platform_fee']} total={p_alice['total']}")

    for uid, label in [(lead["id"], "lead"), (bob["id"], "bob")]:
        p = pu2[uid]
        ok = (
            abs(p.get("food", 0)) < 0.001
            and abs(p.get("total", 0)) < 0.001
            and abs(p.get("transaction_fee", 0)) < 0.001
            and abs(p.get("platform_fee", 0)) < 0.001
            and abs(p.get("extra_fees_total", 0)) < 0.001
        )
        record(ok,
               f"after assign — {label} (still no items) still $0",
               f"food={p.get('food')} total={p.get('total')} "
               f"fees={p.get('transaction_fee')}/{p.get('platform_fee')}/{p.get('extra_fees_total')}")

    # Remove the assignment (qty=0)
    ra2 = http("POST", f"/groups/{gid}/assign",
               json={"user_id": alice["id"], "item_id": burger_id, "quantity": 0})
    record(ra2.status_code == 200, "remove Alice's Burger assignment (qty=0)",
           f"{ra2.status_code}: {ra2.text[:200]}")

    rg3 = http("GET", f"/groups/{gid}")
    eg3 = rg3.json()
    pu3 = {p["user_id"]: p for p in eg3.get("per_user", [])}
    p_alice3 = pu3[alice["id"]]
    ok = (
        abs(p_alice3.get("food", 0)) < 0.001
        and abs(p_alice3.get("total", 0)) < 0.001
        and abs(p_alice3.get("transaction_fee", 0)) < 0.001
        and abs(p_alice3.get("platform_fee", 0)) < 0.001
        and abs(p_alice3.get("extra_fees_total", 0)) < 0.001
    )
    record(ok,
           "after un-assign — alice reverts to $0",
           f"food={p_alice3.get('food')} total={p_alice3.get('total')} "
           f"fees={p_alice3.get('transaction_fee')}/{p_alice3.get('platform_fee')}/{p_alice3.get('extra_fees_total')}")


async def test_item8_fast_mode_unaffected():
    section("1b. Item 8 — FAST/equal mode: behavior MUST NOT apply")

    lead = await make_user("LeadFM")
    alice = await make_user("AliceFM")
    bob = await make_user("BobFM")
    body = {
        "lead_id": lead["id"],
        "title": "Fast Mode Test",
        "total_amount": 30.0,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r = http("POST", "/groups", json=body)
    record(r.status_code == 200, "create fast-mode squad",
           f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return
    gid = r.json()["id"]
    for u in [alice, bob]:
        rj = http("POST", f"/groups/{gid}/join",
                  json={"user_id": u["id"], "joined_via": "code"})
        record(rj.status_code == 200, f"{u['name']} joins fast squad",
               f"{rj.status_code}: {rj.text[:120]}")

    rg = http("GET", f"/groups/{gid}")
    eg = rg.json()
    pu = {p["user_id"]: p for p in eg.get("per_user", [])}
    for uid, label in [(lead["id"], "lead"), (alice["id"], "alice"), (bob["id"], "bob")]:
        p = pu.get(uid)
        record(
            p and p["food"] > 0 and p["total"] > 0,
            f"fast mode — {label} food>0 AND total>0 (NOT zero'd)",
            f"got food={p.get('food') if p else 'N/A'} total={p.get('total') if p else 'N/A'}",
        )
        if p:
            record(abs(p["food"] - 10.0) < 0.01,
                   f"fast mode — {label} food == $10.00 (30/3 equal)",
                   f"got {p.get('food')}")


# ============================================================
# 2) Items 6/7 — Public wallet-config endpoint
# ============================================================
async def test_wallet_config_public(admin_token: str):
    section("2. Items 6/7 — Public /runtime/wallet-config + admin PUT round-trip")

    r = http("GET", "/runtime/wallet-config")
    record(r.status_code == 200, "GET /runtime/wallet-config (no auth) → 200",
           f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        for k in ("apple_pay_enabled", "google_pay_enabled", "issuing_enabled"):
            record(k in body and isinstance(body[k], bool),
                   f"public wallet-config has bool field {k}",
                   f"body={body}")
        record(body.get("apple_pay_enabled") is False,
               "public — apple_pay_enabled == False (initial)",
               f"got {body.get('apple_pay_enabled')}")
        record(body.get("google_pay_enabled") is False,
               "public — google_pay_enabled == False (initial)",
               f"got {body.get('google_pay_enabled')}")
        record(body.get("issuing_enabled") is True,
               "public — issuing_enabled == True (initial)",
               f"got {body.get('issuing_enabled')}")

    headers = {"Authorization": f"Bearer {admin_token}"}
    r2 = http("PUT", "/admin/wallet-config",
              headers=headers,
              json={"apple_pay_enabled": False,
                    "google_pay_enabled": False,
                    "issuing_enabled": False})
    record(r2.status_code == 200,
           "admin PUT /admin/wallet-config (issuing=False) → 200",
           f"{r2.status_code}: {r2.text[:200]}")
    if r2.status_code == 200:
        record(r2.json().get("issuing_enabled") is False,
               "PUT response echoes issuing_enabled=False",
               f"got {r2.json()}")

    r3 = http("GET", "/runtime/wallet-config")
    if r3.status_code == 200:
        record(r3.json().get("issuing_enabled") is False,
               "public reflects issuing_enabled=False after admin PUT",
               f"got {r3.json()}")

    r4 = http("PUT", "/admin/wallet-config",
              headers=headers,
              json={"apple_pay_enabled": False,
                    "google_pay_enabled": False,
                    "issuing_enabled": True})
    record(r4.status_code == 200,
           "admin PUT restore issuing_enabled=True → 200",
           f"{r4.status_code}: {r4.text[:200]}")
    r5 = http("GET", "/runtime/wallet-config")
    if r5.status_code == 200:
        record(r5.json().get("issuing_enabled") is True,
               "public reflects issuing_enabled=True after restore",
               f"got {r5.json()}")


# ============================================================
# 3) Regression smoke
# ============================================================
async def test_regression_smoke():
    section("3. Regression smoke")

    r = http("GET", "/")
    if r.status_code == 200:
        record("SquadPay" in r.text, "GET /api/ → 200 with 'SquadPay API'",
               f"got body={r.text[:160]}")
    else:
        record(False, "GET /api/ → 200", f"{r.status_code}: {r.text[:200]}")

    lead = await make_user("SmokeLead")
    body = {
        "lead_id": lead["id"],
        "title": "Smoke Squad",
        "total_amount": 25.0,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r2 = http("POST", "/groups", json=body)
    record(r2.status_code == 200,
           "POST /groups (sample body) → 200 (fresh squad)",
           f"{r2.status_code}: {r2.text[:200]}")

    r3 = http("POST", "/groups/g_DOES_NOT_EXIST_xyz/repay",
              json={"user_id": "u_nobody", "amount": 1.0})
    record(r3.status_code == 404,
           "POST /groups/{nonexistent}/repay → 404 (not 405)",
           f"{r3.status_code}: {r3.text[:200]}")
    if r3.status_code == 404:
        try:
            d = r3.json().get("detail", "")
        except Exception:
            d = ""
        record("squad" in str(d).lower() or "not found" in str(d).lower(),
               "repay 404 detail mentions 'Squad not found'",
               f"detail={d!r}")

    r4 = http("GET", "/runtime/wallet-config")
    record(r4.status_code == 200,
           "GET /runtime/wallet-config (no auth) → 200 (smoke)",
           f"{r4.status_code}: {r4.text[:200]}")


# ============================================================
async def main():
    print(f"Backend base: {BASE}")
    print(f"Mongo DB:     {DB_NAME}")

    section("0. Admin login")
    tok = admin_login()
    if not tok:
        print("Cannot continue without admin token.")
        return

    await test_item8_itemized_contribution_math()
    await test_item8_fast_mode_unaffected()
    await test_wallet_config_public(tok)
    await test_regression_smoke()

    section("SUMMARY")
    print(f"PASS  {len(passes)}")
    print(f"FAIL  {len(failures)}")
    if failures:
        for f in failures:
            print(f"   - {f}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
