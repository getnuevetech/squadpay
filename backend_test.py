"""
Backend tests for:
  1) NEW Bulk SMS broadcaster — POST /api/admin/bulk-sms/send + GET /api/admin/bulk-sms/history
  2) Paginated broadcasts — GET /api/admin/notifications/broadcasts

Auth: admin@squadpay.us / Letmein@2007#ForReal (super_admin).
Backend URL: from frontend/.env EXPO_PUBLIC_BACKEND_URL.

Important: ensures SMS routing is set to "mock" before sending bulk SMS so
sms_sent == recipient_count, then restores prior mode at the end.
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import uuid
import string
import random
from pathlib import Path

import requests

# ---- Read backend URL from frontend env (per testing rules) ----
def _read_env_url() -> str:
    fp = Path("/app/frontend/.env")
    txt = fp.read_text()
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k in ("EXPO_PUBLIC_BACKEND_URL", "REACT_APP_BACKEND_URL"):
            return v
    raise SystemExit("No backend URL in /app/frontend/.env")


BASE = _read_env_url().rstrip("/") + "/api"
print(f"[setup] BASE = {BASE}")

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"


# ---- tiny test recorder ----
RESULTS: list[tuple[str, bool, str]] = []

def rec(name: str, ok: bool, detail: str = "") -> None:
    flag = "PASS" if ok else "FAIL"
    print(f"  [{flag}] {name}" + (f"  — {detail}" if detail else ""))
    RESULTS.append((name, ok, detail))


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ====== 0) login ======
def admin_login() -> str:
    r = requests.post(
        f"{BASE}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    if r.status_code != 200:
        print("Login failed:", r.status_code, r.text)
        sys.exit(1)
    d = r.json()
    return d.get("access_token") or d.get("token")


# ====== util: set sms routing ======
def set_sms_mode(token: str, mode: str) -> None:
    r = requests.post(
        f"{BASE}/admin/integrations/sms-mode",
        headers=auth_headers(token),
        json={"mode": mode},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"[warn] set sms-mode={mode} failed: {r.status_code} {r.text}")


def get_sms_mode(token: str) -> str:
    r = requests.get(
        f"{BASE}/admin/integrations", headers=auth_headers(token), timeout=30
    )
    if r.status_code == 200:
        d = r.json()
        return (d.get("sms_routing") or {}).get("mode") or "unknown"
    return "unknown"


# ====== seed: ensure we have some users, leads, members, groups ======
def _rand_phone() -> str:
    # avoid +1 to keep it US 10-digit but unique-ish
    return "+1832" + "".join(random.choices(string.digits, k=7))


def register_user(name: str) -> dict:
    r = requests.post(
        f"{BASE}/auth/register",
        json={"name": name},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def verify_phone(user_id: str, phone: str) -> dict:
    r = requests.post(
        f"{BASE}/auth/send-otp",
        json={"user_id": user_id, "phone": phone},
        timeout=30,
    )
    r.raise_for_status()
    r2 = requests.post(
        f"{BASE}/auth/verify-otp",
        json={"user_id": user_id, "phone": phone, "code": "123456"},
        timeout=30,
    )
    r2.raise_for_status()
    return r2.json()


def create_fresh_group(lead_id: str, member_ids: list[str]) -> str:
    body = {
        "lead_id": lead_id,
        "title": f"BulkSMS Test {uuid.uuid4().hex[:6]}",
        "total_amount": 30.0,
        "split_mode": "fast",
        "items": [],
        "tax_amount": 0.0,
        "tip_amount": 0.0,
    }
    r = requests.post(f"{BASE}/groups", json=body, timeout=30)
    r.raise_for_status()
    gid = r.json()["id"]
    for mid in member_ids:
        r2 = requests.post(
            f"{BASE}/groups/{gid}/join",
            json={"user_id": mid},
            timeout=30,
        )
        r2.raise_for_status()
    return gid


def seed_min_squad() -> tuple[str, list[str]]:
    """Make 1 lead + 2 non-lead members, return (group_id, [lead_phone, ...member_phones])."""
    ts = int(time.time())
    lead = register_user(f"BS Lead {ts}")
    m1 = register_user(f"BS Mem1 {ts}")
    m2 = register_user(f"BS Mem2 {ts}")
    lead_phone = _rand_phone()
    m1_phone = _rand_phone()
    m2_phone = _rand_phone()
    verify_phone(lead["id"], lead_phone)
    verify_phone(m1["id"], m1_phone)
    verify_phone(m2["id"], m2_phone)
    gid = create_fresh_group(lead["id"], [m1["id"], m2["id"]])
    return gid, lead["id"], [m1["id"], m2["id"]], [lead_phone, m1_phone, m2_phone]


# ====== TEST 1: Bulk SMS ======
def test_bulk_sms(token: str) -> None:
    print("\n=== TEST 1: Bulk SMS broadcaster ===")

    # 1) 401 without admin bearer
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        json={"message": "hi", "audience": "all_users"},
        timeout=30,
    )
    rec("1) POST /bulk-sms/send without admin bearer → 401",
        r.status_code in (401, 403),
        f"status={r.status_code}")

    H = auth_headers(token)

    # 2) Empty message → 400
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        headers=H,
        json={"message": "   ", "audience": "all_users"},
        timeout=30,
    )
    rec("2) Empty message → 400",
        r.status_code == 400,
        f"status={r.status_code} body={r.text[:120]}")

    # 3) Message > 1000 → 400
    big = "x" * 1001
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        headers=H,
        json={"message": big, "audience": "all_users"},
        timeout=30,
    )
    rec("3) Message > 1000 chars → 400",
        r.status_code == 400,
        f"status={r.status_code} body={r.text[:120]}")

    # 4) audience=vip → 400
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        headers=H,
        json={"message": "hi", "audience": "vip"},
        timeout=30,
    )
    rec("4) audience=vip → 400",
        r.status_code == 400,
        f"status={r.status_code} body={r.text[:120]}")

    # 5) audience=groups w/ empty group_ids → 400 mentioning Squad
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        headers=H,
        json={"message": "hi", "audience": "groups", "group_ids": []},
        timeout=30,
    )
    ok = (r.status_code == 400) and ("squad" in r.text.lower())
    rec("5) audience=groups + empty group_ids → 400 mentioning Squad",
        ok,
        f"status={r.status_code} body={r.text[:200]}")

    # 6) audience=numbers with empty list → 404
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        headers=H,
        json={"message": "hi", "audience": "numbers", "phone_numbers": []},
        timeout=30,
    )
    ok = (r.status_code == 404) and ("no phone" in r.text.lower())
    rec("6) audience=numbers w/ empty list → 404 'No phone numbers resolved...'",
        ok,
        f"status={r.status_code} body={r.text[:200]}")

    # Seed: make sure there's at least 1 fresh squad so leads/members/groups paths exist.
    gid, lead_id, member_ids, phones = seed_min_squad()
    print(f"  [seed] group_id={gid}  lead={lead_id}  members={member_ids}")

    # 7) audience=all_users → 200 with recipient_count > 0
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        headers=H,
        json={"message": "SquadPay test all_users " + uuid.uuid4().hex[:6], "audience": "all_users"},
        timeout=60,
    )
    ok7 = (r.status_code == 200) and (r.json().get("recipient_count", 0) > 0)
    rec("7) audience=all_users → 200 recipient_count > 0",
        ok7,
        f"status={r.status_code} body={r.text[:200]}")
    all_users_count = r.json().get("recipient_count", 0) if r.status_code == 200 else 0
    all_users_sent = r.json().get("sms_sent", 0) if r.status_code == 200 else 0
    all_users_failed = r.json().get("sms_failed", 0) if r.status_code == 200 else 0

    # 8) audience=leads ≤ all_users
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        headers=H,
        json={"message": "SquadPay test leads " + uuid.uuid4().hex[:6], "audience": "leads"},
        timeout=60,
    )
    leads_count = r.json().get("recipient_count", 0) if r.status_code == 200 else -1
    rec("8) audience=leads → 200 and recipient_count <= all_users",
        r.status_code == 200 and 0 <= leads_count <= all_users_count,
        f"status={r.status_code} leads={leads_count} all_users={all_users_count}")

    # 9) audience=members ≤ all_users
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        headers=H,
        json={"message": "SquadPay test members " + uuid.uuid4().hex[:6], "audience": "members"},
        timeout=60,
    )
    members_count = r.json().get("recipient_count", 0) if r.status_code == 200 else -1
    rec("9) audience=members → 200 and recipient_count <= all_users",
        r.status_code == 200 and 0 <= members_count <= all_users_count,
        f"status={r.status_code} members={members_count} all_users={all_users_count}")

    # 10) audience=groups w/ our gid returns just our squad members (3 phones)
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        headers=H,
        json={
            "message": "SquadPay test groups " + uuid.uuid4().hex[:6],
            "audience": "groups",
            "group_ids": [gid],
        },
        timeout=60,
    )
    groups_resp = r.json() if r.status_code == 200 else {}
    groups_count = groups_resp.get("recipient_count", -1)
    # we seeded 3 unique fresh phones
    rec("10) audience=groups w/ known gid → recipient_count == 3 (lead + 2 members)",
        r.status_code == 200 and groups_count == 3,
        f"status={r.status_code} count={groups_count} expected=3")

    # 11) audience=numbers with mixed formats → 1 unique
    r = requests.post(
        f"{BASE}/admin/bulk-sms/send",
        headers=H,
        json={
            "message": "SquadPay test numbers " + uuid.uuid4().hex[:6],
            "audience": "numbers",
            "phone_numbers": ["+12025550123", "2025550123", "(202) 555-0123"],
        },
        timeout=60,
    )
    body_11 = r.json() if r.status_code == 200 else {}
    rec("11) audience=numbers w/ mixed formats → recipient_count == 1",
        r.status_code == 200 and body_11.get("recipient_count") == 1,
        f"status={r.status_code} body={r.text[:200]}")

    # 12) Mock provider counts toward sms_sent for populated audience
    # Use the groups audience response (well-known recipient_count == 3)
    rec("12) Mock SMS → sms_sent == recipient_count and sms_failed == 0 (groups audience, 3 recipients)",
        groups_resp.get("sms_sent") == groups_count and groups_resp.get("sms_failed") == 0,
        f"sms_sent={groups_resp.get('sms_sent')} sms_failed={groups_resp.get('sms_failed')} recipient_count={groups_count}")

    # Also verify for all_users
    rec("12b) Mock SMS → sms_sent == recipient_count (all_users)",
        all_users_sent == all_users_count and all_users_failed == 0,
        f"sms_sent={all_users_sent} sms_failed={all_users_failed} recipient_count={all_users_count}")

    # Record latest sent broadcast id so we can verify it's in history
    latest_broadcast_id = body_11.get("id")

    # 13) GET /admin/bulk-sms/history shape + sort + contains our broadcast
    r = requests.get(
        f"{BASE}/admin/bulk-sms/history",
        headers=H,
        params={"page": 1, "page_size": 20},
        timeout=30,
    )
    body = r.json() if r.status_code == 200 else {}
    keys_ok = set(["items", "page", "page_size", "total", "has_more"]).issubset(set(body.keys()))
    items = body.get("items", []) if isinstance(body, dict) else []
    # Sort DESC by sent_at
    sort_ok = True
    if len(items) >= 2:
        for i in range(len(items) - 1):
            if (items[i].get("sent_at") or "") < (items[i + 1].get("sent_at") or ""):
                sort_ok = False
                break
    contains = any(it.get("id") == latest_broadcast_id for it in items) if latest_broadcast_id else True
    rec("13) GET /bulk-sms/history → shape + sorted DESC + contains latest broadcast",
        r.status_code == 200 and keys_ok and sort_ok and contains,
        f"status={r.status_code} keys_ok={keys_ok} sort_ok={sort_ok} contains={contains} total={body.get('total')}")

    # 14) page_size=5 caps; page=2 returns different slice (or empty + no overlap)
    r1 = requests.get(
        f"{BASE}/admin/bulk-sms/history",
        headers=H, params={"page": 1, "page_size": 5}, timeout=30,
    )
    r2 = requests.get(
        f"{BASE}/admin/bulk-sms/history",
        headers=H, params={"page": 2, "page_size": 5}, timeout=30,
    )
    if r1.status_code == 200 and r2.status_code == 200:
        b1 = r1.json(); b2 = r2.json()
        items1 = b1.get("items", []); items2 = b2.get("items", [])
        ids1 = {it.get("id") for it in items1}
        ids2 = {it.get("id") for it in items2}
        overlap = ids1 & ids2
        cap_ok = len(items1) <= 5 and len(items2) <= 5
        # Page 2 could be empty if total < 6; that's also "no overlap"
        no_overlap = not overlap
        rec("14) page_size=5 caps items.length; page=2 no overlap with page=1",
            cap_ok and no_overlap,
            f"len1={len(items1)} len2={len(items2)} overlap={list(overlap)[:3]} total={b1.get('total')}")
    else:
        rec("14) page_size=5 caps + page=2 no overlap", False,
            f"status1={r1.status_code} status2={r2.status_code}")


# ====== TEST 2: paginated /admin/notifications/broadcasts ======
def test_paginated_broadcasts(token: str) -> None:
    print("\n=== TEST 2: GET /admin/notifications/broadcasts (paginated) ===")

    H = auth_headers(token)

    # First make sure there are at least a few broadcast docs (so paging is meaningful).
    # The Notification Center had its own broadcasts collection (admin_broadcasts).
    # We'll try to ensure at least 6 exist by creating new ones via the notification-center
    # broadcast endpoint. We send tiny in-app-only (no SMS) to leads to avoid noise.
    # Audience "leads" requires at least 1 lead — fine in this env.
    # If creation fails due to schema differences, we just test what's there.
    for i in range(7):
        try:
            requests.post(
                f"{BASE}/admin/notifications/broadcast",
                headers=H,
                json={
                    "message": f"NB pagination seed {i} {uuid.uuid4().hex[:5]}",
                    "audience": {"type": "leads"},
                    "channels": {"in_app": True, "sms": False},
                },
                timeout=30,
            )
        except Exception:
            pass

    # 1) Default call shape
    r = requests.get(f"{BASE}/admin/notifications/broadcasts", headers=H, timeout=30)
    b = r.json() if r.status_code == 200 else {}
    required = {"items", "page", "page_size", "total", "has_more"}
    shape_ok = r.status_code == 200 and required.issubset(b.keys()) and b.get("page") == 1 and b.get("page_size") == 20
    rec("1) Default call: page=1, page_size=20, response shape ok",
        shape_ok,
        f"status={r.status_code} keys={list(b.keys())[:8]} page={b.get('page')} size={b.get('page_size')}")

    total = b.get("total", 0)

    # 2) page_size=5 → items.length <= 5
    r = requests.get(
        f"{BASE}/admin/notifications/broadcasts",
        headers=H, params={"page": 1, "page_size": 5}, timeout=30,
    )
    b1 = r.json() if r.status_code == 200 else {}
    items1 = b1.get("items", [])
    rec("2) page_size=5 → items.length <= 5",
        r.status_code == 200 and len(items1) <= 5,
        f"len={len(items1)} total={total}")

    # 3) page=2 → no overlap with page=1
    r = requests.get(
        f"{BASE}/admin/notifications/broadcasts",
        headers=H, params={"page": 2, "page_size": 5}, timeout=30,
    )
    b2 = r.json() if r.status_code == 200 else {}
    items2 = b2.get("items", [])
    ids1 = {it.get("id") for it in items1}
    ids2 = {it.get("id") for it in items2}
    overlap = ids1 & ids2
    rec("3) page=2 → no overlap with page=1",
        r.status_code == 200 and not overlap,
        f"len2={len(items2)} overlap={list(overlap)[:3]}")

    # 4) has_more correctness
    # On page=1 page_size=1: has_more should be true iff total > 1
    r = requests.get(
        f"{BASE}/admin/notifications/broadcasts",
        headers=H, params={"page": 1, "page_size": 1}, timeout=30,
    )
    bx = r.json() if r.status_code == 200 else {}
    has_more = bx.get("has_more")
    expected_has_more = (bx.get("total", 0) > 1)
    case_a = (has_more is expected_has_more)
    # Last page: page = ceil(total / page_size) with size 5
    if total > 0:
        import math
        last_page = max(1, math.ceil(total / 5))
        r = requests.get(
            f"{BASE}/admin/notifications/broadcasts",
            headers=H, params={"page": last_page, "page_size": 5}, timeout=30,
        )
        bl = r.json() if r.status_code == 200 else {}
        case_b = (bl.get("has_more") is False)
    else:
        case_b = True
    rec("4) has_more true when more pages exist, false on last page",
        case_a and case_b,
        f"case_a(page1size1)={case_a} expected={expected_has_more} got={has_more}; case_b(lastpage)={case_b}")

    # 5) Sort DESC by sent_at
    r = requests.get(
        f"{BASE}/admin/notifications/broadcasts",
        headers=H, params={"page": 1, "page_size": 20}, timeout=30,
    )
    bs = r.json() if r.status_code == 200 else {}
    items = bs.get("items", [])
    sort_ok = True
    if len(items) >= 2:
        if (items[0].get("sent_at") or "") < (items[-1].get("sent_at") or ""):
            sort_ok = False
    rec("5) items[0].sent_at >= items[last].sent_at",
        sort_ok,
        f"len={len(items)} first={items[0].get('sent_at') if items else None} last={items[-1].get('sent_at') if items else None}")


# ====== main ======
def main() -> int:
    token = admin_login()
    print(f"[setup] admin token acquired (len={len(token)})")
    prior_mode = get_sms_mode(token)
    print(f"[setup] prior sms_mode = {prior_mode}")
    set_sms_mode(token, "mock")
    try:
        test_bulk_sms(token)
        test_paginated_broadcasts(token)
    finally:
        # Restore prior mode if known.
        if prior_mode in ("mock", "live"):
            set_sms_mode(token, prior_mode)
            print(f"[teardown] restored sms_mode = {prior_mode}")
        else:
            print("[teardown] could not restore prior sms_mode (unknown). Left as mock.")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print("\n========================================")
    print(f"TOTAL: {len(RESULTS)} | PASS: {passed} | FAIL: {failed}")
    print("========================================")
    if failed:
        print("\nFailed cases:")
        for n, ok, d in RESULTS:
            if not ok:
                print(f"  - {n} :: {d}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
