"""Phase F2 backend test — Stripe Issuing PAN/CVV reveal (OTP-gated) + spend webhook +
admin issuing settings.

Endpoints covered:
  - POST /api/auth/sensitive/send-otp
  - POST /api/auth/sensitive/verify-otp
  - POST /api/groups/{id}/card/ephemeral-key   (OTP-gated reveal)
  - POST /api/webhook/stripe/issuing            (issuing_authorization + issuing_transaction)
  - POST /api/groups/{id}/card/push-provisioning  (501 stub)
  - GET/POST /api/admin/integrations/issuing    (new fields require_otp_for_card_reveal,
                                                  reveal_ttl_seconds)

Phase F1 regression touchpoints:
  - POST /api/groups/{id}/contribute (Path A credit-only) → ends up auto-issuing a
    real ic_… card under the KWIKPAY cardholder.
  - GET /api/contribute/status/{session_id}
  - POST /api/admin/groups/{id}/disable-card

Base URL is read from /app/frontend/.env: EXPO_PUBLIC_BACKEND_URL + '/api'.
"""
import os
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
TS = int(time.time())


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


def grant_credit(tok: str, user_id: str, amount: float, note: str = "F2 grant"):
    r = http(
        "POST",
        f"/admin/users/{user_id}/credits/grant",
        headers=admin_headers(tok),
        json={"amount": amount, "note": note},
    )
    assert r.status_code == 200, f"grant_credit: {r.status_code} {r.text}"
    return r.json()


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
# F.A) Sensitive OTP — send + verify
# ============================================================
def test_sensitive_otp_and_setup():
    """Returns a tuple: (lead_user, member_user, group_id_with_active_card, admin_token).

    Uses 1-buck total and three credit-funded users so we don't have to walk through
    Stripe Checkout interactively. Auto-issues the card upon full funding.
    """
    print("\n=== Phase F2 setup: build a group with an active ic_ card ===")
    tok = admin_login()

    # Ensure issuing OTP requirement is true (default). Reset to defaults first.
    http("POST", "/admin/integrations/issuing",
         headers=admin_headers(tok),
         json={"require_otp_for_card_reveal": True, "reveal_ttl_seconds": 60,
               "card_disable_mode": "auto"})

    # 3 fresh users — fast-split $1 group
    lead = register_and_verify(f"LeadF2_{TS}", f"+1888{TS%10000000:07d}")
    m1 = register_and_verify(f"AliceF2_{TS}", f"+1889{TS%10000000:07d}")
    m2 = register_and_verify(f"BobF2_{TS}", f"+1890{TS%10000000:07d}")

    g = create_fast_split_group(lead["id"], 1.00, f"F2 Card Setup {TS}")
    gid = g["id"]
    join_group(gid, m1["id"])
    join_group(gid, m2["id"])

    g_full = get_group(gid)
    per = {p["user_id"]: p for p in g_full["per_user"]}
    # Grant generous credits to cover each share
    for u in (lead, m1, m2):
        grant_credit(tok, u["id"], round(per[u["id"]]["total"] + 1.0, 2))

    # Each user contributes (Path A — credit-only)
    for u in (lead, m1, m2):
        rc = http("POST", f"/groups/{gid}/contribute",
                  json={"user_id": u["id"], "origin_url": ORIGIN})
        assert rc.status_code == 200, f"contribute({u['name']}): {rc.status_code} {rc.text}"

    g_after = get_group(gid)
    vc = g_after.get("virtual_card") or {}
    record(
        "SETUP.1 group fully funded → status=paid",
        g_after.get("status") == "paid",
        f"status={g_after.get('status')} total={g_after.get('total_amount')}",
    )
    record(
        "SETUP.2 virtual_card.stripe_card_id starts with ic_",
        isinstance(vc.get("stripe_card_id"), str) and vc["stripe_card_id"].startswith("ic_"),
        f"card_id={vc.get('stripe_card_id')}",
    )
    record(
        "SETUP.3 virtual_card.status active",
        vc.get("status") == "active",
        f"status={vc.get('status')}",
    )
    return lead, m1, gid, tok


