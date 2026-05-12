"""
Backend test for the new Credit Rules engine (Batch June 2025).

Covers cases 1–20 from /app/test_result.md → "Credit Rules engine":
  1) Auth gating on admin endpoints.
  2–7) CRUD validation (empty name, empty message, bad criteria.type, missing n,
       bad reward.value, percentage > 100).
  8) Create a valid first_time rule.
  9) PATCH active=false flips status (visible via GET).
 10) DELETE removes the rule (subsequent GET excludes it).
 11) Engine: active first_time rule awards on user's 1st contribution
     (pending status + source_group_id).
 12) Engine: same rule does NOT re-award on 2nd contribution.
 13) Engine: inactive rule does NOT award.
 14–15) pct_user_no_fees rule with value=10 cap=2 → award is capped at 2.
 16) Stacking: two matching rules — default = only first; bidirectional
     stackable_with → both.
 17) Lifecycle: when source group settles, pending credits → active.
 18) Refund: refund-overpayment forfeits the user's credit from that squad.
 19) GET /users/{uid}/credits-summary shape.
 20) GET /contribute/status/{session_id} returns `awarded_credits` field.
"""

import os
import sys
import time
import json
import requests
from typing import List, Tuple

BASE = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://joint-pay-1.preview.emergentagent.com",
).rstrip("/") + "/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

results: List[Tuple[str, bool, str]] = []


def record(case: str, ok: bool, detail: str = "") -> None:
    results.append((case, ok, detail))
    sym = "PASS" if ok else "FAIL"
    print(f"  [{sym}] {case}: {detail}"[:400])


