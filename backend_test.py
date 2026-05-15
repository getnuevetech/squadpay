"""
Focused regression test for the new public endpoint:
    GET /api/runtime/brand

Plus end-to-end check that admin PUT /api/admin/app-config (changing
`brand.support_email` and `brand.default_tip_suggestions`) is reflected
on the public endpoint, then restored.
"""

import sys
import json
import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

results = []


def check(label, ok, info=""):
    results.append((label, ok, info))
    icon = "PASS" if ok else "FAIL"
    print(f"[{icon}] {label}{' — ' + info if info else ''}")
    return ok


def admin_login():
    r = requests.post(
        f"{BASE}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:300]}"
    return r.json()["token"]


def get_app_config(token):
    r = requests.get(
        f"{BASE}/admin/app-config",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    assert r.status_code == 200, f"get app-config failed: {r.status_code} {r.text[:300]}"
    return r.json()


def put_app_config(token, cfg):
    r = requests.put(
        f"{BASE}/admin/app-config",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(cfg),
        timeout=20,
    )
    assert r.status_code == 200, f"put app-config failed: {r.status_code} {r.text[:300]}"
    return r.json()


def get_public_brand():
    r = requests.get(f"{BASE}/runtime/brand", timeout=20)
    return r


# ─── STEP 1 ──────────────────────────────────────────────────────────────
print("\n── STEP 1: GET /api/runtime/brand (no auth)")
r = get_public_brand()
check("step1.http_200", r.status_code == 200, f"got {r.status_code}")
body = {}
try:
    body = r.json()
except Exception as e:
    check("step1.json_body", False, str(e))

for key in ("support_email", "default_tip_suggestions", "currency"):
    check(f"step1.has_key.{key}", key in body, f"body keys={list(body.keys())}")

tips = body.get("default_tip_suggestions")
check("step1.tips_is_list", isinstance(tips, list), f"type={type(tips).__name__}")
check(
    "step1.tips_all_numbers",
    isinstance(tips, list)
    and all(isinstance(t, (int, float)) and not isinstance(t, bool) for t in tips),
    f"tips={tips}",
)

cc = r.headers.get("Cache-Control", "")
check("step1.cache_control_no_store", "no-store" in cc.lower(), f"Cache-Control={cc!r}")

original_email = body.get("support_email")
original_tips = list(tips) if isinstance(tips, list) else None
print(f"   → original support_email = {original_email!r}")
print(f"   → original default_tip_suggestions = {original_tips!r}")

# ─── STEP 2 ──────────────────────────────────────────────────────────────
print("\n── STEP 2: admin login + PUT /api/admin/app-config (change support_email)")
token = admin_login()
check("step2.admin_login_ok", bool(token), "got bearer token")

cfg_before = get_app_config(token)
saved_brand = dict(cfg_before.get("brand") or {})
print(f"   → cfg.brand keys = {list(saved_brand.keys())}")

cfg_mut = json.loads(json.dumps(cfg_before))
cfg_mut["brand"]["support_email"] = "customers@example.com"
put_app_config(token, cfg_mut)
check("step2.put_email_change_ok", True, "PUT 200")

# ─── STEP 3 ──────────────────────────────────────────────────────────────
print("\n── STEP 3: GET /api/runtime/brand (verify email change)")
r3 = get_public_brand()
check("step3.http_200", r3.status_code == 200, f"got {r3.status_code}")
b2 = r3.json()
check(
    "step3.support_email_updated",
    b2.get("support_email") == "customers@example.com",
    f"actual={b2.get('support_email')!r}",
)

# ─── STEP 4 ──────────────────────────────────────────────────────────────
print("\n── STEP 4: restore support_email and verify")
cfg_restore = json.loads(json.dumps(cfg_before))
cfg_restore["brand"]["support_email"] = saved_brand.get("support_email", original_email)
put_app_config(token, cfg_restore)
r4 = get_public_brand()
b3 = r4.json()
check(
    "step4.support_email_restored",
    b3.get("support_email") == original_email,
    f"actual={b3.get('support_email')!r}, original={original_email!r}",
)

# ─── STEP 5 ──────────────────────────────────────────────────────────────
print("\n── STEP 5: change default_tip_suggestions to [10,15,20,25], verify, restore")
cfg_mut2 = json.loads(json.dumps(cfg_before))
cfg_mut2["brand"]["default_tip_suggestions"] = [10, 15, 20, 25]
put_app_config(token, cfg_mut2)
r5 = get_public_brand()
b4 = r5.json()
returned_tips = b4.get("default_tip_suggestions")
check(
    "step5.tips_updated",
    isinstance(returned_tips, list)
    and len(returned_tips) == 4
    and [float(x) for x in returned_tips] == [10.0, 15.0, 20.0, 25.0],
    f"actual={returned_tips!r}",
)

cfg_restore2 = json.loads(json.dumps(cfg_before))
cfg_restore2["brand"]["default_tip_suggestions"] = saved_brand.get("default_tip_suggestions", original_tips)
put_app_config(token, cfg_restore2)
r6 = get_public_brand()
b5 = r6.json()
got_back = b5.get("default_tip_suggestions")
check(
    "step5.tips_restored",
    isinstance(got_back, list)
    and [float(x) for x in got_back] == [float(x) for x in (original_tips or [])],
    f"actual={got_back!r}, original={original_tips!r}",
)

# ─── Summary ─────────────────────────────────────────────────────────────
print("\n══════════════════ SUMMARY ══════════════════")
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = len(results) - n_pass
for label, ok, info in results:
    icon = "✅" if ok else "❌"
    print(f"  {icon} {label}{(' — ' + info) if (info and not ok) else ''}")
print(f"\nTOTAL: {n_pass}/{len(results)} PASS, {n_fail} FAIL")
sys.exit(0 if n_fail == 0 else 1)
