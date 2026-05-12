"""Focused re-test of Rule 5 in POST /api/groups/{group_id}/split-mode.

After main agent fix: route now reads raw `contributions` / `repayments`
arrays from the persisted mongo doc instead of the non-persisted `funding`
aggregate.

Scenarios re-verified here (per review request):
  R5-A) Fresh group, lead contributes -> set_split_mode flips -> expect 400
        "contributions have started".
  R5-B) Fresh group, no contributions, but a single `repayments` entry
        injected directly into the mongo doc -> expect 400 same message.
  R5-C) Fresh group with NO contributions and NO repayments -> happy path
        still works (200, mode flipped).
"""
import os
import sys
import time
import requests
from pymongo import MongoClient

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASS = "Letmein@2007#ForReal"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def record(label, ok, detail=""):
    tag = PASS if ok else FAIL
    print(f"{tag} {label} :: {detail}")
    results.append((label, ok, detail))


def admin_login():
    r = requests.post(
        f"{BASE}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["token"]


def set_sms_mock(admin_token):
    requests.post(
        f"{BASE}/admin/integrations/sms-mode",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "mock"},
        timeout=20,
    ).raise_for_status()


def make_user(name: str, phone: str) -> dict:
    r = requests.post(f"{BASE}/auth/register", json={"name": name}, timeout=20)
    r.raise_for_status()
    user = r.json()
    uid = user["id"]
    requests.post(
        f"{BASE}/auth/send-otp",
        json={"user_id": uid, "phone": phone},
        timeout=20,
    ).raise_for_status()
    r = requests.post(
        f"{BASE}/auth/verify-otp",
        json={"user_id": uid, "phone": phone, "code": "123456", "confirm_existing": True},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def create_group(lead_id: str, title: str, split_mode: str = "itemized") -> dict:
    items = [
        {"name": "Burger", "price": 12.0, "quantity": 1},
        {"name": "Fries", "price": 4.0, "quantity": 1},
        {"name": "Soda", "price": 2.0, "quantity": 1},
    ]
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
    requests.post(
        f"{BASE}/groups/{gid}/join",
        json={"user_id": user_id, "joined_via": "code"},
        timeout=20,
    ).raise_for_status()


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


def grant_credit(admin_token, user_id, amount, note):
    r = requests.post(
        f"{BASE}/admin/users/{user_id}/credits/grant",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"amount": round(amount, 2), "note": note},
        timeout=20,
    )
    r.raise_for_status()


