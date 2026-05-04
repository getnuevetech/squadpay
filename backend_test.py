"""
Backend tests for shortfall settlement at POST /api/groups/{id}/pay.
Covers scenarios A-E from the review request.
"""

import os
import sys
import json
import random
import string
from typing import Optional, Tuple, Dict, Any

import requests
from dotenv import dotenv_values

FRONTEND_ENV = dotenv_values("/app/frontend/.env")
BASE_URL = FRONTEND_ENV.get("EXPO_PUBLIC_BACKEND_URL")
if not BASE_URL:
    print("ERROR: EXPO_PUBLIC_BACKEND_URL missing from /app/frontend/.env")
    sys.exit(1)
API = f"{BASE_URL}/api"
print(f"[setup] API base: {API}")

session = requests.Session()
session.headers["Content-Type"] = "application/json"


def rand_phone() -> str:
    return "+1555" + "".join(random.choices(string.digits, k=7))


def post(path: str, body: dict) -> requests.Response:
    return session.post(f"{API}{path}", data=json.dumps(body), timeout=30)


def get(path: str) -> requests.Response:
    return session.get(f"{API}{path}", timeout=30)


def create_verified_user(name: str) -> Dict[str, Any]:
    r = post("/auth/register", {"name": name})
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    user = r.json()
    phone = rand_phone()
    r = post("/auth/send-otp", {"user_id": user["id"], "phone": phone})
    assert r.status_code == 200, f"send-otp failed: {r.text}"
    r = post("/auth/verify-otp", {"user_id": user["id"], "phone": phone, "code": "123456"})
    assert r.status_code == 200, f"verify-otp failed: {r.text}"
    user = r.json()
    print(f"  [user] {name} -> id={user['id']} phone={phone} verified={user['verified']}")
    return user


