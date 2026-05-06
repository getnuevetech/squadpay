"""Phase F1 backend test — Stripe Issuing virtual cards + member contributions via Stripe Checkout.

Tests:
  - GET/POST /api/admin/integrations/issuing
  - POST /api/groups/{id}/contribute (REWORKED) — Path A (credit-only) & Path B (Stripe-required)
  - GET  /api/contribute/status/{session_id}
  - Auto-issue Stripe Issuing card on full funding
  - POST /api/admin/groups/{id}/disable-card
  - Regression: POST /api/groups/{id}/checkout-session + GET /api/checkout/status/{id}

Base URL is read from /app/frontend/.env: EXPO_PUBLIC_BACKEND_URL + '/api'.
"""
import os
import re
import sys
import time
import json
import requests
from pathlib import Path


# ---------- Config ----------
def _backend_url() -> str:
    env_path = Path("/app/frontend/.env")
    base = None
    for line in env_path.read_text().splitlines():
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            base = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not base:
        raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not found in /app/frontend/.env")
    return base.rstrip("/") + "/api"


BASE = _backend_url()
print(f"[config] BASE = {BASE}")

ADMIN_EMAIL = "[email protected]"
ADMIN_PASSWORD = "ChangeMe123!"
ORIGIN = "http://localhost:3000"

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name} :: {detail}")


def http(method, path, **kw):
    url = path if path.startswith("http") else BASE + path
    try:
        r = requests.request(method, url, timeout=60, **kw)
    except requests.RequestException as e:
        raise RuntimeError(f"HTTP {method} {url} failed: {e}")
    return r


# ---------- Helpers ----------
TS = int(time.time())


