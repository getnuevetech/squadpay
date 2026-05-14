"""SquadPay backend regression test — Shortfall math fix (Dec 2025).

Focus areas (per current review request):
  A) GET /api/groups/{id} — verify funding.remaining_to_collect /
     funding.merchant_remaining math.
  B) POST /api/groups/{id}/pay shortfall_mode=lead is_loan=true — verify
     shortfall covers FULL outstanding (incl fees), not merchant-only.
  C) POST /api/groups/{id}/pay shortfall_mode=member / split_equal —
     obligations carry full amount including fees.
  D) Smoke: check-session, /users/{id}/groups, /groups create,
     /runtime/landing-page (Cache-Control: no-store).

Bypasses /auth/send-otp 5/min IP rate limit by registering users via
/auth/register then flipping `verified=true` directly in MongoDB.

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


# ---------- User factory ----------
_UCOUNTER = [0]
async def make_user(name_prefix: str) -> dict:
    _UCOUNTER[0] += 1
    ts = int(time.time() * 1000)
    # ensure unique phone even when called rapidly
    suffix = (ts + _UCOUNTER[0]) % 10_000_000
    phone = f"+1832{suffix:07d}"
    name = f"{name_prefix}{ts % 100000}{_UCOUNTER[0]}"
    r = http("POST", "/auth/register", json={"name": name})
    if r.status_code != 200:
        raise RuntimeError(f"register failed: {r.status_code} {r.text[:200]}")
    user = r.json()
    await _mark_verified(user["id"], phone)
    user["phone"] = phone
    user["verified"] = True
    return user


async def grant_credit(token: str, user_id: str, amount: float, note: str = "test") -> bool:
    r = http("POST", f"/admin/users/{user_id}/credits/grant",
             headers={"Authorization": f"Bearer {token}"},
             json={"amount": amount, "note": note})
    return r.status_code == 200


def contribute_credit_only(group_id: str, user_id: str, amount: float):
    """Use the /contribute endpoint expecting credit_only path (amount fully covered)."""
    return http("POST", f"/groups/{group_id}/contribute",
                json={"user_id": user_id, "amount": amount})


# ============================================================
# A) GET /api/groups/{id} — funding math
# ============================================================
async def test_funding_math(admin_token: str):
    section("A. GET /groups/{id} — funding.remaining_to_collect vs merchant_remaining")

    lead = await make_user("LeadA")
    m1 = await make_user("M1A")
    m2 = await make_user("M2A")

    body = {
        "lead_id": lead["id"],
        "title": "Funding Math A",
        "total_amount": 60.0,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r = http("POST", "/groups", json=body)
    record(r.status_code == 200, "create fast-split $60 squad",
           f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return None
    gid = r.json()["id"]

    for u in (m1, m2):
        rj = http("POST", f"/groups/{gid}/join",
                  json={"user_id": u["id"], "joined_via": "code"})
        record(rj.status_code == 200, f"{u['name']} joins",
               f"{rj.status_code}: {rj.text[:120]}")

    # Initial state — no contributions yet
    rg = http("GET", f"/groups/{gid}")
    record(rg.status_code == 200, "GET /groups/{gid} initial → 200",
           f"{rg.status_code}: {rg.text[:200]}")
    eg = rg.json()
    funding = eg.get("funding", {})
    per_user = eg.get("per_user", [])
    sum_outstanding = round(sum(p.get("outstanding", 0.0) for p in per_user), 2)

    print(f"     funding={funding}")
    print(f"     sum_outstanding={sum_outstanding}  per_user.total={[p['total'] for p in per_user]}")

    record(
        funding.get("remaining_to_collect") is not None,
        "funding.remaining_to_collect field present"
    )
    record(
        funding.get("merchant_remaining") is not None,
        "funding.merchant_remaining field present (NEW)"
    )
    record(
        abs(funding.get("remaining_to_collect", -1) - sum_outstanding) < 0.02,
        "remaining_to_collect == sum(per_user.outstanding)",
        f"got {funding.get('remaining_to_collect')} vs sum {sum_outstanding}"
    )
    record(
        funding.get("remaining_to_collect", 0) >= funding.get("merchant_remaining", 0) - 0.01,
        "remaining_to_collect >= merchant_remaining (initial, no contributions)",
        f"r2c={funding.get('remaining_to_collect')} merch={funding.get('merchant_remaining')}"
    )

    # Lead contributes own share via credit_only — grant enough credit
    lead_per = next(p for p in per_user if p["user_id"] == lead["id"])
    lead_share = float(lead_per["total"])
    ok = await grant_credit(admin_token, lead["id"], lead_share + 1.0, "test funding A — lead")
    record(ok, f"admin grants lead ${lead_share + 1.0:.2f} credit")

    rc = contribute_credit_only(gid, lead["id"], lead_share)
    record(rc.status_code == 200 and rc.json().get("credit_only") is True,
           f"lead contributes ${lead_share:.2f} via credit_only",
           f"{rc.status_code}: {rc.text[:200]}")

    # State: only lead contributed → partial
    rg = http("GET", f"/groups/{gid}")
    eg = rg.json()
    funding = eg.get("funding", {})
    per_user = eg.get("per_user", [])
    sum_outstanding = round(sum(p.get("outstanding", 0.0) for p in per_user), 2)
    fees_uncollected = round(sum(
        (p.get("transaction_fee", 0) + p.get("platform_fee", 0) + p.get("extra_fees_total", 0))
        for p in per_user
        if p.get("user_id") != lead["id"]
    ), 2)

    print(f"     After lead contributes: funding={funding}")
    print(f"     sum_outstanding={sum_outstanding}  fees_uncollected={fees_uncollected}")

    record(
        abs(funding.get("remaining_to_collect", -1) - sum_outstanding) < 0.02,
        "partial-funded: remaining_to_collect == sum(per_user.outstanding)",
        f"got {funding.get('remaining_to_collect')} vs sum {sum_outstanding}"
    )
    record(
        funding.get("remaining_to_collect", 0) > funding.get("merchant_remaining", 0) - 0.01,
        "partial-funded: remaining_to_collect >= merchant_remaining",
        f"r2c={funding.get('remaining_to_collect')} merch={funding.get('merchant_remaining')}"
    )
    delta = round(funding.get("remaining_to_collect", 0) - funding.get("merchant_remaining", 0), 2)
    record(
        abs(delta - fees_uncollected) < 0.05,
        "partial-funded: delta(r2c - merch) ≈ uncollected fees for non-contributors",
        f"delta={delta} fees_uncollected={fees_uncollected}"
    )

    return {"gid": gid, "lead": lead, "m1": m1, "m2": m2, "lead_share": lead_share}


# ============================================================
# B) POST /pay shortfall_mode=lead is_loan=true
# ============================================================
async def test_pay_lead_loan(admin_token: str):
    section("B. POST /pay shortfall_mode=lead is_loan=true — full amount cover")

    lead = await make_user("LeadB")
    m1 = await make_user("M1B")
    m2 = await make_user("M2B")

    body = {
        "lead_id": lead["id"],
        "title": "Lead Loan Cover B",
        "total_amount": 60.0,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r = http("POST", "/groups", json=body)
    if r.status_code != 200:
        record(False, "create fast-split squad B", f"{r.status_code}: {r.text[:200]}")
        return
    record(True, "create fast-split squad B")
    gid = r.json()["id"]

    for u in (m1, m2):
        rj = http("POST", f"/groups/{gid}/join",
                  json={"user_id": u["id"], "joined_via": "code"})
        if rj.status_code != 200:
            record(False, f"{u['name']} joins B", f"{rj.status_code}: {rj.text[:120]}")
            return
    record(True, "members join squad B")

    # Get per_user; lead pays own share via credit
    rg = http("GET", f"/groups/{gid}")
    per_user = rg.json()["per_user"]
    pm = {p["user_id"]: p for p in per_user}
    lead_share = float(pm[lead["id"]]["total"])
    m1_share = float(pm[m1["id"]]["total"])
    m2_share = float(pm[m2["id"]]["total"])

    print(f"     shares: lead=${lead_share:.2f} m1=${m1_share:.2f} m2=${m2_share:.2f}")

    # Grant lead enough credit, lead contributes
    await grant_credit(admin_token, lead["id"], lead_share + 1.0, "B — lead")
    rc = contribute_credit_only(gid, lead["id"], lead_share)
    record(rc.status_code == 200, "lead contributes own share via credit",
           f"{rc.status_code}: {rc.text[:200]}")

    # Snapshot before pay
    rg = http("GET", f"/groups/{gid}")
    eg_before = rg.json()
    funding_before = eg_before["funding"]
    pm_before = {p["user_id"]: p for p in eg_before["per_user"]}
    print(f"     BEFORE pay: funding={funding_before}")
    print(f"     BEFORE pay: m1.outstanding={pm_before[m1['id']]['outstanding']}  m2.outstanding={pm_before[m2['id']]['outstanding']}")

    expected_shortfall = round(
        pm_before[m1["id"]]["outstanding"] + pm_before[m2["id"]]["outstanding"], 2
    )
    expected_merchant_remaining = funding_before["merchant_remaining"]
    print(f"     expected_shortfall (sum non-lead outstanding) = ${expected_shortfall:.2f}")
    print(f"     merchant_remaining (BEFORE) = ${expected_merchant_remaining:.2f}")

    # CRITICAL: m1+m2 share sum INCLUDES fees, so expected > merchant_remaining
    record(
        expected_shortfall > expected_merchant_remaining - 0.01,
        "expected_shortfall (incl fees) > merchant_remaining (sanity)",
        f"shortfall={expected_shortfall} merch={expected_merchant_remaining}"
    )

    # Lead pays with shortfall_mode=lead, is_loan=true
    rp = http("POST", f"/groups/{gid}/pay",
              json={"user_id": lead["id"], "shortfall_mode": "lead", "is_loan": True})
    record(rp.status_code == 200, "POST /pay shortfall_mode=lead is_loan=true → 200",
           f"{rp.status_code}: {rp.text[:200]}")
    if rp.status_code != 200:
        return

    eg_after = rp.json()
    funding_after = eg_after["funding"]
    contribs = eg_after.get("contributions", [])
    shortfall_contribs = [c for c in contribs if c.get("is_shortfall")]
    print(f"     AFTER pay: funding={funding_after}")
    print(f"     shortfall_contribs={shortfall_contribs}")

    record(len(shortfall_contribs) == 1, "exactly one is_shortfall contribution recorded",
           f"got {len(shortfall_contribs)}")
    if shortfall_contribs:
        sc = shortfall_contribs[0]
        record(sc.get("user_id") == lead["id"], "shortfall contribution.user_id == lead",
               f"got {sc.get('user_id')}")
        record(abs(float(sc.get("amount", 0)) - expected_shortfall) < 0.02,
               f"shortfall contribution.amount == sum(non-lead outstanding) = ${expected_shortfall:.2f}",
               f"got {sc.get('amount')} expected {expected_shortfall}")
        record(sc.get("is_loan") is True, "is_loan=true preserved")
        # CRITICAL: must NOT equal merchant_remaining (old buggy value)
        record(abs(float(sc.get("amount", 0)) - expected_merchant_remaining) > 0.05,
               "shortfall amount != merchant_remaining (old buggy value)",
               f"shortfall={sc.get('amount')} merchant_remaining={expected_merchant_remaining}")

    # total_contributed after = before + expected_shortfall
    delta_contributed = round(
        funding_after["total_contributed"] - funding_before["total_contributed"], 2
    )
    record(abs(delta_contributed - expected_shortfall) < 0.02,
           f"funding.total_contributed delta == ${expected_shortfall:.2f}",
           f"delta={delta_contributed}")

    # Bill state
    record(eg_after.get("status") == "paid",
           "raw status == 'paid' after lead-loan cover",
           f"got status={eg_after.get('status')}")
    record(eg_after.get("funding_mode") in ("shortfall", "lead"),
           "funding_mode set ('shortfall' or 'lead')",
           f"got {eg_after.get('funding_mode')}")

    # merchant_remaining after ≈ 0 (merchant fully paid)
    record(funding_after.get("merchant_remaining", 99) < 0.05,
           "after cover: merchant_remaining ≈ 0",
           f"got {funding_after.get('merchant_remaining')}")

    # For LOAN mode the beneficiaries still owe the lead (their `outstanding` stays).
    # `remaining_to_collect` (sum of all outstanding) will still be > 0 because
    # member1/member2 owe the lead. This is the LOAN repayment flow — distinct
    # from merchant settlement. Document the observation.
    print(f"     NOTE (loan): remaining_to_collect={funding_after.get('remaining_to_collect')} "
          f"— members still owe lead via repay flow (correct loan semantics).")


# ============================================================
# A.3) NEW — after split_equal applied, remaining_to_collect must NOT
#       double-count shortfall_owed
# ============================================================
async def test_split_equal_no_double_count(admin_token: str):
    section("A.3 — After split_equal: remaining_to_collect must NOT include shortfall_owed (no double-count)")

    lead = await make_user("LeadA3")
    m1 = await make_user("M1A3")
    m2 = await make_user("M2A3")

    body = {
        "lead_id": lead["id"],
        "title": "Split Equal No Double Count",
        "total_amount": 60.0,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r = http("POST", "/groups", json=body)
    if r.status_code != 200:
        record(False, "create squad A.3", f"{r.status_code}: {r.text[:200]}")
        return
    gid = r.json()["id"]
    for u in (m1, m2):
        http("POST", f"/groups/{gid}/join", json={"user_id": u["id"], "joined_via": "code"})

    # Lead contributes own share
    rg = http("GET", f"/groups/{gid}")
    eg0 = rg.json()
    pm0 = {p["user_id"]: p for p in eg0["per_user"]}
    lead_share = float(pm0[lead["id"]]["total"])
    m1_share = float(pm0[m1["id"]]["total"])
    m2_share = float(pm0[m2["id"]]["total"])
    await grant_credit(admin_token, lead["id"], lead_share + 1.0, "A.3 lead")
    contribute_credit_only(gid, lead["id"], lead_share)

    # Before /pay — capture the true remaining gap
    rg = http("GET", f"/groups/{gid}")
    eg_before = rg.json()
    funding_before = eg_before["funding"]
    pm_b = {p["user_id"]: p for p in eg_before["per_user"]}
    true_gap = round(
        max(0.0, m1_share - pm_b[m1["id"]]["contributed"] - pm_b[m1["id"]]["repaid"]) +
        max(0.0, m2_share - pm_b[m2["id"]]["contributed"] - pm_b[m2["id"]]["repaid"]),
        2
    )
    print(f"     before split: r2c={funding_before['remaining_to_collect']} true_gap={true_gap}")
    record(
        abs(funding_before["remaining_to_collect"] - true_gap) < 0.02,
        f"before split: remaining_to_collect == true_gap (${true_gap:.2f})",
        f"got {funding_before['remaining_to_collect']} expected {true_gap}"
    )

    # Lead calls /pay with shortfall_mode=split_equal — creates shortfall_owed obligations
    rp = http("POST", f"/groups/{gid}/pay",
              json={"user_id": lead["id"], "shortfall_mode": "split_equal", "is_loan": True})
    record(rp.status_code == 200, "POST /pay shortfall_mode=split_equal → 200",
           f"{rp.status_code}: {rp.text[:200]}")
    if rp.status_code != 200:
        return

    eg_after = rp.json()
    funding_after = eg_after["funding"]
    per_user_after = eg_after["per_user"]
    pm_a = {p["user_id"]: p for p in per_user_after}

    # The 2 absent members now have shortfall_owed set
    m1_owed = float(pm_a[m1["id"]].get("shortfall_owed", 0))
    m2_owed = float(pm_a[m2["id"]].get("shortfall_owed", 0))
    print(f"     after split: m1.shortfall_owed=${m1_owed} m2.shortfall_owed=${m2_owed}")
    record(m1_owed > 0.01 and m2_owed > 0.01,
           "both non-lead members have shortfall_owed > 0 after split_equal",
           f"m1={m1_owed} m2={m2_owed}")

    # per_user.outstanding for each is now INFLATED (own share + shortfall_owed)
    m1_outstanding = float(pm_a[m1["id"]]["outstanding"])
    m2_outstanding = float(pm_a[m2["id"]]["outstanding"])
    sum_outstanding_inflated = round(m1_outstanding + m2_outstanding, 2)
    print(f"     sum(outstanding inflated) = ${sum_outstanding_inflated}")
    print(f"     funding.remaining_to_collect (after) = ${funding_after['remaining_to_collect']}")

    # CRITICAL: remaining_to_collect should be the actual remaining gap
    # (= true_gap, not the inflated sum)
    record(
        abs(funding_after["remaining_to_collect"] - true_gap) < 0.05,
        f"after split: remaining_to_collect ≈ true_gap (${true_gap:.2f}) — NOT double-counted",
        f"got r2c={funding_after['remaining_to_collect']} true_gap={true_gap} "
        f"inflated_sum={sum_outstanding_inflated}"
    )
    # And it must be strictly less than the inflated sum (proves no double-counting)
    record(
        funding_after["remaining_to_collect"] < sum_outstanding_inflated - 0.05,
        f"after split: r2c < sum(inflated outstanding) — confirms no double-counting",
        f"r2c={funding_after['remaining_to_collect']} inflated_sum={sum_outstanding_inflated}"
    )


# ============================================================
# E) End-to-end: $60 + fees bill, lead covers shortfall via lead-loan
# ============================================================
async def test_end_to_end_lead_covers(admin_token: str):
    section("E. End-to-end — bill fully funded after lead covers shortfall")

    lead = await make_user("LeadE")
    m1 = await make_user("M1E")
    m2 = await make_user("M2E")

    body = {
        "lead_id": lead["id"],
        "title": "E2E Lead Covers",
        "total_amount": 60.0,
        "split_mode": "fast",
        "tax": 0, "tip": 0, "items": [],
    }
    r = http("POST", "/groups", json=body)
    if r.status_code != 200:
        record(False, "create E2E squad", f"{r.status_code}: {r.text[:200]}")
        return
    gid = r.json()["id"]
    for u in (m1, m2):
        http("POST", f"/groups/{gid}/join", json={"user_id": u["id"], "joined_via": "code"})

    # Read shares
    rg = http("GET", f"/groups/{gid}")
    pm0 = {p["user_id"]: p for p in rg.json()["per_user"]}
    lead_share = float(pm0[lead["id"]]["total"])
    m1_share = float(pm0[m1["id"]]["total"])
    m2_share = float(pm0[m2["id"]]["total"])
    total_bill = round(lead_share + m1_share + m2_share, 2)
    print(f"     shares: lead=${lead_share} m1=${m1_share} m2=${m2_share}  total=${total_bill}")

    # Lead contributes own share
    await grant_credit(admin_token, lead["id"], lead_share + 1.0, "E2E lead")
    contribute_credit_only(gid, lead["id"], lead_share)

    # Check r2c == m1_share + m2_share (NOT total_bill - lead_share, which would
    # equal that anyway in this case; the key is r2c includes m1+m2 fees)
    rg = http("GET", f"/groups/{gid}")
    eg_before = rg.json()
    funding_before = eg_before["funding"]
    expected_r2c = round(m1_share + m2_share, 2)
    print(f"     before /pay: r2c={funding_before['remaining_to_collect']} expected=${expected_r2c}")
    record(
        abs(funding_before["remaining_to_collect"] - expected_r2c) < 0.05,
        f"E2E before /pay: r2c == m1+m2 share (${expected_r2c}, incl fees)",
        f"got {funding_before['remaining_to_collect']} expected {expected_r2c}"
    )
    # CRITICAL: must NOT equal the old broken value (m1+m2 merchant-only = $40)
    # nor the v1 buggy double-count value (would be ~2× expected_r2c after split)
    merchant_only_old_value = round(60.0 - lead_share, 2)  # rough old value
    if abs(expected_r2c - merchant_only_old_value) > 0.5:
        record(
            abs(funding_before["remaining_to_collect"] - merchant_only_old_value) > 0.5,
            f"E2E before /pay: r2c != old merchant-only value (${merchant_only_old_value})",
            f"got {funding_before['remaining_to_collect']}"
        )

    # Lead pays with shortfall_mode=lead, is_loan=true
    rp = http("POST", f"/groups/{gid}/pay",
              json={"user_id": lead["id"], "shortfall_mode": "lead", "is_loan": True})
    record(rp.status_code == 200, "E2E POST /pay lead/is_loan → 200",
           f"{rp.status_code}: {rp.text[:200]}")
    if rp.status_code != 200:
        return

    eg_after = rp.json()
    funding_after = eg_after["funding"]
    contribs = eg_after.get("contributions", [])
    shortfall_contribs = [c for c in contribs if c.get("is_shortfall")]
    record(len(shortfall_contribs) == 1, "E2E: exactly 1 is_shortfall contribution",
           f"got {len(shortfall_contribs)}")
    if shortfall_contribs:
        sc = shortfall_contribs[0]
        record(
            abs(float(sc.get("amount", 0)) - expected_r2c) < 0.05,
            f"E2E: shortfall contribution.amount == ${expected_r2c:.2f} (NOT 2× nor merchant-only)",
            f"got {sc.get('amount')} expected {expected_r2c}"
        )

    # After: total_contributed should equal total_bill
    total_contributed_after = funding_after["total_contributed"]
    record(
        abs(total_contributed_after - total_bill) < 0.05,
        f"E2E after /pay: total_contributed == total_bill (${total_bill:.2f})",
        f"got {total_contributed_after}"
    )
    # remaining_to_collect after — for LOAN mode, members still owe lead
    # (their outstanding stays > 0). r2c counts each user's own gap which
    # may still show m1/m2 own_gap depending on how shortfall_owed propagates.
    # Per fix v2 spec: r2c = sum(max(0, total - contributed - repaid)).
    # After lead covers, m1/m2 contributed=0 still, repaid=0, total=share → r2c still = share+share.
    # Document this as info (it represents the LOAN they owe lead).
    print(f"     E2E after /pay: r2c={funding_after['remaining_to_collect']} merchant_remaining={funding_after['merchant_remaining']}")
    record(
        funding_after["merchant_remaining"] < 0.05,
        "E2E after /pay: merchant_remaining ≈ 0 (merchant fully paid)",
        f"got {funding_after['merchant_remaining']}"
    )


# ============================================================
# C) POST /pay shortfall_mode=member / split_equal — obligations
# ============================================================
async def test_pay_member_and_split(admin_token: str):
    section("C. POST /pay shortfall_mode=member / split_equal — obligations carry full amount")

    for mode in ("member", "split_equal"):
        section(f"  C.{mode}")
        lead = await make_user(f"LeadC{mode[:1].upper()}")
        m1 = await make_user(f"M1C{mode[:1].upper()}")
        m2 = await make_user(f"M2C{mode[:1].upper()}")

        r = http("POST", "/groups",
                 json={"lead_id": lead["id"], "title": f"C-{mode}", "total_amount": 60.0,
                       "split_mode": "fast", "tax": 0, "tip": 0, "items": []})
        if r.status_code != 200:
            record(False, f"create squad C-{mode}", f"{r.status_code}")
            continue
        gid = r.json()["id"]
        for u in (m1, m2):
            http("POST", f"/groups/{gid}/join", json={"user_id": u["id"]})

        rg = http("GET", f"/groups/{gid}")
        pm = {p["user_id"]: p for p in rg.json()["per_user"]}
        lead_share = float(pm[lead["id"]]["total"])
        await grant_credit(admin_token, lead["id"], lead_share + 1.0, f"C-{mode}")
        contribute_credit_only(gid, lead["id"], lead_share)

        rg = http("GET", f"/groups/{gid}")
        eg = rg.json()
        pm_b = {p["user_id"]: p for p in eg["per_user"]}
        expected_shortfall = round(
            pm_b[m1["id"]]["outstanding"] + pm_b[m2["id"]]["outstanding"], 2
        )

        payload = {"user_id": lead["id"], "shortfall_mode": mode, "is_loan": True}
        if mode == "member":
            payload["funder_member_id"] = m1["id"]
        rp = http("POST", f"/groups/{gid}/pay", json=payload)
        record(rp.status_code == 200, f"POST /pay shortfall_mode={mode} → 200",
               f"{rp.status_code}: {rp.text[:200]}")
        if rp.status_code != 200:
            continue

        eg_after = rp.json()
        obligations = eg_after.get("shortfall_obligations", [])
        target_kind = "shortfall_member" if mode == "member" else "shortfall_split"
        relevant = [o for o in obligations if o.get("kind") == target_kind]

        if mode == "member":
            record(len(relevant) == 1, "exactly 1 shortfall_member obligation",
                   f"got {len(relevant)}: {relevant}")
            if relevant:
                o = relevant[0]
                record(o.get("user_id") == m1["id"],
                       "obligation.user_id == funder_member_id (m1)",
                       f"got {o.get('user_id')}")
                record(abs(float(o.get("amount", 0)) - expected_shortfall) < 0.02,
                       f"obligation.amount == ${expected_shortfall:.2f} (FULL incl fees)",
                       f"got {o.get('amount')} expected {expected_shortfall}")
        else:  # split_equal
            record(len(relevant) >= 2, "≥2 shortfall_split obligations",
                   f"got {len(relevant)}")
            total_obligation = round(sum(float(o.get("amount", 0)) for o in relevant), 2)
            record(abs(total_obligation - expected_shortfall) < 0.05,
                   f"sum(obligations) == ${expected_shortfall:.2f} (FULL incl fees)",
                   f"got total={total_obligation} expected {expected_shortfall}")

        # Status should remain 'open' since obligations are deferred
        record(eg_after.get("status") == "open",
               f"mode={mode}: raw status stays 'open' (deferred)",
               f"got status={eg_after.get('status')}")


# ============================================================
# D) Smoke — auth/check-session, /users/{id}/groups, /groups create,
#    /runtime/landing-page Cache-Control: no-store
# ============================================================
async def test_smoke_endpoints():
    section("D. Smoke — unrelated endpoints")

    # 1) POST /api/auth/check-session — needs a valid user. Use a fresh one.
    smoke_user = await make_user("Smoke")
    r = http("POST", "/auth/check-session",
             json={"user_id": smoke_user["id"], "session_id": "bogus"})
    record(r.status_code == 200,
           "POST /auth/check-session → 200 (no 500)",
           f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        record("valid" in body, "check-session response has 'valid' key",
               f"body={body}")

    # 2) GET /api/users/{id}/groups
    r2 = http("GET", f"/users/{smoke_user['id']}/groups")
    record(r2.status_code == 200,
           "GET /users/{id}/groups → 200",
           f"{r2.status_code}: {r2.text[:200]}")
    if r2.status_code == 200:
        record(isinstance(r2.json(), list),
               "/users/{id}/groups returns list", f"got {type(r2.json())}")

    # 3) POST /api/groups (create)
    r3 = http("POST", "/groups",
              json={"lead_id": smoke_user["id"], "title": "Smoke Squad",
                    "total_amount": 25.0, "split_mode": "fast",
                    "tax": 0, "tip": 0, "items": []})
    record(r3.status_code == 200,
           "POST /groups (smoke) → 200",
           f"{r3.status_code}: {r3.text[:200]}")

    # 4) GET /api/runtime/landing-page Cache-Control: no-store
    r4 = http("GET", "/runtime/landing-page")
    record(r4.status_code == 200,
           "GET /runtime/landing-page → 200",
           f"{r4.status_code}: {r4.text[:200]}")
    if r4.status_code == 200:
        cc = r4.headers.get("Cache-Control", "")
        record("no-store" in cc.lower(),
               "Cache-Control header contains 'no-store'",
               f"got Cache-Control={cc!r}")


# ============================================================
async def main():
    print(f"Backend base: {BASE}")
    print(f"Mongo DB:     {DB_NAME}")

    section("0. Admin login")
    tok = admin_login()
    if not tok:
        print("Cannot continue without admin token.")
        return

    try:
        await test_funding_math(tok)
    except Exception as e:
        record(False, "test_funding_math crashed", repr(e))

    try:
        await test_split_equal_no_double_count(tok)
    except Exception as e:
        record(False, "test_split_equal_no_double_count crashed", repr(e))

    try:
        await test_pay_lead_loan(tok)
    except Exception as e:
        record(False, "test_pay_lead_loan crashed", repr(e))

    try:
        await test_end_to_end_lead_covers(tok)
    except Exception as e:
        record(False, "test_end_to_end_lead_covers crashed", repr(e))

    try:
        await test_pay_member_and_split(tok)
    except Exception as e:
        record(False, "test_pay_member_and_split crashed", repr(e))

    try:
        await test_smoke_endpoints()
    except Exception as e:
        record(False, "test_smoke_endpoints crashed", repr(e))

    section("SUMMARY")
    print(f"PASS  {len(passes)}")
    print(f"FAIL  {len(failures)}")
    if failures:
        for f in failures:
            print(f"   - {f}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
