"""Backend test for new GET /api/runtime/fee-labels public endpoint.

Validates:
  1. Public unauthenticated GET returns 200 with correct shape + Cache-Control: no-store
  2. Admin login + GET /api/admin/app-config
  3. Admin PUTs core_fees.platform_fee_label, transaction_fee_label, extra_fees[0].name
  4. Public GET reflects changes
  5. Restore originals
  6. Public GET reflects defaults
"""
import copy
import sys
import time

import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PW = "Letmein@2007#ForReal"

PASS = 0
FAIL = 0
FAILURES: list = []


def _ok(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS: {label}{(' - ' + extra) if extra else ''}")
    else:
        FAIL += 1
        msg = f"{label}{(' - ' + extra) if extra else ''}"
        FAILURES.append(msg)
        print(f"  FAIL: {msg}")


def step(n, title):
    print(f"\n=== STEP {n}: {title} ===")


def main():
    sess = requests.Session()
    sess.headers.update({"Accept": "application/json"})

    # Step 1: public GET /runtime/fee-labels (no auth)
    step(1, "GET /api/runtime/fee-labels (public, no auth)")
    r = sess.get(f"{BASE}/runtime/fee-labels", timeout=15)
    _ok("HTTP 200", r.status_code == 200, f"got {r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        print(f"\nFATAL: cannot continue. body={r.text}")
        sys.exit(1)
    body = r.json()
    print(f"  body: {body}")
    required_keys = {"transaction_fee_label", "platform_fee_label", "insurance_label", "extra_fees"}
    missing = required_keys - set(body.keys())
    _ok("required keys present", not missing, f"missing={missing}")
    _ok("transaction_fee_label is str", isinstance(body.get("transaction_fee_label"), str))
    _ok("platform_fee_label is str", isinstance(body.get("platform_fee_label"), str))
    _ok("insurance_label is str", isinstance(body.get("insurance_label"), str))
    _ok("extra_fees is list", isinstance(body.get("extra_fees"), list))
    extras = body.get("extra_fees") or []
    for i, e in enumerate(extras):
        _ok(f"extra_fees[{i}] is dict", isinstance(e, dict))
        _ok(f"extra_fees[{i}].id present", isinstance(e, dict) and bool(e.get("id")))
        _ok(f"extra_fees[{i}].name present", isinstance(e, dict) and "name" in e)
    cc = r.headers.get("Cache-Control") or ""
    _ok(
        "Cache-Control has no-store/no-cache",
        ("no-store" in cc.lower()) or ("no-cache" in cc.lower()),
        f"got '{cc}'",
    )

    default_tx = body.get("transaction_fee_label")
    default_platform = body.get("platform_fee_label")
    default_ins = body.get("insurance_label")
    default_extras = copy.deepcopy(extras)
    print(f"  initial public values: tx='{default_tx}' platform='{default_platform}' ins='{default_ins}'")
    print(f"  initial public extras: {default_extras}")

    # Step 2: admin login + GET app-config
    step(2, "Admin login + GET /admin/app-config + PUTs")
    r = sess.post(
        f"{BASE}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PW},
        timeout=15,
    )
    _ok("admin login 200", r.status_code == 200, f"got {r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        print(f"\nFATAL: admin login failed. body={r.text}")
        sys.exit(1)
    token = r.json().get("token")
    _ok("admin token present", bool(token))
    auth = {"Authorization": f"Bearer {token}"}

    r = sess.get(f"{BASE}/admin/app-config", headers=auth, timeout=15)
    _ok("GET /admin/app-config 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code != 200:
        print(f"\nFATAL: get app-config failed. body={r.text}")
        sys.exit(1)
    cfg = r.json()
    core_fees = cfg.get("core_fees") or {}
    orig_platform_label = core_fees.get("platform_fee_label")
    orig_tx_label = core_fees.get("transaction_fee_label")
    orig_ins_label = core_fees.get("insurance_label")
    orig_extras = copy.deepcopy(cfg.get("extra_fees") or [])
    print(f"  current platform_fee_label='{orig_platform_label}'")
    print(f"  current transaction_fee_label='{orig_tx_label}'")
    print(f"  current extras[0]={orig_extras[0] if orig_extras else None}")
    _ok("orig platform_fee_label present", bool(orig_platform_label))
    _ok("orig extras has at least one entry", len(orig_extras) >= 1)

    def _put(payload, label):
        rr = sess.put(
            f"{BASE}/admin/app-config",
            json=payload,
            headers=auth,
            timeout=20,
        )
        _ok(f"PUT app-config ({label}) 200", rr.status_code == 200,
            f"got {rr.status_code} body={rr.text[:300]}")
        return rr

    # PUT 1: change platform_fee_label
    p1 = copy.deepcopy(cfg)
    p1["core_fees"]["platform_fee_label"] = "Service Fee"
    _put(p1, "platform_fee_label=Service Fee")

    # PUT 2: change transaction_fee_label
    p2 = copy.deepcopy(p1)
    p2["core_fees"]["transaction_fee_label"] = "Processing Fee"
    _put(p2, "transaction_fee_label=Processing Fee")

    # PUT 3: change extra_fees[0].name
    p3 = copy.deepcopy(p2)
    if not p3.get("extra_fees"):
        p3["extra_fees"] = [{"id": "extra_1", "name": "Extra Fee 1", "type": "flat", "value": 0, "enabled": False}]
    p3["extra_fees"][0]["name"] = "Concierge Fee"
    _put(p3, "extra_fees[0].name=Concierge Fee")

    time.sleep(0.5)

    # Step 3: re-fetch public /runtime/fee-labels
    step(3, "GET /api/runtime/fee-labels - verify updated values")
    r = sess.get(f"{BASE}/runtime/fee-labels", timeout=15)
    _ok("HTTP 200", r.status_code == 200, f"got {r.status_code}")
    body2 = r.json()
    print(f"  body: {body2}")
    _ok(
        "platform_fee_label == 'Service Fee'",
        body2.get("platform_fee_label") == "Service Fee",
        f"got '{body2.get('platform_fee_label')}'",
    )
    _ok(
        "transaction_fee_label == 'Processing Fee'",
        body2.get("transaction_fee_label") == "Processing Fee",
        f"got '{body2.get('transaction_fee_label')}'",
    )
    extras2 = body2.get("extra_fees") or []
    _ok("extras[0] present", len(extras2) >= 1)
    if extras2:
        _ok(
            "extras[0].name == 'Concierge Fee'",
            extras2[0].get("name") == "Concierge Fee",
            f"got '{extras2[0].get('name')}'",
        )

    cc2 = r.headers.get("Cache-Control") or ""
    _ok(
        "Cache-Control still no-store/no-cache after update",
        ("no-store" in cc2.lower()) or ("no-cache" in cc2.lower()),
        f"got '{cc2}'",
    )

    # Step 4: restore originals via another PUT
    step(4, "Restore originals via PUT /admin/app-config")
    restore = copy.deepcopy(p3)
    restore["core_fees"]["platform_fee_label"] = orig_platform_label
    restore["core_fees"]["transaction_fee_label"] = orig_tx_label
    if orig_ins_label is not None:
        restore["core_fees"]["insurance_label"] = orig_ins_label
    if orig_extras:
        by_id = {e.get("id"): e for e in orig_extras if isinstance(e, dict) and e.get("id")}
        for i, slot in enumerate(restore.get("extra_fees") or []):
            sid = slot.get("id")
            if sid in by_id:
                restore["extra_fees"][i] = copy.deepcopy(by_id[sid])
    _put(restore, "restore")
    time.sleep(0.5)

    # Step 5: confirm defaults are back
    step(5, "GET /api/runtime/fee-labels - confirm defaults restored")
    r = sess.get(f"{BASE}/runtime/fee-labels", timeout=15)
    _ok("HTTP 200", r.status_code == 200, f"got {r.status_code}")
    body3 = r.json()
    print(f"  body: {body3}")
    _ok(
        f"platform_fee_label restored to '{orig_platform_label}'",
        body3.get("platform_fee_label") == orig_platform_label,
        f"got '{body3.get('platform_fee_label')}'",
    )
    _ok(
        f"transaction_fee_label restored to '{orig_tx_label}'",
        body3.get("transaction_fee_label") == orig_tx_label,
        f"got '{body3.get('transaction_fee_label')}'",
    )
    if orig_ins_label is not None:
        _ok(
            f"insurance_label restored to '{orig_ins_label}'",
            body3.get("insurance_label") == orig_ins_label,
            f"got '{body3.get('insurance_label')}'",
        )
    extras3 = body3.get("extra_fees") or []
    if orig_extras:
        _ok(
            f"extras[0].name restored to '{orig_extras[0].get('name')}'",
            len(extras3) >= 1 and extras3[0].get("name") == orig_extras[0].get("name"),
            f"got '{extras3[0].get('name') if extras3 else None}'",
        )

    print(f"\n{'=' * 60}")
    print(f"PASS: {PASS}   FAIL: {FAIL}")
    if FAILURES:
        print("Failures:")
        for f in FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 60}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