def setup_scenario(label: str, num_members: int = 2, total_amount: float = 60.0,
                   members_who_pay: int = 1) -> Tuple[Dict, list, Dict]:
    """
    Create lead + N members, group with equal-split (fast), have lead + a subset of
    members contribute their full share, leaving the rest as shortfall.
    Returns (lead, members, enriched_group).
    """
    print(f"\n=== Setup for {label} ===")
    lead = create_verified_user(f"Lead-{label}")
    members = [create_verified_user(f"Member-{label}-{i+1}") for i in range(num_members)]

    # Lead creates a fast (equal) split group
    body = {
        "lead_id": lead["id"],
        "title": f"Dinner {label}",
        "total_amount": total_amount,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r = post("/groups", body)
    assert r.status_code == 200, f"create group failed: {r.text}"
    group = r.json()
    gid = group["id"]
    print(f"  [group] id={gid} code={group['code']} total_amount={group['total_amount']}")

    # Members join
    for m in members:
        r = post(f"/groups/{gid}/join", {"user_id": m["id"]})
        assert r.status_code == 200, f"join failed: {r.text}"

    # Reload group to get per_user shares
    r = get(f"/groups/{gid}")
    assert r.status_code == 200
    group = r.json()
    print(f"  [shares] per_user totals = {[(p['user_id'], p['total']) for p in group['per_user']]}")

    # Lead contributes full share
    r = post(f"/groups/{gid}/contribute", {"user_id": lead["id"]})
    assert r.status_code == 200, f"lead contribute failed: {r.text}"

    # `members_who_pay` members contribute full share
    for m in members[:members_who_pay]:
        r = post(f"/groups/{gid}/contribute", {"user_id": m["id"]})
        assert r.status_code == 200, f"member contribute failed: {r.text}"

    r = get(f"/groups/{gid}")
    enriched = r.json()
    print(f"  [funding] total_contributed={enriched['funding']['total_contributed']} "
          f"remaining_to_collect={enriched['funding']['remaining_to_collect']} "
          f"status={enriched['status']}")
    assert enriched["funding"]["remaining_to_collect"] > 0, \
        "Setup failed: shortfall must be > 0"
    return lead, members, enriched


def scenario_A():
    lead, members, group = setup_scenario("A", num_members=2, members_who_pay=1)
    gid = group["id"]
    pre_remaining = group["funding"]["remaining_to_collect"]
    body = {"user_id": lead["id"], "shortfall_mode": "lead", "is_loan": True}
    print(f"  [pay] body={body}")
    r = post(f"/groups/{gid}/pay", body)
    print(f"  [pay] status={r.status_code} body={r.text[:300]}")
    assert r.status_code == 200, f"Scenario A pay failed: {r.text}"
    after = r.json()
    print(f"  [post-pay] status={after['status']} funding_mode={after.get('funding_mode')} "
          f"remaining_to_collect={after['funding']['remaining_to_collect']} "
          f"settlement={after.get('shortfall_settlement')}")
    assert after["funding"]["remaining_to_collect"] == 0, \
        f"Expected remaining_to_collect=0, got {after['funding']['remaining_to_collect']}"
    # Loan mode -> status='paid' (not closed). Per code, only gift closes the group.
    assert after["status"] in ("paid", "closed"), f"Unexpected status {after['status']}"
    settlement = after.get("shortfall_settlement")
    assert settlement and settlement["mode"] == "lead" and settlement["is_loan"] is True, \
        f"Bad settlement: {settlement}"
    # Check shortfall contribution recorded
    r = get(f"/groups/{gid}")
    fresh = r.json()
    contribs = [c for c in fresh.get("contributions", []) if c.get("is_shortfall")]
    print(f"  [contribs.shortfall] {contribs}")
    assert any(c["user_id"] == lead["id"] and c.get("is_loan") is True for c in contribs), \
        "No lead loan-shortfall contribution recorded"
    # Outstanding amounts: non-paying member should still owe (loan)
    non_paying = members[1]["id"]
    np_per = next(p for p in fresh["per_user"] if p["user_id"] == non_paying)
    print(f"  [non-paying member outstanding] {np_per['outstanding']}")
    assert np_per["outstanding"] > 0, "Non-paying member should still owe under LOAN mode"
    print("  [PASS] Scenario A — lead covers as LOAN")
    return True


def scenario_B():
    lead, members, group = setup_scenario("B", num_members=2, members_who_pay=1)
    gid = group["id"]
    body = {"user_id": lead["id"], "shortfall_mode": "lead", "is_loan": False}
    print(f"  [pay] body={body}")
    r = post(f"/groups/{gid}/pay", body)
    print(f"  [pay] status={r.status_code} body={r.text[:300]}")
    assert r.status_code == 200, f"Scenario B pay failed: {r.text}"
    after = r.json()
    print(f"  [post-pay] status={after['status']} remaining={after['funding']['remaining_to_collect']} "
          f"settlement={after.get('shortfall_settlement')}")
    assert after["funding"]["remaining_to_collect"] == 0
    assert after["status"] == "closed", f"Gift mode should close group; got {after['status']}"
    settlement = after.get("shortfall_settlement")
    assert settlement and settlement["mode"] == "lead" and settlement["is_loan"] is False
    # Non-paying member should NOT owe (gift)
    non_paying = members[1]["id"]
    np_per = next(p for p in after["per_user"] if p["user_id"] == non_paying)
    print(f"  [non-paying member outstanding] {np_per['outstanding']}")
    assert np_per["outstanding"] == 0, \
        "Non-paying member should owe nothing under GIFT mode"
    print("  [PASS] Scenario B — lead covers as GIFT")
    return True


def scenario_C():
    lead, members, group = setup_scenario("C", num_members=2, members_who_pay=1)
    gid = group["id"]
    # The funder is the member who already paid (members[0]); members[1] still owes
    funder = members[0]
    body = {
        "user_id": lead["id"],
        "shortfall_mode": "member",
        "is_loan": True,
        "funder_member_id": funder["id"],
    }
    print(f"  [pay] body={body}")
    r = post(f"/groups/{gid}/pay", body)
    print(f"  [pay] status={r.status_code} body={r.text[:300]}")
    assert r.status_code == 200, f"Scenario C pay failed: {r.text}"
    after = r.json()
    print(f"  [post-pay] status={after['status']} remaining={after['funding']['remaining_to_collect']} "
          f"settlement={after.get('shortfall_settlement')}")
    assert after["funding"]["remaining_to_collect"] == 0
    settlement = after.get("shortfall_settlement")
    assert settlement and settlement["mode"] == "member" and settlement["is_loan"] is True
    assert settlement.get("funder_id") == funder["id"], f"funder_id mismatch: {settlement}"
    # Verify funder contribution
    contribs = [c for c in after.get("contributions", []) if c.get("is_shortfall")]
    print(f"  [shortfall contribs] {contribs}")
    assert any(c["user_id"] == funder["id"] and c.get("is_loan") is True for c in contribs), \
        "Funder member shortfall contribution not recorded"
    print("  [PASS] Scenario C — member assigned shortfall as LOAN")
    return True


def scenario_D():
    lead, members, group = setup_scenario("D", num_members=2, members_who_pay=1)
    gid = group["id"]
    body = {"user_id": lead["id"], "shortfall_mode": "split_equal"}
    print(f"  [pay] body={body}")
    r = post(f"/groups/{gid}/pay", body)
    print(f"  [pay] status={r.status_code} body={r.text[:300]}")
    assert r.status_code == 200, f"Scenario D pay failed: {r.text}"
    after = r.json()
    print(f"  [post-pay] status={after['status']} remaining={after['funding']['remaining_to_collect']} "
          f"settlement={after.get('shortfall_settlement')}")
    settlement = after.get("shortfall_settlement")
    assert settlement and settlement["mode"] == "split_equal"
    assert settlement["is_loan"] is False, "split_equal should always be gift"
    assert after["status"] == "closed", f"split_equal (gift) should close; got {after['status']}"
    # Non-paying member should owe nothing under gift
    non_paying = members[1]["id"]
    np_per = next(p for p in after["per_user"] if p["user_id"] == non_paying)
    assert np_per["outstanding"] == 0, "Non-paying member should owe nothing under split_equal gift"
    # remaining_to_collect should be ~0 (allow tiny rounding from per_share rounding)
    assert after["funding"]["remaining_to_collect"] <= 0.1, \
        f"Remaining still > 0.1: {after['funding']['remaining_to_collect']}"
    print("  [PASS] Scenario D — split equally as gift")
    return True


def scenario_E():
    lead, members, group = setup_scenario("E", num_members=2, members_who_pay=1)
    gid = group["id"]
    body = {"user_id": lead["id"]}  # no shortfall options
    print(f"  [pay] body={body}")
    r = post(f"/groups/{gid}/pay", body)
    print(f"  [pay] status={r.status_code} body={r.text[:300]}")
    assert r.status_code == 400, \
        f"Expected 400 'bill is short', got {r.status_code}: {r.text}"
    body_json = r.json()
    detail = body_json.get("detail", "")
    assert "short" in detail.lower(), f"Expected 'short' in detail, got: {detail}"
    print(f"  [PASS] Scenario E — legacy call returns 400 ({detail!r})")
    return True


def main():
    results = {}
    for name, fn in [
        ("A", scenario_A),
        ("B", scenario_B),
        ("C", scenario_C),
        ("D", scenario_D),
        ("E", scenario_E),
    ]:
        try:
            fn()
            results[name] = "PASS"
        except AssertionError as e:
            results[name] = f"FAIL: {e}"
            print(f"  [FAIL] Scenario {name}: {e}")
        except Exception as e:
            results[name] = f"ERROR: {e}"
            print(f"  [ERROR] Scenario {name}: {e}")
            import traceback; traceback.print_exc()

    print("\n=== RESULTS ===")
    for k, v in results.items():
        print(f"  Scenario {k}: {v}")
    failed = [k for k, v in results.items() if not v.startswith("PASS")]
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
