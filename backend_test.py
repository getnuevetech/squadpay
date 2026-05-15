"""Backend regression test — per-fee enable/disable + max-$ caps.

Reviews the new pricing knobs added to /api/admin/app-config:
  • core_fees.{transaction_fee,platform_fee,insurance}_enabled
  • core_fees.{transaction_fee,platform_fee,insurance}_cap
  • each extra_fees[].cap

Uses the existing live preview backend. The test group `g_4a39452c2e`
must exist (3 members, $60 merchant, Equal split).
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time
from typing import Any, Dict

import requests

BACKEND_URL = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"
GROUP_ID = "g_4a39452c2e"

TOL = 0.02  # $0.02 tolerance

passes: list[str] = []
fails: list[str] = []


def _result(ok: bool, label: str, extra: str = "") -> None:
    line = f"{'✅' if ok else '❌'} {label}"
    if extra:
        line += f" — {extra}"
    print(line)
    (passes if ok else fails).append(line)


def admin_login() -> str:
    r = requests.post(
        f"{BACKEND_URL}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    r.raise_for_status()
    body = r.json()
    tok = body.get("access_token") or body.get("token")
    assert tok, f"no admin token in response: {body}"
    return tok


def get_app_config(tok: str) -> Dict[str, Any]:
    r = requests.get(
        f"{BACKEND_URL}/admin/app-config",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def put_app_config(tok: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.put(
        f"{BACKEND_URL}/admin/app-config",
        json=cfg,
        headers={"Authorization": f"Bearer {tok}"},
        timeout=30,
    )
    if r.status_code >= 400:
        print(f"  PUT failed {r.status_code}: {r.text[:400]}")
    r.raise_for_status()
    return r.json()


def get_group() -> Dict[str, Any]:
    r = requests.get(f"{BACKEND_URL}/groups/{GROUP_ID}", timeout=20)
    if r.status_code >= 400:
        print(f"  GET group failed {r.status_code}: {r.text[:400]}")
    r.raise_for_status()
    return r.json()


def first_member_breakdown(g: Dict[str, Any]) -> Dict[str, Any]:
    """Return the first non-zero per_user row (any member since equal split)."""
    for p in g.get("per_user", []):
        if p.get("total", 0) > 0:
            return p
    return g["per_user"][0]


def near(actual: float, expected: float, tol: float = TOL) -> bool:
    return abs(float(actual) - float(expected)) <= tol


def assert_member(p: Dict[str, Any], *, food=None, platform=None, insurance=None, tx=None, total=None, label: str) -> None:
    parts = []
    ok = True
    if food is not None:
        a = float(p.get("food", 0))
        good = near(a, food)
        parts.append(f"food={a:.2f}(exp {food:.2f}){'' if good else ' ✗'}")
        ok = ok and good
    if platform is not None:
        a = float(p.get("platform_fee", 0))
        good = near(a, platform)
        parts.append(f"platform={a:.2f}(exp {platform:.2f}){'' if good else ' ✗'}")
        ok = ok and good
    if insurance is not None:
        a = float(p.get("insurance", 0))
        good = near(a, insurance)
        parts.append(f"insurance={a:.2f}(exp {insurance:.2f}){'' if good else ' ✗'}")
        ok = ok and good
    if tx is not None:
        a = float(p.get("transaction_fee", 0))
        good = near(a, tx)
        parts.append(f"tx={a:.2f}(exp {tx:.2f}){'' if good else ' ✗'}")
        ok = ok and good
    if total is not None:
        a = float(p.get("total", 0))
        good = near(a, total)
        parts.append(f"total={a:.2f}(exp {total:.2f}){'' if good else ' ✗'}")
        ok = ok and good
    _result(ok, label, "  ".join(parts))


# ────────────────────────────────────────────────────────────────────
# Run tests
# ────────────────────────────────────────────────────────────────────
def main() -> int:
    print(f"BACKEND={BACKEND_URL}")
    tok = admin_login()
    print("admin login OK")

    # Snapshot original config to restore at end
    original_cfg = get_app_config(tok)
    original_core = copy.deepcopy(original_cfg.get("core_fees") or {})
    original_extras = copy.deepcopy(original_cfg.get("extra_fees") or [])

    # ─── A) Schema verification ──────────────────────────────
    cf = original_cfg.get("core_fees") or {}
    schema_ok = True
    schema_parts = []
    for f, want in [
        ("transaction_fee_enabled", True),
        ("platform_fee_enabled", True),
        ("insurance_enabled", True),
    ]:
        has = f in cf
        is_val = cf.get(f) is True if has else False
        schema_parts.append(f"{f}={'present' if has else 'MISSING'}={cf.get(f)}")
        schema_ok = schema_ok and has and is_val
    for f in ("transaction_fee_cap", "platform_fee_cap", "insurance_cap"):
        has = f in cf
        val = cf.get(f, None)
        is_zero = val == 0 or val == 0.0
        schema_parts.append(f"{f}={'present' if has else 'MISSING'}={val}")
        schema_ok = schema_ok and has and is_zero
    extras = original_cfg.get("extra_fees") or []
    extras_cap_ok = all(("cap" in e) for e in extras)
    schema_parts.append(f"extras[].cap={'all-present' if extras_cap_ok else 'MISSING-IN-SOME'} (n={len(extras)})")
    _result(schema_ok and extras_cap_ok, "A) GET /admin/app-config schema", "  ".join(schema_parts))

    # Helper to mutate core fees from a known base
    def cfg_with(**overrides) -> Dict[str, Any]:
        out = copy.deepcopy(original_cfg)
        out["core_fees"] = {**copy.deepcopy(original_core), **overrides}
        return out

    # ─── Baseline ────────────────────────────────────────────
    # Make sure we're at known state (all enabled, all caps 0)
    baseline = cfg_with(
        transaction_fee_enabled=True,
        platform_fee_enabled=True,
        insurance_enabled=True,
        transaction_fee_cap=0,
        platform_fee_cap=0,
        insurance_cap=0,
    )
    put_app_config(tok, baseline)
    g = get_group()
    p0 = first_member_breakdown(g)
    print(f"\nBaseline first-member breakdown: food={p0.get('food'):.2f} "
          f"platform={p0.get('platform_fee'):.2f} insurance={p0.get('insurance'):.2f} "
          f"tx={p0.get('transaction_fee'):.2f} total={p0.get('total'):.2f}")
    assert_member(p0, food=20.00, platform=0.50, insurance=0.21, tx=0.41, total=21.12,
                  label="Baseline (all enabled, caps 0)")

    # Derived live rates (tx & insurance %) from baseline so we don't hard-code 2% vs 3%.
    # food=$20, platform=$0.50 → insurance_base=$20.50
    insurance_rate = round(p0.get("insurance", 0) / 20.50, 4) if p0.get("insurance") else 0
    # tx_base = food + platform + insurance
    tx_base = 20.00 + p0.get("platform_fee", 0) + p0.get("insurance", 0)
    tx_rate = round(p0.get("transaction_fee", 0) / tx_base, 4) if tx_base else 0
    print(f"Derived live rates: insurance≈{insurance_rate*100:.2f}%  tx≈{tx_rate*100:.2f}%")

    # ─── B) Disable Transaction Fee ──────────────────────────
    put_app_config(tok, cfg_with(transaction_fee_enabled=False))
    g = get_group()
    p = first_member_breakdown(g)
    # food=$20, platform=$0.50, insurance=1%×$20.50≈$0.21, tx=$0, total≈$20.71
    assert_member(p, platform=0.50, insurance=0.21, tx=0.00, total=20.71,
                  label="B) tx DISABLED")
    # Re-enable & verify baseline restores
    put_app_config(tok, cfg_with(transaction_fee_enabled=True))
    g = get_group()
    p = first_member_breakdown(g)
    assert_member(p, total=21.12, tx=0.41, label="B) tx RE-ENABLED → baseline")

    # ─── C) Disable Platform Fee ─────────────────────────────
    put_app_config(tok, cfg_with(platform_fee_enabled=False))
    g = get_group()
    p = first_member_breakdown(g)
    # platform=$0, insurance_base=$20.00, insurance=1%×$20=$0.20
    # tx_base = $20.20, tx=2%×$20.20≈$0.40, total≈$20.60
    assert_member(p, platform=0.00, insurance=0.20, tx=0.40, total=20.60,
                  label="C) platform DISABLED")
    put_app_config(tok, cfg_with(platform_fee_enabled=True))

    # ─── D) Disable Insurance ────────────────────────────────
    put_app_config(tok, cfg_with(insurance_enabled=False))
    g = get_group()
    p = first_member_breakdown(g)
    # insurance=0, tx_base=$20+$0.50=$20.50, tx=2%×$20.50≈$0.41, total≈$20.91
    assert_member(p, platform=0.50, insurance=0.00, tx=0.41, total=20.91,
                  label="D) insurance DISABLED")
    put_app_config(tok, cfg_with(insurance_enabled=True))

    # ─── E) Cap — transaction_fee_cap=$0.10 ──────────────────
    put_app_config(tok, cfg_with(transaction_fee_cap=0.10))
    g = get_group()
    p = first_member_breakdown(g)
    # tx capped to $0.10, total = $20 + $0.50 + $0.21 + $0.10 = $20.81
    assert_member(p, platform=0.50, insurance=0.21, tx=0.10, total=20.81,
                  label="E) tx_cap=$0.10")
    put_app_config(tok, cfg_with(transaction_fee_cap=0))
    g = get_group()
    p = first_member_breakdown(g)
    assert_member(p, total=21.12, tx=0.41,
                  label="E) tx_cap=0 → uncapped restored")

    # ─── F) Cap — platform_fee_cap=$0.20 ─────────────────────
    put_app_config(tok, cfg_with(platform_fee_cap=0.20))
    g = get_group()
    p = first_member_breakdown(g)
    # platform capped to $0.20 (from $0.50 fixed)
    # insurance_base = $20.00 + $0.20 = $20.20 → insurance = 1%×20.20 = $0.20
    # tx_base = $20.20 + $0.20 = $20.40 → tx = 2%×$20.40 = $0.408 → $0.41
    # total = $20 + $0.20 + $0.20 + $0.41 = $20.81
    assert_member(p, platform=0.20, insurance=0.20, tx=0.41, total=20.81,
                  label="F) platform_fee_cap=$0.20 (feeds next layer)")
    put_app_config(tok, cfg_with(platform_fee_cap=0))

    # ─── G) Combined: platform disabled + tx_cap=$0.05 ──────
    put_app_config(tok, cfg_with(platform_fee_enabled=False, transaction_fee_cap=0.05))
    g = get_group()
    p = first_member_breakdown(g)
    # platform=$0, insurance_base=$20 → insurance=$0.20
    # tx pre-cap = 2%×($20+0+$0.20) = 2%×$20.20 = $0.404 → capped to $0.05
    # total = $20 + 0 + $0.20 + $0.05 = $20.25
    assert_member(p, platform=0.00, insurance=0.20, tx=0.05, total=20.25,
                  label="G) Combined: platform OFF + tx_cap=$0.05")
    # Restore both
    put_app_config(tok, cfg_with(platform_fee_enabled=True, transaction_fee_cap=0))
    g = get_group()
    p = first_member_breakdown(g)
    assert_member(p, total=21.12, tx=0.41, platform=0.50,
                  label="G) Restored → baseline")

    # ─── H) Smoke: existing endpoints still work ─────────────
    # auth/check-session
    r1 = requests.post(f"{BACKEND_URL}/auth/check-session", json={"user_id": "nobody", "session_id": "none"}, timeout=20)
    _result(r1.status_code in (200, 401, 404),
            "H1) POST /auth/check-session reachable",
            f"status={r1.status_code}")
    # runtime/landing-page
    r2 = requests.get(f"{BACKEND_URL}/runtime/landing-page", timeout=20)
    cc = r2.headers.get("cache-control", "")
    _result(r2.status_code == 200 and "no-store" in cc.lower(),
            "H2) GET /runtime/landing-page",
            f"status={r2.status_code} cache-control={cc!r}")
    # Group create — needs a real verified lead. Use a quick register-only ping
    # to ensure /groups path is alive (we expect 4xx for unverified/no-member-yet,
    # not 5xx).
    ts = int(time.time())
    rreg = requests.post(
        f"{BACKEND_URL}/auth/register",
        json={"name": f"FeeTester {ts}"},
        timeout=20,
    )
    if rreg.status_code == 200:
        uid = rreg.json().get("id")
        rgrp = requests.post(
            f"{BACKEND_URL}/groups",
            json={
                "lead_id": uid,
                "title": "FeeTest Bill",
                "total_amount": 30.0,
                "split_mode": "fast",
                "tax": 0,
                "tip": 0,
                "items": [],
            },
            timeout=20,
        )
        # Lead unverified → expect 403 or 4xx (not 5xx)
        _result(rgrp.status_code < 500,
                "H3) POST /groups reachable (unverified path)",
                f"status={rgrp.status_code}")
    else:
        _result(rreg.status_code < 500,
                "H3) POST /auth/register reachable",
                f"status={rreg.status_code}")

    # ─── Restore original config exactly ────────────────────
    print("\nRestoring original admin config...")
    restore_payload = copy.deepcopy(original_cfg)
    restore_payload["core_fees"] = original_core
    restore_payload["extra_fees"] = original_extras
    put_app_config(tok, restore_payload)
    final_cfg = get_app_config(tok)
    final_cf = final_cfg.get("core_fees") or {}
    restored_ok = (
        final_cf.get("transaction_fee_enabled") is True
        and final_cf.get("platform_fee_enabled") is True
        and final_cf.get("insurance_enabled") is True
        and float(final_cf.get("transaction_fee_cap", 0)) == 0
        and float(final_cf.get("platform_fee_cap", 0)) == 0
        and float(final_cf.get("insurance_cap", 0)) == 0
    )
    _result(restored_ok, "FINAL: all toggles ON + caps 0 restored",
            f"tx_en={final_cf.get('transaction_fee_enabled')} "
            f"pf_en={final_cf.get('platform_fee_enabled')} "
            f"ins_en={final_cf.get('insurance_enabled')} "
            f"tx_cap={final_cf.get('transaction_fee_cap')} "
            f"pf_cap={final_cf.get('platform_fee_cap')} "
            f"ins_cap={final_cf.get('insurance_cap')}")
    # Final baseline sanity
    g = get_group()
    p = first_member_breakdown(g)
    assert_member(p, food=20.00, platform=0.50, insurance=0.21, tx=0.41, total=21.12,
                  label="FINAL group baseline check")

    print("\n" + "=" * 60)
    print(f"PASS: {len(passes)}   FAIL: {len(fails)}")
    for f in fails:
        print(f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
