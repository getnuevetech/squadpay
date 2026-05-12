"""Focused backend test for POST /api/groups/{group_id}/split-mode.

Covers all 8 validation/happy-path scenarios from the review request.
"""
import os
import sys
import time
import json
import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASS = "Letmein@2007#ForReal"

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def record(label, ok, detail=""):
    tag = PASS if ok else FAIL
    print(f"{tag} {label} :: {detail}")
    results.append((label, ok, detail))


def admin_login():
    r = requests.post(f"{BASE}/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]


def set_sms_mock(admin_token):
    r = requests.post(
        f"{BASE}/admin/integrations/sms-mode",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "mock"},
        timeout=20,
    )
    r.raise_for_status()


def make_user(name: str, phone: str) -> dict:
    r = requests.post(f"{BASE}/auth/register", json={"name": name}, timeout=20)
    r.raise_for_status()
    user = r.json()
    uid = user["id"]
    r = requests.post(f"{BASE}/auth/send-otp", json={"user_id": uid, "phone": phone}, timeout=20)
    r.raise_for_status()
    r = requests.post(
        f"{BASE}/auth/verify-otp",
        json={"user_id": uid, "phone": phone, "code": "123456", "confirm_existing": True},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def create_group(lead_id: str, title: str, split_mode: str = "itemized", items=None, total=None) -> dict:
    items = items or [
        {"name": "Burger", "price": 12.0, "quantity": 1},
        {"name": "Fries", "price": 4.0, "quantity": 1},
        {"name": "Soda", "price": 2.0, "quantity": 1},
    ]
    if total is None:
        total = sum(i["price"] * i["quantity"] for i in items)
    payload = {
        "lead_id": lead_id,
        "title": title,
        "total_amount": total,
        "split_mode": split_mode,
        "tax": 0.0,
        "tip": 0.0,
        "items": items,
    }
    r = requests.post(f"{BASE}/groups", json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def join_group(gid: str, user_id: str):
    r = requests.post(f"{BASE}/groups/{gid}/join", json={"user_id": user_id, "joined_via": "code"}, timeout=20)
    r.raise_for_status()
    return r.json()


def set_split_mode(gid: str, user_id: str, mode):
    return requests.post(
        f"{BASE}/groups/{gid}/split-mode",
        json={"user_id": user_id, "split_mode": mode},
        timeout=20,
    )


def get_group(gid: str) -> dict:
    r = requests.get(f"{BASE}/groups/{gid}", timeout=20)
    r.raise_for_status()
    return r.json()


def main():
    ts = int(time.time())
    print(f"== split-mode endpoint test, ts={ts} ==")

    admin_token = admin_login()
    set_sms_mock(admin_token)
    print("admin login + sms mock ok")

    suffix = f"{ts % 10000000:07d}"
    alice = make_user(f"Alice{ts}", f"+1500{suffix}")
    bob = make_user(f"Bob{ts}", f"+1501{suffix}")
    carol = make_user(f"Carol{ts}", f"+1502{suffix}")
    print(f"users: alice={alice['id']} bob={bob['id']} carol={carol['id']}")

    group = create_group(alice["id"], f"DinnerA{ts}", split_mode="itemized")
    gid = group["id"]
    join_group(gid, bob["id"])
    join_group(gid, carol["id"])
    group = get_group(gid)
    print(f"group {gid} created, split_mode={group['split_mode']}, total={group['total_amount']}")

    # 1) Invalid split_mode (note: route does .strip().lower() so trailing/leading
    # whitespace and case differences are normalised. Only truly invalid tokens
    # should be rejected.)
    for bad in ["smart", "", "items", "equal"]:
        r = set_split_mode(gid, alice["id"], bad)
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = r.text
        ok = r.status_code == 400 and "split_mode must be" in str(detail).lower()
        record(f"invalid mode={bad!r}", ok, f"status={r.status_code} detail={detail!r}")

    # Missing field
    r = requests.post(f"{BASE}/groups/{gid}/split-mode", json={"user_id": alice["id"]}, timeout=20)
    record("invalid mode (missing field) -> 4xx", r.status_code in (400, 422), f"status={r.status_code} body={r.text[:200]}")

    # 2) Unknown group_id
    r = set_split_mode("g_DOES_NOT_EXIST_X", alice["id"], "fast")
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    ok = r.status_code == 404 and "group not found" in str(detail).lower()
    record("unknown group_id -> 404", ok, f"status={r.status_code} detail={detail!r}")

    # 3) Non-lead caller -> 403
    r = set_split_mode(gid, bob["id"], "fast")
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    ok = r.status_code == 403 and "only the lead" in str(detail).lower()
    record("non-lead caller -> 403", ok, f"status={r.status_code} detail={detail!r}")

    # 7) HAPPY: itemized -> fast
    r = set_split_mode(gid, alice["id"], "fast")
    ok = r.status_code == 200
    body = r.json() if ok else {}
    record(
        "happy: itemized -> fast (200)",
        ok and body.get("split_mode") == "fast",
        f"status={r.status_code} split_mode={body.get('split_mode')}",
    )
    if ok:
        per = body.get("per_user", [])
        total = float(body.get("total_amount") or 0)
        expected_share = total / 3.0
        food_shares = [p["food"] for p in per]
        food_ok = len(food_shares) == 3 and all(abs(f - expected_share) <= 0.02 for f in food_shares)
        record(
            "fast mode: per_user food == total/members",
            food_ok,
            f"shares={food_shares}, expected≈{expected_share:.2f}",
        )
    fresh = get_group(gid)
    record("persistence: fast saved", fresh.get("split_mode") == "fast", f"split_mode={fresh.get('split_mode')}")

    # 8) Idempotency
    r = set_split_mode(gid, alice["id"], "fast")
    body2 = r.json() if r.status_code == 200 else {}
    record(
        "idempotency: fast -> fast (200)",
        r.status_code == 200 and body2.get("split_mode") == "fast",
        f"status={r.status_code} split_mode={body2.get('split_mode')}",
    )

    # 7b) HAPPY reverse: fast -> itemized
    r = set_split_mode(gid, alice["id"], "itemized")
    body = r.json() if r.status_code == 200 else {}
    record(
        "happy: fast -> itemized (200)",
        r.status_code == 200 and body.get("split_mode") == "itemized",
        f"status={r.status_code} split_mode={body.get('split_mode')}",
    )

    # Assign all items to alice
    items = body.get("items", [])
    for it in items:
        ar = requests.post(
            f"{BASE}/groups/{gid}/assign",
            json={"user_id": alice["id"], "item_id": it["id"], "quantity": it["quantity"]},
            timeout=20,
        )
        ar.raise_for_status()
    fresh = get_group(gid)
    per = {p["user_id"]: p for p in fresh.get("per_user", [])}
    alice_food = per.get(alice["id"], {}).get("food", -1)
    bob_food = per.get(bob["id"], {}).get("food", -1)
    carol_food = per.get(carol["id"], {}).get("food", -1)
    itemized_ok = abs(alice_food - 18.0) < 0.01 and abs(bob_food) < 0.01 and abs(carol_food) < 0.01
    record(
        "itemized mode: shares reflect claimed items",
        itemized_ok,
        f"alice={alice_food} bob={bob_food} carol={carol_food} (expected 18/0/0)",
    )

    # 5) Contributions started -> 400
    sr = set_split_mode(gid, alice["id"], "fast")
    record("setup: back to fast before contribute", sr.status_code == 200, f"status={sr.status_code}")

    fresh = get_group(gid)
    alice_per = next((p for p in fresh["per_user"] if p["user_id"] == alice["id"]), None)
    contrib_amount = alice_per["total"] if alice_per else 5.0

    # Contribute requires cash (Stripe) when no credits — to keep the test
    # self-contained, admin-grant Alice enough credits to fund her share so
    # contribute can complete without Stripe redirection.
    grant_r = requests.post(
        f"{BASE}/admin/users/{alice['id']}/credits/grant",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"amount": round(contrib_amount + 1, 2), "note": "test split-mode contribute"},
        timeout=20,
    )
    record(
        "setup: admin grants credit to alice",
        grant_r.status_code == 200,
        f"status={grant_r.status_code} body={grant_r.text[:200]}",
    )

    cr = requests.post(
        f"{BASE}/groups/{gid}/contribute",
        json={"user_id": alice["id"], "amount": contrib_amount},
        timeout=30,
    )
    record(
        "setup: alice contributes",
        cr.status_code == 200,
        f"status={cr.status_code} amount={contrib_amount} body={cr.text[:200]}",
    )

    r = set_split_mode(gid, alice["id"], "itemized")
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    ok = r.status_code == 400 and "contributions have started" in str(detail).lower()
    record(
        "contributions started -> 400",
        ok,
        f"status={r.status_code} detail={detail!r}",
    )

    # 4) status != 'open' lock
    fresh = get_group(gid)
    rtc = float((fresh.get("funding") or {}).get("remaining_to_collect") or 0)
    if rtc > 0:
        for u in (bob, carol):
            per_u = next((p for p in fresh["per_user"] if p["user_id"] == u["id"]), None)
            if not per_u:
                continue
            amt = per_u["total"]
            # Grant credit so contribute can complete without Stripe
            requests.post(
                f"{BASE}/admin/users/{u['id']}/credits/grant",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"amount": round(amt + 1, 2), "note": "test split-mode contribute"},
                timeout=20,
            )
            cr = requests.post(
                f"{BASE}/groups/{gid}/contribute",
                json={"user_id": u["id"], "amount": amt},
                timeout=30,
            )
            print(f"  {u['name']} contribute -> {cr.status_code}: {cr.text[:160]}")
        fresh = get_group(gid)

    raw_status = fresh.get("status")
    print(f"  after contributions: status={raw_status} derived={fresh.get('derived_status')} rtc={fresh.get('funding',{}).get('remaining_to_collect')}")

    if raw_status == "open":
        pr = requests.post(f"{BASE}/groups/{gid}/pay", json={"user_id": alice["id"]}, timeout=30)
        print(f"  /pay -> {pr.status_code}: {pr.text[:200]}")
        fresh = get_group(gid)
        raw_status = fresh.get("status")

    if raw_status != "open":
        r = set_split_mode(gid, alice["id"], "fast")
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = r.text
        ok = r.status_code == 400 and "locked" in str(detail).lower()
        record(
            f"status != 'open' (status={raw_status}) -> 400 locked",
            ok,
            f"status={r.status_code} detail={detail!r}",
        )
    else:
        record(
            "status != 'open' lock test",
            False,
            f"could not move group out of 'open' to verify (status={raw_status})",
        )

    # 6) is_blocked -> 403  (fresh group)
    block_group_data = create_group(alice["id"], f"BlockTest{ts}", split_mode="fast")
    bgid = block_group_data["id"]
    join_group(bgid, bob["id"])
    br = requests.post(
        f"{BASE}/admin/groups/{bgid}/block",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"is_blocked": True, "reason": "test split-mode block"},
        timeout=20,
    )
    if br.status_code != 200:
        record("setup: admin blocks group", False, f"status={br.status_code} body={br.text[:200]}")
    else:
        record("setup: admin blocks group", True, "")
        r = set_split_mode(bgid, alice["id"], "itemized")
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = r.text
        ok = r.status_code == 403 and "blocked by an administrator" in str(detail).lower()
        record(
            "is_blocked group -> 403",
            ok,
            f"status={r.status_code} detail={detail!r}",
        )

    print("\n=== SUMMARY ===")
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"{passed}/{total} assertions passed")
    failed = [r for r in results if not r[1]]
    if failed:
        print("FAILED:")
        for label, _, detail in failed:
            print(f"  - {label}: {detail}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