def main():
    ts = int(time.time())
    print(f"== Rule-5 re-test, ts={ts} ==")
    print(f"BASE={BASE}")
    print(f"MONGO={MONGO_URL} db={DB_NAME}")

    admin_token = admin_login()
    set_sms_mock(admin_token)
    print("admin login + sms mock ok")

    mc = MongoClient(MONGO_URL)
    db = mc[DB_NAME]

    # =================================================================
    # R5-C HAPPY PATH (do this first while group still has no contribs)
    # We will use the same group later for contribute scenario, so create
    # a SEPARATE group for the happy path sanity check.
    # =================================================================
    suffix = f"{ts % 10000000:07d}"
    happy_lead = make_user(f"HappyLead{ts}", f"+1520{suffix}")
    happy_g = create_group(happy_lead["id"], f"HappyDinner{ts}", split_mode="itemized")
    h_gid = happy_g["id"]
    print(f"happy group {h_gid} created (itemized)")
    # Sanity: no contributions / repayments persisted in raw doc
    raw_h = db.groups.find_one({"id": h_gid}, {"_id": 0})
    record(
        "R5-C setup: happy group has zero contribs/repays in raw doc",
        not (raw_h.get("contributions") or raw_h.get("repayments")),
        f"contributions={raw_h.get('contributions')} repayments={raw_h.get('repayments')}",
    )
    r = set_split_mode(h_gid, happy_lead["id"], "fast")
    body = r.json() if r.status_code == 200 else {}
    record(
        "R5-C happy path: itemized -> fast (200)",
        r.status_code == 200 and body.get("split_mode") == "fast",
        f"status={r.status_code} split_mode={body.get('split_mode')}",
    )
    # And reverse
    r = set_split_mode(h_gid, happy_lead["id"], "itemized")
    body = r.json() if r.status_code == 200 else {}
    record(
        "R5-C happy path reverse: fast -> itemized (200)",
        r.status_code == 200 and body.get("split_mode") == "itemized",
        f"status={r.status_code} split_mode={body.get('split_mode')}",
    )

    # =================================================================
    # R5-A: Contribute -> rule 5 must fire
    # =================================================================
    alice = make_user(f"Alice{ts}", f"+1521{suffix}")
    bob = make_user(f"Bob{ts}", f"+1522{suffix}")
    carol = make_user(f"Carol{ts}", f"+1523{suffix}")
    print(f"users: alice={alice['id']} bob={bob['id']} carol={carol['id']}")

    g = create_group(alice["id"], f"ContribDinner{ts}", split_mode="itemized")
    gid = g["id"]
    join_group(gid, bob["id"])
    join_group(gid, carol["id"])
    g = get_group(gid)
    print(f"contrib group {gid} created split={g['split_mode']} total={g['total_amount']}")

    # Flip itemized -> fast first while no contribs to set up a known state
    r = set_split_mode(gid, alice["id"], "fast")
    assert r.status_code == 200, f"setup flip to fast failed: {r.status_code} {r.text}"

    g = get_group(gid)
    alice_per = next((p for p in g["per_user"] if p["user_id"] == alice["id"]), None)
    share = float(alice_per["total"]) if alice_per else 6.50
    print(f"alice per-user total: {share}")

    # Grant credit to fund the contribute (avoid Stripe redirection)
    grant_credit(admin_token, alice["id"], share + 1.0, "rule5 contribute")

    cr = requests.post(
        f"{BASE}/groups/{gid}/contribute",
        json={"user_id": alice["id"], "amount": share},
        timeout=30,
    )
    record(
        "R5-A setup: alice contributes (cash via credit)",
        cr.status_code == 200,
        f"status={cr.status_code} amount={share} body={cr.text[:200]}",
    )

    # Verify the raw mongo doc actually has a contribution row > 0
    raw = db.groups.find_one({"id": gid}, {"_id": 0})
    contribs = raw.get("contributions") or []
    contributed_sum = sum(float(c.get("amount") or 0) for c in contribs)
    record(
        "R5-A raw doc has contributions[] amount>0",
        contributed_sum > 0.01,
        f"contributions={contribs} sum={contributed_sum}",
    )

    # Now try to flip split mode - MUST be 400 with 'contributions have started'
    r = set_split_mode(gid, alice["id"], "itemized")
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    ok = r.status_code == 400 and "contributions have started" in str(detail).lower()
    record(
        "R5-A contributions>0 -> 400 'contributions have started'",
        ok,
        f"status={r.status_code} detail={detail!r}",
    )

    # =================================================================
    # R5-B: Repayments path -> rule 5 must fire
    # The /repay endpoint only fires after a paid group with loans, which is
    # a heavy setup. Easiest: inject a synthetic repayment row directly into
    # mongo on a fresh group with zero contributions, then verify rule 5
    # blocks. This isolates the new code path (sum from raw `repayments`).
    # =================================================================
    rep_lead = make_user(f"RepLead{ts}", f"+1524{suffix}")
    rep_g = create_group(rep_lead["id"], f"RepDinner{ts}", split_mode="itemized")
    r_gid = rep_g["id"]
    # Inject a repayment row directly in mongo
    fake_repay = {
        "id": f"rep_{r_gid[-6:]}_synthetic",
        "user_id": rep_lead["id"],
        "amount": 4.25,
        "created_at": "2025-01-01T00:00:00+00:00",
    }
    db.groups.update_one({"id": r_gid}, {"$set": {"repayments": [fake_repay]}})
    raw_r = db.groups.find_one({"id": r_gid}, {"_id": 0})
    repays = raw_r.get("repayments") or []
    repaid_sum = sum(float(x.get("amount") or 0) for x in repays)
    record(
        "R5-B setup: raw doc has repayments[] amount>0",
        repaid_sum > 0.01,
        f"repayments={repays} sum={repaid_sum}",
    )
    # Now try to flip split mode -- MUST be 400 with 'contributions have started'
    r = set_split_mode(r_gid, rep_lead["id"], "fast")
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    ok = r.status_code == 400 and "contributions have started" in str(detail).lower()
    record(
        "R5-B repayments>0 -> 400 'contributions have started'",
        ok,
        f"status={r.status_code} detail={detail!r}",
    )

    # =================================================================
    # SUMMARY
    # =================================================================
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