def jpost(path, body=None, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = requests.post(BASE + path, headers=h,
                      data=json.dumps(body or {}), timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text}


def jpatch(path, body=None, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = requests.patch(BASE + path, headers=h,
                       data=json.dumps(body or {}), timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text}


def jget(path, token=None):
    h = {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = requests.get(BASE + path, headers=h, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text}


def jdelete(path, token=None):
    h = {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = requests.delete(BASE + path, headers=h, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text}


def admin_login():
    sc, j = jpost("/admin/auth/login",
                  {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert sc == 200, f"Admin login failed: {sc} {j}"
    return j["token"]


def ensure_sms_mock(token):
    sc, _ = jpost("/admin/integrations/sms-mode", {"mode": "mock"}, token=token)
    assert sc == 200


def register_and_verify(name, phone):
    sc, j = jpost("/auth/register", {"name": name})
    assert sc == 200, f"register failed: {sc} {j}"
    user = j
    sc, _ = jpost("/auth/send-otp",
                  {"user_id": user["id"], "phone": phone})
    assert sc == 200, f"send-otp failed: {sc}"
    sc, j = jpost("/auth/verify-otp",
                  {"user_id": user["id"], "phone": phone, "code": "123456"})
    assert sc == 200, f"verify-otp failed: {sc} {j}"
    return j


def grant_credit(token, user_id, amount):
    sc, j = jpost(f"/admin/users/{user_id}/credits/grant",
                  {"amount": amount, "note": "test-engine"}, token=token)
    assert sc == 200, f"grant failed: {sc} {j}"
    return j


def create_fast_group(lead_id, title, total_amount):
    sc, j = jpost("/groups", {
        "lead_id": lead_id, "title": title,
        "total_amount": total_amount, "split_mode": "fast",
        "tax": 0.0, "tip": 0.0, "items": [],
    })
    assert sc == 200, f"create group failed: {sc} {j}"
    return j


def join_group(gid, user_id):
    sc, j = jpost(f"/groups/{gid}/join",
                  {"user_id": user_id, "joined_via": "code"})
    assert sc == 200, f"join failed: {sc} {j}"
    return j


def contribute_credit_only(gid, user_id, amount):
    return jpost(f"/groups/{gid}/contribute",
                 {"user_id": user_id, "amount": amount,
                  "notify_on_settled": False})


def delete_all_rules(token):
    sc, lst = jget("/admin/credit-rules?page=1&page_size=200", token=token)
    for r in lst.get("items", []):
        jdelete(f"/admin/credit-rules/{r['id']}", token=token)


def safe_create_rule(token, payload):
    """POST creates the rule. Even when the response is 500 (known bug:
    `_id` ObjectId leaks into the response body), the doc IS inserted, so we
    fall back to a listing lookup by name to recover the rule_id. Returns
    (status_code_from_post, rule_doc_or_None)."""
    sc, body = jpost("/admin/credit-rules", payload, token=token)
    if sc == 200 and isinstance(body, dict) and body.get("id"):
        return sc, body
    # Fallback: list and find by name
    sc_l, lst = jget("/admin/credit-rules?page=1&page_size=200", token=token)
    if sc_l == 200:
        for r in lst.get("items", []):
            if r.get("name") == payload.get("name"):
                return sc, r
    return sc, None


def main():
    print(f"== Credit Rules engine integration test — BASE={BASE} ==")
    token = admin_login()
    ensure_sms_mock(token)

    # ---- CASE 1: Auth gating ----
    sc_get, _ = jget("/admin/credit-rules")
    sc_post, _ = jpost("/admin/credit-rules", {"name": "x"})
    sc_patch, _ = jpatch("/admin/credit-rules/anything", {"active": False})
    sc_del, _ = jdelete("/admin/credit-rules/anything")
    record("Case 1 (auth gating)",
           sc_get == 401 and sc_post == 401 and sc_patch == 401 and sc_del == 401,
           f"GET={sc_get} POST={sc_post} PATCH={sc_patch} DELETE={sc_del}")

    # ---- CASES 2-7: Validation ----
    base = {
        "name": "Test Rule", "active": True, "message": "hi",
        "criteria": {"type": "first_time"},
        "reward": {"type": "fixed", "value": 1.0},
    }
    p = dict(base); p["name"] = "  "
    sc, j = jpost("/admin/credit-rules", p, token=token)
    record("Case 2 (empty name → 400)", sc == 400,
           f"sc={sc} detail={j.get('detail')!r}")

    p = dict(base); p["message"] = "  "
    sc, j = jpost("/admin/credit-rules", p, token=token)
    record("Case 3 (empty message → 400)", sc == 400,
           f"sc={sc} detail={j.get('detail')!r}")

    p = dict(base); p["criteria"] = {"type": "vip"}
    sc, j = jpost("/admin/credit-rules", p, token=token)
    record("Case 4 (criteria.type='vip' → 400)", sc == 400,
           f"sc={sc} detail={j.get('detail')!r}")

    p = dict(base); p["criteria"] = {"type": "nth_contribution"}
    sc, j = jpost("/admin/credit-rules", p, token=token)
    record("Case 5 (nth_contribution missing n → 400)", sc == 400,
           f"sc={sc} detail={j.get('detail')!r}")

    p = dict(base); p["reward"] = {"type": "fixed", "value": 0}
    sc, j = jpost("/admin/credit-rules", p, token=token)
    record("Case 6 (fixed value <= 0 → 400)", sc == 400,
           f"sc={sc} detail={j.get('detail')!r}")

    p = dict(base); p["reward"] = {"type": "pct_user_no_fees", "value": 101}
    sc, j = jpost("/admin/credit-rules", p, token=token)
    record("Case 7 (pct value > 100 → 400)", sc == 400,
           f"sc={sc} detail={j.get('detail')!r}")

    # ---- CASE 8: Valid POST ----
    valid = {
        "name": "First-time gift", "active": True,
        "message": "Welcome — enjoy a credit on us",
        "criteria": {"type": "first_time"},
        "reward": {"type": "fixed", "value": 3},
        "expiry_days": None, "stackable_with": [],
    }
    sc, doc = jpost("/admin/credit-rules", valid, token=token)
    # Workaround for known bug: even on 500, rule is inserted; fall back to listing.
    if sc != 200 or not (doc and doc.get("id")):
        sc_l, lst = jget("/admin/credit-rules?page=1&page_size=200", token=token)
        if sc_l == 200:
            doc = next((r for r in lst.get("items", [])
                        if r.get("name") == valid["name"]), {}) or {}
    rule8 = (doc or {}).get("id", "")
    record("Case 8 (POST valid rule → 200)",
           sc == 200 and rule8.startswith("cr_rule_")
           and isinstance(doc, dict) and doc.get("active") is True,
           f"sc={sc} id={rule8} (server ALSO inserts the rule; 500 is from "
           f"JSON-serializing ObjectId leaked from insert_one mutation)")

    # ---- CASE 9: PATCH active=false ----
    sc_p, patched = jpatch(f"/admin/credit-rules/{rule8}",
                           {"active": False}, token=token)
    sc_l, lst = jget("/admin/credit-rules?page=1&page_size=200", token=token)
    found = next((r for r in lst.get("items", []) if r.get("id") == rule8), None)
    record("Case 9 (PATCH active=false visible via GET)",
           sc_p == 200 and patched.get("active") is False
           and sc_l == 200 and found is not None
           and found.get("active") is False,
           f"PATCH sc={sc_p} active={patched.get('active')} "
           f"LIST sc={sc_l} found_active={found and found.get('active')}")

    # ---- CASE 10: DELETE ----
    sc_d, _ = jdelete(f"/admin/credit-rules/{rule8}", token=token)
    sc_l2, lst2 = jget("/admin/credit-rules?page=1&page_size=200", token=token)
    still = any(r.get("id") == rule8 for r in lst2.get("items", []))
    record("Case 10 (DELETE removes rule)",
           sc_d == 200 and not still,
           f"DELETE sc={sc_d} still_there={still}")

    # ---- Cleanup before engine tests ----
    delete_all_rules(token)

    # =================================================================
    # ENGINE INTEGRATION (Cases 11–18)
    # =================================================================
    ts = int(time.time())
    sfx = ts % 100000

    # Alice + Bob (stub member)
    alice = register_and_verify(f"AliceCR{ts}",
                                f"+18320{sfx:05d}1")
    print(f"  alice.id={alice['id']}")
    bob = register_and_verify(f"BobCR{ts}",
                              f"+18320{sfx:05d}2")
    grant_credit(token, alice["id"], 200.0)

    # Create first_time fixed $3 rule (workaround for ObjectId-500 bug)
    sc_r, r_ft = safe_create_rule(token, {
        "name": "FT Welcome", "active": True, "message": "Welcome credit",
        "criteria": {"type": "first_time"},
        "reward": {"type": "fixed", "value": 3},
        "stackable_with": [],
    })
    assert r_ft and r_ft.get("id"), f"R_FT create failed: sc={sc_r} body={r_ft}"
    rule_ft_id = r_ft["id"]

    # ---- Case 11: first_time rule awards on 1st contribution ----
    g1 = create_fast_group(alice["id"], f"G1-{ts}", 4.0)
    join_group(g1["id"], bob["id"])
    sc, c1 = contribute_credit_only(g1["id"], alice["id"], 2.0)
    if sc != 200:
        record("Case 11 (first-time awards on 1st)", False,
               f"contribute sc={sc} body={c1}")
    else:
        awarded = c1.get("awarded_credits") or []
        sc_s, summary = jget(f"/users/{alice['id']}/credits-summary")
        pending_rows = [
            r for r in summary.get("items", [])
            if r.get("status") == "pending"
            and r.get("source_group_id") == g1["id"]
            and abs(float(r.get("amount") or 0) - 3.0) < 0.001
        ]
        ok11 = len(awarded) >= 1 or len(pending_rows) >= 1
        record("Case 11 (first-time awards on 1st contribution)", ok11,
               f"resp.awarded={len(awarded)} pending_g1=${len(pending_rows)} "
               f"summary.pending={summary.get('pending')}")

    # ---- Case 12: Same user 2nd contrib → no award ----
    g2 = create_fast_group(alice["id"], f"G2-{ts}", 4.0)
    join_group(g2["id"], bob["id"])
    sc, c2 = contribute_credit_only(g2["id"], alice["id"], 2.0)
    awarded2 = c2.get("awarded_credits") or []
    sc_s, summary2 = jget(f"/users/{alice['id']}/credits-summary")
    new_from_g2 = [r for r in summary2.get("items", [])
                   if r.get("source_group_id") == g2["id"]
                   and r.get("rule_id") == rule_ft_id]
    record("Case 12 (first_time does not re-award)",
           sc == 200 and len(awarded2) == 0 and len(new_from_g2) == 0,
           f"sc={sc} resp.awarded={len(awarded2)} g2_ft_credits={len(new_from_g2)}")

    # ---- Case 13: Pause rule, new user, new group → no award ----
    sc_p, _ = jpatch(f"/admin/credit-rules/{rule_ft_id}",
                     {"active": False}, token=token)
    dan = register_and_verify(f"DanCR{ts}", f"+18320{sfx:05d}3")
    grant_credit(token, dan["id"], 50.0)
    g3 = create_fast_group(dan["id"], f"G3-{ts}", 4.0)
    join_group(g3["id"], bob["id"])
    sc, c3 = contribute_credit_only(g3["id"], dan["id"], 2.0)
    awarded3 = c3.get("awarded_credits") or []
    sc_s, dan_sum = jget(f"/users/{dan['id']}/credits-summary")
    # Only rule-awarded credits count here (admin grant remains in wallet)
    rule_awarded_for_dan = [r for r in dan_sum.get("items", [])
                            if r.get("rule_id")]
    record("Case 13 (paused rule does not award)",
           sc_p == 200 and sc == 200 and len(awarded3) == 0
           and len(rule_awarded_for_dan) == 0,
           f"awarded={len(awarded3)} rule_awarded_rows={len(rule_awarded_for_dan)} "
           f"dan.pending={dan_sum.get('pending')} "
           f"dan.available={dan_sum.get('available')}")

    # ---- Cases 14/15: pct_user_no_fees value=10 cap=2 ----
    delete_all_rules(token)
    sc_r, r_pct = safe_create_rule(token, {
        "name": "Pct cap", "active": True, "message": "Capped",
        "criteria": {"type": "first_time"},
        "reward": {"type": "pct_user_no_fees", "value": 10, "cap": 2},
        "stackable_with": [],
    })
    assert r_pct and r_pct.get("id"), f"R_PCT failed: sc={sc_r} body={r_pct}"

    eve = register_and_verify(f"EveCR{ts}", f"+18320{sfx:05d}4")
    grant_credit(token, eve["id"], 200.0)
    g4 = create_fast_group(eve["id"], f"G4-{ts}", 100.0)
    join_group(g4["id"], bob["id"])
    sc, c4 = contribute_credit_only(g4["id"], eve["id"], 50.0)
    awarded4 = c4.get("awarded_credits") or []
    sc_s, eve_sum = jget(f"/users/{eve['id']}/credits-summary")
    pending_eve = [r for r in eve_sum.get("items", [])
                   if r.get("source_group_id") == g4["id"]]
    amt = pending_eve[0].get("amount") if pending_eve else None
    record("Case 14/15 (pct_user_no_fees 10% on $50, cap=2 → $2)",
           sc == 200 and len(awarded4) >= 1
           and amt is not None and abs(float(amt) - 2.0) < 0.001,
           f"awarded={len(awarded4)} pending_amount={amt}")

    # ---- Case 16a: Two rules, no stacking → only one awards ----
    delete_all_rules(token)
    sc_r, ra = safe_create_rule(token, {
        "name": "Stack-A", "active": True, "message": "A",
        "criteria": {"type": "first_time"},
        "reward": {"type": "fixed", "value": 3},
        "stackable_with": [],
    })
    assert ra and ra.get("id"), f"Stack-A failed: sc={sc_r}"
    rule_a_id = ra["id"]
    time.sleep(0.1)
    sc_r, rb = safe_create_rule(token, {
        "name": "Stack-B", "active": True, "message": "B",
        "criteria": {"type": "first_time"},
        "reward": {"type": "fixed", "value": 2},
        "stackable_with": [],
    })
    assert rb and rb.get("id"), f"Stack-B failed: sc={sc_r}"
    rule_b_id = rb["id"]

    georgia = register_and_verify(f"GeoCR{ts}", f"+18320{sfx:05d}5")
    grant_credit(token, georgia["id"], 200.0)
    g5 = create_fast_group(georgia["id"], f"G5-{ts}", 4.0)
    join_group(g5["id"], bob["id"])
    sc, c5 = contribute_credit_only(g5["id"], georgia["id"], 2.0)
    awarded5 = c5.get("awarded_credits") or []
    sc_s, geo_sum = jget(f"/users/{georgia['id']}/credits-summary")
    geo_g5 = [r for r in geo_sum.get("items", [])
              if r.get("source_group_id") == g5["id"] and r.get("rule_id")]
    record("Case 16a (no stackable_with → only first rule awards)",
           sc == 200 and len(awarded5) == 1 and len(geo_g5) == 1,
           f"awarded={len(awarded5)} pending_g5={len(geo_g5)} "
           f"first_rule={geo_g5[0].get('rule_id') if geo_g5 else None}")

    # ---- Case 16b: bidirectional stackable_with → both award ----
    jpatch(f"/admin/credit-rules/{rule_a_id}",
           {"stackable_with": [rule_b_id]}, token=token)
    jpatch(f"/admin/credit-rules/{rule_b_id}",
           {"stackable_with": [rule_a_id]}, token=token)
    harry = register_and_verify(f"HarCR{ts}", f"+18320{sfx:05d}6")
    grant_credit(token, harry["id"], 200.0)
    g6 = create_fast_group(harry["id"], f"G6-{ts}", 4.0)
    join_group(g6["id"], bob["id"])
    sc, c6 = contribute_credit_only(g6["id"], harry["id"], 2.0)
    awarded6 = c6.get("awarded_credits") or []
    sc_s, har_sum = jget(f"/users/{harry['id']}/credits-summary")
    har_g6 = [r for r in har_sum.get("items", [])
              if r.get("source_group_id") == g6["id"] and r.get("rule_id")]
    rule_ids = {r.get("rule_id") for r in har_g6}
    record("Case 16b (bidirectional stackable_with → both rules award)",
           sc == 200 and len(awarded6) == 2
           and {rule_a_id, rule_b_id} <= rule_ids,
           f"awarded={len(awarded6)} pending_g6={len(har_g6)} rule_ids={rule_ids}")

    # ---- Case 17: Settle group → pending → active ----
    delete_all_rules(token)
    sc_r, _ = safe_create_rule(token, {
        "name": "FT-Settle", "active": True, "message": "settle",
        "criteria": {"type": "first_time"},
        "reward": {"type": "fixed", "value": 3},
    })
    assert _ and _.get("id"), f"FT-Settle failed: sc={sc_r}"
    ivan = register_and_verify(f"IvanCR{ts}", f"+18320{sfx:05d}7")
    grant_credit(token, ivan["id"], 200.0)
    g7 = create_fast_group(ivan["id"], f"G7-{ts}", 4.0)
    join_group(g7["id"], bob["id"])
    sc, c7 = contribute_credit_only(g7["id"], ivan["id"], 2.0)
    sc_s, ivan_sum = jget(f"/users/{ivan['id']}/credits-summary")
    pending_ivan_pre = [r for r in ivan_sum.get("items", [])
                        if r.get("source_group_id") == g7["id"]
                        and r.get("status") == "pending"]
    pre_ok = sc == 200 and len(pending_ivan_pre) == 1
    # Grant Bob credit so he can credit-only contribute his share too
    grant_credit(token, bob["id"], 50.0)
    sc2, c7b = contribute_credit_only(g7["id"], bob["id"], 2.0)
    sc_g, g7_after = jget(f"/groups/{g7['id']}")
    sc_s, ivan_sum2 = jget(f"/users/{ivan['id']}/credits-summary")
    active_ivan = [r for r in ivan_sum2.get("items", [])
                   if r.get("source_group_id") == g7["id"]
                   and r.get("status") == "active"]
    record("Case 17 (settle promotes pending→active)",
           pre_ok and sc2 == 200
           and g7_after.get("status") == "paid"
           and len(active_ivan) == 1,
           f"pre_pending={len(pending_ivan_pre)} "
           f"bob_contrib_sc={sc2} g7.status={g7_after.get('status')} "
           f"post_active={len(active_ivan)}")

    # ---- Case 18: Refund-overpayment → forfeited ----
    sc_r, settle_rule = safe_create_rule(token, {
        "name": "FT-Forfeit", "active": True, "message": "forfeit",
        "criteria": {"type": "first_time"},
        "reward": {"type": "fixed", "value": 3},
    })
    assert settle_rule and settle_rule.get("id"), f"FT-Forfeit failed: sc={sc_r}"
    jack = register_and_verify(f"JackCR{ts}", f"+18320{sfx:05d}8")
    grant_credit(token, jack["id"], 200.0)
    g8 = create_fast_group(jack["id"], f"G8-{ts}", 4.0)
    join_group(g8["id"], bob["id"])
    # Jack contributes full $4 -> overpays his $2 share
    sc, c8 = contribute_credit_only(g8["id"], jack["id"], 4.0)
    sc_g, g8_after = jget(f"/groups/{g8['id']}")
    settled = sc == 200 and g8_after.get("status") == "paid"
    sc_s, jack_sum_pre = jget(f"/users/{jack['id']}/credits-summary")
    jack_g8_active_pre = [r for r in jack_sum_pre.get("items", [])
                          if r.get("source_group_id") == g8["id"]
                          and r.get("status") == "active"]

    sc_ref, refund_body = jpost(
        f"/groups/{g8['id']}/refund-overpayment",
        {"user_id": jack["id"]})
    sc_s, jack_sum_post = jget(f"/users/{jack['id']}/credits-summary")
    jack_g8_post = [r for r in jack_sum_post.get("items", [])
                    if r.get("source_group_id") == g8["id"]
                    and r.get("rule_id")]
    statuses_post = [r.get("status") for r in jack_g8_post]
    forfeited_ok = bool(jack_g8_post) and all(
        s == "forfeited" for s in statuses_post)
    record("Case 18 (refund-overpayment → credits forfeited)",
           settled and sc_ref == 200 and forfeited_ok,
           f"g8.status={g8_after.get('status')} pre_active={len(jack_g8_active_pre)} "
           f"refund_sc={sc_ref} refund_keys="
           f"{list(refund_body.keys()) if isinstance(refund_body, dict) else None} "
           f"statuses_after={statuses_post}")

    # ---- Case 19: credits-summary shape ----
    sc, summary19 = jget(f"/users/{alice['id']}/credits-summary")
    required = {"pending", "available", "consumed_lifetime", "items"}
    shape_ok = (sc == 200 and required <= set(summary19.keys())
                and isinstance(summary19.get("items"), list)
                and isinstance(summary19.get("pending"), (int, float))
                and isinstance(summary19.get("available"), (int, float))
                and isinstance(summary19.get("consumed_lifetime"), (int, float)))
    record("Case 19 (credits-summary shape)",
           shape_ok,
           f"sc={sc} keys={sorted(summary19.keys())} "
           f"pending={summary19.get('pending')} "
           f"available={summary19.get('available')} "
           f"items_len={len(summary19.get('items') or [])}")

    # ---- Case 20: GET /contribute/status returns awarded_credits ----
    kira = register_and_verify(f"KiraCR{ts}", f"+18320{sfx:05d}9")
    g9 = create_fast_group(kira["id"], f"G9-{ts}", 4.0)
    join_group(g9["id"], bob["id"])
    sc, cresp = jpost(f"/groups/{g9['id']}/contribute", {
        "user_id": kira["id"], "amount": 2.0, "notify_on_settled": False,
        "origin_url": "https://joint-pay-1.preview.emergentagent.com",
    })
    if sc != 200 or not cresp.get("session_id"):
        record("Case 20 (status returns awarded_credits)", False,
               f"contribute sc={sc} body_keys="
               f"{list(cresp.keys()) if isinstance(cresp, dict) else None}")
    else:
        sid = cresp["session_id"]
        sc_s, status_body = jget(f"/contribute/status/{sid}")
        has = isinstance(status_body, dict) and "awarded_credits" in status_body
        is_list = isinstance(status_body.get("awarded_credits"), list)
        record("Case 20 (status returns awarded_credits field)",
               sc_s == 200 and has and is_list,
               f"sc={sc_s} has_field={has} is_list={is_list} "
               f"value={status_body.get('awarded_credits') if has else None}")

    # ---- Summary ----
    print("\n=== Credit Rules engine test summary ===")
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"  Passed: {passed}/{len(results)}")
    for case, ok, detail in results:
        if not ok:
            print(f"  [FAIL] {case}: {detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
