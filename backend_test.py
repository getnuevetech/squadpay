"""Phase B backend tests: persistent users + admin block/unblock + group block.

Runs end-to-end against the live preview backend at EXPO_PUBLIC_BACKEND_URL/api.
"""
import os
import sys
import uuid
import requests
from typing import Optional

# ---------- Resolve base URL ----------
ENV_PATH = "/app/frontend/.env"
BASE = None
with open(ENV_PATH) as fh:
    for line in fh:
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE = line.strip().split("=", 1)[1].strip().strip('"').rstrip("/")
            break
if not BASE:
    print("FATAL: EXPO_PUBLIC_BACKEND_URL not found")
    sys.exit(2)
API = f"{BASE}/api"
print(f"[setup] API base = {API}")

ADMIN_EMAIL = "[email protected]"
ADMIN_PASSWORD = "ChangeMe123!"

RUN_TAG = uuid.uuid4().hex[:6]

def _phone(seed: int) -> str:
    digits = "".join(c for c in RUN_TAG if c.isdigit()).ljust(3, "0")[:3]
    return f"+1555{digits}{seed:04d}"

PHONE_A = _phone(9001)
PHONE_C = _phone(9002)

PASS = []
FAIL = []

def _record(name: str, ok: bool, detail: str = ""):
    icon = "PASS" if ok else "FAIL"
    line = f"[{icon}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    (PASS if ok else FAIL).append(name)

def expect(name: str, cond: bool, detail: str = ""):
    _record(name, bool(cond), detail)
    return bool(cond)

def http(method: str, path: str, *, json_body=None, headers=None, params=None,
         expect_status: Optional[int] = None, name: Optional[str] = None):
    url = f"{API}{path}"
    try:
        r = requests.request(method, url, json=json_body, headers=headers, params=params, timeout=30)
    except Exception as e:
        _record(name or f"{method} {path}", False, f"network error: {e}")
        return None
    if expect_status is not None:
        ok = r.status_code == expect_status
        _record(name or f"{method} {path} → {expect_status}", ok,
                f"got {r.status_code} body={r.text[:200]}")
    return r


