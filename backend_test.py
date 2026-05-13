"""Phase A — SquadPay admin console: total_contributed + audit-log filters + CSV export.

Covers (per review request):
  A) total_contributed happy path (list + detail)
  B) total_contributed includes credit-applied amounts
  C) total_contributed includes repayments
  D) audit-log substring + case-insensitive action filter; `total` field
  E) audit-log date_from / date_to range filter
  F) audit-log destructive=true/false filter
  G) audit-log CSV export — primary test
  H) RBAC (401 without token; support role consistency between /audit-log and export)
  I) Regression smoke (metrics + users + native PI)
"""
from __future__ import annotations
import asyncio
import datetime as dt
import io
import csv
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://joint-pay-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client[DB_NAME]

results: List[Tuple[str, bool, str]] = []
failures_verbatim: List[str] = []


def record(name: str, ok: bool, info: str = ""):
    results.append((name, ok, info))
    status = "✅" if ok else "❌"
    print(f"  {status} {name} {('— ' + info) if info else ''}")
    if not ok and info:
        failures_verbatim.append(f"{name}: {info}")


# ── helpers ─────────────────────────────────────────────────────────────
async def admin_login(client: httpx.AsyncClient, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD) -> str:
    r = await client.post(
        f"{API}/admin/auth/login",
        json={"email": email, "password": password},
    )
    r.raise_for_status()
    return r.json()["token"]


async def ensure_sms_mock(client: httpx.AsyncClient, token: str):
    r = await client.post(
        f"{API}/admin/integrations/sms-mode",
        headers={"Authorization": f"Bearer {token}"},
        json={"mode": "mock"},
    )
    if r.status_code not in (200, 204):
        print(f"[warn] could not set sms mock: {r.status_code} {r.text[:200]}")


def fresh_phone(seed: int) -> str:
    return f"+1832{seed % 10000000:07d}"


async def register_user(client: httpx.AsyncClient, name: str, phone: str) -> Dict[str, Any]:
    """Register and mark verified via direct mongo write to avoid the 5/min
    send-otp rate-limit. Matches what /verify-otp would set."""
    r = await client.post(f"{API}/auth/register", json={"name": name})
    r.raise_for_status()
    user = r.json()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "phone": phone,
            "verified": True,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }},
    )
    user["phone"] = phone
    user["verified"] = True
    return user


async def create_group(client: httpx.AsyncClient, lead: Dict[str, Any], total: float,
                       title: str = "Pizza Night", split_mode: str = "fast") -> Dict[str, Any]:
    r = await client.post(
        f"{API}/groups",
        json={
            "lead_id": lead["id"],
            "title": title,
            "total_amount": total,
            "split_mode": split_mode,
            "tax": 0.0,
            "tip": 0.0,
            "items": [],
        },
    )
    r.raise_for_status()
    return r.json()


async def join_group(client: httpx.AsyncClient, code: str, user_id: str) -> Dict[str, Any]:
    r = await client.get(f"{API}/groups/by-code/{code}")
    r.raise_for_status()
    gid = r.json()["id"]
    r = await client.post(f"{API}/groups/{gid}/join", json={"user_id": user_id, "joined_via": "code"})
    r.raise_for_status()
    return r.json()


