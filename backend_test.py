"""Backend test for the STRICT funding_complete check (penny-rounding bug fix).

Targets /app/backend/core.py :: _recompute_group lines 889-891:

    total_cents   = int(round(float(total_amount) * 100))
    covered_cents = int(round(float(value_covered) * 100))
    funding_complete = covered_cents >= total_cents and total_amount > 0

Previously this was:
    funding_complete = (value_covered + 0.01) >= total_amount
which caused a 1¢-shortfall bill to be marked complete.

Scenarios (per review request):
    #1  POSITIVE — exact funding with Lead-absorbs-residual ($94.43/2)
    #2  NEGATIVE — 1¢ shortfall MUST NOT mark complete (CRITICAL)
    #3  EDGE — Over-funding by $0.01 still completes
    #4  EDGE — cover_amount (shortfall settlement) counts toward value_covered
    #5  REGRESSION — GET /api/groups, GET /api/groups/{id}, /api/admin/groups
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
MOCK_OTP = "123456"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

MONGO_URL = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
DB_NAME = os.environ.get("DB_NAME") or "test_database"

PASS: List[str] = []
FAIL: List[Tuple[str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append((name, detail))
        print(f"  FAIL  {name}  -- {detail}")


def section(t: str) -> None:
    print(f"\n=== {t} ===")


# ---------------- Mongo helpers ---------------------------------------------

def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _db_op(fn):
    """Run an async db function with a fresh client."""

    async def _wrap():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            return await fn(client[DB_NAME])
        finally:
            client.close()

    return _run_async(_wrap())


def _direct_verify_and_session(user_id: str, phone: str) -> Optional[str]:
    """Set verified=true + a fresh session_id on the user (bypass OTP rate-limit)."""
    sid = "sess_test_" + uuid.uuid4().hex[:16]

    async def _go(db):
        res = await db.users.update_one(
            {"id": user_id},
            {"$set": {"phone": phone, "verified": True, "current_session_id": sid}},
        )
        return res.modified_count > 0

    return sid if _db_op(_go) else None


def _insert_contribution(
    group_id: str,
    user_id: str,
    amount: float,
    *,
    set_status_paid: bool = False,
    funding_mode: str = "group",
) -> None:
    """Append a synthetic credit-only contribution row directly into mongo.

    This bypasses contribute_routes' legacy `(total_contributed + 0.01) >= total`
    threshold so we can isolate _recompute_group's NEW strict check.
    """
    contrib = {
        "id": "c_test_" + uuid.uuid4().hex[:12],
        "user_id": user_id,
        "amount": round(float(amount), 2),
        "cash_paid": 0.0,
        "credit_applied": round(float(amount), 2),
        "notify_on_settled": False,
        "via": "test_direct_insert",
        "at": "2025-06-01T00:00:00Z",
    }

    async def _go(db):
        update: Dict[str, Any] = {"$push": {"contributions": contrib}}
        if set_status_paid:
            update["$set"] = {
                "status": "paid",
                "funding_mode": funding_mode,
                "lead_paid_at": "2025-06-01T00:00:00Z",
                "lead_shortfall": 0.0,
            }
        await db.groups.update_one({"id": group_id}, update)

    _db_op(_go)


def _set_settlement_cover(group_id: str, user_id: str, amount: float) -> None:
    """Inject shortfall_settlement.amount to simulate a cover."""

    async def _go(db):
        await db.groups.update_one(
            {"id": group_id},
            {
                "$set": {
                    "shortfall_settlement": {
                        "user_id": user_id,
                        "amount": round(float(amount), 2),
                        "mode": "lead",
                        "is_loan": True,
                        "at": "2025-06-01T00:00:00Z",
                    }
                }
            },
        )

    _db_op(_go)


def _raw_status(group_id: str) -> str:
    async def _go(db):
        g = await db.groups.find_one({"id": group_id}, {"_id": 0, "status": 1})
        return (g or {}).get("status") or ""

    return _db_op(_go)


# ---------------- API helpers ------------------------------------------------

def _phone() -> str:
    digits = "".join(c for c in uuid.uuid4().hex if c.isdigit())
    return "555" + (digits + "0000000")[:7]


def register_and_verify(name: str) -> Dict[str, Any]:
    r = requests.post(f"{BASE}/auth/register", json={"name": name}, timeout=20)
    assert r.status_code == 200, f"register({name}) -> {r.status_code} {r.text[:200]}"
    uid = r.json()["id"]
    phone = _phone()
    sid = _direct_verify_and_session(uid, phone)
    assert sid, f"failed to verify user {uid}"
    return {"id": uid, "phone": phone, "name": name, "session_id": sid}


def create_group_fast(lead_id: str, total: float, title: str = "Strict-fund Test") -> Dict[str, Any]:
    body = {
        "lead_id": lead_id,
        "title": title,
        "total_amount": total,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r = requests.post(f"{BASE}/groups", json=body, timeout=20)
    assert r.status_code == 200, f"create group -> {r.status_code} {r.text[:200]}"
    return r.json()


def join(group_id: str, user_id: str) -> Dict[str, Any]:
    r = requests.post(
        f"{BASE}/groups/{group_id}/join",
        json={"user_id": user_id, "joined_via": "code"},
        timeout=20,
    )
    assert r.status_code == 200, f"join -> {r.status_code} {r.text[:200]}"
    return r.json()


def get_group(group_id: str) -> Dict[str, Any]:
    r = requests.get(f"{BASE}/groups/{group_id}", timeout=20)
    assert r.status_code == 200, f"get group -> {r.status_code} {r.text[:200]}"
    return r.json()


def find_member(group: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    for p in group["per_user"]:
        if p["user_id"] == user_id:
            return p
    raise AssertionError(f"user_id {user_id} not in per_user")


def lead_member_id(group: Dict[str, Any]) -> str:
    for m in group["members"]:
        if (m.get("role") or "").lower() == "lead":
            return m["user_id"]
    return group["members"][0]["user_id"]


def admin_login() -> str:
    r = requests.post(
        f"{BASE}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"admin login -> {r.status_code} {r.text[:200]}"
    j = r.json()
    return j.get("token") or j.get("access_token")


def grant_credit_admin(admin_token: str, user_id: str, amount: float, reason: str = "Test") -> None:
    r = requests.post(
        f"{BASE}/admin/users/{user_id}/credits/grant",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"amount": amount, "note": reason},
        timeout=20,
    )
    assert r.status_code == 200, f"grant_credit -> {r.status_code} {r.text[:200]}"


def contribute_credit(group_id: str, user_id: str, amount: float) -> Tuple[int, Dict[str, Any]]:
    r = requests.post(
        f"{BASE}/groups/{group_id}/contribute",
        json={"user_id": user_id, "amount": amount, "notify_on_settled": False},
        timeout=30,
    )
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"text": r.text[:300]}


def payout_eligibility(user_id: str, session_id: str, group_id: str) -> Tuple[int, Dict[str, Any]]:
    r = requests.get(
        f"{BASE}/payout/eligibility",
        params={"user_id": user_id, "session_id": session_id, "group_id": group_id},
        timeout=20,
    )
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"text": r.text[:300]}


# ---------------- Tests ------------------------------------------------------

def setup_2member_group(total: float) -> Dict[str, Any]:
    lead = register_and_verify(f"Lead_{uuid.uuid4().hex[:6]}")
    member = register_and_verify(f"Member_{uuid.uuid4().hex[:6]}")
    g = create_group_fast(lead["id"], total)
    g = join(g["id"], member["id"])
    g = get_group(g["id"])
    return {"lead": lead, "member": member, "group": g}


# ---------- Scenario #1 — POSITIVE exact funding -----------------------------

def test_scenario1_exact_funding_positive():
    section("#1 POSITIVE — exact funding $94.43/2 with Lead-absorbs-residual")
    s = setup_2member_group(94.43)
    g = s["group"]
    gid = g["id"]
    lead_id = lead_member_id(g)
    lp = find_member(g, lead_id)
    mp = next(p for p in g["per_user"] if p["user_id"] != lead_id)

    # 1a) Lead per_user.total != member per_user.total (lead 1¢ higher).
    check(
        "#1a Lead.food == 47.22 (absorbed residual)",
        abs(lp["food"] - 47.22) < 0.005,
        f"lead.food={lp['food']}",
    )
    check(
        "#1b Member.food == 47.21",
        abs(mp["food"] - 47.21) < 0.005,
        f"member.food={mp['food']}",
    )
    check(
        "#1c lead.total != member.total (lead 1c higher)",
        round(lp["total"] - mp["total"], 2) == 0.01,
        f"lead.total={lp['total']} member.total={mp['total']}",
    )

    # 1d) Member contributes exact food share ($47.21) via direct insert
    # (avoids contribute_routes' legacy $0.01 buggy threshold).
    _insert_contribution(gid, s["member"]["id"], 47.21)
    g_after = get_group(gid)
    check(
        "#1d after member-only contrib: derived_status == 'contributing'",
        g_after["derived_status"] == "contributing",
        f"got {g_after['derived_status']}",
    )
    check(
        "#1d2 merchant_remaining != 0 after member-only",
        g_after["funding"]["merchant_remaining"] > 0.005,
        f"merchant_remaining={g_after['funding']['merchant_remaining']}",
    )

    # 1e) Lead contributes exact food share ($47.22). Total contributed = 94.43.
    _insert_contribution(gid, lead_id, 47.22)
    g_final = get_group(gid)
    check(
        "#1e after both contrib: derived_status == 'contributed'",
        g_final["derived_status"] == "contributed",
        f"got {g_final['derived_status']}  total_contributed={g_final['funding']['total_contributed']}",
    )
    check(
        "#1f merchant_remaining == 0.00 (exact match)",
        abs(g_final["funding"]["merchant_remaining"]) < 0.005,
        f"merchant_remaining={g_final['funding']['merchant_remaining']}",
    )
    check(
        "#1g total_contributed == 94.43 EXACTLY",
        abs(g_final["funding"]["total_contributed"] - 94.43) < 0.005,
        f"total_contributed={g_final['funding']['total_contributed']}",
    )


# ---------- Scenario #2 — NEGATIVE 1c shortfall (CRITICAL) -------------------

def test_scenario2_one_cent_shortfall_negative():
    section("#2 NEGATIVE — 1c shortfall MUST NOT be marked complete (CRITICAL)")
    s = setup_2member_group(94.43)
    g = s["group"]
    gid = g["id"]
    lead_id = lead_member_id(g)

    # Both contribute $47.21 (lead UNDERPAYS their residual cent).
    # total_contributed = $94.42 vs total_amount = $94.43.
    _insert_contribution(gid, s["member"]["id"], 47.21)
    _insert_contribution(gid, lead_id, 47.21)
    g_after = get_group(gid)

    tc = g_after["funding"]["total_contributed"]
    mr = g_after["funding"]["merchant_remaining"]
    r2c = g_after["funding"]["remaining_to_collect"]

    check(
        "#2a total_contributed == 94.42 (1c short)",
        abs(tc - 94.42) < 0.005,
        f"total_contributed={tc}",
    )
    check(
        "#2b CRITICAL: derived_status == 'contributing' (NOT 'contributed')",
        g_after["derived_status"] == "contributing",
        f"got '{g_after['derived_status']}' — funding_complete leaked through!  tc={tc} ta={g_after.get('total_amount') or g_after.get('total')}",
    )
    check(
        "#2c merchant_remaining == 0.01 (1c uncollected)",
        abs(mr - 0.01) < 0.005,
        f"merchant_remaining={mr}",
    )
    check(
        "#2d remaining_to_collect > 0",
        r2c > 0.005,
        f"remaining_to_collect={r2c}",
    )

    # 2e) Try payout — MUST be refused (raw status stayed 'open' because we
    # bypassed contribute_routes via direct mongo insert).
    raw = _raw_status(gid)
    check(
        "#2e raw status remained 'open' (no premature 'paid' from this path)",
        raw == "open",
        f"raw status={raw}",
    )
    code, body = payout_eligibility(s["lead"]["id"], s["lead"]["session_id"], gid)
    check(
        "#2f /payout/eligibility returns 200",
        code == 200,
        f"got {code} {body}",
    )
    if code == 200:
        reasons = body.get("reasons") or []
        check(
            "#2g CRITICAL: payout NOT eligible (squad not fully funded)",
            body.get("eligible") is False and "group_not_paid" in reasons,
            f"eligible={body.get('eligible')} reasons={reasons}",
        )


# ---------- Scenario #3 — EDGE Over-funding ---------------------------------

def test_scenario3_over_funding_edge():
    section("#3 EDGE — Over-funding by 1c still completes ($89.21/2, paid 89.22)")
    s = setup_2member_group(89.21)
    g = s["group"]
    gid = g["id"]
    lead_id = lead_member_id(g)
    lp = find_member(g, lead_id)
    mp = next(p for p in g["per_user"] if p["user_id"] != lead_id)
    check(
        "#3a $89.21/2 lead.food == 44.61",
        abs(lp["food"] - 44.61) < 0.005,
        f"lead.food={lp['food']}",
    )
    check(
        "#3b $89.21/2 member.food == 44.60",
        abs(mp["food"] - 44.60) < 0.005,
        f"member.food={mp['food']}",
    )

    # Lead overpays by 1c ($44.62), member exact ($44.60). Total = $89.22.
    _insert_contribution(gid, lead_id, 44.62)
    _insert_contribution(gid, s["member"]["id"], 44.60)
    g_after = get_group(gid)
    tc = g_after["funding"]["total_contributed"]
    mr = g_after["funding"]["merchant_remaining"]

    check(
        "#3c over-funded total_contributed == 89.22",
        abs(tc - 89.22) < 0.005,
        f"total_contributed={tc}",
    )
    check(
        "#3d derived_status == 'contributed' (covered_cents >= total_cents)",
        g_after["derived_status"] == "contributed",
        f"got '{g_after['derived_status']}'",
    )
    check(
        "#3e merchant_remaining == 0 (surplus absorbed, NOT negative)",
        abs(mr) < 0.005 and mr >= 0,
        f"merchant_remaining={mr}",
    )


# ---------- Scenario #4 — EDGE cover_amount ---------------------------------

def test_scenario4_cover_amount_edge():
    section("#4 EDGE — cover_amount (shortfall settlement) counts toward value_covered")
    s = setup_2member_group(94.43)
    g = s["group"]
    gid = g["id"]
    lead_id = lead_member_id(g)

    # Lead contributes own $47.22. Member contributes $0. Bill is short $47.21.
    _insert_contribution(gid, lead_id, 47.22)
    g_mid = get_group(gid)
    check(
        "#4a before cover: derived_status == 'contributing'",
        g_mid["derived_status"] == "contributing",
        f"got '{g_mid['derived_status']}'",
    )

    # Now inject shortfall_settlement cover of $47.21 (lead covers member's gap).
    _set_settlement_cover(gid, lead_id, 47.21)
    g_cov = get_group(gid)

    # value_covered = total_contributed ($47.22) + cover_amount ($47.21) = $94.43.
    # funding_complete = True. derived_status -> 'contributed'.
    check(
        "#4b after cover: derived_status == 'contributed'",
        g_cov["derived_status"] == "contributed",
        f"got '{g_cov['derived_status']}'  tc={g_cov['funding']['total_contributed']}",
    )

    # 4c — 1c-shortfall cover: replace cover with $47.20 (1c short).
    _set_settlement_cover(gid, lead_id, 47.20)
    g_short = get_group(gid)
    check(
        "#4c cover 1c short -> derived_status reverts to 'contributing'",
        g_short["derived_status"] == "contributing",
        f"got '{g_short['derived_status']}'  value_covered = tc+cover = {g_short['funding']['total_contributed']}+47.20",
    )


# ---------- Pipeline: real contribute endpoint reveals secondary bug --------

def test_pipeline_real_contribute_path():
    section("PIPELINE — /contribute endpoint with credit_only path on $94.43/2")
    admin_tok = admin_login()
    s = setup_2member_group(94.43)
    gid = s["group"]["id"]
    lead_id = lead_member_id(s["group"])

    # Grant credits + ask each member to contribute their FOOD share ($47.21).
    # The credit_only branch in contribute_routes (line ~100) has the legacy
    # `total_contributed + 0.01 >= total_amount` buggy threshold; this test
    # will reveal whether it has been updated to match the new strict logic.
    grant_credit_admin(admin_tok, s["member"]["id"], 100.0, "scenario test")
    grant_credit_admin(admin_tok, lead_id, 100.0, "scenario test")

    code1, b1 = contribute_credit(gid, s["member"]["id"], 47.21)
    check(
        "PIPE-A member /contribute $47.21 -> 200",
        code1 == 200,
        f"got {code1} {b1}",
    )
    code2, b2 = contribute_credit(gid, lead_id, 47.21)
    check(
        "PIPE-B lead /contribute $47.21 -> 200",
        code2 == 200,
        f"got {code2} {b2}",
    )

    g_after = get_group(gid)
    raw = _raw_status(gid)
    tc = g_after["funding"]["total_contributed"]
    print(f"  pipeline state: raw_status={raw}  tc={tc}  derived={g_after['derived_status']}")

    # Expectation per review: with $94.42 collected on $94.43 bill, the bill
    # must NOT be marked fully funded.
    check(
        "PIPE-C raw status remained 'open' (contribute path did NOT flip status='paid' on 1c short)",
        raw == "open",
        f"raw status={raw} — contribute_routes line 101/390 still uses legacy "
        f"`+0.01` threshold and flipped status='paid' despite 1c short!",
    )
    check(
        "PIPE-D derived_status == 'contributing' (1c short)",
        g_after["derived_status"] == "contributing",
        f"got '{g_after['derived_status']}' — likely cascade from PIPE-C (raw_status='paid' "
        "forces derived='contributed' regardless of new strict check).",
    )


# ---------- Regression smoke ------------------------------------------------

def test_regression_smoke():
    section("#5 REGRESSION smoke — no 5xx on key endpoints")
    r = requests.get(f"{BASE}/runtime/landing-page", timeout=20)
    check("smoke landing-page 200", r.status_code == 200, f"got {r.status_code}")

    r = requests.get(f"{BASE}/runtime/brand", timeout=20)
    check("smoke runtime/brand 200", r.status_code == 200, f"got {r.status_code}")

    admin_tok = admin_login()
    r = requests.get(
        f"{BASE}/admin/groups",
        headers={"Authorization": f"Bearer {admin_tok}"},
        timeout=30,
    )
    check("smoke /admin/groups 200 (no 5xx after fix)", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        data = r.json()
        items = data.get("items") if isinstance(data, dict) else data
        check("admin/groups returned a list", isinstance(items, list), f"type={type(items).__name__}")


# ---------- Main ------------------------------------------------------------

def main():
    print("Strict funding_complete check — Backend regression test")
    print(f"Target: {BASE}")
    print(f"Mongo:  {MONGO_URL}/{DB_NAME}")

    tests = [
        ("Scenario #1 (POSITIVE)", test_scenario1_exact_funding_positive),
        ("Scenario #2 (NEGATIVE)", test_scenario2_one_cent_shortfall_negative),
        ("Scenario #3 (OVER-FUND)", test_scenario3_over_funding_edge),
        ("Scenario #4 (COVER)", test_scenario4_cover_amount_edge),
        ("Pipeline (real contribute)", test_pipeline_real_contribute_path),
        ("Regression smoke", test_regression_smoke),
    ]
    for label, fn in tests:
        try:
            fn()
        except Exception as e:
            FAIL.append((label, f"unhandled exception: {e!r}"))
            print(f"  FAIL  {label} crashed: {e!r}")

    print(f"\n=== TOTALS ===")
    print(f"PASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    if FAIL:
        print("--- failures ---")
        for name, detail in FAIL:
            print(f"  - {name}\n      {detail}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
