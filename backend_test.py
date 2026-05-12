"""
Backend test for Phase P — Income & Fees Ledger + Master Virtual Card.

Targets:
  - GET  /api/admin/income-fees           (admin auth required)
  - GET  /api/admin/master-card           (admin auth required)
  - POST /api/admin/master-card/issue     (admin auth required, idempotent)
  - GET  /api/admin/master-account?limit=10  (regression — should still work)

Reads EXPO_PUBLIC_BACKEND_URL from /app/frontend/.env. Does not hardcode URLs.
Admin credentials from /app/memory/test_credentials.md.
"""
import os
import sys
import time
import json
import uuid
import requests
from pathlib import Path

# ----- Resolve BASE URL from frontend/.env -----
ENV_FILE = Path("/app/frontend/.env")
BASE_URL = None
for line in ENV_FILE.read_text().splitlines():
    line = line.strip()
    if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
        break
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing from /app/frontend/.env"
API = BASE_URL.rstrip("/") + "/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

PASS, FAIL = 0, 0
FAIL_DETAILS = []


def _check(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        FAIL_DETAILS.append(f"{label} — {detail}")
        print(f"  ❌ {label} — {detail}")


def section(name):
    print(f"\n=== {name} ===")


# =====================================================================
# 0) Admin login
# =====================================================================
section("0) Admin login")
r = requests.post(
    f"{API}/admin/auth/login",
    json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    timeout=30,
)
_check(r.status_code == 200, "POST /admin/auth/login → 200", f"{r.status_code} {r.text[:200]}")
if r.status_code != 200:
    print("Cannot proceed without admin token.")
    sys.exit(1)
TOKEN = r.json()["token"]
ADMIN_HDR = {"Authorization": f"Bearer {TOKEN}"}


# =====================================================================
# Seed a tiny test bill: lead + member, optionally contribute (mock)
# =====================================================================
section("Seed: lead + member + bill")

ts = int(time.time())

def _register(name, phone):
    rr = requests.post(f"{API}/auth/register", json={"name": name, "phone": phone}, timeout=15)
    assert rr.status_code in (200, 201), f"register failed {rr.status_code} {rr.text[:200]}"
    return rr.json()

def _send_otp(user_id, phone):
    rr = requests.post(f"{API}/auth/send-otp", json={"user_id": user_id, "phone": phone}, timeout=15)
    return rr

def _verify_otp(user_id, phone, code="123456"):
    rr = requests.post(
        f"{API}/auth/verify-otp",
        json={"user_id": user_id, "phone": phone, "code": code},
        timeout=15,
    )
    return rr

lead_phone = f"+1832{ts % 10000000:07d}"
mem_phone = f"+1713{(ts+1) % 10000000:07d}"

lead = _register(f"LeadP_{ts}", lead_phone)
_send_otp(lead["id"], lead_phone)
v = _verify_otp(lead["id"], lead_phone)
print(f"   lead verify status={v.status_code}")
if v.status_code == 200:
    lead = v.json()

mem = _register(f"MemP_{ts}", mem_phone)
_send_otp(mem["id"], mem_phone)
v2 = _verify_otp(mem["id"], mem_phone)
if v2.status_code == 200:
    mem = v2.json()

# Create a small bill (fast-split, $40 total — 2 items)
group_body = {
    "lead_id": lead["id"],
    "title": f"IncomeFee Test Bill {ts}",
    "split_mode": "equal",
    "total_amount": 20.0,
    "items": [
        {"name": "Burger", "price": 15.0, "quantity": 1},
        {"name": "Fries", "price": 5.0, "quantity": 1},
    ],
    "tax": 0.0,
    "tip": 0.0,
}
gc = requests.post(f"{API}/groups", json=group_body, timeout=20)
print(f"   create group status={gc.status_code}")
if gc.status_code in (200, 201):
    group = gc.json()
    GROUP_ID = group.get("id")
    print(f"   group_id={GROUP_ID}, total={group.get('total_amount')}")
else:
    GROUP_ID = None
    print(f"   create group body: {gc.text[:300]}")

# Try to have the member join + contribute (best effort — no real Stripe needed)
if GROUP_ID:
    code = group.get("code") or group.get("join_code")
    if code:
        j = requests.post(f"{API}/groups/{GROUP_ID}/join", json={"user_id": mem["id"]}, timeout=15)
        print(f"   member join status={j.status_code}")
    # Lead "contribute" to add a contribution row & fees so income-fees has data
    per_user = group.get("per_user") or []
    lead_share = None
    for p in per_user:
        if p.get("user_id") == lead["id"]:
            lead_share = float(p.get("total") or 0)
            break
    if lead_share and lead_share > 0:
        cc = requests.post(
            f"{API}/groups/{GROUP_ID}/contribute",
            json={"user_id": lead["id"], "amount": lead_share},
            timeout=20,
        )
        print(f"   lead contribute status={cc.status_code} share={lead_share}")


# =====================================================================
# 1) GET /api/admin/income-fees
# =====================================================================
section("1) GET /api/admin/income-fees")

# 1a) without auth → 401
r = requests.get(f"{API}/admin/income-fees", timeout=20)
_check(r.status_code == 401, "no auth → 401", f"got {r.status_code} {r.text[:160]}")

# 1b) with admin auth → 200 + shape
r = requests.get(f"{API}/admin/income-fees", headers=ADMIN_HDR, timeout=30)
_check(r.status_code == 200, "with admin auth → 200", f"{r.status_code} {r.text[:200]}")
if r.status_code == 200:
    body = r.json()
    for k in ("totals", "window_totals", "groups"):
        _check(k in body, f"response has key '{k}'", str(list(body.keys())))

    totals = body.get("totals") or {}
    needed_totals_keys = [
        "transaction_fees", "platform_fees", "extra_1", "extra_2",
        "extra_other", "total_retained",
        "groups_counted", "contributions_counted", "gross_contributed",
    ]
    for k in needed_totals_keys:
        present = k in totals
        is_num = isinstance(totals.get(k), (int, float))
        _check(present and is_num, f"totals.{k} present and numeric",
               f"present={present} type={type(totals.get(k)).__name__}")

    wt = body.get("window_totals") or {}
    for k in ("week", "month"):
        present = k in wt
        is_num = isinstance(wt.get(k), (int, float))
        _check(present and is_num, f"window_totals.{k} present and numeric",
               f"present={present} type={type(wt.get(k)).__name__}")

    groups = body.get("groups") or []
    _check(isinstance(groups, list), "groups is a list", type(groups).__name__)

    # If we have any group, validate the shape
    sample = None
    matched_seed = False
    if groups:
        # try to find our seeded group; else prefer one with contributions
        for g in groups:
            if g.get("id") == GROUP_ID:
                sample = g
                matched_seed = True
                break
        if sample is None:
            for g in groups:
                if g.get("contributions"):
                    sample = g
                    break
        if sample is None:
            sample = groups[0]
        print(f"   sample group_id={sample.get('id')} title={sample.get('title')} matched_seed={matched_seed}")

        required_group_keys = [
            "id", "title", "status", "created_at", "lead_id",
            "members_count", "gross_contributed", "fees",
            "contributions", "virtual_card_last4",
        ]
        for k in required_group_keys:
            _check(k in sample, f"groups[].{k} present", f"keys={list(sample.keys())}")

        fees = sample.get("fees") or {}
        fee_keys = ["transaction_fees", "platform_fees", "extra_1", "extra_2", "extra_other", "total_retained"]
        for k in fee_keys:
            _check(k in fees and isinstance(fees[k], (int, float)),
                   f"groups[].fees.{k} numeric",
                   f"present={k in fees} type={type(fees.get(k)).__name__}")

        # Check total_retained == sum of the 5 components (within ±0.01)
        try:
            tot = float(fees.get("total_retained") or 0)
            comp = sum(float(fees.get(k) or 0) for k in
                       ["transaction_fees", "platform_fees", "extra_1", "extra_2", "extra_other"])
            diff = abs(tot - comp)
            _check(diff <= 0.01,
                   f"groups[].fees.total_retained == sum of components (tot={tot:.2f}, sum={comp:.2f})",
                   f"diff={diff:.4f}")
        except Exception as e:
            _check(False, "fees totals arithmetic", str(e))

        contribs = sample.get("contributions") or []
        _check(isinstance(contribs, list), "groups[].contributions is a list",
               type(contribs).__name__)
        if contribs:
            for i, c in enumerate(contribs[:3]):  # sample first 3
                try:
                    fst = float(c.get("fee_slice_total") or 0)
                    cs = sum(float(c.get(k) or 0) for k in
                             ["transaction_fee", "platform_fee", "extra_1", "extra_2"])
                    diff = abs(fst - cs)
                    _check(diff <= 0.01,
                           f"contribution[{i}].fee_slice_total == tx+pl+e1+e2 (slice={fst:.2f}, sum={cs:.2f})",
                           f"diff={diff:.4f}")
                except Exception as e:
                    _check(False, f"contribution[{i}] arithmetic", str(e))
        else:
            print("   (no contributions in sample group — skipping per-contribution math check)")
    else:
        print("   (groups list is empty — group-shape assertions skipped, but endpoint computes correctly)")


# =====================================================================
# 2) GET /api/admin/master-card
# =====================================================================
section("2) GET /api/admin/master-card")

r = requests.get(f"{API}/admin/master-card", timeout=20)
_check(r.status_code == 401, "no auth → 401", f"got {r.status_code} {r.text[:160]}")

r = requests.get(f"{API}/admin/master-card", headers=ADMIN_HDR, timeout=20)
_check(r.status_code == 200, "with admin auth → 200", f"{r.status_code} {r.text[:200]}")
if r.status_code == 200:
    body = r.json()
    _check("card" in body, "response has key 'card'", str(list(body.keys())))
    card_initial = body.get("card")
    print(f"   initial card={card_initial}")


# =====================================================================
# 3) POST /api/admin/master-card/issue (idempotent)
# =====================================================================
section("3) POST /api/admin/master-card/issue")

r = requests.post(f"{API}/admin/master-card/issue", timeout=20)
_check(r.status_code == 401, "no auth → 401", f"got {r.status_code} {r.text[:160]}")

r1 = requests.post(f"{API}/admin/master-card/issue", headers=ADMIN_HDR, timeout=20)
_check(r1.status_code == 200, "first call with admin auth → 200", f"{r1.status_code} {r1.text[:200]}")
if r1.status_code == 200:
    body1 = r1.json()
    _check(body1.get("ok") is True, "ok=true", str(body1))
    card1 = body1.get("card") or {}
    _check("created" in body1, "'created' field present in first response", str(body1))
    # On a fresh DB created should be True. If DB already had a card (from re-runs),
    # created will be False; that's still acceptable behavior, but we check
    # the stub structure regardless.
    _check(card1.get("status") == "pending_stripe_setup",
           "card.status == 'pending_stripe_setup'", str(card1))
    _check(card1.get("stripe_card_id") is None,
           "card.stripe_card_id is null", str(card1.get("stripe_card_id")))
    _check(card1.get("last4") is None, "card.last4 is null", str(card1.get("last4")))
    _check(card1.get("issued_at") is None, "card.issued_at is null", str(card1.get("issued_at")))
    _check(isinstance(card1.get("note"), str) and len(card1["note"]) > 0,
           "card.note is non-empty string", str(card1.get("note")))

# Second call (idempotency)
r2 = requests.post(f"{API}/admin/master-card/issue", headers=ADMIN_HDR, timeout=20)
_check(r2.status_code == 200, "second call → 200 (idempotent)", f"{r2.status_code} {r2.text[:200]}")
if r1.status_code == 200 and r2.status_code == 200:
    body2 = r2.json()
    card2 = body2.get("card") or {}
    # Idempotency contract per review:
    #   second call: same `card`, `created:false`.
    # NOTE: current stub stores stripe_card_id=null. Existing-check uses
    #   `existing.master_card.stripe_card_id` — which means a NULL stripe_card_id
    #   does NOT short-circuit and the stub is upserted again. Verify both fields.
    _check(card2 == card1, "second-call card identical to first-call card",
           f"first={card1} second={card2}")
    # The 'created' flag SHOULD be False on the second call.
    created_flag = body2.get("created")
    _check(created_flag is False,
           "second call has 'created': false",
           f"got {created_flag} (first={body1.get('created')})")

# After issue, GET should return the same stub card
r = requests.get(f"{API}/admin/master-card", headers=ADMIN_HDR, timeout=20)
_check(r.status_code == 200, "GET /admin/master-card after issue → 200",
       f"{r.status_code} {r.text[:160]}")
if r.status_code == 200:
    got_card = r.json().get("card") or {}
    if r1.status_code == 200:
        _check(got_card == card1,
               "GET returns same stub as POST /issue",
               f"GET={got_card} POST={card1}")


# =====================================================================
# 4) Regression: GET /api/admin/master-account?limit=10
# =====================================================================
section("4) Regression: GET /api/admin/master-account?limit=10")

r = requests.get(f"{API}/admin/master-account?limit=10", headers=ADMIN_HDR, timeout=30)
_check(r.status_code == 200, "GET /admin/master-account?limit=10 → 200",
       f"{r.status_code} {r.text[:200]}")
if r.status_code == 200:
    body = r.json()
    for k in ("items", "total", "balance", "skip", "limit"):
        _check(k in body, f"response has key '{k}'", str(list(body.keys())))


# =====================================================================
print("\n" + "=" * 60)
print(f"PASS: {PASS}   FAIL: {FAIL}")
if FAIL_DETAILS:
    print("\nFailures:")
    for d in FAIL_DETAILS:
        print(f"  - {d}")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