# ── Scenario A: total_contributed happy path ───────────────────────────
async def test_A_total_contributed_basic(client: httpx.AsyncClient, token: str) -> Dict[str, Any]:
    print("\n[A] total_contributed happy path (list + detail)")
    ts = int(time.time())
    tom = await register_user(client, f"TomA {ts}", fresh_phone(ts * 10 + 1))
    alice = await register_user(client, f"AliceA {ts}", fresh_phone(ts * 10 + 2))
    bob = await register_user(client, f"BobA {ts}", fresh_phone(ts * 10 + 3))
    record("A.users_registered", all([tom["verified"], alice["verified"], bob["verified"]]))

    # Fast-split $30 group; tom leads, alice + bob join → 3 members = $10 each
    g = await create_group(client, tom, total=30.0, title=f"PhaseA-1 {ts}", split_mode="fast")
    await join_group(client, g["code"], alice["id"])
    await join_group(client, g["code"], bob["id"])
    record("A.group_created_with_members", True, f"gid={g['id']} code={g['code']}")

    # AliceA contributes $10 (full share — no credits, so cash_owed=10 will
    # require Stripe Checkout, NOT what we want for this test). Instead we
    # grant 10 in credit so contribute goes through `credit_only` path with
    # cash_owed=0. But the review request says A is happy-path BEFORE credits
    # are granted in B. Workaround: directly insert a contribution row in mongo
    # to simulate a settled $10 contribution — this exercises the SAME read
    # path that total_contributed sums.
    # Better: use credit-only contribute via admin grant to keep flow real.
    # We'll grant $10 credit, then call /contribute amount=10 which routes
    # through the credit_only path (no Stripe).
    r = await client.post(
        f"{API}/admin/users/{alice['id']}/credits/grant",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": 10.0, "note": "phaseA test"},
    )
    record("A.alice_credit_granted", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")

    r = await client.post(
        f"{API}/groups/{g['id']}/contribute",
        json={"user_id": alice["id"], "amount": 10.0, "notify_on_settled": False},
    )
    record("A.alice_contributed_10", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")

    # Verify mongo row: contribution.amount == 10
    grp = await db.groups.find_one({"id": g["id"]}, {"_id": 0})
    alice_contribs = [c for c in (grp.get("contributions") or []) if c.get("user_id") == alice["id"]]
    contribs_sum = sum(float(c.get("amount") or 0) for c in alice_contribs)
    record("A.db_alice_contrib_sum_10", abs(contribs_sum - 10.0) < 0.01,
           f"sum={contribs_sum} rows={alice_contribs}")

    # Detail: GET /api/admin/users/{alice.id} → total_contributed == 10.0
    r = await client.get(
        f"{API}/admin/users/{alice['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    record("A.user_detail_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        tc = body.get("total_contributed")
        record("A.detail_total_contributed_10", abs(float(tc or 0) - 10.0) < 0.01,
               f"got total_contributed={tc}")

    # List: GET /api/admin/users?q=<alice phone> → row has total_contributed == 10
    r = await client.get(
        f"{API}/admin/users",
        params={"q": alice["phone"], "limit": 50},
        headers={"Authorization": f"Bearer {token}"},
    )
    record("A.user_list_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        items = r.json().get("items", [])
        row = next((it for it in items if it.get("id") == alice["id"]), None)
        record("A.list_row_present", row is not None, f"found {len(items)} rows")
        if row:
            tc = row.get("total_contributed")
            record("A.list_total_contributed_10", abs(float(tc or 0) - 10.0) < 0.01,
                   f"got total_contributed={tc}")

    return {"tom": tom, "alice": alice, "bob": bob, "group1": g}


# ── Scenario B: total_contributed includes credit-applied portion ──────
async def test_B_credit_applied(client: httpx.AsyncClient, token: str, ctx: Dict[str, Any]):
    print("\n[B] total_contributed includes credit-applied portion")
    tom = ctx["tom"]
    alice = ctx["alice"]
    bob = ctx["bob"]
    ts = int(time.time())

    # Grant Alice $5 credit (in addition to whatever's left from A)
    r = await client.post(
        f"{API}/admin/users/{alice['id']}/credits/grant",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": 5.0, "note": "phaseB credit"},
    )
    record("B.alice_credit_5_granted", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")

    # Create SECOND fast-split $30 group with tom as lead; alice + bob join
    g2 = await create_group(client, tom, total=30.0, title=f"PhaseB-2 {ts}", split_mode="fast")
    await join_group(client, g2["code"], alice["id"])
    await join_group(client, g2["code"], bob["id"])

    # Alice contributes $10 → credit-FIFO will consume $5 credit + need $5 cash
    # This means /contribute will trigger Stripe Checkout (cash_owed=5>0).
    # We instead need the contribution to actually settle so the row gets
    # recorded with amount=10. We can do this by granting MORE credit so the
    # whole 10 is credit-only — but then credit_applied=10, cash_paid=0, and
    # the review request specifically wants "credit_applied=5, cash_paid=5
    # but amount=10". The only way to make this happen without a real Stripe
    # checkout completion is to either:
    #   (a) Drive a Stripe Checkout session and webhook simulate, OR
    #   (b) Directly write a contribution row into mongo matching the shape.
    # We use (b) — same data shape the contribute route produces — to verify
    # the admin endpoint's summation logic includes credit_applied portions.
    from uuid import uuid4
    contrib = {
        "id": f"c_{uuid4().hex[:10]}",
        "user_id": alice["id"],
        "amount": 10.0,
        "cash_paid": 5.0,
        "credit_applied": 5.0,
        "notify_on_settled": False,
        "via": "mixed",
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    await db.groups.update_one(
        {"id": g2["id"]},
        {"$push": {"contributions": contrib}},
    )
    record("B.simulated_mixed_contrib_inserted", True, f"amount=10 (cash=5+credit=5) in {g2['id']}")

    # Detail: total_contributed should now be 10 (from g1) + 10 (from g2) = 20.0
    r = await client.get(
        f"{API}/admin/users/{alice['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    record("B.user_detail_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        tc = r.json().get("total_contributed")
        record("B.detail_total_contributed_20", abs(float(tc or 0) - 20.0) < 0.01,
               f"got total_contributed={tc}, expected 20.0")

    # List: alice's row should also reflect 20.0
    r = await client.get(
        f"{API}/admin/users",
        params={"q": alice["phone"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    if r.status_code == 200:
        items = r.json().get("items", [])
        row = next((it for it in items if it.get("id") == alice["id"]), None)
        if row:
            tc = row.get("total_contributed")
            record("B.list_total_contributed_20", abs(float(tc or 0) - 20.0) < 0.01,
                   f"got total_contributed={tc}, expected 20.0")
    return {"g2": g2}


# ── Scenario C: total_contributed includes repayments ──────────────────
async def test_C_repayments(client: httpx.AsyncClient, token: str, ctx: Dict[str, Any]):
    print("\n[C] total_contributed includes repayments")
    alice = ctx["alice"]
    # Take the first group from A and inject a repayment row for alice (simulating
    # she paid tom back). This is the same shape the /repay endpoint creates.
    g1 = ctx["group1"]
    from uuid import uuid4
    rep = {
        "id": f"rep_{uuid4().hex[:10]}",
        "user_id": alice["id"],
        "amount": 3.50,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    await db.groups.update_one(
        {"id": g1["id"]},
        {"$push": {"repayments": rep}},
    )
    record("C.repayment_injected", True, f"rep amount=3.5 in {g1['id']}")

    # Detail total_contributed now expected: 20.0 (from A+B) + 3.5 = 23.5
    r = await client.get(
        f"{API}/admin/users/{alice['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if r.status_code == 200:
        tc = r.json().get("total_contributed")
        record("C.detail_total_contributed_23_5", abs(float(tc or 0) - 23.5) < 0.01,
               f"got total_contributed={tc}, expected 23.5 (20.0 contribs + 3.5 repayment)")
    else:
        record("C.detail_total_contributed_23_5", False, f"{r.status_code}: {r.text[:200]}")


# ── Scenario D: audit-log substring + case-insensitive filter ──────────
async def test_D_audit_action_filter(client: httpx.AsyncClient, token: str, ctx: Dict[str, Any]):
    print("\n[D] audit-log substring + case-insensitive `action` filter")
    bob = ctx["bob"]

    # Block then unblock BobA so we have admin.block_user + admin.unblock_user rows
    r = await client.post(
        f"{API}/admin/users/{bob['id']}/block",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_blocked": True, "reason": "phaseA test"},
    )
    record("D.block_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")

    r = await client.post(
        f"{API}/admin/users/{bob['id']}/block",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_blocked": False},
    )
    record("D.unblock_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")

    # Filter: action=block → should return both block_user + unblock_user rows
    r = await client.get(
        f"{API}/admin/audit-log",
        params={"action": "block", "limit": 500},
        headers={"Authorization": f"Bearer {token}"},
    )
    record("D.action_filter_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        items = body.get("items", [])
        actions = [i.get("action") for i in items]
        # Check both target_id matches bob, since other test runs may have produced more
        bob_actions = [i for i in items if i.get("target_id") == bob["id"]]
        bob_action_names = sorted(set(a.get("action") for a in bob_actions))
        record("D.has_block_user", "admin.block_user" in bob_action_names, f"bob_actions={bob_action_names}")
        record("D.has_unblock_user", "admin.unblock_user" in bob_action_names, f"bob_actions={bob_action_names}")
        record("D.total_field_present", "total" in body, f"keys={list(body.keys())}")
        record("D.total_matches_items", isinstance(body.get("total"), int) and body.get("total") >= len(items),
               f"total={body.get('total')} items_len={len(items)}")
        total_lower = body.get("total")

        # Case-insensitive: action=BLOCK should yield same set
        r2 = await client.get(
            f"{API}/admin/audit-log",
            params={"action": "BLOCK", "limit": 500},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r2.status_code == 200:
            total_upper = r2.json().get("total")
            record("D.case_insensitive_total_match", total_lower == total_upper,
                   f"lower={total_lower}, upper={total_upper}")
        else:
            record("D.case_insensitive_total_match", False, f"{r2.status_code}: {r2.text[:200]}")


# ── Scenario E: audit-log date range ───────────────────────────────────
async def test_E_audit_date_range(client: httpx.AsyncClient, token: str):
    print("\n[E] audit-log date_from / date_to filter")
    now = dt.datetime.now(dt.timezone.utc)
    yesterday = (now - dt.timedelta(days=1)).isoformat()
    tomorrow = (now + dt.timedelta(days=1)).isoformat()

    r = await client.get(
        f"{API}/admin/audit-log",
        params={"date_from": yesterday, "date_to": tomorrow, "limit": 500},
        headers={"Authorization": f"Bearer {token}"},
    )
    record("E.range_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        items = r.json().get("items", [])
        record("E.items_returned", len(items) > 0, f"got {len(items)} items")
        # Verify all rows within bounds
        all_in_bounds = True
        offender = None
        for it in items:
            at_str = it.get("at") or ""
            if at_str < yesterday or at_str > tomorrow:
                all_in_bounds = False
                offender = at_str
                break
        record("E.all_within_bounds", all_in_bounds, f"offender_at={offender}")

    # Future date range → 0 items
    r = await client.get(
        f"{API}/admin/audit-log",
        params={"date_from": "2099-01-01T00:00:00.000Z", "limit": 50},
        headers={"Authorization": f"Bearer {token}"},
    )
    if r.status_code == 200:
        body = r.json()
        record("E.future_range_zero_items", len(body.get("items", [])) == 0 and body.get("total") == 0,
               f"items={len(body.get('items', []))} total={body.get('total')}")
    else:
        record("E.future_range_zero_items", False, f"{r.status_code}: {r.text[:200]}")


# ── Scenario F: audit-log destructive filter ───────────────────────────
async def test_F_destructive(client: httpx.AsyncClient, token: str):
    print("\n[F] audit-log destructive filter")
    r = await client.get(
        f"{API}/admin/audit-log",
        params={"destructive": "true", "limit": 200},
        headers={"Authorization": f"Bearer {token}"},
    )
    record("F.destructive_true_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        items = r.json().get("items", [])
        all_true = all(bool(it.get("destructive")) is True for it in items)
        record("F.all_destructive_true", all_true, f"counter-examples={[i.get('action') for i in items if not i.get('destructive')]}")

    r = await client.get(
        f"{API}/admin/audit-log",
        params={"destructive": "false", "limit": 200},
        headers={"Authorization": f"Bearer {token}"},
    )
    record("F.destructive_false_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        items = r.json().get("items", [])
        all_false = all(bool(it.get("destructive")) is False for it in items)
        record("F.all_destructive_false", all_false,
               f"counter-examples={[i.get('action') for i in items if i.get('destructive')]}")


# ── Scenario G: audit-log CSV export — primary test ────────────────────
async def test_G_audit_csv_export(client: httpx.AsyncClient, token: str):
    print("\n[G] audit-log CSV export — primary test")
    r = await client.get(
        f"{API}/admin/audit-log/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    record("G.export_status_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return
    ctype = r.headers.get("content-type", "")
    cdisp = r.headers.get("content-disposition", "")
    record("G.content_type_csv", "text/csv" in ctype.lower(), f"content-type={ctype}")
    record("G.content_disp_attachment", "attachment" in cdisp.lower(), f"content-disposition={cdisp}")
    record("G.content_disp_filename", "filename=" in cdisp.lower(), f"content-disposition={cdisp}")

    body = r.text
    lines = body.splitlines()
    record("G.body_has_more_than_header", len(lines) > 1, f"line count={len(lines)}")
    expected_header = "at,admin_email,action,destructive,target_type,target_id,ip,payload_json"
    record("G.header_exact_match", len(lines) > 0 and lines[0] == expected_header,
           f"actual_first_line={lines[0] if lines else '<empty>'}")

    # CSV parse + spot-check
    reader = csv.reader(io.StringIO(body))
    rows = list(reader)
    record("G.csv_parses", len(rows) >= 2, f"parsed_rows={len(rows)}")
    if len(rows) >= 2:
        record("G.row_has_8_cols", len(rows[1]) == 8, f"col_count={len(rows[1])}")

    # Filtered export: action=block → reduced set
    r2 = await client.get(
        f"{API}/admin/audit-log/export",
        params={"action": "block"},
        headers={"Authorization": f"Bearer {token}"},
    )
    record("G.filtered_export_200", r2.status_code == 200, f"{r2.status_code}: {r2.text[:200]}")
    if r2.status_code == 200:
        body2 = r2.text
        lines2 = body2.splitlines()
        record("G.filtered_smaller_than_full", len(lines2) <= len(lines),
               f"filtered={len(lines2)} full={len(lines)}")
        # Every data row should have 'block' in column 2 (action) substring
        reader2 = csv.reader(io.StringIO(body2))
        all_rows = list(reader2)
        if len(all_rows) > 1:
            data_rows = all_rows[1:]
            actions_lower = [row[2].lower() for row in data_rows if len(row) >= 3]
            all_have_block = all("block" in a for a in actions_lower)
            record("G.filtered_all_contain_block", all_have_block,
                   f"non_block_actions={[a for a in actions_lower if 'block' not in a][:5]}")


# ── Scenario H: RBAC ───────────────────────────────────────────────────
async def test_H_rbac(client: httpx.AsyncClient, admin_token: str):
    print("\n[H] RBAC")
    # No bearer → 401 on both endpoints
    r = await client.get(f"{API}/admin/audit-log")
    record("H.no_bearer_log_401", r.status_code == 401, f"{r.status_code}: {r.text[:120]}")
    r = await client.get(f"{API}/admin/audit-log/export")
    record("H.no_bearer_export_401", r.status_code == 401, f"{r.status_code}: {r.text[:120]}")

    # Create a fresh 'support' role admin (super_admin only)
    ts = int(time.time())
    support_email = f"support_phaseA_{ts}@squadpay.us"
    support_password = "Sup!Strong#Pwd_2026"
    r = await client.post(
        f"{API}/admin/admins",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": support_email,
            "password": support_password,
            "name": "Support PhaseA",
            "role": "support",
        },
    )
    record("H.support_admin_created", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return

    try:
        support_token = await admin_login(client, support_email, support_password)
        record("H.support_login_ok", True, "")
    except Exception as e:
        record("H.support_login_ok", False, f"login failed: {e}")
        return

    # GET /audit-log as support
    r = await client.get(
        f"{API}/admin/audit-log",
        headers={"Authorization": f"Bearer {support_token}"},
    )
    log_status = r.status_code
    record("H.support_log_status", log_status in (200, 403), f"{log_status}: {r.text[:200]}")

    # GET /audit-log/export as support
    r = await client.get(
        f"{API}/admin/audit-log/export",
        headers={"Authorization": f"Bearer {support_token}"},
    )
    export_status = r.status_code
    record("H.support_export_status", export_status in (200, 403), f"{export_status}: {r.text[:200]}")

    # RBAC consistency: both endpoints must give same result for support
    record("H.support_rbac_consistent", log_status == export_status,
           f"log={log_status} export={export_status} — should be SAME for both endpoints")


# ── Scenario I: regression smoke ───────────────────────────────────────
async def test_I_regression(client: httpx.AsyncClient, token: str, ctx: Dict[str, Any]):
    print("\n[I] regression smoke (metrics, users list, native PI)")

    # GET /admin/metrics → 200
    r = await client.get(f"{API}/admin/metrics", headers={"Authorization": f"Bearer {token}"})
    record("I.metrics_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")

    # GET /admin/users → 200 with items > 0
    r = await client.get(
        f"{API}/admin/users",
        params={"limit": 50},
        headers={"Authorization": f"Bearer {token}"},
    )
    record("I.users_list_200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        items = r.json().get("items", [])
        record("I.users_list_nonempty", len(items) > 0, f"count={len(items)}")

    # Native PI smoke: tom contributes his share in group1
    tom = ctx["tom"]
    g1 = ctx["group1"]
    enriched = await (await client.get(f"{API}/groups/{g1['id']}")).aread()
    # Re-fetch via httpx
    r = await client.get(f"{API}/groups/{g1['id']}")
    if r.status_code == 200:
        g = r.json()
        per = next((p for p in g.get("per_user", []) if p["user_id"] == tom["id"]), None)
        tom_share = per.get("total") if per else 0.0
        remaining = per.get("remaining_share") if per else 0.0
        amt = remaining if remaining and remaining > 0.01 else tom_share
        r2 = await client.post(
            f"{API}/groups/{g1['id']}/contribute-payment-intent",
            json={"user_id": tom["id"], "amount": amt, "notify_on_settled": False},
        )
        record("I.native_pi_200", r2.status_code == 200, f"{r2.status_code}: {r2.text[:300]}")
        if r2.status_code == 200:
            body = r2.json()
            record("I.native_pi_has_client_secret", bool(body.get("client_secret")),
                   f"keys={list(body.keys())[:8]}")


# ── runner ─────────────────────────────────────────────────────────────
async def run_all():
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        token = await admin_login(client)
        print(f"✅ admin login ok, token len={len(token)}")
        await ensure_sms_mock(client, token)

        ctx = await test_A_total_contributed_basic(client, token)
        await test_B_credit_applied(client, token, ctx)
        await test_C_repayments(client, token, ctx)
        await test_D_audit_action_filter(client, token, ctx)
        await test_E_audit_date_range(client, token)
        await test_F_destructive(client, token)
        await test_G_audit_csv_export(client, token)
        await test_H_rbac(client, token)
        await test_I_regression(client, token, ctx)

    # Summary
    print("\n" + "=" * 72)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"RESULTS: {passed}/{len(results)} pass, {failed} fail")
    if failed:
        print("\nFAILURES:")
        for name, ok, info in results:
            if not ok:
                print(f"  ❌ {name}: {info}")
    print("=" * 72)
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(run_all())
    raise SystemExit(0 if ok else 1)
