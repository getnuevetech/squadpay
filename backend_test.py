"""
Backend regression test for two targeted fixes:

FIX A — extra_fees[].cap preserved on reload (BUG in load_app_config)
FIX B — Public fee-labels endpoint reflects admin label edits (regression)
"""

import json
import sys
import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PWD = "Letmein@2007#ForReal"

results = []  # (step, status, detail)


def log(step, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {step}  {detail}")
    results.append((step, ok, detail))


def admin_login():
    r = requests.post(f"{BASE}/admin/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PWD},
                      timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def get_cfg(token):
    r = requests.get(f"{BASE}/admin/app-config",
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def put_cfg(token, body):
    r = requests.put(f"{BASE}/admin/app-config",
                     headers={"Authorization": f"Bearer {token}"},
                     json=body, timeout=30)
    return r


def get_fee_labels():
    r = requests.get(f"{BASE}/runtime/fee-labels", timeout=30)
    return r


# ---------- FIX A ----------
def fix_a():
    print("\n=== FIX A: extra_fees[].cap preservation ===")
    token = admin_login()
    log("A1 admin login", True)

    cfg = get_cfg(token)
    extra_fees = cfg.get("extra_fees") or []
    if not extra_fees:
        log("A2 GET app-config has extra_fees[0]", False, f"extra_fees={extra_fees}")
        return
    original = dict(extra_fees[0])
    log("A2 GET app-config", True,
        f"current extra_fees[0]={original}")

    # Build the PUT body — preserve all existing fields, override extra_fees[0]
    new_extras = list(extra_fees)
    new_extras[0] = {
        "id": "extra_1",
        "name": "Concierge Fee",
        "type": "flat",
        "value": 5.0,
        "enabled": True,
        "cap": 50.0,
    }
    put_body = {
        "core_fees": cfg.get("core_fees"),
        "extra_fees": new_extras,
        "card": cfg.get("card"),
        "sms": cfg.get("sms"),
        "brand": cfg.get("brand"),
        "feature_flags": cfg.get("feature_flags"),
    }
    # Drop None
    put_body = {k: v for k, v in put_body.items() if v is not None}

    r = put_cfg(token, put_body)
    log("A3 PUT app-config with cap=50.0", r.status_code == 200,
        f"status={r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        return

    cfg2 = get_cfg(token)
    ef0 = (cfg2.get("extra_fees") or [{}])[0]
    log("A4 GET app-config extra_fees[0].cap == 50.0",
        abs(float(ef0.get("cap") or 0) - 50.0) < 1e-6,
        f"actual cap={ef0.get('cap')}, full row={ef0}")

    log("A5 extra_fees[0].name == 'Concierge Fee'",
        ef0.get("name") == "Concierge Fee",
        f"actual name={ef0.get('name')}")

    # Public endpoint
    rf = get_fee_labels()
    rf_json = rf.json() if rf.status_code == 200 else {}
    public_ef0 = (rf_json.get("extra_fees") or [{}])[0]
    log("A6 /runtime/fee-labels extra_fees[0].name == 'Concierge Fee'",
        rf.status_code == 200 and public_ef0.get("name") == "Concierge Fee",
        f"status={rf.status_code} extra_fees[0]={public_ef0}")

    # Restore
    restore_extras = list(cfg2.get("extra_fees") or [])
    restore_extras[0] = original
    restore_body = {
        "core_fees": cfg2.get("core_fees"),
        "extra_fees": restore_extras,
        "card": cfg2.get("card"),
        "sms": cfg2.get("sms"),
        "brand": cfg2.get("brand"),
        "feature_flags": cfg2.get("feature_flags"),
    }
    restore_body = {k: v for k, v in restore_body.items() if v is not None}
    rr = put_cfg(token, restore_body)
    log("A7 restore extra_fees[0] to original",
        rr.status_code == 200,
        f"status={rr.status_code}")


# ---------- FIX B ----------
def fix_b():
    print("\n=== FIX B: public fee-labels reflects admin edits ===")
    token = admin_login()
    log("B1 admin login", True)

    cfg = get_cfg(token)
    cf = cfg.get("core_fees") or {}
    orig_platform = cf.get("platform_fee_label")
    orig_tx = cf.get("transaction_fee_label")
    orig_ins = cf.get("insurance_label")
    log("B2 capture originals", True,
        f"platform={orig_platform!r} tx={orig_tx!r} ins={orig_ins!r}")

    def edit_label(field, value):
        c = get_cfg(token)
        new_cf = dict(c.get("core_fees") or {})
        new_cf[field] = value
        body = {
            "core_fees": new_cf,
            "extra_fees": c.get("extra_fees"),
            "card": c.get("card"),
            "sms": c.get("sms"),
            "brand": c.get("brand"),
            "feature_flags": c.get("feature_flags"),
        }
        body = {k: v for k, v in body.items() if v is not None}
        r = put_cfg(token, body)
        return r

    # platform_fee_label = "Service Charge"
    r = edit_label("platform_fee_label", "Service Charge")
    log("B3 PUT platform_fee_label='Service Charge'",
        r.status_code == 200, f"status={r.status_code}")
    rf = get_fee_labels()
    rfj = rf.json() if rf.status_code == 200 else {}
    log("B4 /runtime/fee-labels platform_fee_label == 'Service Charge'",
        rfj.get("platform_fee_label") == "Service Charge",
        f"actual={rfj.get('platform_fee_label')!r}")

    # transaction_fee_label = "Processing Fee"
    r = edit_label("transaction_fee_label", "Processing Fee")
    log("B5 PUT transaction_fee_label='Processing Fee'",
        r.status_code == 200, f"status={r.status_code}")
    rf = get_fee_labels()
    rfj = rf.json() if rf.status_code == 200 else {}
    log("B6 /runtime/fee-labels transaction_fee_label == 'Processing Fee'",
        rfj.get("transaction_fee_label") == "Processing Fee",
        f"actual={rfj.get('transaction_fee_label')!r}")

    # insurance_label = "Protection"
    r = edit_label("insurance_label", "Protection")
    log("B7 PUT insurance_label='Protection'",
        r.status_code == 200, f"status={r.status_code}")
    rf = get_fee_labels()
    rfj = rf.json() if rf.status_code == 200 else {}
    log("B8 /runtime/fee-labels insurance_label == 'Protection'",
        rfj.get("insurance_label") == "Protection",
        f"actual={rfj.get('insurance_label')!r}")

    # Restore all
    c = get_cfg(token)
    new_cf = dict(c.get("core_fees") or {})
    new_cf["platform_fee_label"] = orig_platform
    new_cf["transaction_fee_label"] = orig_tx
    new_cf["insurance_label"] = orig_ins
    body = {
        "core_fees": new_cf,
        "extra_fees": c.get("extra_fees"),
        "card": c.get("card"),
        "sms": c.get("sms"),
        "brand": c.get("brand"),
        "feature_flags": c.get("feature_flags"),
    }
    body = {k: v for k, v in body.items() if v is not None}
    r = put_cfg(token, body)
    log("B9 restore all 3 labels", r.status_code == 200,
        f"status={r.status_code}")

    rf = get_fee_labels()
    rfj = rf.json() if rf.status_code == 200 else {}
    log("B10 post-restore platform_fee_label",
        rfj.get("platform_fee_label") == orig_platform,
        f"actual={rfj.get('platform_fee_label')!r} expected={orig_platform!r}")
    log("B11 post-restore transaction_fee_label",
        rfj.get("transaction_fee_label") == orig_tx,
        f"actual={rfj.get('transaction_fee_label')!r} expected={orig_tx!r}")
    log("B12 post-restore insurance_label",
        rfj.get("insurance_label") == orig_ins,
        f"actual={rfj.get('insurance_label')!r} expected={orig_ins!r}")


if __name__ == "__main__":
    try:
        fix_a()
        fix_b()
    except Exception as exc:
        log("EXC unexpected exception", False, repr(exc))
        raise
    finally:
        print("\n=== SUMMARY ===")
        passed = sum(1 for _, ok, _ in results if ok)
        total = len(results)
        for step, ok, detail in results:
            tag = "PASS" if ok else "FAIL"
            print(f"[{tag}] {step}")
        print(f"\nTotal: {passed}/{total} passed")
        sys.exit(0 if passed == total else 1)
