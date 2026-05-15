"""Regression test for layered-fee refactor — Dec 2025.

Verifies the new `_compute_layered_member_fees()` math against the live
preview backend. See review request in test_result.md for the full spec.

Layering order (Equal):
    Share/Total/N  →  + Platform  →  + Extras  →  + Insurance%  →  + Tx%
"""
from __future__ import annotations
import sys
import time
import json

import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"
TOL = 0.02

PASS = []
FAIL = []


def _ok(label, cond, extra=""):
    (PASS if cond else FAIL).append((label, extra))
    print(("✅" if cond else "❌"), label, ("→ " + extra) if extra else "")


def _approx(a, b, tol=TOL):
    return abs(float(a) - float(b)) <= tol


# ───────── Admin helpers ─────────
def admin_login():
    r = requests.post(BASE + "/admin/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    r.raise_for_status()
    return r.json()["token"]


def get_app_config(admin_token):
    r = requests.get(BASE + "/admin/app-config",
                     headers={"Authorization": "Bearer " + admin_token})
    r.raise_for_status()
    return r.json()


def put_app_config(admin_token, cfg):
    r = requests.put(
        BASE + "/admin/app-config",
        headers={"Authorization": "Bearer " + admin_token,
                 "Content-Type": "application/json"},
        json=cfg,
    )
    if not r.ok:
        print("[put-cfg] error", r.status_code, r.text[:400])
    r.raise_for_status()
    return r.json()


# ───────── User helpers ─────────
def _phone_for(seed):
    base = int(time.time() * 1000) % 10_000_000_000
    n = (base + seed * 17) % 10_000_000_000
    return f"+1{str(n).zfill(10)[:10]}"


def register(name):
    r = requests.post(BASE + "/auth/register", json={"name": name})
    r.raise_for_status()
    return r.json()


def send_otp(uid, phone):
    r = requests.post(BASE + "/auth/send-otp", json={"user_id": uid, "phone": phone})
    if r.status_code == 429:
        return {"rate_limited": True}
    r.raise_for_status()
    return r.json()


def verify_otp(uid, phone, code="123456"):
    r = requests.post(
        BASE + "/auth/verify-otp",
        json={"user_id": uid, "phone": phone, "code": code, "confirm_existing": True},
    )
    if not r.ok:
        print("[verify-otp]", r.status_code, r.text[:200])
    r.raise_for_status()
    return r.json()


def create_user(name_prefix, seed):
    user = register(f"{name_prefix}{int(time.time()*1000)%100000}")
    phone = _phone_for(seed)
    send_otp(user["id"], phone)
    verified = verify_otp(user["id"], phone)
    return verified or user


def create_group(lead_id, title, total, split="fast", tax=0.0, tip=0.0, items=None):
    body = {
        "lead_id": lead_id, "title": title, "total_amount": total,
        "split_mode": split, "tax": tax, "tip": tip,
        "items": items or [],
    }
    r = requests.post(BASE + "/groups", json=body)
    r.raise_for_status()
    return r.json()


def join_group(gid, uid):
    r = requests.post(BASE + f"/groups/{gid}/join",
                      json={"user_id": uid, "joined_via": "code"})
    r.raise_for_status()
    return r.json()


def get_group(gid):
    r = requests.get(BASE + f"/groups/{gid}")
    r.raise_for_status()
    return r.json()


def assign_item(gid, uid, item_id, qty):
    r = requests.post(BASE + f"/groups/{gid}/assign",
                      json={"user_id": uid, "item_id": item_id, "quantity": qty})
    r.raise_for_status()
    return r.json()


# ───────── Compute expected layered fees (mirror of core.py) ─────────
def expected_layered(share, pct_base, cfg):
    core = cfg["core_fees"]
    extras_cfg = [e for e in (cfg.get("extra_fees") or []) if e.get("enabled")]
    if core["platform_fee_type"] == "percent":
        platform = round(core["platform_fee_value"] / 100.0 * pct_base, 2)
    else:
        platform = round(core["platform_fee_value"], 2)
    extras_total = 0.0
    for e in extras_cfg:
        if e["type"] == "percent":
            amt = round(e["value"] / 100.0 * pct_base, 2)
        else:
            amt = round(e["value"], 2)
        extras_total += amt
    insurance = round(core["insurance_pct"] / 100.0 * (share + platform + extras_total), 2)
    tx = round(core["transaction_fee_pct"] / 100.0 * (share + platform + extras_total + insurance), 2)
    total = round(share + platform + extras_total + insurance + tx, 2)
    return {
        "platform": platform, "extras_total": round(extras_total, 2),
        "insurance": insurance, "tx": tx, "total": total,
    }


# ════════════════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════════════════

def test_H_admin_config_schema(cfg):
    print("\n──── Test H: GET /admin/app-config returns new fields ────")
    core = cfg.get("core_fees", {})
    for fld in ("platform_fee_type", "platform_fee_value", "insurance_pct",
                "insurance_label", "transaction_fee_pct", "platform_fee_label",
                "transaction_fee_label"):
        _ok(f"H.{fld} present", fld in core, f"value={core.get(fld)}")
    _ok("H.platform_fee_type valid",
        core.get("platform_fee_type") in ("fixed", "percent"),
        f"got {core.get('platform_fee_type')}")


def test_A_existing_group(cfg):
    print("\n──── Test A: Existing group g_4a39452c2e ────")
    g = get_group("g_4a39452c2e")
    pu = g.get("per_user", [])
    _ok("A.has_3_members", len(pu) == 3, f"got {len(pu)}")
    if len(pu) < 3:
        return
    totals = [p["total"] for p in pu]
    _ok("A.all_totals_equal (no asymmetry)",
        all(_approx(t, totals[0], 0.01) for t in totals),
        f"totals={totals}")

    exp = expected_layered(share=20.0, pct_base=20.0, cfg=cfg)
    _ok("A.share=20", _approx(pu[0]["food"], 20.0),
        f"food={pu[0]['food']}")
    _ok("A.platform_match",
        _approx(pu[0]["platform_fee"], exp["platform"]),
        f"actual={pu[0]['platform_fee']} expected={exp['platform']}")
    _ok("A.insurance_match",
        _approx(pu[0]["insurance"], exp["insurance"]),
        f"actual={pu[0]['insurance']} expected={exp['insurance']}")
    _ok("A.tx_match",
        _approx(pu[0]["transaction_fee"], exp["tx"]),
        f"actual={pu[0]['transaction_fee']} expected={exp['tx']}")
    _ok("A.total_match",
        _approx(pu[0]["total"], exp["total"]),
        f"actual={pu[0]['total']} expected={exp['total']}")

    lead_p = next((p for p in pu if p["user_id"] == g["lead_id"]), None)
    lead_gap = max(0.0, lead_p["total"] - lead_p["contributed"] - lead_p.get("repaid", 0))
    other_gaps = sum(
        max(0.0, p["total"] - p["contributed"] - p.get("repaid", 0))
        for p in pu if p["user_id"] != g["lead_id"]
    )
    expected_r2c = round(lead_gap + other_gaps, 2)
    actual_r2c = g["funding"]["remaining_to_collect"]
    _ok("A.r2c symmetric sum (lead+others)",
        _approx(actual_r2c, expected_r2c),
        f"actual={actual_r2c} expected={expected_r2c}")

    expected_fees_total = sum(
        p["platform_fee"] + p["transaction_fee"] + p["insurance"] +
        p.get("extra_fees_total", 0) for p in pu
    )
    _ok("A.fees_total_includes_insurance",
        _approx(g["funding"]["fees_total"], expected_fees_total),
        f"actual={g['funding']['fees_total']} expected={round(expected_fees_total,2)}")

    for fld in ("platform_fee", "extra_fees", "extra_fees_total",
                "insurance", "transaction_fee", "total"):
        _ok(f"A.per_user has '{fld}'", all(fld in p for p in pu),
            f"sample={pu[0].get(fld)}")


def test_B_new_equal_2member(cfg):
    print("\n──── Test B: New 2-member equal $40 bill ────")
    lead = create_user("LeadB", 1001)
    m1 = create_user("MemB", 1002)
    g = create_group(lead["id"], "test_B_equal_40", 40.0, split="fast")
    join_group(g["id"], m1["id"])
    g = get_group(g["id"])
    pu = g["per_user"]
    _ok("B.2_members", len(pu) == 2, f"got {len(pu)}")
    exp = expected_layered(share=20.0, pct_base=20.0, cfg=cfg)
    print(f"[B] expected layered: {exp}")
    for p in pu:
        tag = p["user_id"][-6:]
        _ok(f"B.{tag}.share=20", _approx(p["food"], 20.0), f"food={p['food']}")
        _ok(f"B.{tag}.platform", _approx(p["platform_fee"], exp["platform"]),
            f"got {p['platform_fee']} exp {exp['platform']}")
        _ok(f"B.{tag}.insurance", _approx(p["insurance"], exp["insurance"]),
            f"got {p['insurance']} exp {exp['insurance']}")
        _ok(f"B.{tag}.tx", _approx(p["transaction_fee"], exp["tx"]),
            f"got {p['transaction_fee']} exp {exp['tx']}")
        _ok(f"B.{tag}.total", _approx(p["total"], exp["total"]),
            f"got {p['total']} exp {exp['total']}")
    expected_r2c = round(2 * exp["total"], 2)
    _ok("B.r2c == 2× total",
        _approx(g["funding"]["remaining_to_collect"], expected_r2c),
        f"actual={g['funding']['remaining_to_collect']} expected={expected_r2c}")


def test_C_itemized(cfg):
    print("\n──── Test C: Itemized 2-member, claimant takes $30 items, tax=$3 tip=$2 ────")
    lead = create_user("LeadC", 2001)
    m1 = create_user("MemC", 2002)
    items = [{"name": "Burger", "price": 30.0, "quantity": 1}]
    g = create_group(lead["id"], "test_C_itemized", 30.0,
                     split="itemized", tax=3.0, tip=2.0, items=items)
    join_group(g["id"], m1["id"])
    g = get_group(g["id"])
    item_id = g["items"][0]["id"]
    assign_item(g["id"], lead["id"], item_id, 1)
    g = get_group(g["id"])
    total_bill = g["total"]
    _ok("C.total=35", _approx(total_bill, 35.0), f"got {total_bill}")
    pu = g["per_user"]
    p_lead = next(p for p in pu if p["user_id"] == lead["id"])
    p_m1 = next(p for p in pu if p["user_id"] == m1["id"])
    _ok("C.lead.food=30", _approx(p_lead["food"], 30.0), f"food={p_lead['food']}")
    _ok("C.lead.tax_tip=5", _approx(p_lead["tax_tip"], 5.0),
        f"tax_tip={p_lead['tax_tip']}")
    _ok("C.lead.merchant_share=35",
        _approx(p_lead["merchant_share"], 35.0),
        f"share={p_lead['merchant_share']}")
    # pct_base = total / N = 35/2 = 17.5
    exp_lead = expected_layered(share=35.0, pct_base=17.5, cfg=cfg)
    print(f"[C] expected lead layered: {exp_lead}")
    _ok("C.lead.platform",
        _approx(p_lead["platform_fee"], exp_lead["platform"]),
        f"got {p_lead['platform_fee']} exp {exp_lead['platform']}")
    _ok("C.lead.insurance",
        _approx(p_lead["insurance"], exp_lead["insurance"]),
        f"got {p_lead['insurance']} exp {exp_lead['insurance']}")
    _ok("C.lead.tx",
        _approx(p_lead["transaction_fee"], exp_lead["tx"]),
        f"got {p_lead['transaction_fee']} exp {exp_lead['tx']}")
    _ok("C.lead.total",
        _approx(p_lead["total"], exp_lead["total"]),
        f"got {p_lead['total']} exp {exp_lead['total']}")
    _ok("C.m1.food=0", _approx(p_m1["food"], 0.0), f"food={p_m1['food']}")
    _ok("C.m1.total=0", _approx(p_m1["total"], 0.0), f"total={p_m1['total']}")
    _ok("C.m1.platform=0",
        _approx(p_m1["platform_fee"], 0.0), f"platform={p_m1['platform_fee']}")
    _ok("C.m1.tx=0", _approx(p_m1["transaction_fee"], 0.0),
        f"tx={p_m1['transaction_fee']}")
    _ok("C.m1.insurance=0", _approx(p_m1.get("insurance", 0), 0.0),
        f"ins={p_m1.get('insurance')}")


def test_D_percent_platform(admin_token, original_cfg):
    print("\n──── Test D: platform_fee_type=percent value=2 ────")
    cfg = json.loads(json.dumps(original_cfg))
    cfg["core_fees"]["platform_fee_type"] = "percent"
    cfg["core_fees"]["platform_fee_value"] = 2.0
    new_cfg = put_app_config(admin_token, cfg)
    lead = create_user("LeadD", 3001)
    m1 = create_user("MemD", 3002)
    g = create_group(lead["id"], "test_D_percent", 40.0, split="fast")
    join_group(g["id"], m1["id"])
    g = get_group(g["id"])
    p = g["per_user"][0]
    exp = expected_layered(share=20.0, pct_base=20.0, cfg=new_cfg)
    print(f"[D] expected with platform 2%: {exp}")
    _ok("D.platform = 2% × 20 = 0.40",
        _approx(p["platform_fee"], 0.40),
        f"got {p['platform_fee']}")
    _ok("D.insurance matches layered formula",
        _approx(p["insurance"], exp["insurance"]),
        f"got {p['insurance']} exp {exp['insurance']}")
    _ok("D.tx matches layered formula",
        _approx(p["transaction_fee"], exp["tx"]),
        f"got {p['transaction_fee']} exp {exp['tx']}")
    _ok("D.total matches layered formula",
        _approx(p["total"], exp["total"]),
        f"got {p['total']} exp {exp['total']}")


def test_E_insurance_5pct(admin_token, original_cfg):
    print("\n──── Test E: insurance_pct=5 ────")
    cfg = json.loads(json.dumps(original_cfg))
    cfg["core_fees"]["insurance_pct"] = 5.0
    new_cfg = put_app_config(admin_token, cfg)
    lead = create_user("LeadE", 4001)
    m1 = create_user("MemE", 4002)
    g = create_group(lead["id"], "test_E_ins5", 40.0, split="fast")
    join_group(g["id"], m1["id"])
    g = get_group(g["id"])
    p = g["per_user"][0]
    exp = expected_layered(share=20.0, pct_base=20.0, cfg=new_cfg)
    print(f"[E] expected with insurance 5%: {exp}")
    _ok("E.insurance ≈ 5% × (share+platform+extras)",
        _approx(p["insurance"], exp["insurance"]),
        f"got {p['insurance']} exp {exp['insurance']}")
    _ok("E.tx layered over insurance",
        _approx(p["transaction_fee"], exp["tx"]),
        f"got {p['transaction_fee']} exp {exp['tx']}")
    _ok("E.total matches",
        _approx(p["total"], exp["total"]),
        f"got {p['total']} exp {exp['total']}")


def test_F_pay_shortfall(cfg):
    print("\n──── Test F: POST /pay shortfall_mode=lead smoke ────")
    lead = create_user("LeadF", 5001)
    m1 = create_user("MemF", 5002)
    g = create_group(lead["id"], "test_F_shortfall", 40.0, split="fast")
    join_group(g["id"], m1["id"])
    # Without lead contributing own share, /pay should 400
    r = requests.post(BASE + f"/groups/{g['id']}/pay",
                      json={"user_id": lead["id"], "shortfall_mode": "lead",
                            "is_loan": True})
    _ok("F.pay without own contribution → 400",
        r.status_code == 400,
        f"status={r.status_code} body={r.text[:120]}")
    _ok("F.error mentions 'contribute your own share'",
        "contribute your own share" in r.text.lower(),
        f"body={r.text[:150]}")


def test_I_smoke():
    print("\n──── Test I: smoke unaffected endpoints ────")
    r = requests.get(BASE + "/runtime/landing-page")
    _ok("I.landing_page 200", r.status_code == 200, f"status={r.status_code}")
    cc = r.headers.get("Cache-Control") or ""
    _ok("I.landing_page Cache-Control no-store",
        "no-store" in cc.lower(), f"cc={cc}")
    r = requests.post(BASE + "/auth/check-session",
                      json={"user_id": "u_fake", "session_id": "x"})
    _ok("I.check_session 200", r.status_code == 200, f"status={r.status_code}")
    r = requests.get(BASE + "/users/u_faae5405ba/groups")
    _ok("I.user_groups 200", r.status_code == 200, f"status={r.status_code}")


# ════════════════════════════════════════════════════════════════════════════
def main():
    print(f"BASE = {BASE}")
    admin_token = admin_login()
    original_cfg = get_app_config(admin_token)
    print("[setup] current core_fees:",
          json.dumps(original_cfg["core_fees"], indent=2))

    try:
        test_H_admin_config_schema(original_cfg)
        test_A_existing_group(original_cfg)
        test_B_new_equal_2member(original_cfg)
        test_C_itemized(original_cfg)
        test_D_percent_platform(admin_token, original_cfg)
        # After D, must restore for subsequent tests:
        print("[teardown D] restoring platform_fee_type=fixed, value=0.50")
        cfg_after_d = json.loads(json.dumps(original_cfg))
        put_app_config(admin_token, cfg_after_d)
        test_E_insurance_5pct(admin_token, original_cfg)
        # Restore again before next:
        print("[teardown E] restoring insurance_pct=1.0")
        put_app_config(admin_token, original_cfg)
        test_F_pay_shortfall(original_cfg)
        test_I_smoke()
    finally:
        print("\n[teardown] restoring original app-config")
        put_app_config(admin_token, original_cfg)

    print("\n══════════════════ SUMMARY ══════════════════")
    print(f"PASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    if FAIL:
        print("\nFailures:")
        for label, extra in FAIL:
            print(f"  ❌ {label} {extra}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