def admin_login() -> str:
    r = http("POST", "/admin/auth/login",
             json_body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
             expect_status=200, name="admin/auth/login super_admin")
    if r is None or r.status_code != 200:
        print("FATAL: admin login failed"); sys.exit(2)
    return r.json()["token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def register(name: str) -> str:
    r = requests.post(f"{API}/auth/register", json={"name": name}, timeout=15)
    r.raise_for_status()
    return r.json()["id"]


def send_otp(user_id: str, phone: str):
    r = requests.post(f"{API}/auth/send-otp", json={"user_id": user_id, "phone": phone}, timeout=15)
    r.raise_for_status()


def verify_otp(user_id: str, phone: str, code: str = "123456") -> requests.Response:
    return requests.post(f"{API}/auth/verify-otp",
                         json={"user_id": user_id, "phone": phone, "code": code}, timeout=15)


# ============ Scenario A ============
def scenario_A():
    print("\n=== Scenario A: persistent user collapse ===")
    placeholder_a = register("Foo")
    send_otp(placeholder_a, PHONE_A)
    r1 = verify_otp(placeholder_a, PHONE_A)
    expect("A: first verify-otp 200", r1.status_code == 200, f"{r1.status_code} {r1.text[:200]}")
    if r1.status_code != 200:
        return None, None
    A1 = r1.json()["id"]
    expect("A: first verify-otp returns own placeholder id (no prior collapse)", A1 == placeholder_a,
           f"A1={A1} placeholder={placeholder_a}")

    gbody = {
        "lead_id": A1,
        "title": "Pizza Night",
        "total_amount": 30.0,
        "split_mode": "fast",
        "tax": 0.0, "tip": 0.0,
        "items": [{"name": "Pizza", "price": 30.0, "quantity": 1}],
    }
    rg = requests.post(f"{API}/groups", json=gbody, timeout=15)
    expect("A: create group as A1", rg.status_code == 200, f"{rg.status_code} {rg.text[:200]}")
    if rg.status_code != 200:
        return A1, None
    G1 = rg.json()["id"]

    placeholder_b = register("Bar")
    expect("A: placeholder_b distinct from A1", placeholder_b != A1)
    send_otp(placeholder_b, PHONE_A)
    r2 = verify_otp(placeholder_b, PHONE_A)
    expect("A: 2nd verify-otp 200 (collapse)", r2.status_code == 200, f"{r2.status_code} {r2.text[:200]}")
    if r2.status_code == 200:
        body = r2.json()
        expect("A: collapsed user_id == A1", body["id"] == A1, f"got {body['id']}")
        expect("A: name refreshed to 'Bar'", body.get("name") == "Bar", f"name={body.get('name')}")

    r3 = requests.get(f"{API}/users/{placeholder_b}", timeout=15)
    expect("A: placeholder_b deleted (GET → 404)", r3.status_code == 404, f"{r3.status_code}")

    r4 = requests.get(f"{API}/users/{A1}/groups", timeout=15)
    has = r4.status_code == 200 and any(g["id"] == G1 for g in r4.json())
    expect("A: A1/groups still includes original group", has, f"{r4.status_code} {r4.text[:200]}")

    r5 = requests.get(f"{API}/users/{A1}", timeout=15)
    expect("A: GET /users/A1 name == Bar",
           r5.status_code == 200 and r5.json().get("name") == "Bar",
           f"{r5.status_code} {r5.text[:120]}")
    return A1, G1


# ============ Scenario B ============
def scenario_B(token, A1, G1):
    print("\n=== Scenario B: admin list + detail ===")
    digits = PHONE_A.lstrip("+")[1:]  # drop leading 1
    r = http("GET", "/admin/users", params={"q": digits},
             headers=auth_headers(token), expect_status=200, name="B: admin/users search by phone")
    if r is None or r.status_code != 200:
        return
    items = r.json().get("items", [])
    a_row = next((u for u in items if u["id"] == A1), None)
    expect("B: search results contain A1", a_row is not None,
           f"items={[u['id'] for u in items][:5]} total={r.json().get('total')}")
    if a_row:
        expect("B: A1 groups_led >= 1", a_row.get("groups_led", 0) >= 1, f"groups_led={a_row.get('groups_led')}")

    r2 = http("GET", f"/admin/users/{A1}", headers=auth_headers(token),
              expect_status=200, name="B: admin/users/{A1}")
    if r2 and r2.status_code == 200:
        led = r2.json().get("led_groups", [])
        expect("B: led_groups includes G1", any(g["id"] == G1 for g in led),
               f"led_ids={[g['id'] for g in led]}")


# ============ Scenario C ============
def scenario_C(token, A1):
    print("\n=== Scenario C: block A1 then verify enforcement ===")
    r = http("POST", f"/admin/users/{A1}/block",
             json_body={"is_blocked": True, "reason": "test"},
             headers=auth_headers(token), expect_status=200, name="C: block A1")
    if r and r.status_code == 200:
        expect("C: response is_blocked=true", r.json().get("is_blocked") is True)
        expect("C: response blocked_reason='test'", r.json().get("blocked_reason") == "test")

    r2 = http("GET", f"/admin/users/{A1}", headers=auth_headers(token),
              expect_status=200, name="C: GET admin user shows blocked")
    if r2 and r2.status_code == 200:
        b = r2.json()
        expect("C: detail blocked=true", b.get("is_blocked") is True)
        expect("C: detail reason='test'", b.get("blocked_reason") == "test")

    pid = register("Baz")
    send_otp(pid, PHONE_A)
    r3 = verify_otp(pid, PHONE_A)
    try:
        body3 = r3.json().get("detail", "")
    except Exception:
        body3 = r3.text
    expect("C: blocked user verify-otp → 403", r3.status_code == 403, f"{r3.status_code} {r3.text[:200]}")
    expect("C: response message contains 'blocked'", "block" in str(body3).lower(), f"detail={body3}")

    rg = requests.post(f"{API}/groups", json={
        "lead_id": A1, "title": "Should Fail", "total_amount": 10.0,
        "split_mode": "fast", "items": [{"name": "X", "price": 10.0, "quantity": 1}],
    }, timeout=15)
    expect("C: create group as blocked A1 → 403", rg.status_code == 403, f"{rg.status_code} {rg.text[:200]}")

    cid = register("Cara")
    send_otp(cid, PHONE_C)
    rc = verify_otp(cid, PHONE_C)
    if rc.status_code != 200:
        expect("C: setup user C verified", False, rc.text[:200])
        return None
    Cuid = rc.json()["id"]
    rgc = requests.post(f"{API}/groups", json={
        "lead_id": Cuid, "title": "Cara's Bill", "total_amount": 20.0,
        "split_mode": "fast", "items": [{"name": "Soup", "price": 20.0, "quantity": 1}],
    }, timeout=15)
    expect("C: setup create C's group", rgc.status_code == 200, f"{rgc.status_code} {rgc.text[:200]}")
    if rgc.status_code != 200:
        return Cuid
    Cgid = rgc.json()["id"]

    rj = requests.post(f"{API}/groups/{Cgid}/join", json={"user_id": A1}, timeout=15)
    expect("C: join with blocked A1 → 403", rj.status_code == 403, f"{rj.status_code} {rj.text[:200]}")

    rcontr = requests.post(f"{API}/groups/{Cgid}/contribute", json={"user_id": A1}, timeout=15)
    expect("C: contribute with blocked A1 → 403", rcontr.status_code == 403, f"{rcontr.status_code} {rcontr.text[:200]}")
    return Cuid


# ============ Scenario D ============
def scenario_D(token, A1):
    print("\n=== Scenario D: unblock restores access ===")
    r = http("POST", f"/admin/users/{A1}/block",
             json_body={"is_blocked": False},
             headers=auth_headers(token), expect_status=200, name="D: unblock A1")
    if r and r.status_code == 200:
        expect("D: response is_blocked=false", r.json().get("is_blocked") is False)

    pid = register("BarAgain")
    send_otp(pid, PHONE_A)
    r2 = verify_otp(pid, PHONE_A)
    expect("D: verify-otp after unblock → 200", r2.status_code == 200, f"{r2.status_code} {r2.text[:200]}")
    if r2.status_code == 200:
        expect("D: collapse still maps to A1", r2.json()["id"] == A1, f"got {r2.json()['id']}")
        expect("D: A1 verified=true", r2.json().get("verified") is True)

    rg = requests.post(f"{API}/groups", json={
        "lead_id": A1, "title": "Post-Unblock Bill", "total_amount": 12.0,
        "split_mode": "fast", "items": [{"name": "Cake", "price": 12.0, "quantity": 1}],
    }, timeout=15)
    expect("D: create group after unblock → 200", rg.status_code == 200, f"{rg.status_code} {rg.text[:200]}")


# ============ Scenario E ============
def scenario_E(token, A1, G1, Cuid):
    print("\n=== Scenario E: group block ===")
    if not G1:
        expect("E: G1 exists", False, "skipped"); return
    r = http("POST", f"/admin/groups/{G1}/block",
             json_body={"is_blocked": True, "reason": "dispute"},
             headers=auth_headers(token), expect_status=200, name="E: block group G1")
    if r and r.status_code == 200:
        expect("E: group is_blocked=true", r.json().get("is_blocked") is True)
        expect("E: group blocked_reason='dispute'", r.json().get("blocked_reason") == "dispute")

    if Cuid:
        rj = requests.post(f"{API}/groups/{G1}/join", json={"user_id": Cuid}, timeout=15)
        expect("E: join blocked group → 403", rj.status_code == 403, f"{rj.status_code} {rj.text[:200]}")

    rco = requests.post(f"{API}/groups/{G1}/contribute", json={"user_id": A1}, timeout=15)
    expect("E: contribute on blocked group → 403", rco.status_code == 403, f"{rco.status_code} {rco.text[:200]}")

    rp = requests.post(f"{API}/groups/{G1}/pay", json={"user_id": A1}, timeout=15)
    expect("E: pay blocked group → 403", rp.status_code == 403, f"{rp.status_code} {rp.text[:200]}")

    ru = http("POST", f"/admin/groups/{G1}/block",
              json_body={"is_blocked": False},
              headers=auth_headers(token), expect_status=200, name="E: unblock group G1")
    if ru and ru.status_code == 200:
        expect("E: group is_blocked=false", ru.json().get("is_blocked") is False)

    if Cuid:
        rj2 = requests.post(f"{API}/groups/{G1}/join", json={"user_id": Cuid}, timeout=15)
        expect("E: join after unblock not 403", rj2.status_code != 403, f"{rj2.status_code} {rj2.text[:200]}")

    rco2 = requests.post(f"{API}/groups/{G1}/contribute", json={"user_id": A1}, timeout=15)
    expect("E: contribute after unblock not 403", rco2.status_code != 403, f"{rco2.status_code} {rco2.text[:200]}")


# ============ Scenario F ============
def scenario_F(super_token, A1):
    print("\n=== Scenario F: admin auth + RBAC ===")
    r = requests.get(f"{API}/admin/users", timeout=15)
    expect("F: GET /admin/users without Bearer → 401", r.status_code == 401, f"{r.status_code} {r.text[:200]}")

    support_email = f"support+{RUN_TAG}@example.com"
    rc = http("POST", "/admin/admins",
              json_body={"email": support_email, "password": "Support123!", "name": "Support User", "role": "support"},
              headers=auth_headers(super_token), expect_status=200, name="F: create support admin")
    if rc is None or rc.status_code != 200:
        return None

    rl = http("POST", "/admin/auth/login",
              json_body={"email": support_email, "password": "Support123!"},
              expect_status=200, name="F: login as support")
    if rl is None or rl.status_code != 200:
        return None
    sup_token = rl.json()["token"]

    rb = http("POST", f"/admin/users/{A1}/block",
              json_body={"is_blocked": True, "reason": "rbac test"},
              headers=auth_headers(sup_token), name="F: block as support")
    expect("F: support block_user is 403", rb is not None and rb.status_code == 403,
           f"{rb.status_code if rb is not None else 'no resp'} {rb.text[:200] if rb is not None else ''}")
    if rb is not None and rb.status_code == 403:
        try:
            detail = rb.json().get("detail", "")
        except Exception:
            detail = rb.text
        expect("F: support 403 mentions roles", "role" in detail.lower(), f"detail={detail}")
    return sup_token


# ============ Scenario G ============
def scenario_G(token, A1, G1):
    print("\n=== Scenario G: audit log ===")
    r = http("GET", "/admin/audit-log", params={"limit": 100},
             headers=auth_headers(token), expect_status=200, name="G: GET audit-log")
    if r is None or r.status_code != 200:
        return
    items = r.json().get("items", [])
    actions = [i["action"] for i in items]
    print(f"   audit actions sample: {actions[:15]}")

    block_user = next((i for i in items if i["action"] == "admin.block_user" and i.get("target_id") == A1), None)
    unblock_user = next((i for i in items if i["action"] == "admin.unblock_user" and i.get("target_id") == A1), None)
    block_group = next((i for i in items if i["action"] == "admin.block_group" and i.get("target_id") == G1), None)
    unblock_group = next((i for i in items if i["action"] == "admin.unblock_group" and i.get("target_id") == G1), None)

    expect("G: admin.block_user entry for A1", block_user is not None)
    if block_user:
        expect("G: block_user destructive=true", block_user.get("destructive") is True)
        expect("G: block_user target_type=user", block_user.get("target_type") == "user")
    expect("G: admin.unblock_user entry for A1", unblock_user is not None)
    if unblock_user:
        expect("G: unblock_user destructive=true", unblock_user.get("destructive") is True)
    expect("G: admin.block_group entry for G1", block_group is not None)
    if block_group:
        expect("G: block_group destructive=true", block_group.get("destructive") is True)
        expect("G: block_group target_type=group", block_group.get("target_type") == "group")
    expect("G: admin.unblock_group entry for G1", unblock_group is not None)
    if unblock_group:
        expect("G: unblock_group destructive=true", unblock_group.get("destructive") is True)


# ============ Scenario H ============
def scenario_H(token, A1, G1):
    print("\n=== Scenario H: search & filters ===")
    http("POST", f"/admin/users/{A1}/block",
         json_body={"is_blocked": True, "reason": "filter test"},
         headers=auth_headers(token), expect_status=200, name="H: re-block A1 for filter")
    r1 = http("GET", "/admin/users", params={"blocked": "true"},
              headers=auth_headers(token), expect_status=200, name="H: list blocked=true")
    if r1 and r1.status_code == 200:
        items = r1.json().get("items", [])
        all_blocked = all(u.get("is_blocked") is True for u in items)
        expect("H: blocked=true returns only blocked users", all_blocked,
               f"items={[u['id'] + ':' + str(u.get('is_blocked')) for u in items[:5]]}")
        expect("H: A1 included in blocked filter", any(u["id"] == A1 for u in items))
    http("POST", f"/admin/users/{A1}/block",
         json_body={"is_blocked": False},
         headers=auth_headers(token), expect_status=200, name="H: unblock A1 after filter")

    r2 = http("GET", "/admin/users", params={"verified": "true", "limit": 50},
              headers=auth_headers(token), expect_status=200, name="H: list verified=true")
    if r2 and r2.status_code == 200:
        items = r2.json().get("items", [])
        all_v = all(u.get("verified") is True for u in items)
        expect("H: verified=true returns only verified", all_v,
               f"sample={[u.get('verified') for u in items[:5]]}")

    r3 = http("GET", "/admin/groups", params={"status": "open", "limit": 50},
              headers=auth_headers(token), expect_status=200, name="H: list groups status=open")
    if r3 and r3.status_code == 200:
        items = r3.json().get("items", [])
        all_open = all(g.get("status") == "open" for g in items)
        expect("H: status=open returns only open groups", all_open,
               f"sample={[g.get('status') for g in items[:5]]}")

    r4 = http("GET", "/admin/users", params={"skip": 0, "limit": 2},
              headers=auth_headers(token), expect_status=200, name="H: pagination users limit=2")
    if r4 and r4.status_code == 200:
        items = r4.json().get("items", [])
        expect("H: at most 2 items returned", len(items) <= 2, f"got {len(items)}")


def main():
    token = admin_login()
    A1, G1 = scenario_A()
    if not A1:
        print("\nFATAL: scenario A failed; aborting")
        sys.exit(2)
    scenario_B(token, A1, G1)
    Cuid = scenario_C(token, A1)
    scenario_D(token, A1)
    scenario_E(token, A1, G1, Cuid)
    scenario_F(token, A1)
    scenario_G(token, A1, G1)
    scenario_H(token, A1, G1)

    print("\n========== SUMMARY ==========")
    print(f"PASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    if FAIL:
        print("\nFailing assertions:")
        for f in FAIL:
            print(" -", f)
        sys.exit(1)
    print("All Phase B assertions passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