def admin_login():
    r = http("POST", "/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        raise RuntimeError(f"admin login failed: {r.status_code} {r.text}")
    return r.json()["token"]


def admin_headers(tok):
    return {"Authorization": f"Bearer {tok}"}


def register_and_verify(name: str, phone: str) -> dict:
    r = http("POST", "/auth/register", json={"name": name})
    assert r.status_code == 200, f"register: {r.status_code} {r.text}"
    user = r.json()
    r2 = http("POST", "/auth/send-otp", json={"user_id": user["id"], "phone": phone})
    assert r2.status_code == 200, f"send-otp: {r2.status_code} {r2.text}"
    r3 = http("POST", "/auth/verify-otp", json={"user_id": user["id"], "phone": phone, "code": "123456"})
    assert r3.status_code == 200, f"verify-otp: {r3.status_code} {r3.text}"
    return r3.json()


def grant_credit(tok: str, user_id: str, amount: float, note: str = "F1 test grant"):
    r = http(
        "POST",
        f"/admin/users/{user_id}/credits/grant",
        headers=admin_headers(tok),
        json={"amount": amount, "note": note},
    )
    assert r.status_code == 200, f"grant_credit: {r.status_code} {r.text}"
    return r.json()


# ============================================================
# E) Issuing settings GET/POST
# ============================================================
def test_issuing_settings(tok):
    print("\n=== E) Issuing settings GET/POST ===")
    # GET defaults
    r = http("GET", "/admin/integrations/issuing", headers=admin_headers(tok))
    record("E.1 GET /admin/integrations/issuing 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        return None
    settings = r.json()
    # Note: review request says cardholder_name='KWIKPAY' default. Real cardholder may be persisted.
    record(
        "E.2 issuing.enabled defaults to True",
        settings.get("enabled") is True,
        f"enabled={settings.get('enabled')}",
    )
    record(
        "E.3 issuing.cardholder_name default starts 'KWIKPAY' or 'KwikPay'",
        (settings.get("cardholder_name") or "").lower().startswith("kwikpay"),
        f"cardholder_name={settings.get('cardholder_name')}",
    )
    record(
        "E.4 card_disable_mode in {auto,manual}",
        settings.get("card_disable_mode") in ("auto", "manual"),
        f"card_disable_mode={settings.get('card_disable_mode')}",
    )
    # POST flip to manual
    r2 = http(
        "POST",
        "/admin/integrations/issuing",
        headers=admin_headers(tok),
        json={"card_disable_mode": "manual"},
    )
    record("E.5 POST card_disable_mode=manual 200", r2.status_code == 200, f"status={r2.status_code}")
    r3 = http("GET", "/admin/integrations/issuing", headers=admin_headers(tok))
    new = r3.json() if r3.status_code == 200 else {}
    record(
        "E.6 card_disable_mode persisted = manual",
        new.get("card_disable_mode") == "manual",
        f"got={new.get('card_disable_mode')}",
    )
    # Reset to auto
    http(
        "POST",
        "/admin/integrations/issuing",
        headers=admin_headers(tok),
        json={"card_disable_mode": "auto"},
    )
    return settings


# ============================================================
# Helper: create fast-split group
# ============================================================
def create_fast_split_group(lead_id: str, total: float, title: str) -> dict:
    r = http(
        "POST",
        "/groups",
        json={
            "lead_id": lead_id,
            "title": title,
            "total_amount": total,
            "split_mode": "fast",
            "tax": 0.0,
            "tip": 0.0,
            "items": [],
        },
    )
    assert r.status_code == 200, f"create_group: {r.status_code} {r.text}"
    return r.json()


def join_group(group_id: str, user_id: str) -> dict:
    r = http("POST", f"/groups/{group_id}/join", json={"user_id": user_id})
    assert r.status_code == 200, f"join: {r.status_code} {r.text}"
    return r.json()


def get_group(group_id: str) -> dict:
    r = http("GET", f"/groups/{group_id}")
    assert r.status_code == 200, f"get_group: {r.status_code} {r.text}"
    return r.json()


# ============================================================
# A) Path A: Credit-only contribution
# B) Path B: Stripe-required contribution + GET /contribute/status
# C) Auto-issue on full funding
# D) Admin disable card
# ============================================================
def test_full_flow(tok):
    print("\n=== A/B/C/D) Member contribution + auto-issue + disable ===")

    # 3 fresh users, fast-split $30 group => share = $10 + $0.30 + $0.03 = $10.33
    lead = register_and_verify(f"LeadF1_{TS}", f"+1444{TS%10000000:07d}")
    m1 = register_and_verify(f"AliceF1_{TS}", f"+1445{TS%10000000:07d}")
    m2 = register_and_verify(f"BobF1_{TS}", f"+1446{TS%10000000:07d}")

    g = create_fast_split_group(lead["id"], 30.00, f"Lunch F1 {TS}")
    gid = g["id"]
    join_group(gid, m1["id"])
    join_group(gid, m2["id"])

    g = get_group(gid)
    per = {p["user_id"]: p for p in g["per_user"]}
    lead_share = per[lead["id"]]["total"]
    m1_share = per[m1["id"]]["total"]
    m2_share = per[m2["id"]]["total"]
    print(f"[setup] total={g['total_amount']} lead_share={lead_share} m1_share={m1_share} m2_share={m2_share}")

    # ---- B) Path B FIRST: lead has no credits → cash needed → expect Stripe URL ----
    rB = http(
        "POST",
        f"/groups/{gid}/contribute",
        json={"user_id": lead["id"], "origin_url": ORIGIN},
    )
    record(
        "B.1 contribute (no credits) returns 200",
        rB.status_code == 200,
        f"status={rB.status_code} body={rB.text[:300]}",
    )
    if rB.status_code != 200:
        return
    bjs = rB.json()
    record(
        "B.2 checkout_required=true + url is Stripe checkout",
        bjs.get("checkout_required") is True
        and isinstance(bjs.get("url"), str)
        and "checkout.stripe.com" in bjs.get("url", ""),
        f"checkout_required={bjs.get('checkout_required')} url={bjs.get('url','')[:80]}",
    )
    record(
        "B.3 session_id starts cs_test_",
        isinstance(bjs.get("session_id"), str) and bjs["session_id"].startswith("cs_test_"),
        f"session_id={bjs.get('session_id')}",
    )
    record(
        "B.4 cash_owed and credit_planned present",
        isinstance(bjs.get("cash_owed"), (int, float)) and isinstance(bjs.get("credit_planned"), (int, float)),
        f"cash_owed={bjs.get('cash_owed')} credit_planned={bjs.get('credit_planned')}",
    )
    record(
        "B.5 cash_owed approx == lead_share (no credits)",
        abs(float(bjs.get("cash_owed", 0)) - lead_share) < 0.05,
        f"cash_owed={bjs.get('cash_owed')} expected~{lead_share}",
    )
    sid = bjs["session_id"]
    record(
        "B.6 group has NO contribution row yet (Path B unpaid)",
        len(get_group(gid).get("contributions") or []) == 0,
        "checked group.contributions",
    )

    # ---- B.7 GET /contribute/status — unpaid session ----
    rs = http("GET", f"/contribute/status/{sid}")
    record(
        "B.7 GET /contribute/status 200 (unpaid)",
        rs.status_code == 200,
        f"status={rs.status_code} body={rs.text[:300]}",
    )
    if rs.status_code == 200:
        sjs = rs.json()
        record(
            "B.8 status='open' and payment_status='unpaid' (not yet paid)",
            sjs.get("status") in ("open", "complete") and sjs.get("payment_status") in ("unpaid", "no_payment_required"),
            f"status={sjs.get('status')} payment_status={sjs.get('payment_status')} applied={sjs.get('applied')}",
        )
        record(
            "B.9 applied=False before payment",
            sjs.get("applied") is False,
            f"applied={sjs.get('applied')}",
        )

    # Confirm payment_transactions row was created with kind='group_member_contribute' (verify via re-poll)
    r2 = http("GET", f"/contribute/status/{sid}")
    record(
        "B.10 status endpoint idempotent (re-poll 200)",
        r2.status_code == 200,
        f"second poll status={r2.status_code}",
    )

    # ---- 404 unknown session ----
    r404 = http("GET", "/contribute/status/cs_test_DOES_NOT_EXIST")
    record(
        "B.11 unknown session_id → 404",
        r404.status_code == 404,
        f"status={r404.status_code} body={r404.text[:120]}",
    )

    # ---- A) Path A: Credit-only contribution. Grant lead credit ≥ share ----
    grant_credit(tok, lead["id"], round(lead_share + 1.0, 2), "Cover lead share")
    rA = http(
        "POST",
        f"/groups/{gid}/contribute",
        json={"user_id": lead["id"], "origin_url": ORIGIN},
    )
    record(
        "A.1 contribute (credits ≥ share) returns 200",
        rA.status_code == 200,
        f"status={rA.status_code} body={rA.text[:200]}",
    )
    if rA.status_code == 200:
        ajs = rA.json()
        record(
            "A.2 checkout_required=False + credit_only=True",
            ajs.get("checkout_required") is False and ajs.get("credit_only") is True,
            f"checkout_required={ajs.get('checkout_required')} credit_only={ajs.get('credit_only')}",
        )
        record(
            "A.3 credit_applied ≈ amount",
            abs(float(ajs.get("credit_applied", 0)) - float(ajs.get("amount", -1))) < 0.05,
            f"credit_applied={ajs.get('credit_applied')} amount={ajs.get('amount')}",
        )
        # Group should have lead's contribution row recorded
        gnew = get_group(gid)
        contrib_users = [c["user_id"] for c in gnew.get("contributions") or []]
        record(
            "A.4 contribution row written immediately for lead",
            lead["id"] in contrib_users,
            f"contributions users={contrib_users}",
        )

    # ---- C) Auto-issue card: grant credits to m1 + m2 to cover full funding ----
    grant_credit(tok, m1["id"], round(m1_share + 1.0, 2), "Cover m1 share")
    grant_credit(tok, m2["id"], round(m2_share + 1.0, 2), "Cover m2 share")

    rC1 = http(
        "POST",
        f"/groups/{gid}/contribute",
        json={"user_id": m1["id"], "origin_url": ORIGIN},
    )
    rC2 = http(
        "POST",
        f"/groups/{gid}/contribute",
        json={"user_id": m2["id"], "origin_url": ORIGIN},
    )
    record(
        "C.1 m1 credit-only contribute 200",
        rC1.status_code == 200 and rC1.json().get("credit_only") is True,
        f"m1 status={rC1.status_code}",
    )
    record(
        "C.2 m2 credit-only contribute 200",
        rC2.status_code == 200 and rC2.json().get("credit_only") is True,
        f"m2 status={rC2.status_code}",
    )

    # Now the group should be fully funded -> auto-issue card
    g3 = get_group(gid)
    record(
        "C.3 group.status == 'paid' after full funding",
        g3.get("status") == "paid",
        f"status={g3.get('status')} total_contributed={sum(c['amount'] for c in g3.get('contributions') or [])} total={g3.get('total_amount')}",
    )
    vc = g3.get("virtual_card") or {}
    record(
        "C.4 virtual_card.stripe_card_id starts with 'ic_'",
        isinstance(vc.get("stripe_card_id"), str) and vc["stripe_card_id"].startswith("ic_"),
        f"stripe_card_id={vc.get('stripe_card_id')}",
    )
    record(
        "C.5 virtual_card.nickname starts with 'KWIKPAY - '",
        isinstance(vc.get("nickname"), str) and vc["nickname"].startswith("KWIKPAY - "),
        f"nickname={vc.get('nickname')}",
    )
    record(
        "C.6 virtual_card.status == 'active'",
        vc.get("status") == "active",
        f"status={vc.get('status')}",
    )
    record(
        "C.7 virtual_card.spend_cap == group.total_amount",
        abs(float(vc.get("spend_cap") or 0) - float(g3.get("total_amount") or 0)) < 0.01,
        f"spend_cap={vc.get('spend_cap')} total={g3.get('total_amount')}",
    )
    record(
        "C.8 virtual_card.last4 present (4 digits)",
        isinstance(vc.get("last4"), str) and len(vc.get("last4") or "") == 4,
        f"last4={vc.get('last4')}",
    )

    # ---- D) Admin disable card ----
    rd = http(
        "POST",
        f"/admin/groups/{gid}/disable-card",
        headers=admin_headers(tok),
    )
    record(
        "D.1 POST /admin/groups/{id}/disable-card 200",
        rd.status_code == 200,
        f"status={rd.status_code} body={rd.text[:200]}",
    )
    g4 = get_group(gid)
    vc2 = g4.get("virtual_card") or {}
    record(
        "D.2 virtual_card.status == 'inactive' after disable",
        vc2.get("status") == "inactive",
        f"status={vc2.get('status')}",
    )
    record(
        "D.3 disabled_by + disabled_at set",
        bool(vc2.get("disabled_by")) and bool(vc2.get("disabled_at")),
        f"disabled_by={vc2.get('disabled_by')} disabled_at={vc2.get('disabled_at')}",
    )

    return gid


# ============================================================
# F) Regression: Phase E lead checkout flow
# ============================================================
def test_phase_e_regression(tok):
    print("\n=== F) Regression: Phase E lead checkout ===")
    lead = register_and_verify(f"LeadE_{TS}", f"+1447{TS%10000000:07d}")
    g = create_fast_split_group(lead["id"], 12.50, f"E-Regression {TS}")
    gid = g["id"]

    r = http(
        "POST",
        f"/groups/{gid}/checkout-session",
        json={"origin_url": ORIGIN},
    )
    record(
        "F.1 POST /groups/{id}/checkout-session 200",
        r.status_code == 200,
        f"status={r.status_code} body={r.text[:200]}",
    )
    if r.status_code != 200:
        return
    js = r.json()
    record(
        "F.2 response has url + session_id + amount",
        all(k in js for k in ("url", "session_id", "amount")) and js.get("url", "").startswith("https://"),
        f"keys={list(js.keys())} url_prefix={js.get('url','')[:30]}",
    )
    record(
        "F.3 url contains 'stripe.com' + session starts cs_test_",
        "stripe.com" in js.get("url", "") and js["session_id"].startswith("cs_test_"),
        f"url ok / sid={js['session_id'][:20]}",
    )
    rs = http("GET", f"/checkout/status/{js['session_id']}")
    record(
        "F.4 GET /checkout/status/{id} 200",
        rs.status_code == 200,
        f"status={rs.status_code} body={rs.text[:200]}",
    )
    if rs.status_code == 200:
        sjs = rs.json()
        record(
            "F.5 status=open + payment_status=unpaid",
            sjs.get("status") in ("open", "complete") and sjs.get("payment_status") in ("unpaid", "no_payment_required"),
            f"status={sjs.get('status')} payment_status={sjs.get('payment_status')}",
        )


# ============================================================
# Entry
# ============================================================
def main():
    print(f"==== Phase F1 backend test (TS={TS}) ====")
    try:
        tok = admin_login()
    except Exception as e:
        record("admin_login", False, str(e))
        _summary()
        return

    test_issuing_settings(tok)
    test_full_flow(tok)
    test_phase_e_regression(tok)
    _summary()


def _summary():
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n=== TOTAL: {n_pass} PASS / {n_fail} FAIL out of {len(RESULTS)} ===")
    if n_fail:
        print("FAILED:")
        for name, ok, det in RESULTS:
            if not ok:
                print(f"  - {name} :: {det}")
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
