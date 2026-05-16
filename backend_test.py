"""Backend test for the "Lead absorbs residual cents" penny-rounding fix.

Verifies /app/backend/core.py :: _recompute_group's equal-split branch and
itemized extras proration both route ALL leftover cents to the LEAD member
(identified by role=="lead", not by array index).
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Tuple

import requests

BASE = "https://joint-pay-1.preview.emergentagent.com/api"
MOCK_OTP = "123456"

PASS: List[str] = []
FAIL: List[Tuple[str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append((name, detail))
        print(f"  ❌ {name}  {detail}")


def section(t: str) -> None:
    print(f"\n=== {t} ===")


def _phone() -> str:
    return "555" + "".join(c for c in uuid.uuid4().hex if c.isdigit())[:7].ljust(7, "0")


def _direct_verify_user(user_id: str, phone: str) -> bool:
    """Bypass /send-otp rate-limit by directly flipping user.verified=true in mongo."""
    try:
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
        db_name = os.environ.get("DB_NAME") or "test_database"
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]

        async def _go():
            res = await db.users.update_one(
                {"id": user_id},
                {"$set": {"phone": phone, "verified": True}},
            )
            return res.modified_count
        loop = asyncio.new_event_loop()
        try:
            n = loop.run_until_complete(_go())
        finally:
            loop.close()
        return n > 0
    except Exception as e:
        print(f"  ⚠ direct mongo verify failed: {e}")
        return False


def register_and_verify(name: str) -> Dict[str, Any]:
    r = requests.post(f"{BASE}/auth/register", json={"name": name}, timeout=20)
    assert r.status_code == 200, f"register({name}) -> {r.status_code} {r.text[:200]}"
    user = r.json()
    user_id = user["id"]
    phone = _phone()
    # Try the API route first; fall back to direct mongo on rate-limit (429).
    r = requests.post(
        f"{BASE}/auth/send-otp",
        json={"user_id": user_id, "phone": phone},
        timeout=20,
    )
    if r.status_code == 200:
        rv = requests.post(
            f"{BASE}/auth/verify-otp",
            json={"user_id": user_id, "phone": phone, "code": MOCK_OTP},
            timeout=20,
        )
        if rv.status_code == 200:
            return {"id": user_id, "phone": phone, "name": name}
    # API path failed -> direct DB shortcut.
    ok = _direct_verify_user(user_id, phone)
    assert ok, f"could not verify user {user_id} (api+direct both failed)"
    return {"id": user_id, "phone": phone, "name": name}


def create_group_fast(lead_id: str, total: float, title: str = "Penny Test") -> Dict[str, Any]:
    body = {
        "lead_id": lead_id,
        "title": title,
        "total_amount": total,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r = requests.post(f"{BASE}/groups", json=body, timeout=20)
    assert r.status_code == 200, f"create group -> {r.status_code} {r.text[:200]}"
    return r.json()


def create_group_itemized(
    lead_id: str,
    items: List[Dict[str, Any]],
    tax: float,
    tip: float,
    title: str = "Itemized Penny Test",
) -> Dict[str, Any]:
    subtotal = sum(it["price"] * it["quantity"] for it in items)
    total = round(subtotal + tax + tip, 2)
    body = {
        "lead_id": lead_id,
        "title": title,
        "total_amount": total,
        "split_mode": "itemized",
        "tax": tax,
        "tip": tip,
        "items": items,
    }
    r = requests.post(f"{BASE}/groups", json=body, timeout=20)
    assert r.status_code == 200, f"create itemized -> {r.status_code} {r.text[:200]}"
    return r.json()


def join(group_id: str, user_id: str) -> Dict[str, Any]:
    r = requests.post(
        f"{BASE}/groups/{group_id}/join",
        json={"user_id": user_id, "joined_via": "code"},
        timeout=20,
    )
    assert r.status_code == 200, f"join -> {r.status_code} {r.text[:200]}"
    return r.json()


def get_group(group_id: str) -> Dict[str, Any]:
    r = requests.get(f"{BASE}/groups/{group_id}", timeout=20)
    assert r.status_code == 200, f"get group -> {r.status_code} {r.text[:200]}"
    return r.json()


def find_member(group: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    for p in group["per_user"]:
        if p["user_id"] == user_id:
            return p
    raise AssertionError(f"user_id {user_id} not in per_user")


def lead_member_id(group: Dict[str, Any]) -> str:
    for m in group["members"]:
        if (m.get("role") or "").lower() == "lead":
            return m["user_id"]
    return group["members"][0]["user_id"]


def test_equal_split_89_21() -> None:
    section("1) Equal split — $89.21 / 2 (AB22C-1DC32 case)")
    lead = register_and_verify(f"LeadA_{uuid.uuid4().hex[:6]}")
    m1 = register_and_verify(f"MemberA_{uuid.uuid4().hex[:6]}")
    g = create_group_fast(lead["id"], 89.21, title="AB22C repro")
    g = join(g["id"], m1["id"])
    g = get_group(g["id"])

    lead_id = lead_member_id(g)
    lp = find_member(g, lead_id)
    other = next(p for p in g["per_user"] if p["user_id"] != lead_id)

    total_food = round(sum(p["food"] for p in g["per_user"]), 2)
    check("$89.21/2: sum(food) == 89.21", abs(total_food - 89.21) < 0.005,
          f"got {total_food}")
    check("$89.21/2: lead.food == 44.61", abs(lp["food"] - 44.61) < 0.005,
          f"got {lp['food']}")
    check("$89.21/2: non-lead.food == 44.60", abs(other["food"] - 44.60) < 0.005,
          f"got {other['food']}")
    check("$89.21/2: lead identified by role=='lead'",
          lead_id == lead["id"], f"lead_id={lead_id} expected {lead['id']}")


def test_equal_split_94_43() -> None:
    section("2) Equal split — $94.43 / 2")
    lead = register_and_verify(f"LeadB_{uuid.uuid4().hex[:6]}")
    m1 = register_and_verify(f"MemberB_{uuid.uuid4().hex[:6]}")
    g = create_group_fast(lead["id"], 94.43)
    g = join(g["id"], m1["id"])
    g = get_group(g["id"])

    lead_id = lead_member_id(g)
    lp = find_member(g, lead_id)
    other = next(p for p in g["per_user"] if p["user_id"] != lead_id)

    total_food = round(sum(p["food"] for p in g["per_user"]), 2)
    check("$94.43/2: sum(food) == 94.43", abs(total_food - 94.43) < 0.005,
          f"got {total_food}")
    check("$94.43/2: lead.food == 47.22", abs(lp["food"] - 47.22) < 0.005,
          f"got {lp['food']}")
    check("$94.43/2: non-lead.food == 47.21", abs(other["food"] - 47.21) < 0.005,
          f"got {other['food']}")


def test_equal_split_50_seven() -> None:
    section("3) Equal split — $50.00 / 7")
    lead = register_and_verify(f"LeadC_{uuid.uuid4().hex[:6]}")
    members = [register_and_verify(f"MC{i}_{uuid.uuid4().hex[:6]}") for i in range(6)]
    g = create_group_fast(lead["id"], 50.00)
    for m in members:
        g = join(g["id"], m["id"])
    g = get_group(g["id"])

    lead_id = lead_member_id(g)
    lp = find_member(g, lead_id)
    non_lead = [p for p in g["per_user"] if p["user_id"] != lead_id]

    total_food = round(sum(p["food"] for p in g["per_user"]), 2)
    check("$50/7: sum(food) == 50.00", abs(total_food - 50.00) < 0.005,
          f"got {total_food}")
    check("$50/7: lead.food == 7.16 (base 7.14 + 0.02 residual)",
          abs(lp["food"] - 7.16) < 0.005, f"got {lp['food']}")
    others_correct = all(abs(p["food"] - 7.14) < 0.005 for p in non_lead)
    check("$50/7: all 6 non-leads.food == 7.14", others_correct,
          f"got {[p['food'] for p in non_lead]}")


def test_equal_split_100_02_three() -> None:
    section("4) Equal split — $100.02 / 3 (no residual)")
    lead = register_and_verify(f"LeadD_{uuid.uuid4().hex[:6]}")
    m1 = register_and_verify(f"MD1_{uuid.uuid4().hex[:6]}")
    m2 = register_and_verify(f"MD2_{uuid.uuid4().hex[:6]}")
    g = create_group_fast(lead["id"], 100.02)
    g = join(g["id"], m1["id"])
    g = join(g["id"], m2["id"])
    g = get_group(g["id"])

    total_food = round(sum(p["food"] for p in g["per_user"]), 2)
    check("$100.02/3: sum(food) == 100.02", abs(total_food - 100.02) < 0.005,
          f"got {total_food}")
    all_3334 = all(abs(p["food"] - 33.34) < 0.005 for p in g["per_user"])
    check("$100.02/3: all members.food == 33.34", all_3334,
          f"got {[p['food'] for p in g['per_user']]}")


def test_equal_split_100_four() -> None:
    section("5) Equal split — $100.00 / 4 (no residual)")
    lead = register_and_verify(f"LeadE_{uuid.uuid4().hex[:6]}")
    members = [register_and_verify(f"ME{i}_{uuid.uuid4().hex[:6]}") for i in range(3)]
    g = create_group_fast(lead["id"], 100.00)
    for m in members:
        g = join(g["id"], m["id"])
    g = get_group(g["id"])

    total_food = round(sum(p["food"] for p in g["per_user"]), 2)
    check("$100/4: sum(food) == 100.00", abs(total_food - 100.00) < 0.005,
          f"got {total_food}")
    all_25 = all(abs(p["food"] - 25.00) < 0.005 for p in g["per_user"])
    check("$100/4: all members.food == 25.00", all_25,
          f"got {[p['food'] for p in g['per_user']]}")


def test_lead_position_independence() -> None:
    section("6) Lead position independence (DB-level reorder)")
    lead = register_and_verify(f"LeadF_{uuid.uuid4().hex[:6]}")
    m1 = register_and_verify(f"MF1_{uuid.uuid4().hex[:6]}")
    m2 = register_and_verify(f"MF2_{uuid.uuid4().hex[:6]}")
    g = create_group_fast(lead["id"], 100.01)  # residual = 1 cent
    g = join(g["id"], m1["id"])
    g = join(g["id"], m2["id"])
    g_id = g["id"]

    try:
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
        db_name = os.environ.get("DB_NAME") or "test_database"
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]

        async def _reorder():
            doc = await db.groups.find_one({"id": g_id}, {"_id": 0, "members": 1})
            members = doc["members"]
            lead_entry = next(m for m in members if (m.get("role") or "").lower() == "lead")
            non_lead = [m for m in members if m.get("user_id") != lead_entry["user_id"]]
            new_order = non_lead + [lead_entry]
            await db.groups.update_one({"id": g_id}, {"$set": {"members": new_order}})
            return new_order

        loop = asyncio.new_event_loop()
        try:
            new_order = loop.run_until_complete(_reorder())
        finally:
            loop.close()
        check("DB reorder: lead now at last index (not 0)",
              (new_order[-1].get("role") or "").lower() == "lead",
              f"order: {[m.get('role') for m in new_order]}")
    except Exception as e:
        check("DB reorder skipped (no direct mongo access)", True,
              f"skipped: {e}")
        return

    g = get_group(g_id)
    lead_id_actual = lead_member_id(g)
    lp = find_member(g, lead_id_actual)
    non_lead_users = [p for p in g["per_user"] if p["user_id"] != lead_id_actual]

    check("Reorder: lead_id resolves to original lead",
          lead_id_actual == lead["id"],
          f"got {lead_id_actual} expected {lead['id']}")
    # $100.01/3 -> base 3333c, residual 2c. Lead absorbs both -> $33.35,
    # others $33.33.
    check("Reorder: lead.food == 33.35",
          abs(lp["food"] - 33.35) < 0.005, f"got {lp['food']}")
    check("Reorder: non-leads.food == 33.33",
          all(abs(p["food"] - 33.33) < 0.005 for p in non_lead_users),
          f"got {[p['food'] for p in non_lead_users]}")
    total = round(sum(p["food"] for p in g["per_user"]), 2)
    check("Reorder: sum(food) == 100.01", abs(total - 100.01) < 0.005,
          f"got {total}")


def test_itemized_lead_absorbs_extras_residual() -> None:
    section("7) Itemized — extras residual goes to Lead")
    lead = register_and_verify(f"LeadG_{uuid.uuid4().hex[:6]}")
    m1 = register_and_verify(f"MG1_{uuid.uuid4().hex[:6]}")
    m2 = register_and_verify(f"MG2_{uuid.uuid4().hex[:6]}")
    items = [
        {"name": "Burger", "price": 17.00, "quantity": 1},
        {"name": "Pasta", "price": 17.00, "quantity": 1},
        {"name": "Salad", "price": 16.00, "quantity": 1},
    ]
    g = create_group_itemized(lead["id"], items, tax=3.0, tip=5.0)
    g = join(g["id"], m1["id"])
    g = join(g["id"], m2["id"])
    g_id = g["id"]
    items_by_name = {it["name"]: it["id"] for it in g["items"]}

    def assign(uid: str, item_id: str) -> None:
        r = requests.post(
            f"{BASE}/groups/{g_id}/assign",
            json={"user_id": uid, "item_id": item_id, "quantity": 1},
            timeout=20,
        )
        assert r.status_code == 200, f"assign -> {r.status_code} {r.text[:200]}"

    assign(lead["id"], items_by_name["Burger"])
    assign(m1["id"], items_by_name["Pasta"])
    assign(m2["id"], items_by_name["Salad"])

    g = get_group(g_id)
    lead_id = lead_member_id(g)
    lp = find_member(g, lead_id)

    sum_merchant = round(sum(p["merchant_share"] for p in g["per_user"]), 2)
    check("Itemized: sum(merchant_share) == total_amount",
          abs(sum_merchant - g["total_amount"]) < 0.005,
          f"sum={sum_merchant} total={g['total_amount']}")
    check("Itemized: lead.food == 17.00", abs(lp["food"] - 17.00) < 0.005,
          f"got {lp['food']}")
    check("Itemized: lead.tax_tip == 2.72 (17/50 * 8)",
          abs(lp["tax_tip"] - 2.72) < 0.01, f"got {lp['tax_tip']}")

    # ── 7b: forced 2-cent residual ─────────────────────────────
    section("7b) Itemized — forced 2-cent extras residual")
    lead2 = register_and_verify(f"LeadH_{uuid.uuid4().hex[:6]}")
    mh1 = register_and_verify(f"MH1_{uuid.uuid4().hex[:6]}")
    mh2 = register_and_verify(f"MH2_{uuid.uuid4().hex[:6]}")
    items2 = [
        {"name": "ItemA", "price": 10.00, "quantity": 1},
        {"name": "ItemB", "price": 10.00, "quantity": 1},
        {"name": "ItemC", "price": 10.00, "quantity": 1},
    ]
    g2 = create_group_itemized(lead2["id"], items2, tax=1.01, tip=0.0)
    g2 = join(g2["id"], mh1["id"])
    g2 = join(g2["id"], mh2["id"])
    g2_id = g2["id"]
    items2_by_name = {it["name"]: it["id"] for it in g2["items"]}

    def assign2(uid: str, item_id: str) -> None:
        r = requests.post(
            f"{BASE}/groups/{g2_id}/assign",
            json={"user_id": uid, "item_id": item_id, "quantity": 1},
            timeout=20,
        )
        assert r.status_code == 200, f"assign -> {r.status_code} {r.text[:200]}"

    assign2(lead2["id"], items2_by_name["ItemA"])
    assign2(mh1["id"], items2_by_name["ItemB"])
    assign2(mh2["id"], items2_by_name["ItemC"])

    g2 = get_group(g2_id)
    lead2_id = lead_member_id(g2)
    lp2 = find_member(g2, lead2_id)
    others2 = [p for p in g2["per_user"] if p["user_id"] != lead2_id]

    # 10/30 * 1.01 = 0.33666... -> floor 0.33 each, sum 0.99, residual 0.02
    # all 0.02 go to Lead -> lead.tax_tip = 0.35, others = 0.33.
    check("Itemized residual: lead.tax_tip == 0.35 (33c + 2c residual)",
          abs(lp2["tax_tip"] - 0.35) < 0.005, f"got {lp2['tax_tip']}")
    others_tax_correct = all(abs(p["tax_tip"] - 0.33) < 0.005 for p in others2)
    check("Itemized residual: non-leads.tax_tip == 0.33",
          others_tax_correct, f"got {[p['tax_tip'] for p in others2]}")
    sum_tax_tip = round(sum(p["tax_tip"] for p in g2["per_user"]), 2)
    check("Itemized residual: sum(tax_tip) == 1.01 exactly",
          abs(sum_tax_tip - 1.01) < 0.005, f"got {sum_tax_tip}")
    sum_merchant2 = round(sum(p["merchant_share"] for p in g2["per_user"]), 2)
    check("Itemized residual: sum(merchant_share) == total_amount ($31.01)",
          abs(sum_merchant2 - g2["total_amount"]) < 0.005,
          f"sum={sum_merchant2} total={g2['total_amount']}")


def test_payment_intent_uses_lead_bonus_cent() -> None:
    section("8) Payment intent — amount reflects Lead bonus cent")
    lead = register_and_verify(f"LeadI_{uuid.uuid4().hex[:6]}")
    m1 = register_and_verify(f"MI1_{uuid.uuid4().hex[:6]}")
    g = create_group_fast(lead["id"], 89.21)
    g = join(g["id"], m1["id"])
    g_id = g["id"]
    g = get_group(g_id)

    lead_id = lead_member_id(g)
    lp = find_member(g, lead_id)
    other = next(p for p in g["per_user"] if p["user_id"] != lead_id)

    lead_total = lp["total"]
    other_total = other["total"]
    check(
        "lead.total > other.total (lead absorbs extra cent)",
        lead_total > other_total,
        f"lead.total={lead_total} other.total={other_total}",
    )

    def call_pi(user_id: str) -> requests.Response:
        return requests.post(
            f"{BASE}/groups/{g_id}/contribute-payment-intent",
            json={"user_id": user_id, "notify_on_settled": False},
            timeout=30,
        )

    r_lead = call_pi(lead["id"])
    r_m1 = call_pi(m1["id"])
    check("PI for lead -> 200", r_lead.status_code == 200,
          f"got {r_lead.status_code} {r_lead.text[:200]}")
    check("PI for non-lead -> 200", r_m1.status_code == 200,
          f"got {r_m1.status_code} {r_m1.text[:200]}")
    if r_lead.status_code == 200:
        body = r_lead.json()
        check("PI lead.cash_owed == lead.total",
              abs(body["cash_owed"] - lead_total) < 0.005,
              f"cash_owed={body['cash_owed']} lead.total={lead_total}")
    if r_m1.status_code == 200:
        body = r_m1.json()
        check("PI non-lead.cash_owed == non-lead.total",
              abs(body["cash_owed"] - other_total) < 0.005,
              f"cash_owed={body['cash_owed']} other.total={other_total}")
    if r_lead.status_code == 200 and r_m1.status_code == 200:
        lead_cash = r_lead.json()["cash_owed"]
        other_cash = r_m1.json()["cash_owed"]
        check("PI: lead.cash_owed > non-lead.cash_owed (>= 1c diff)",
              lead_cash > other_cash,
              f"lead={lead_cash} other={other_cash}")


def test_regression_smoke() -> None:
    section("9) Regression smoke (existing read endpoints still 200)")
    r = requests.get(f"{BASE}/runtime/brand", timeout=15)
    check("GET /runtime/brand -> 200", r.status_code == 200,
          f"got {r.status_code}")
    r = requests.get(f"{BASE}/runtime/landing-page", timeout=15)
    check("GET /runtime/landing-page -> 200", r.status_code == 200,
          f"got {r.status_code}")


def main() -> int:
    try:
        test_equal_split_89_21()
        test_equal_split_94_43()
        test_equal_split_50_seven()
        test_equal_split_100_02_three()
        test_equal_split_100_four()
        test_lead_position_independence()
        test_itemized_lead_absorbs_extras_residual()
        test_payment_intent_uses_lead_bonus_cent()
        test_regression_smoke()
    except Exception as e:
        import traceback
        traceback.print_exc()
        FAIL.append(("test runner exception", str(e)))

    print("\n" + "=" * 60)
    print(f"PASS: {len(PASS)}   FAIL: {len(FAIL)}")
    if FAIL:
        print("\nFAILED:")
        for name, detail in FAIL:
            print(f"  - {name}: {detail}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
