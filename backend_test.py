"""
Backend tests for the redesigned shortfall settlement + 4-state derived status machine.
"""

import os
import sys
import json
from typing import Any, Dict, List, Optional, Tuple

import requests

def _read_env(path: str, key: str) -> Optional[str]:
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None

BASE_URL = (_read_env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    print("FATAL: EXPO_PUBLIC_BACKEND_URL not set")
    sys.exit(1)
API = f"{BASE_URL}/api"
print(f"API base = {API}\n")


class TestError(Exception):
    pass


def _req(method: str, path: str, **kw) -> Tuple[int, Any]:
    url = f"{API}{path}"
    r = requests.request(method, url, timeout=30, **kw)
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


def post(path: str, payload: dict) -> Tuple[int, Any]:
    return _req("POST", path, json=payload)


def get(path: str) -> Tuple[int, Any]:
    return _req("GET", path)


def register_and_verify(name: str, phone: str) -> dict:
    sc, user = post("/auth/register", {"name": name})
    if sc != 200:
        raise TestError(f"register {name} failed {sc} {user}")
    uid = user["id"]
    sc, _ = post("/auth/send-otp", {"user_id": uid, "phone": phone})
    if sc != 200:
        raise TestError(f"send-otp failed {sc}")
    sc, user = post("/auth/verify-otp", {"user_id": uid, "phone": phone, "code": "123456"})
    if sc != 200:
        raise TestError(f"verify-otp failed {sc} {user}")
    return user


def make_itemized_group(lead: dict, members: List[dict], items: List[dict],
                       title: str = "Dinner", tax: float = 0.0, tip: float = 0.0,
                       total_amount: Optional[float] = None) -> dict:
    subtotal = sum(it["price"] * it["quantity"] for it in items)
    if total_amount is None:
        total_amount = subtotal + tax + tip
    sc, group = post("/groups", {
        "lead_id": lead["id"], "title": title, "total_amount": total_amount,
        "split_mode": "itemized", "tax": tax, "tip": tip, "items": items,
    })
    if sc != 200:
        raise TestError(f"create group failed {sc} {group}")
    for m in members:
        sc, group = post(f"/groups/{group['id']}/join", {"user_id": m["id"]})
        if sc != 200:
            raise TestError(f"join failed {sc} {group}")
    return group


def assign(group_id: str, user_id: str, item_id: str, quantity: int) -> dict:
    sc, g = post(f"/groups/{group_id}/assign",
                 {"user_id": user_id, "item_id": item_id, "quantity": quantity})
    if sc != 200:
        raise TestError(f"assign failed {sc} {g}")
    return g


def contribute(group_id: str, user_id: str, amount: Optional[float] = None) -> Tuple[int, Any]:
    payload = {"user_id": user_id}
    if amount is not None:
        payload["amount"] = amount
    return post(f"/groups/{group_id}/contribute", payload)


def per_user_for(group: dict, user_id: str) -> dict:
    return next((p for p in group["per_user"] if p["user_id"] == user_id), {})


RESULTS = []


def report(name: str, ok: bool, details: str = ""):
    RESULTS.append({"name": name, "ok": ok, "details": details})
    flag = "PASS" if ok else "FAIL"
    print(f"  [{flag}] {name}")
    if details and not ok:
        for line in details.splitlines():
            print(f"          {line}")


def summarize_group(g: dict) -> str:
    notif = [(n.get("kind"), n.get("user_id"), n.get("delivered_via")) for n in (g.get("notifications") or [])]
    obs = [(o.get("kind"), o.get("user_id"), o.get("amount")) for o in (g.get("shortfall_obligations") or [])]
    pu = [{"user": p["user_id"][-6:], "total": p["total"], "contributed": p["contributed"],
           "shortfall_owed": p.get("shortfall_owed"), "outstanding": p["outstanding"]}
          for p in g["per_user"]]
    return (f"status={g.get('status')} derived={g.get('derived_status')} "
            f"funding_mode={g.get('funding_mode')} "
            f"remaining={g['funding']['remaining_to_collect']} "
            f"total_contributed={g['funding']['total_contributed']}\n"
            f"per_user={json.dumps(pu)}\nobligations={obs}\nnotifications={notif}")


def fresh_trio_with_shortfall(scenario: str):
    """Lead+2 members, 3 $20 items each assigned to one. Lead+m1 contribute, m2 doesn't."""
    lead = register_and_verify(f"Lead {scenario}", "+12025550100")
    m1 = register_and_verify(f"Avery {scenario}", "+12025550101")
    m2 = register_and_verify(f"Riley {scenario}", "+12025550102")
    items = [
        {"name": "Pasta", "price": 20.0, "quantity": 1},
        {"name": "Pizza", "price": 20.0, "quantity": 1},
        {"name": "Burger", "price": 20.0, "quantity": 1},
    ]
    group = make_itemized_group(lead, [m1, m2], items, title=f"Test {scenario}")
    gid = group["id"]
    item_ids = [it["id"] for it in group["items"]]
    assign(gid, lead["id"], item_ids[0], 1)
    assign(gid, m1["id"], item_ids[1], 1)
    g = assign(gid, m2["id"], item_ids[2], 1)
    sc, _ = contribute(gid, lead["id"])
    if sc != 200:
        raise TestError(f"lead contribute failed {sc}")
    sc, _ = contribute(gid, m1["id"])
    if sc != 200:
        raise TestError(f"m1 contribute failed {sc}")
    return lead, m1, m2, gid


def scenario_A():
    print("\n=== A: shortfall_mode='lead' is_loan=true ===")
    lead, m1, m2, gid = fresh_trio_with_shortfall("A")
    sc, body = post(f"/groups/{gid}/pay", {
        "user_id": lead["id"], "shortfall_mode": "lead", "is_loan": True,
    })
    print(f"  HTTP {sc}")
    if sc != 200:
        report("A: pay returns 200", False, str(body))
        return
    print("  " + summarize_group(body))
    report("A: status='paid'", body.get("status") == "paid", f"got {body.get('status')}")
    report("A: derived_status='repaying'", body.get("derived_status") == "repaying",
           f"got {body.get('derived_status')}")
    report("A: remaining_to_collect=0", body["funding"]["remaining_to_collect"] <= 0.01,
           f"got {body['funding']['remaining_to_collect']}")
    notif = body.get("notifications") or []
    lead_covered = [n for n in notif if n.get("kind") == "shortfall_lead_covered"]
    report("A: notifications include shortfall_lead_covered for beneficiary",
           len(lead_covered) >= 1 and any(n.get("user_id") == m2["id"] for n in lead_covered),
           f"lead_covered={lead_covered}")
    report("A: notifications delivered_via=sms_mock",
           all(n.get("delivered_via") == "sms_mock" for n in lead_covered), "")
    m2p = per_user_for(body, m2["id"])
    report("A: m2 still has outstanding (loan)", m2p["outstanding"] > 0.01,
           f"m2 outstanding={m2p['outstanding']}")
    settlement = body.get("shortfall_settlement") or {}
    report("A: settlement.mode/is_loan/funder_id correct",
           settlement.get("mode") == "lead" and settlement.get("is_loan") is True
           and settlement.get("funder_id") == lead["id"],
           f"settlement={settlement}")


def scenario_B():
    print("\n=== B: shortfall_mode='lead' is_loan=false ===")
    lead, m1, m2, gid = fresh_trio_with_shortfall("B")
    sc, body = post(f"/groups/{gid}/pay", {
        "user_id": lead["id"], "shortfall_mode": "lead", "is_loan": False,
    })
    print(f"  HTTP {sc}")
    if sc != 200:
        report("B: pay returns 200", False, str(body))
        return
    print("  " + summarize_group(body))
    report("B: status='closed'", body.get("status") == "closed", f"got {body.get('status')}")
    report("B: derived_status='settled'", body.get("derived_status") == "settled",
           f"got {body.get('derived_status')}")
    notif = body.get("notifications") or []
    gift_notifs = [n for n in notif if n.get("kind") == "shortfall_lead_covered"]
    msg_ok = any("gift" in (n.get("message") or "").lower() for n in gift_notifs)
    report("B: gift wording in lead-covered notification", msg_ok, f"notifs={gift_notifs}")
    m2p = per_user_for(body, m2["id"])
    report("B: m2 outstanding=0 (gift waives)", m2p["outstanding"] <= 0.01,
           f"m2 outstanding={m2p['outstanding']}")


def scenario_C():
    print("\n=== C: shortfall_mode='member' is_loan=true funder_member_id=m1 ===")
    lead, m1, m2, gid = fresh_trio_with_shortfall("C")
    sc, before = get(f"/groups/{gid}")
    shortfall = before["funding"]["remaining_to_collect"]
    funder_total = per_user_for(before, m1["id"])["total"]
    funder_already = per_user_for(before, m1["id"])["contributed"]
    sc, body = post(f"/groups/{gid}/pay", {
        "user_id": lead["id"], "shortfall_mode": "member",
        "is_loan": True, "funder_member_id": m1["id"],
    })
    print(f"  HTTP {sc}, shortfall was ${shortfall}")
    if sc != 200:
        report("C: pay returns 200", False, str(body))
        return None
    print("  " + summarize_group(body))
    report("C: status stays 'open'", body.get("status") == "open", f"got {body.get('status')}")
    report("C: derived_status='contributing'", body.get("derived_status") == "contributing",
           f"got {body.get('derived_status')}")
    obs = body.get("shortfall_obligations") or []
    funder_ob = next((o for o in obs if o["user_id"] == m1["id"]), None)
    report("C: shortfall_obligation kind=shortfall_member for funder",
           funder_ob is not None and funder_ob.get("kind") == "shortfall_member",
           f"funder_ob={funder_ob}")
    if funder_ob:
        report("C: obligation amount equals shortfall",
               abs(funder_ob["amount"] - shortfall) < 0.02,
               f"got {funder_ob['amount']} expected {shortfall}")
    notif = body.get("notifications") or []
    funder_notif = [n for n in notif
                    if n.get("user_id") == m1["id"] and n.get("kind") == "shortfall_assigned"]
    report("C: notification shortfall_assigned, sms_mock",
           len(funder_notif) >= 1 and funder_notif[0].get("delivered_via") == "sms_mock",
           f"funder_notif={funder_notif}")
    funder_pu = per_user_for(body, m1["id"])
    report("C: per_user[funder].shortfall_owed == shortfall",
           abs(funder_pu.get("shortfall_owed", 0) - shortfall) < 0.02,
           f"shortfall_owed={funder_pu.get('shortfall_owed')} expected {shortfall}")
    expected_outstanding = round(funder_total + funder_pu.get("shortfall_owed", 0) - funder_already, 2)
    report("C: per_user[funder].outstanding == total + shortfall_owed - contributed",
           abs(funder_pu["outstanding"] - expected_outstanding) < 0.02,
           f"outstanding={funder_pu['outstanding']} expected={expected_outstanding}")
    return body, m1, lead, m2, gid, shortfall


def scenario_D(group_after_C, m1, lead, m2, gid, shortfall):
    print("\n=== D: After C, funder /contribute (no amount) → settles ===")
    sc, body = contribute(gid, m1["id"])
    print(f"  HTTP {sc}")
    if sc != 200:
        report("D: contribute returns 200", False, str(body))
        return
    print("  " + summarize_group(body))
    report("D: status='paid'", body.get("status") == "paid", f"got {body.get('status')}")
    report("D: derived_status='settled'", body.get("derived_status") == "settled",
           f"got {body.get('derived_status')}")
    report("D: total_contributed >= total_amount",
           body["funding"]["total_contributed"] + 0.01 >= body["total_amount"],
           f"contributed={body['funding']['total_contributed']} total={body['total_amount']}")
    funder_pu = per_user_for(body, m1["id"])
    report("D: per_user[funder].outstanding == 0", funder_pu["outstanding"] <= 0.01,
           f"outstanding={funder_pu['outstanding']}")


def scenario_E():
    print("\n=== E: shortfall_mode='split_equal' ===")
    lead, m1, m2, gid = fresh_trio_with_shortfall("E")
    sc, before = get(f"/groups/{gid}")
    shortfall = before["funding"]["remaining_to_collect"]
    sc, body = post(f"/groups/{gid}/pay", {
        "user_id": lead["id"], "shortfall_mode": "split_equal",
    })
    print(f"  HTTP {sc}")
    if sc != 200:
        report("E: pay returns 200", False, str(body))
        return
    print("  " + summarize_group(body))
    report("E: status stays 'open'", body.get("status") == "open", f"got {body.get('status')}")
    report("E: derived_status='contributing'",
           body.get("derived_status") == "contributing", f"got {body.get('derived_status')}")
    obs = body.get("shortfall_obligations") or []
    non_lead_ids = {m1["id"], m2["id"]}
    ob_users = {o["user_id"] for o in obs}
    sum_amounts = round(sum(o["amount"] for o in obs), 2)
    report("E: one obligation per non-lead member", ob_users == non_lead_ids,
           f"ob_users={ob_users} expected={non_lead_ids}")
    report("E: sum of obligations == shortfall", abs(sum_amounts - shortfall) < 0.05,
           f"sum={sum_amounts} expected {shortfall}")
    notif = body.get("notifications") or []
    assigned_notifs = [n for n in notif if n.get("kind") == "shortfall_assigned"]
    assigned_users = {n["user_id"] for n in assigned_notifs}
    report("E: notifications shortfall_assigned for each non-lead",
           assigned_users == non_lead_ids, f"assigned_users={assigned_users}")
    m1_split = next((o["amount"] for o in obs if o["user_id"] == m1["id"]), 0)
    m1_pu = per_user_for(body, m1["id"])
    report("E: m1.outstanding == split share (already contributed share)",
           abs(m1_pu["outstanding"] - m1_split) < 0.05,
           f"m1 outstanding={m1_pu['outstanding']} split={m1_split}")
    m2_split = next((o["amount"] for o in obs if o["user_id"] == m2["id"]), 0)
    m2_pu = per_user_for(body, m2["id"])
    expected_m2 = round(m2_pu["total"] + m2_split, 2)
    report("E: m2.outstanding == share + split",
           abs(m2_pu["outstanding"] - expected_m2) < 0.05,
           f"m2 outstanding={m2_pu['outstanding']} expected={expected_m2}")


def scenario_F():
    print("\n=== F: items lock after settle ===")
    lead = register_and_verify("Lead F", "+12025550110")
    m1 = register_and_verify("Sage F", "+12025550111")
    items = [{"name": "Brunch", "price": 20.0, "quantity": 2}]
    group = make_itemized_group(lead, [m1], items, title="Test F")
    gid = group["id"]
    iid = group["items"][0]["id"]
    assign(gid, lead["id"], iid, 1)
    assign(gid, m1["id"], iid, 1)
    contribute(gid, lead["id"])
    contribute(gid, m1["id"])
    sc, after = get(f"/groups/{gid}")
    if after.get("status") != "paid":
        sc2, after = post(f"/groups/{gid}/pay", {"user_id": lead["id"]})
        print(f"  fallback /pay -> {sc2}")
    print(f"  status before append = {after.get('status')}, derived={after.get('derived_status')}")
    sc, body = post(f"/groups/{gid}/items/append",
                    {"user_id": lead["id"], "items": [{"name": "Coffee", "price": 5.0, "quantity": 1}]})
    print(f"  append HTTP {sc} body={body}")
    msg = (body.get("detail") if isinstance(body, dict) else "") or ""
    report("F: append returns 400 when status='paid'", sc == 400, f"sc={sc} body={body}")
    report("F: error mentions settled bill",
           "settled" in msg.lower() or "added" in msg.lower(), f"msg={msg}")


def scenario_G():
    print("\n=== G: unclaimed→shortfall, lead /pay loan ===")
    lead = register_and_verify("Lead G", "+12025550120")
    m1 = register_and_verify("Quinn G", "+12025550121")
    items = [
        {"name": "Steak", "price": 25.0, "quantity": 1},
        {"name": "Wine", "price": 25.0, "quantity": 1},
    ]
    group = make_itemized_group(lead, [m1], items, title="Test G", total_amount=50.0)
    gid = group["id"]
    iid_steak = group["items"][0]["id"]
    g_after = assign(gid, lead["id"], iid_steak, 1)
    lead_pu = per_user_for(g_after, lead["id"])
    print(f"  lead share={lead_pu['total']}, unclaimed={len(g_after.get('unclaimed') or [])}")
    sc, _ = contribute(gid, lead["id"])
    if sc != 200:
        report("G: lead contribute share", False, f"sc={sc}")
        return
    sc, body = post(f"/groups/{gid}/pay", {
        "user_id": lead["id"], "shortfall_mode": "lead", "is_loan": True,
    })
    print(f"  pay HTTP {sc}")
    if sc != 200:
        report("G: pay 200 with unclaimed items", False, str(body))
        return
    print("  " + summarize_group(body))
    report("G: pay returns 200 (unclaimed handled as shortfall)", True, "")
    report("G: status='paid'", body.get("status") == "paid", f"got {body.get('status')}")


def scenario_H():
    print("\n=== H: 4-state machine sanity ===")

    # H1
    lead = register_and_verify("Lead H1", "+12025550130")
    m1 = register_and_verify("Drew H1", "+12025550131")
    items = [{"name": "Soup", "price": 10.0, "quantity": 2}]
    g = make_itemized_group(lead, [m1], items, title="H1", total_amount=20.0)
    sc, g = get(f"/groups/{g['id']}")
    print(f"  H1 status={g.get('status')} derived={g.get('derived_status')}")
    report("H1: fresh open group derived='contributing'",
           g.get("derived_status") == "contributing", f"derived={g.get('derived_status')}")

    # H2
    iid = g["items"][0]["id"]
    assign(g["id"], lead["id"], iid, 1)
    assign(g["id"], m1["id"], iid, 1)
    contribute(g["id"], lead["id"])
    sc, g2 = contribute(g["id"], m1["id"])
    print(f"  H2 status={g2.get('status')} derived={g2.get('derived_status')}")
    derived_h2 = g2.get("derived_status")
    report("H2: after all contribute, derived in {contributed, settled} (NOT 'repaying')",
           derived_h2 in ("contributed", "settled"),
           f"derived={derived_h2} status={g2.get('status')}")

    # H3: same as H2 effectively if auto-finalized; just verify settled state
    print(f"  H3 status={g2.get('status')} derived={g2.get('derived_status')}")
    report("H3: group-funded path → derived='settled'",
           g2.get("derived_status") == "settled",
           f"derived={g2.get('derived_status')} status={g2.get('status')}")

    # H4: lead /pay with shortfall_mode='lead' is_loan=true → 'repaying'
    lead4, m4a, m4b, gid4 = fresh_trio_with_shortfall("H4")
    sc, g4 = post(f"/groups/{gid4}/pay", {
        "user_id": lead4["id"], "shortfall_mode": "lead", "is_loan": True,
    })
    print(f"  H4 pay HTTP {sc}, derived={g4.get('derived_status') if isinstance(g4, dict) else g4}")
    report("H4: lead loan path → derived='repaying'",
           isinstance(g4, dict) and g4.get("derived_status") == "repaying",
           f"derived={g4.get('derived_status') if isinstance(g4, dict) else g4}")


def main():
    try:
        scenario_A()
        scenario_B()
        result_C = scenario_C()
        if result_C:
            scenario_D(*result_C)
        scenario_E()
        scenario_F()
        scenario_G()
        scenario_H()
    except TestError as e:
        print(f"FATAL TEST SETUP ERROR: {e}")
        import traceback; traceback.print_exc()
    finally:
        print("\n\n=== SUMMARY ===")
        passed = sum(1 for r in RESULTS if r["ok"])
        failed = sum(1 for r in RESULTS if not r["ok"])
        for r in RESULTS:
            print(f"  [{'PASS' if r['ok'] else 'FAIL'}] {r['name']}")
            if not r["ok"] and r["details"]:
                for line in r["details"].splitlines():
                    print(f"            {line}")
        print(f"\nTotal: {passed} passed, {failed} failed, {len(RESULTS)} total")
        sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
