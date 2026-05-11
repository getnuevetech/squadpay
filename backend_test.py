"""
Phase N backend test — Lead removes a non-contributing member.

Endpoint: POST /api/groups/{group_id}/remove-member
Body:     { "user_id": "<lead_id>", "target_id": "<member_to_remove_id>" }

Acceptance:
  1. Non-lead caller → 403 "lead can remove"
  2. Bill status != "open" → 400 "Members can no longer be removed"
  3. Target = lead → 400 "lead cannot be removed"
  4. Target not in group → 404 "not part of this group"
  5. Target has contributed → 400 "already contributed"
  6. Happy path: 200; member gone; assignments scrubbed; notifications +N (N=orig members)
  7. After removal, contributing member can still contribute and pay normally
"""
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests

BACKEND_URL = os.environ.get(
    "BACKEND_URL",
    "https://joint-pay-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BACKEND_URL}/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

TS = int(time.time())
RESULTS: List[Dict[str, Any]] = []


def record(name: str, ok: bool, info: str = ""):
    RESULTS.append({"name": name, "ok": ok, "info": info})
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {name}" + (f"  -- {info}" if info else ""))


def assert_eq(name: str, actual, expected, tol: float = 0.0):
    if isinstance(expected, float) or isinstance(actual, float):
        ok = abs(float(actual) - float(expected)) <= tol
    else:
        ok = actual == expected
    record(name, ok, "" if ok else f"expected={expected!r} actual={actual!r}")


def assert_contains(name: str, haystack: str, needle: str):
    ok = needle.lower() in (haystack or "").lower()
    record(name, ok, "" if ok else f"expected substring {needle!r} in {haystack!r}")


# ───────────────────────── admin & user helpers ─────────────────────────

def admin_login() -> str:
    r = requests.post(
        f"{API}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"admin login failed: {r.status_code} {r.text}")
    body = r.json()
    tok = body.get("access_token") or body.get("token")
    if not tok:
        raise RuntimeError(f"no token in login response: {body}")
    return tok


def auth_headers(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def register_user(name: str) -> str:
    r = requests.post(f"{API}/auth/register", json={"name": name}, timeout=15)
    r.raise_for_status()
    return r.json()["id"]


def send_otp(user_id: str, phone: str) -> Dict[str, Any]:
    r = requests.post(
        f"{API}/auth/send-otp",
        json={"user_id": user_id, "phone": phone},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def verify_otp(user_id: str, phone: str, code: str = "123456") -> Dict[str, Any]:
    r = requests.post(
        f"{API}/auth/verify-otp",
        json={"user_id": user_id, "phone": phone, "code": code},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"verify-otp failed: {r.status_code} {r.text}")
    return r.json()


def _phone_for(suffix: int, salt: int = 0) -> str:
    """Build a deterministic but per-run unique +1XXXXXXXXXX phone."""
    last4 = f"{(TS + salt) % 10000:04d}"
    sfx = f"{suffix:03d}"
    return f"+1832{last4}{sfx}"


def create_verified_user(name: str, suffix: int, salt: int = 0) -> str:
    uid = register_user(name)
    phone = _phone_for(suffix, salt)
    send_otp(uid, phone)
    resp = verify_otp(uid, phone, "123456")
    return resp.get("user", {}).get("id") or resp.get("id") or uid


def create_fast_group(lead_id: str, title: str, total: float) -> str:
    body = {
        "lead_id": lead_id,
        "title": title,
        "total_amount": total,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r = requests.post(f"{API}/groups", json=body, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"create group failed: {r.status_code} {r.text}")
    return r.json()["id"]


def join_group(gid: str, uid: str):
    r = requests.post(f"{API}/groups/{gid}/join", json={"user_id": uid}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"join failed: {r.status_code} {r.text}")


def get_group(gid: str) -> Dict[str, Any]:
    r = requests.get(f"{API}/groups/{gid}", timeout=20)
    r.raise_for_status()
    return r.json()


def remove_member(gid: str, lead_id: str, target_id: str) -> requests.Response:
    return requests.post(
        f"{API}/groups/{gid}/remove-member",
        json={"user_id": lead_id, "target_id": target_id},
        timeout=20,
    )


def grant_credit(admin_tok: str, user_id: str, amount: float, note: str = "Phase N test") -> Dict[str, Any]:
    r = requests.post(
        f"{API}/admin/users/{user_id}/credits/grant",
        headers=auth_headers(admin_tok),
        json={"amount": amount, "note": note},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"grant credit failed: {r.status_code} {r.text}")
    return r.json()


def contribute_full_credit(gid: str, uid: str) -> Dict[str, Any]:
    """Contribute the user's full remaining share via credit (no Stripe)."""
    r = requests.post(
        f"{API}/groups/{gid}/contribute",
        json={"user_id": uid, "notify_on_settled": False},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"contribute failed: {r.status_code} {r.text}")
    return r.json()


def user_total_in_group(group_doc: Dict[str, Any], uid: str) -> float:
    for p in group_doc.get("per_user") or []:
        if p.get("user_id") == uid:
            return float(p.get("total") or 0.0)
    return 0.0


# ───────────────────────────── main test ────────────────────────────────

def main() -> int:
    print(f"=== Phase N Test against {API} ===")

    # --- admin login (only needed for grant credit + driving paid state) ---
    try:
        tok = admin_login()
        record("admin login", True)
    except Exception as e:
        record("admin login", False, str(e))
        return 1

    # ============================================================
    # Setup A: lead + 2 members in a fresh fast-split group.
    # Used for scenarios 1, 3, 4, 5, 6, 7.
    # ============================================================
    try:
        lead_id = create_verified_user(f"Lead N{TS}", 100)
        m1_id = create_verified_user(f"Alice N{TS}", 101)
        m2_id = create_verified_user(f"Bob N{TS}", 102)
        outsider_id = create_verified_user(f"Carl N{TS}", 103)
        record("setupA. created lead + 2 members + outsider", True,
               f"lead={lead_id} m1={m1_id} m2={m2_id} outsider={outsider_id}")
    except Exception as e:
        record("setupA. created lead + 2 members + outsider", False, str(e))
        return 1

    # Create the main test group ($60 fast-split → ~$20 each + fees)
    try:
        gid = create_fast_group(lead_id, f"Phase N Main Bill {TS}", 60.0)
        join_group(gid, m1_id)
        join_group(gid, m2_id)
        record("setupA. created $60 fast-split group + joined m1, m2", True, f"gid={gid}")
    except Exception as e:
        record("setupA. created $60 fast-split group + joined m1, m2", False, str(e))
        return 1

    # ------------------------------------------------------------
    # Scenario 1 — Non-lead caller → 403 "lead can remove"
    # ------------------------------------------------------------
    r = remove_member(gid, lead_id=m1_id, target_id=m2_id)
    assert_eq("1a. non-lead caller status", r.status_code, 403)
    try:
        d = r.json().get("detail") or ""
    except Exception:
        d = r.text
    assert_contains("1b. detail mentions 'lead can remove'", d, "lead can remove")

    # ------------------------------------------------------------
    # Scenario 3 — Target = lead → 400 "lead cannot be removed"
    # ------------------------------------------------------------
    r = remove_member(gid, lead_id=lead_id, target_id=lead_id)
    assert_eq("3a. target=lead status", r.status_code, 400)
    try:
        d = r.json().get("detail") or ""
    except Exception:
        d = r.text
    assert_contains("3b. detail mentions 'lead cannot be removed'", d, "lead cannot be removed")

    # ------------------------------------------------------------
    # Scenario 4 — Target not in group → 404 "not part of this group"
    # ------------------------------------------------------------
    r = remove_member(gid, lead_id=lead_id, target_id=outsider_id)
    assert_eq("4a. target-not-member status", r.status_code, 404)
    try:
        d = r.json().get("detail") or ""
    except Exception:
        d = r.text
    assert_contains("4b. detail mentions 'not part of this group'", d, "not part of this group")

    # ------------------------------------------------------------
    # Scenario 5 — Target has contributed → 400 "already contributed"
    # First find m1's share, grant exact credit, contribute partial.
    # ------------------------------------------------------------
    grp_now = get_group(gid)
    m1_share = user_total_in_group(grp_now, m1_id)
    print(f"  m1 share (with fees) = ${m1_share:.2f}")
    # Grant a small partial credit so m1 makes a tiny but non-zero contribution.
    try:
        partial = round(min(5.0, max(0.5, m1_share / 5.0)), 2)
        grant_credit(tok, m1_id, partial, note="Phase N partial contribute")
        c_resp = requests.post(
            f"{API}/groups/{gid}/contribute",
            json={"user_id": m1_id, "amount": partial, "notify_on_settled": False},
            timeout=20,
        )
        record("5a. m1 partial credit-only contribute returns 200",
               c_resp.status_code == 200,
               f"{c_resp.status_code} {c_resp.text[:200]}")
        if c_resp.status_code == 200:
            body = c_resp.json()
            record("5b. credit_only path taken (checkout_required=False)",
                   body.get("checkout_required") is False and body.get("credit_only") is True,
                   f"resp={body}")
    except Exception as e:
        record("5a. m1 partial credit-only contribute returns 200", False, str(e))

    r = remove_member(gid, lead_id=lead_id, target_id=m1_id)
    assert_eq("5c. target contributed status", r.status_code, 400)
    try:
        d = r.json().get("detail") or ""
    except Exception:
        d = r.text
    assert_contains("5d. detail mentions 'already contributed'", d, "already contributed")

    # ------------------------------------------------------------
    # Scenario 6 — Happy path: remove m2 (no contribution).
    # ------------------------------------------------------------
    grp_before = get_group(gid)
    original_member_count = len(grp_before.get("members") or [])
    notif_before = len(grp_before.get("notifications") or [])
    record("6.pre. orig member count == 3", original_member_count == 3,
           f"got {original_member_count}")
    print(f"  notifications before = {notif_before}, member_count = {original_member_count}")

    r = remove_member(gid, lead_id=lead_id, target_id=m2_id)
    assert_eq("6a. happy path status", r.status_code, 200)
    if r.status_code == 200:
        body = r.json()
        members_after = body.get("members") or []
        member_ids_after = {m.get("user_id") for m in members_after}
        record("6b. m2 no longer in response.members",
               m2_id not in member_ids_after,
               f"members={member_ids_after}")
        record("6c. lead + m1 still in response.members",
               lead_id in member_ids_after and m1_id in member_ids_after,
               f"members={member_ids_after}")
        assignments_after = body.get("assignments") or []
        rows_for_m2 = [a for a in assignments_after if a.get("user_id") == m2_id]
        record("6d. no assignment rows for removed user",
               len(rows_for_m2) == 0,
               f"got {rows_for_m2}")
        notifs_after = body.get("notifications") or []
        gain = len(notifs_after) - notif_before
        assert_eq("6e. notifications grew by exactly N (orig member count)",
                  gain, original_member_count)
        # Inspect the *new* notifications (last N entries)
        new_notifs = notifs_after[-original_member_count:] if original_member_count > 0 else []
        kinds_ok = all(n.get("kind") == "member_removed" for n in new_notifs)
        record("6f. all new notifications have kind='member_removed'",
               kinds_ok and len(new_notifs) == original_member_count,
               f"new_kinds={[n.get('kind') for n in new_notifs]}")
        target_user_ids = {n.get("user_id") for n in new_notifs}
        expected_recipients = {lead_id, m1_id, m2_id}
        record("6g. one notification per ORIGINAL member (incl. removed)",
               target_user_ids == expected_recipients,
               f"got={target_user_ids} expected={expected_recipients}")
        # Recompute math: per_user must only have 2 entries (lead + m1).
        per_user = body.get("per_user") or []
        record("6h. per_user has 2 rows after removal",
               len(per_user) == 2,
               f"per_user_ids={[p.get('user_id') for p in per_user]}")
        # No 5xx anywhere → recompute math executed without error.
        total_after = float(body.get("total_amount") or 0.0)
        record("6i. group total_amount unchanged ($60)",
               abs(total_after - 60.0) < 0.5,
               f"total_after={total_after}")

    # ------------------------------------------------------------
    # Scenario 7 — After removal, contributing member can still
    # contribute and pay normally (bill settles).
    # ------------------------------------------------------------
    grp_after = get_group(gid)
    m1_remaining = 0.0
    for p in grp_after.get("per_user") or []:
        if p.get("user_id") == m1_id:
            m1_remaining = max(0.0, float(p.get("total") or 0.0) - float(p.get("contributed") or 0.0))
    lead_remaining = 0.0
    for p in grp_after.get("per_user") or []:
        if p.get("user_id") == lead_id:
            lead_remaining = max(0.0, float(p.get("total") or 0.0) - float(p.get("contributed") or 0.0))
    print(f"  m1 remaining = ${m1_remaining:.2f}, lead remaining = ${lead_remaining:.2f}")

    # Grant credits to m1 and lead so we can settle the bill purely via credits
    # (no Stripe Checkout needed). Slightly over to avoid rounding misses.
    try:
        grant_credit(tok, m1_id, round(m1_remaining + 1.0, 2), note="Phase N final m1")
        grant_credit(tok, lead_id, round(lead_remaining + 1.0, 2), note="Phase N final lead")
        record("7a. granted credits for m1 + lead", True)
    except Exception as e:
        record("7a. granted credits for m1 + lead", False, str(e))

    # m1 contributes full remaining via credit_only
    try:
        c1 = requests.post(
            f"{API}/groups/{gid}/contribute",
            json={"user_id": m1_id, "notify_on_settled": False},
            timeout=20,
        )
        record("7b. m1 contribute (post-removal) returns 200",
               c1.status_code == 200,
               f"{c1.status_code} {c1.text[:160]}")
        if c1.status_code == 200:
            b1 = c1.json()
            record("7c. m1 contribute used credit_only path",
                   b1.get("checkout_required") is False,
                   f"resp_keys={list(b1.keys())}")
    except Exception as e:
        record("7b. m1 contribute (post-removal) returns 200", False, str(e))

    # lead contributes full remaining via credit_only → should auto-flip to paid
    try:
        c2 = requests.post(
            f"{API}/groups/{gid}/contribute",
            json={"user_id": lead_id, "notify_on_settled": False},
            timeout=20,
        )
        record("7d. lead contribute (post-removal) returns 200",
               c2.status_code == 200,
               f"{c2.status_code} {c2.text[:160]}")
    except Exception as e:
        record("7d. lead contribute (post-removal) returns 200", False, str(e))

    # Verify bill auto-flipped to paid
    final_grp = get_group(gid)
    record("7e. group.status flipped to 'paid' (or beyond)",
           final_grp.get("status") in ("paid", "closed"),
           f"status={final_grp.get('status')}, derived={final_grp.get('derived_status')}")

    # ------------------------------------------------------------
    # Scenario 2 — Bill status != "open" → 400 "Members can no longer be removed"
    # Reuse the now-paid group; try to remove m1 (should fail with 400).
    # ------------------------------------------------------------
    r = remove_member(gid, lead_id=lead_id, target_id=m1_id)
    assert_eq("2a. paid bill, remove blocked status", r.status_code, 400)
    try:
        d = r.json().get("detail") or ""
    except Exception:
        d = r.text
    assert_contains("2b. detail mentions 'Members can no longer be removed'",
                    d, "members can no longer be removed")

    # ============================================================
    # SUMMARY
    # ============================================================
    print()
    print("=" * 60)
    passed = sum(1 for x in RESULTS if x["ok"])
    failed = sum(1 for x in RESULTS if not x["ok"])
    print(f"TOTAL: {passed} pass / {failed} fail")
    if failed:
        print("\nFailures:")
        for x in RESULTS:
            if not x["ok"]:
                print(f"  - {x['name']}  {x['info']}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