def test_sensitive_otp(lead, m1):
    print("\n=== F.A) Sensitive OTP — send + verify ===")

    # missing user
    r = http("POST", "/auth/sensitive/send-otp", json={"user_id": "u_does_not_exist_xx"})
    record("A.1 send-otp missing user → 404", r.status_code == 404,
           f"status={r.status_code} body={r.text[:120]}")

    # unverified user — register without verifying
    rr = http("POST", "/auth/register", json={"name": f"Unverif_{TS}"})
    unverified_id = rr.json()["id"]
    r = http("POST", "/auth/sensitive/send-otp", json={"user_id": unverified_id})
    record("A.2 send-otp unverified user → 403", r.status_code == 403,
           f"status={r.status_code} body={r.text[:120]}")

    # happy path — verified user
    r = http("POST", "/auth/sensitive/send-otp", json={"user_id": lead["id"]})
    record("A.3 send-otp verified lead → 200", r.status_code == 200,
           f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        js = r.json()
        record("A.4 send-otp body.ok==true",
               js.get("ok") is True, f"ok={js.get('ok')}")
        record("A.5 send-otp body has 'mocked' + 'message' keys",
               "mocked" in js and "message" in js, f"keys={list(js.keys())}")

    # verify wrong code → 400
    r = http("POST", "/auth/sensitive/verify-otp",
             json={"user_id": lead["id"], "code": "000000"})
    record("A.6 verify-otp wrong code → 400", r.status_code == 400,
           f"status={r.status_code} body={r.text[:120]}")

    # NOTE: wrong code attempt did NOT burn the OTP record (only the OTP is burnt
    # when the correct code is presented in the current implementation).
    # Verify with correct code → 200 + reveal_token + expires_in=300
    # If the wrong code path ALSO burned, this would 400. Either way we can
    # send-otp again to ensure a fresh record before the correct verify.
    http("POST", "/auth/sensitive/send-otp", json={"user_id": lead["id"]})
    r = http("POST", "/auth/sensitive/verify-otp",
             json={"user_id": lead["id"], "code": "123456"})
    record("A.7 verify-otp correct code → 200", r.status_code == 200,
           f"status={r.status_code} body={r.text[:200]}")
    reveal_token = None
    if r.status_code == 200:
        js = r.json()
        reveal_token = js.get("reveal_token")
        record("A.8 reveal_token returned (string)",
               isinstance(reveal_token, str) and len(reveal_token) > 16,
               f"reveal_token={(reveal_token or '')[:24]}...")
        record("A.9 expires_in == 300", js.get("expires_in") == 300,
               f"expires_in={js.get('expires_in')}")

    # OTP single-use: re-using same code MUST 400 (record was burned on success)
    r = http("POST", "/auth/sensitive/verify-otp",
             json={"user_id": lead["id"], "code": "123456"})
    record("A.10 verify-otp twice with same code → 400 (single-use)",
           r.status_code == 400,
           f"status={r.status_code} body={r.text[:120]}")

    return reveal_token


# ============================================================
# F.C) Ephemeral key auth chain
# ============================================================
def test_ephemeral_key_auth_chain(lead, m1, gid, tok):
    """Walk through every rejection branch of the ephemeral-key route, plus the
    happy auth path that should reach Stripe (with FAKE nonce → 502)."""
    print("\n=== F.C) Ephemeral key — auth chain rejections ===")

    # Make sure require_otp_for_card_reveal=True (default test mode)
    http("POST", "/admin/integrations/issuing", headers=admin_headers(tok),
         json={"require_otp_for_card_reveal": True})

    # 1) Group not found → 404
    r = http("POST", "/groups/g_does_not_exist/card/ephemeral-key",
             json={"user_id": lead["id"], "reveal_token": "x" * 32,
                   "nonce": "abcdefghij", "stripe_version": "2024-04-10"})
    record("C.1 unknown group → 404", r.status_code == 404,
           f"status={r.status_code} body={r.text[:120]}")

    # 1b) Group has no card (create a fresh empty group) → 400
    fresh_group_lead = register_and_verify(f"NoCardLead_{TS}", f"+1891{TS%10000000:07d}")
    g_no_card = create_fast_split_group(fresh_group_lead["id"], 5.00, f"NoCard {TS}")
    r = http("POST", f"/groups/{g_no_card['id']}/card/ephemeral-key",
             json={"user_id": fresh_group_lead["id"], "reveal_token": "x" * 32,
                   "nonce": "abcdefghij", "stripe_version": "2024-04-10"})
    record("C.2 group has no issued card → 400",
           r.status_code == 400 and "no issued card" in r.text.lower(),
           f"status={r.status_code} body={r.text[:160]}")

    # 3) Wrong user (not lead) → 403
    r = http("POST", f"/groups/{gid}/card/ephemeral-key",
             json={"user_id": m1["id"], "reveal_token": "x" * 32,
                   "nonce": "abcdefghij", "stripe_version": "2024-04-10"})
    record("C.3 non-lead user → 403",
           r.status_code == 403,
           f"status={r.status_code} body={r.text[:160]}")

    # 4) Lead user but missing reveal_token (OTP required) → 401
    # Explicitly send empty token (Pydantic requires the field)
    r = http("POST", f"/groups/{gid}/card/ephemeral-key",
             json={"user_id": lead["id"], "reveal_token": "definitelynotvalid",
                   "nonce": "abcdefghij", "stripe_version": "2024-04-10"})
    record("C.4 invalid reveal_token → 401",
           r.status_code == 401,
           f"status={r.status_code} body={r.text[:160]}")

    # 5) Generate a real reveal token. Then test nonce/version validation.
    http("POST", "/auth/sensitive/send-otp", json={"user_id": lead["id"]})
    rv = http("POST", "/auth/sensitive/verify-otp",
              json={"user_id": lead["id"], "code": "123456"})
    assert rv.status_code == 200, rv.text
    rt = rv.json()["reveal_token"]

    # 5a) nonce too short
    r = http("POST", f"/groups/{gid}/card/ephemeral-key",
             json={"user_id": lead["id"], "reveal_token": rt,
                   "nonce": "abc", "stripe_version": "2024-04-10"})
    record("C.5 nonce too short → 400",
           r.status_code == 400,
           f"status={r.status_code} body={r.text[:160]}")
    # NOTE: Above call BURNED the reveal_token. Mint another for next checks.

    http("POST", "/auth/sensitive/send-otp", json={"user_id": lead["id"]})
    rv = http("POST", "/auth/sensitive/verify-otp",
              json={"user_id": lead["id"], "code": "123456"})
    rt2 = rv.json()["reveal_token"]

    # 5b) Missing stripe_version
    r = http("POST", f"/groups/{gid}/card/ephemeral-key",
             json={"user_id": lead["id"], "reveal_token": rt2,
                   "nonce": "abcdefghij", "stripe_version": ""})
    record("C.6 missing stripe_version → 400",
           r.status_code == 400,
           f"status={r.status_code} body={r.text[:160]}")

    # 6) Happy auth path — fake but plausible nonce → expect 502 (Stripe rejects fake nonce).
    http("POST", "/auth/sensitive/send-otp", json={"user_id": lead["id"]})
    rv = http("POST", "/auth/sensitive/verify-otp",
              json={"user_id": lead["id"], "code": "123456"})
    rt3 = rv.json()["reveal_token"]
    r = http("POST", f"/groups/{gid}/card/ephemeral-key",
             json={"user_id": lead["id"], "reveal_token": rt3,
                   "nonce": "fakenonce_BUT_long_enough_xx",
                   "stripe_version": "2024-04-10"})
    record("C.7 valid auth + fake nonce → 502 (auth layer passed; Stripe rejects)",
           r.status_code == 502,
           f"status={r.status_code} body={r.text[:200]}")

    # 7) Token reuse → 401 (token was burned)
    r = http("POST", f"/groups/{gid}/card/ephemeral-key",
             json={"user_id": lead["id"], "reveal_token": rt3,
                   "nonce": "fakenonce_BUT_long_enough_xx",
                   "stripe_version": "2024-04-10"})
    record("C.8 reuse burned reveal_token → 401",
           r.status_code == 401,
           f"status={r.status_code} body={r.text[:160]}")

    # 8) Toggle require_otp_for_card_reveal=false → can call without reveal_token (still fake nonce → 502)
    http("POST", "/admin/integrations/issuing", headers=admin_headers(tok),
         json={"require_otp_for_card_reveal": False})
    r = http("POST", f"/groups/{gid}/card/ephemeral-key",
             json={"user_id": lead["id"], "reveal_token": "irrelevant_now",
                   "nonce": "fakenonce_BUT_long_enough_xx",
                   "stripe_version": "2024-04-10"})
    record("C.9 OTP toggled off → auth passes w/o token, fake nonce 502",
           r.status_code == 502,
           f"status={r.status_code} body={r.text[:200]}")
    # restore
    http("POST", "/admin/integrations/issuing", headers=admin_headers(tok),
         json={"require_otp_for_card_reveal": True})


def test_ephemeral_key_inactive_card(lead, gid, tok):
    """C.X) After admin disables the card, ephemeral-key must 400 'Card is disabled'."""
    print("\n=== F.C') Ephemeral key — inactive card path ===")

    # Disable card via admin endpoint
    rd = http("POST", f"/admin/groups/{gid}/disable-card",
              headers=admin_headers(tok))
    record("C.10 admin disable-card 200",
           rd.status_code == 200,
           f"status={rd.status_code} body={rd.text[:200]}")

    g_after = get_group(gid)
    record("C.11 virtual_card.status == inactive after disable",
           (g_after.get("virtual_card") or {}).get("status") == "inactive",
           f"status={(g_after.get('virtual_card') or {}).get('status')}")

    # Get a fresh reveal_token then try
    http("POST", "/auth/sensitive/send-otp", json={"user_id": lead["id"]})
    rv = http("POST", "/auth/sensitive/verify-otp",
              json={"user_id": lead["id"], "code": "123456"})
    rt = rv.json()["reveal_token"]
    r = http("POST", f"/groups/{gid}/card/ephemeral-key",
             json={"user_id": lead["id"], "reveal_token": rt,
                   "nonce": "fakenonce_BUT_long_enough_xx",
                   "stripe_version": "2024-04-10"})
    record("C.12 inactive card → 400 'Card is disabled'",
           r.status_code == 400,
           f"status={r.status_code} body={r.text[:160]}")


# ============================================================
# F.D) Issuing webhook
# ============================================================
def test_issuing_webhook(gid, tok):
    """Inject simulated Stripe Issuing webhook events and verify side-effects on
    group.virtual_card.transactions[] + spent + auto-disable when cap reached.

    This requires the card to still be ACTIVE. Because the previous test in the
    chain disabled the card, we'll create a NEW group + new card just for the
    webhook tests.
    """
    print("\n=== F.D) Issuing webhook (auth + transaction events) ===")

    # Build a fresh group with an active card (1 buck again).
    lead = register_and_verify(f"WHLead_{TS}", f"+1892{TS%10000000:07d}")
    g = create_fast_split_group(lead["id"], 1.00, f"WH F2 {TS}")
    gid_wh = g["id"]
    grant_credit(tok, lead["id"], 5.0, "WH funding")
    rc = http("POST", f"/groups/{gid_wh}/contribute",
              json={"user_id": lead["id"], "origin_url": ORIGIN})
    assert rc.status_code == 200, f"contribute lead: {rc.text}"

    g_after = get_group(gid_wh)
    vc = g_after.get("virtual_card") or {}
    card_id = vc.get("stripe_card_id")
    record("D.1 fresh card auto-issued for webhook test",
           bool(card_id) and card_id.startswith("ic_"),
           f"card_id={card_id}")

    # ---- Authorization-only event ----
    auth_evt = {
        "type": "issuing_authorization.created",
        "data": {
            "object": {
                "id": f"iauth_{TS}_test1",
                "amount": -150,
                "approved": True,
                "card": {"id": card_id},
                "merchant_data": {"name": "Test Coffee", "category": "eating_places", "city": "SF"},
            }
        },
    }
    r = http("POST", "/webhook/stripe/issuing", json=auth_evt)
    record("D.2 authorization webhook 200", r.status_code == 200,
           f"status={r.status_code} body={r.text[:160]}")
    if r.status_code == 200:
        js = r.json()
        record("D.3 webhook reply has ok=true + type matches",
               js.get("ok") is True and js.get("type") == "issuing_authorization.created",
               f"reply={js}")

    # Authorization should NOT mutate spent
    g_check = get_group(gid_wh)
    spent_after_auth = (g_check.get("virtual_card") or {}).get("spent") or 0.0
    record("D.4 spent unchanged after authorization event",
           abs(float(spent_after_auth) - 0.0) < 0.001,
           f"spent={spent_after_auth}")

    # ---- Transaction settled event (-$2 → bumps spent by 2.0) ----
    txn_evt = {
        "type": "issuing_transaction.created",
        "data": {
            "object": {
                "id": f"itxn_{TS}_t1",
                "amount": -200,  # -$2.00 from cardholder POV
                "currency": "usd",
                "type": "capture",
                "card": card_id,  # spec: data.object.card == card_id (string)
                "merchant_data": {"name": "Test Coffee", "category": "eating_places", "city": "SF"},
            }
        },
    }
    r = http("POST", "/webhook/stripe/issuing", json=txn_evt)
    record("D.5 transaction webhook 200", r.status_code == 200,
           f"status={r.status_code} body={r.text[:160]}")

    g_check = get_group(gid_wh)
    vc_check = g_check.get("virtual_card") or {}
    txns = vc_check.get("transactions") or []
    record("D.6 group.virtual_card.transactions has 1 row",
           len(txns) >= 1,
           f"len(txns)={len(txns)} sample={(txns[0] if txns else None)}")
    record("D.7 spent bumped by 2.00",
           abs(float(vc_check.get("spent") or 0) - 2.0) < 0.01,
           f"spent={vc_check.get('spent')}")
    # Auto-disable: card_disable_mode='auto' (default) and spent (2.0) >= cap (1.0)
    record("D.8 auto-disable triggered (status inactive, spent >= cap)",
           vc_check.get("status") == "inactive",
           f"status={vc_check.get('status')} spent={vc_check.get('spent')} cap={vc_check.get('spend_cap')}")

    # ---- Webhook for unknown card → still 200 (just no-op) ----
    txn_evt2 = {
        "type": "issuing_transaction.created",
        "data": {
            "object": {
                "id": f"itxn_{TS}_unk",
                "amount": -100,
                "currency": "usd",
                "type": "capture",
                "card": "ic_DOESNT_EXIST_X",
                "merchant_data": {"name": "Nope", "city": "Nowhere"},
            }
        },
    }
    r = http("POST", "/webhook/stripe/issuing", json=txn_evt2)
    record("D.9 webhook for unknown card returns 200 (silent no-op)",
           r.status_code == 200,
           f"status={r.status_code} body={r.text[:160]}")


# ============================================================
# F.E) Push provisioning stub
# ============================================================
def test_push_provisioning(gid):
    print("\n=== F.E) Push provisioning stub ===")
    r = http("POST", f"/groups/{gid}/card/push-provisioning")
    # Spec: should return 501 with body {ok:false, available:false, reason, alternative}
    record("E.1 push-provisioning returns 501",
           r.status_code == 501,
           f"status={r.status_code} body={r.text[:200]}")
    try:
        js = r.json()
    except Exception:
        js = None
    if isinstance(js, dict):
        record("E.2 body shape (ok=false, available=false, reason+alternative)",
               js.get("ok") is False and js.get("available") is False
               and isinstance(js.get("reason"), str) and isinstance(js.get("alternative"), str),
               f"body={js}")
    else:
        # If it's a list (FastAPI tuple-return bug) flag it
        record("E.2 body shape (ok=false, available=false, reason+alternative)",
               False, f"body type={type(js).__name__} body={r.text[:200]}")


# ============================================================
# F.F) Admin issuing settings — round trip + new fields
# ============================================================
def test_issuing_settings_roundtrip(tok):
    print("\n=== F.F) Admin issuing settings — round-trip + new F2 fields ===")
    # Reset to defaults first
    http("POST", "/admin/integrations/issuing", headers=admin_headers(tok),
         json={"require_otp_for_card_reveal": True, "reveal_ttl_seconds": 60})

    r = http("GET", "/admin/integrations/issuing", headers=admin_headers(tok))
    record("F.1 GET defaults 200", r.status_code == 200, f"status={r.status_code}")
    settings = r.json() if r.status_code == 200 else {}
    record("F.2 require_otp_for_card_reveal default True",
           settings.get("require_otp_for_card_reveal") is True,
           f"value={settings.get('require_otp_for_card_reveal')}")
    record("F.3 reveal_ttl_seconds default 60",
           settings.get("reveal_ttl_seconds") == 60,
           f"value={settings.get('reveal_ttl_seconds')}")

    # POST update both
    r = http("POST", "/admin/integrations/issuing", headers=admin_headers(tok),
             json={"require_otp_for_card_reveal": False, "reveal_ttl_seconds": 90})
    record("F.4 POST {require_otp:false, ttl:90} 200",
           r.status_code == 200, f"status={r.status_code} body={r.text[:160]}")
    r = http("GET", "/admin/integrations/issuing", headers=admin_headers(tok))
    new = r.json() if r.status_code == 200 else {}
    record("F.5 require_otp_for_card_reveal persisted=False",
           new.get("require_otp_for_card_reveal") is False,
           f"value={new.get('require_otp_for_card_reveal')}")
    record("F.6 reveal_ttl_seconds persisted=90",
           new.get("reveal_ttl_seconds") == 90,
           f"value={new.get('reveal_ttl_seconds')}")

    # Reset to defaults
    r = http("POST", "/admin/integrations/issuing", headers=admin_headers(tok),
             json={"require_otp_for_card_reveal": True, "reveal_ttl_seconds": 60})
    record("F.7 reset to defaults 200", r.status_code == 200,
           f"status={r.status_code}")
    r = http("GET", "/admin/integrations/issuing", headers=admin_headers(tok))
    js = r.json() if r.status_code == 200 else {}
    record("F.8 after reset → require_otp=True + ttl=60",
           js.get("require_otp_for_card_reveal") is True and js.get("reveal_ttl_seconds") == 60,
           f"value={js.get('require_otp_for_card_reveal')} ttl={js.get('reveal_ttl_seconds')}")


# ============================================================
# F.G) Phase F1 regression
# ============================================================
def test_f1_regression(tok):
    print("\n=== F.G) Phase F1 regression: contribute Path A + B + status + disable-card + admin issuing ===")
    # Already exercised contribute Path A in setup. Re-run a quick Path B and status.
    lead = register_and_verify(f"RegLead_{TS}", f"+1893{TS%10000000:07d}")
    g = create_fast_split_group(lead["id"], 30.00, f"F1 Regress {TS}")
    gid = g["id"]

    # Path B: no credits → expect Stripe URL
    r = http("POST", f"/groups/{gid}/contribute",
             json={"user_id": lead["id"], "origin_url": ORIGIN})
    record("G.1 Path B contribute 200", r.status_code == 200,
           f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        js = r.json()
        record("G.2 checkout_required=true with cs_test_ session",
               js.get("checkout_required") is True
               and isinstance(js.get("session_id"), str)
               and js["session_id"].startswith("cs_test_"),
               f"checkout_required={js.get('checkout_required')} sid={js.get('session_id')}")
        sid = js.get("session_id")
        rs = http("GET", f"/contribute/status/{sid}")
        record("G.3 GET /contribute/status 200 (unpaid)",
               rs.status_code == 200,
               f"status={rs.status_code} body={rs.text[:200]}")
        if rs.status_code == 200:
            sjs = rs.json()
            record("G.4 status=open + payment_status=unpaid + applied=false",
                   sjs.get("status") in ("open", "complete")
                   and sjs.get("payment_status") in ("unpaid", "no_payment_required")
                   and sjs.get("applied") is False,
                   f"status={sjs.get('status')} pay={sjs.get('payment_status')} applied={sjs.get('applied')}")

    # Path A regression: grant credits, contribute → credit_only true
    grant_credit(tok, lead["id"], 50.0, "regress")
    r = http("POST", f"/groups/{gid}/contribute",
             json={"user_id": lead["id"], "origin_url": ORIGIN})
    record("G.5 Path A contribute 200 (credit_only)",
           r.status_code == 200 and r.json().get("credit_only") is True,
           f"status={r.status_code} body={r.text[:200]}")


# ============================================================
# Entry
# ============================================================
def main():
    print(f"==== Phase F2 backend test (TS={TS}) ====")
    try:
        lead, m1, gid, tok = test_sensitive_otp_and_setup()
    except Exception as e:
        record("setup", False, str(e))
        _summary()
        return

    test_sensitive_otp(lead, m1)
    test_ephemeral_key_auth_chain(lead, m1, gid, tok)
    test_issuing_webhook(gid, tok)
    test_push_provisioning(gid)
    test_issuing_settings_roundtrip(tok)
    # Run inactive card path AFTER webhook test (which uses a fresh group),
    # so we don't break the webhook test by disabling first.
    test_ephemeral_key_inactive_card(lead, gid, tok)
    test_f1_regression(tok)
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
