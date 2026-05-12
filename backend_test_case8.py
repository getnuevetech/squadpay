"""
Focused re-test for Case 8 of the Credit Rules engine.
Verifies POST /api/admin/credit-rules happy path returns 200 with `id` (no `_id`)
and the created rule appears in GET /api/admin/credit-rules.
"""
import os
import sys
import time
import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"


def main() -> int:
    ts = int(time.time())
    print(f"[case8] base={BASE} ts={ts}")

    # 1) admin login
    r = requests.post(f"{BASE}/admin/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=20)
    if r.status_code != 200:
        print(f"FAIL admin login: {r.status_code} {r.text[:200]}")
        return 1
    token = r.json().get("token") or r.json().get("access_token") or r.json().get("admin_token")
    if not token:
        print(f"FAIL no token in login response: {r.json()}")
        return 1
    H = {"Authorization": f"Bearer {token}"}
    print("[case8] admin login OK")

    # 2) Case 8 happy path POST /api/admin/credit-rules
    payload = {
        "name": f"Welcome bonus {ts}",
        "active": True,
        "message": "Hello",
        "criteria": {"type": "first_time"},
        "reward": {"type": "fixed", "value": 3},
    }
    r = requests.post(f"{BASE}/admin/credit-rules", json=payload, headers=H, timeout=20)
    print(f"[case8] POST status={r.status_code}")
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:300]}
    print(f"[case8] POST body keys={list(body.keys()) if isinstance(body, dict) else type(body)}")

    failures = []
    if r.status_code != 200:
        failures.append(f"POST status {r.status_code} (expected 200). body={body}")
    if isinstance(body, dict):
        rid = body.get("id")
        if not rid:
            failures.append(f"response missing `id` (body={body})")
        elif not str(rid).startswith("cr_rule_"):
            failures.append(f"response.id does not start with 'cr_rule_': {rid!r}")
        if "_id" in body:
            failures.append(f"response leaks `_id` key: {body.get('_id')!r}")
        # check other expected fields are preserved
        for k in ("name", "active", "message", "criteria", "reward"):
            if k not in body:
                failures.append(f"response missing `{k}` key")
        if body.get("name") != payload["name"]:
            failures.append(f"response name mismatch: {body.get('name')!r} vs {payload['name']!r}")
        if body.get("active") is not True:
            failures.append(f"response active != True: {body.get('active')!r}")
    else:
        failures.append("response not a dict")

    if failures:
        print("STEP 1 FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1

    created_id = body["id"]
    print(f"[case8] created id={created_id}")

    # 3) Verify rule appears in GET /api/admin/credit-rules
    r = requests.get(f"{BASE}/admin/credit-rules", headers=H, timeout=20)
    if r.status_code != 200:
        print(f"FAIL GET list status={r.status_code} body={r.text[:300]}")
        return 1
    try:
        list_body = r.json()
    except Exception:
        print(f"FAIL GET list not JSON: {r.text[:300]}")
        return 1

    # accept either {items:[...]} or [...]
    items = list_body.get("items") if isinstance(list_body, dict) else list_body
    if items is None and isinstance(list_body, dict):
        # try other common keys
        items = list_body.get("rules") or list_body.get("data")
    if not isinstance(items, list):
        print(f"FAIL GET list shape unexpected: {list_body!r}")
        return 1
    print(f"[case8] GET returned {len(items)} rules")

    match = next((it for it in items if isinstance(it, dict) and it.get("id") == created_id), None)
    if not match:
        print(f"FAIL created rule {created_id} not found in GET list (ids={[it.get('id') for it in items if isinstance(it, dict)]})")
        return 1
    if "_id" in match:
        print(f"FAIL GET list leaks `_id` for rule {created_id}: {match.get('_id')!r}")
        return 1
    if match.get("name") != payload["name"]:
        print(f"FAIL GET list name mismatch: {match.get('name')!r}")
        return 1
    print(f"[case8] rule appears in GET list with correct name + no _id leak")

    # 4) Cleanup — delete the rule
    r = requests.delete(f"{BASE}/admin/credit-rules/{created_id}", headers=H, timeout=20)
    print(f"[case8] cleanup DELETE status={r.status_code}")

    print("PASS Case 8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
