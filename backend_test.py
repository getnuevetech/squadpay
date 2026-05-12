"""
Backend test suite for the NEW Admin Notification Center endpoints.

Covers all 18 cases listed in the review request:
  POST /api/admin/notifications/broadcast (admin auth required)
  GET  /api/admin/notifications/broadcasts (admin auth required)
  GET  /api/users/{user_id}/inbox
  POST /api/users/{user_id}/inbox/{msg_id}/read
  POST /api/users/{user_id}/inbox/read-all

Uses the live preview backend via EXPO_PUBLIC_BACKEND_URL.
"""

from __future__ import annotations

import os
import time
import json
import requests
from typing import Dict, Any, List, Tuple

# ---------- Config ----------
BACKEND_BASE = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://joint-pay-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BACKEND_BASE}/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

TS = int(time.time())


# ---------- Helpers ----------
def _short(resp: requests.Response, n: int = 280) -> str:
    try:
        body = json.dumps(resp.json())
    except Exception:
        body = resp.text or ""
    return body[:n]


class Results:
    def __init__(self):
        self.rows: List[Tuple[str, bool, str]] = []

    def add(self, case: str, ok: bool, note: str = ""):
        self.rows.append((case, ok, note))
        flag = "PASS" if ok else "FAIL"
        print(f"[{flag}] {case} — {note}")

    def summary(self):
        passed = sum(1 for _, ok, _ in self.rows if ok)
        failed = len(self.rows) - passed
        print("\n" + "=" * 72)
        print(f"SUMMARY: {passed}/{len(self.rows)} PASS, {failed} FAIL")
        print("=" * 72)
        for case, ok, note in self.rows:
            mark = "✅" if ok else "❌"
            print(f"  {mark} {case}: {note}")
        return failed


R = Results()


def admin_login() -> str:
    r = requests.post(
        f"{API}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json().get("token")
    assert token, f"No token in admin login response: {_short(r)}"
    return token


def set_sms_mode_mock(admin_token: str):
    """Ensure SMS routing is in mock so sms_sent counter increments cleanly."""
    r = requests.post(
        f"{API}/admin/integrations/sms-mode",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "mock"},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"[warn] set sms mode mock returned {r.status_code} {_short(r)}")


def register_user(name: str) -> str:
    r = requests.post(f"{API}/auth/register", json={"name": name}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


_phone_counter = 0


def make_phone() -> str:
    """Return a fresh-looking US phone number unique to this run."""
    global _phone_counter
    _phone_counter += 1
    # Build a 10-digit US number that's unique per call
    tail = (TS * 10 + _phone_counter) % 10_000_000
    return f"+1832{tail:07d}"


def verify_user(user_id: str, phone: str) -> str:
    """Send + verify OTP in mock mode → returns the (possibly collapsed) user id."""
    r = requests.post(
        f"{API}/auth/send-otp",
        json={"user_id": user_id, "phone": phone},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"send-otp failed: {r.status_code} {_short(r)}")

    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={
            "user_id": user_id,
            "phone": phone,
            "code": "123456",
            "confirm_existing": True,
        },
        timeout=30,
    )
    if r2.status_code != 200:
        raise RuntimeError(f"verify-otp failed: {r2.status_code} {_short(r2)}")
    return r2.json().get("id") or user_id


def create_user_full(name: str) -> Dict[str, str]:
    uid = register_user(name)
    phone = make_phone()
    final_uid = verify_user(uid, phone)
    return {"id": final_uid, "name": name, "phone": phone}


def create_group(lead_id: str, title: str, total: float = 30.0) -> str:
    r = requests.post(
        f"{API}/groups",
        json={
            "lead_id": lead_id,
            "title": title,
            "total_amount": total,
            "split_mode": "fast",
            "tax": 0.0,
            "tip": 0.0,
            "items": [],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def join_group(group_id: str, user_id: str):
    r = requests.post(
        f"{API}/groups/{group_id}/join",
        json={"user_id": user_id, "joined_via": "code"},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"join failed: {r.status_code} {_short(r)}")


# ---------- Setup: admin + fixture users + group ----------
print(f"[setup] Backend base: {API}")
admin_token = admin_login()
print(f"[setup] Admin login OK, token len={len(admin_token)}")

set_sms_mode_mock(admin_token)

# Fixture: lead + 2 members + 1 lone user (verified, no group)
print("[setup] creating fixture users + group...")
lead = create_user_full(f"NotifLead{TS}")
member_a = create_user_full(f"NotifMemA{TS}")
member_b = create_user_full(f"NotifMemB{TS}")
lonely = create_user_full(f"NotifSolo{TS}")
print(f"[setup] lead={lead['id']} memA={member_a['id']} memB={member_b['id']} solo={lonely['id']}")

group_id = create_group(lead["id"], f"NotifGroup-{TS}", total=30.0)
join_group(group_id, member_a["id"])
join_group(group_id, member_b["id"])
print(f"[setup] group={group_id} (lead + 2 members)")

H_ADMIN = {"Authorization": f"Bearer {admin_token}"}


# ---------------- Case 1: 401 without admin token ----------------
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    json={
        "message": "hi",
        "audience": {"type": "all"},
        "channels": {"in_app": True, "sms": False},
    },
    timeout=30,
)
R.add(
    "C1 401 without admin token",
    r.status_code in (401, 403),
    f"status={r.status_code} body={_short(r, 120)}",
)


# ---------------- Case 3: empty message → 400 ----------------
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    headers=H_ADMIN,
    json={
        "message": "   ",
        "audience": {"type": "all"},
        "channels": {"in_app": True, "sms": False},
    },
    timeout=30,
)
R.add(
    "C3 empty message → 400",
    r.status_code == 400,
    f"status={r.status_code} body={_short(r, 160)}",
)


# ---------------- Case 4: message > 1000 chars → 400 ----------------
long_msg = "A" * 1001
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    headers=H_ADMIN,
    json={
        "message": long_msg,
        "audience": {"type": "all"},
        "channels": {"in_app": True, "sms": False},
    },
    timeout=30,
)
R.add(
    "C4 message >1000 chars → 400",
    r.status_code == 400,
    f"status={r.status_code} body={_short(r, 160)}",
)


# ---------------- Case 5: both channels off → 400 ----------------
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    headers=H_ADMIN,
    json={
        "message": "hello there",
        "audience": {"type": "all"},
        "channels": {"in_app": False, "sms": False},
    },
    timeout=30,
)
R.add(
    "C5 both channels off → 400",
    r.status_code == 400,
    f"status={r.status_code} body={_short(r, 160)}",
)


# ---------------- Case 6: audience.type=vip → 400 ----------------
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    headers=H_ADMIN,
    json={
        "message": "hi vips",
        "audience": {"type": "vip"},
        "channels": {"in_app": True, "sms": False},
    },
    timeout=30,
)
R.add(
    "C6 audience=vip → 400",
    r.status_code == 400,
    f"status={r.status_code} body={_short(r, 160)}",
)


# ---------------- Case 7: audience.type=groups with empty group_ids → 400 ----------------
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    headers=H_ADMIN,
    json={
        "message": "hi groups",
        "audience": {"type": "groups", "group_ids": []},
        "channels": {"in_app": True, "sms": False},
    },
    timeout=30,
)
R.add(
    "C7 groups audience with empty group_ids → 400",
    r.status_code == 400,
    f"status={r.status_code} body={_short(r, 160)}",
)


# ---------------- Case 2 + Case 8 + Case 12 + Case 14: audience=all → 200 ----------------
broadcast_msg_all = f"Hello from SquadPay test {TS} — all users"
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    headers=H_ADMIN,
    json={
        "message": broadcast_msg_all,
        "audience": {"type": "all"},
        "channels": {"in_app": True, "sms": False},
    },
    timeout=60,
)
ok_status = r.status_code == 200
body_all = r.json() if ok_status else {}
R.add(
    "C2 valid admin token → 200 (audience=all, in_app only)",
    ok_status,
    f"status={r.status_code} body={_short(r, 200)}",
)

# C8 — recipient_count > 0
rc_all = int(body_all.get("recipient_count") or 0)
R.add(
    "C8 audience=all recipient_count > 0",
    rc_all > 0,
    f"recipient_count={rc_all}",
)

# C14 — response shape
required_keys = {"id", "recipient_count", "in_app_delivered", "sms_sent", "sms_failed"}
missing = [k for k in required_keys if k not in body_all]
R.add(
    "C14 response shape includes id/recipient_count/in_app_delivered/sms_sent/sms_failed",
    not missing,
    f"missing={missing} body={_short(r, 200)}",
)
broadcast_id_all = body_all.get("id")


# C12 — in-app persisted: check the lead's inbox contains this message
def get_inbox(user_id: str) -> Dict[str, Any]:
    rr = requests.get(f"{API}/users/{user_id}/inbox", timeout=30)
    rr.raise_for_status()
    return rr.json()


inbox_lead = get_inbox(lead["id"])
items_lead = inbox_lead.get("items") or []
has_msg = any(
    it.get("message") == broadcast_msg_all and it.get("broadcast_id") == broadcast_id_all
    for it in items_lead
)
R.add(
    "C12 in_app=true persists user_inbox doc for recipient (lead)",
    has_msg,
    f"inbox_count={len(items_lead)} found_match={has_msg}",
)


# ---------------- Case 9: audience=leads ----------------
broadcast_msg_leads = f"Leads-only message {TS}"
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    headers=H_ADMIN,
    json={
        "message": broadcast_msg_leads,
        "audience": {"type": "leads"},
        "channels": {"in_app": True, "sms": False},
    },
    timeout=60,
)
body_leads = r.json() if r.status_code == 200 else {}
ok_leads = r.status_code == 200 and int(body_leads.get("recipient_count") or 0) > 0
R.add(
    "C9 audience=leads → 200 with recipient_count>0",
    ok_leads,
    f"status={r.status_code} rc={body_leads.get('recipient_count')}",
)
broadcast_id_leads = body_leads.get("id")

# Verify subset: our lead should have received it; members A/B should NOT
# (unless they happen to lead some other group too — but they're fresh users).
inbox_lead2 = get_inbox(lead["id"])
inbox_a = get_inbox(member_a["id"])
inbox_b = get_inbox(member_b["id"])
inbox_solo = get_inbox(lonely["id"])

lead_got = any(it.get("broadcast_id") == broadcast_id_leads for it in inbox_lead2.get("items", []))
a_got = any(it.get("broadcast_id") == broadcast_id_leads for it in inbox_a.get("items", []))
b_got = any(it.get("broadcast_id") == broadcast_id_leads for it in inbox_b.get("items", []))
solo_got = any(it.get("broadcast_id") == broadcast_id_leads for it in inbox_solo.get("items", []))

R.add(
    "C9 leads-subset: our lead received, members/solo did not",
    lead_got and (not a_got) and (not b_got) and (not solo_got),
    f"lead={lead_got} memA={a_got} memB={b_got} solo={solo_got}",
)


# ---------------- Case 10: audience=members ----------------
broadcast_msg_members = f"Members-only message {TS}"
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    headers=H_ADMIN,
    json={
        "message": broadcast_msg_members,
        "audience": {"type": "members"},
        "channels": {"in_app": True, "sms": False},
    },
    timeout=60,
)
body_mem = r.json() if r.status_code == 200 else {}
ok_mem = r.status_code == 200 and int(body_mem.get("recipient_count") or 0) > 0
R.add(
    "C10 audience=members → 200 with recipient_count>0",
    ok_mem,
    f"status={r.status_code} rc={body_mem.get('recipient_count')}",
)
broadcast_id_mem = body_mem.get("id")

# Verify subset: member A and B should receive; our lead and lonely should NOT
inbox_lead3 = get_inbox(lead["id"])
inbox_a3 = get_inbox(member_a["id"])
inbox_b3 = get_inbox(member_b["id"])
inbox_solo3 = get_inbox(lonely["id"])

lead_got_m = any(it.get("broadcast_id") == broadcast_id_mem for it in inbox_lead3.get("items", []))
a_got_m = any(it.get("broadcast_id") == broadcast_id_mem for it in inbox_a3.get("items", []))
b_got_m = any(it.get("broadcast_id") == broadcast_id_mem for it in inbox_b3.get("items", []))
solo_got_m = any(it.get("broadcast_id") == broadcast_id_mem for it in inbox_solo3.get("items", []))

R.add(
    "C10 members-subset: members A&B received, lead and solo did not",
    a_got_m and b_got_m and (not lead_got_m) and (not solo_got_m),
    f"lead={lead_got_m} memA={a_got_m} memB={b_got_m} solo={solo_got_m}",
)


# ---------------- Case 11: audience=groups with valid ids ----------------
broadcast_msg_groups = f"Group-targeted message {TS}"
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    headers=H_ADMIN,
    json={
        "message": broadcast_msg_groups,
        "audience": {"type": "groups", "group_ids": [group_id]},
        "channels": {"in_app": True, "sms": False},
    },
    timeout=30,
)
body_g = r.json() if r.status_code == 200 else {}
rc_g = int(body_g.get("recipient_count") or 0)
ok_g = r.status_code == 200 and rc_g == 3  # lead + 2 members
R.add(
    "C11 audience=groups([group_id]) → recipient_count==3",
    ok_g,
    f"status={r.status_code} rc={rc_g}",
)
broadcast_id_g = body_g.get("id")

# Solo (not in the group) should NOT receive
inbox_solo4 = get_inbox(lonely["id"])
solo_got_g = any(it.get("broadcast_id") == broadcast_id_g for it in inbox_solo4.get("items", []))
inbox_a4 = get_inbox(member_a["id"])
a_got_g = any(it.get("broadcast_id") == broadcast_id_g for it in inbox_a4.get("items", []))
R.add(
    "C11 groups-audience: members of group receive, outsiders do not",
    a_got_g and (not solo_got_g),
    f"memA={a_got_g} solo={solo_got_g}",
)


# ---------------- Case 13: channels.sms=true → sms_sent increments (mock provider) ----------------
broadcast_msg_sms = f"SMS test {TS}"
r = requests.post(
    f"{API}/admin/notifications/broadcast",
    headers=H_ADMIN,
    json={
        "message": broadcast_msg_sms,
        "audience": {"type": "groups", "group_ids": [group_id]},
        "channels": {"in_app": True, "sms": True},
    },
    timeout=60,
)
body_sms = r.json() if r.status_code == 200 else {}
ok_sms = r.status_code == 200 and int(body_sms.get("sms_sent") or 0) > 0
R.add(
    "C13 channels.sms=true increments sms_sent (mock provider counts as delivered)",
    ok_sms,
    f"status={r.status_code} sms_sent={body_sms.get('sms_sent')} sms_failed={body_sms.get('sms_failed')}",
)
broadcast_id_sms = body_sms.get("id")


# ---------------- Case 15: GET /admin/notifications/broadcasts ----------------
r = requests.get(f"{API}/admin/notifications/broadcasts", headers=H_ADMIN, timeout=30)
ok_list = r.status_code == 200
items = (r.json() or {}).get("items", []) if ok_list else []
ids_in_list = {it.get("id") for it in items}
recent = {broadcast_id_all, broadcast_id_leads, broadcast_id_mem, broadcast_id_g, broadcast_id_sms}
recent.discard(None)
found_recent = recent.issubset(ids_in_list) if recent else False
R.add(
    "C15 GET /admin/notifications/broadcasts returns recently-sent broadcasts",
    ok_list and found_recent,
    f"status={r.status_code} items={len(items)} all_recent_present={found_recent}",
)


# ---------------- Case 16: GET inbox sorted DESC by created_at, accurate unread count ----------------
inbox_a_final = get_inbox(member_a["id"])
items_a = inbox_a_final.get("items") or []
sorted_ok = all(
    items_a[i].get("created_at", "") >= items_a[i + 1].get("created_at", "")
    for i in range(len(items_a) - 1)
)
unread_reported = inbox_a_final.get("unread")
unread_actual = sum(1 for it in items_a if not it.get("read_at"))
R.add(
    "C16 inbox sorted DESC by created_at and unread count accurate",
    sorted_ok and unread_reported == unread_actual,
    f"sorted={sorted_ok} unread_reported={unread_reported} unread_actual={unread_actual} items={len(items_a)}",
)


# ---------------- Case 17: POST /users/{uid}/inbox/{msg_id}/read marks one ----------------
unread_items_a = [it for it in items_a if not it.get("read_at")]
if not unread_items_a:
    R.add("C17 mark one as read", False, "no unread items to mark for member_a")
else:
    target = unread_items_a[0]
    msg_id = target["id"]
    r = requests.post(
        f"{API}/users/{member_a['id']}/inbox/{msg_id}/read",
        timeout=30,
    )
    ok_mark = r.status_code == 200 and (r.json() or {}).get("updated") == 1
    # Re-fetch to confirm unread decremented
    inbox_after = get_inbox(member_a["id"])
    new_unread = inbox_after.get("unread")
    expected = unread_reported - 1
    R.add(
        "C17 mark one as read → unread decrements by 1",
        ok_mark and new_unread == expected,
        f"resp={_short(r, 120)} unread_before={unread_reported} unread_after={new_unread} expected={expected}",
    )


# ---------------- Case 18: POST /users/{uid}/inbox/read-all clears unread ----------------
r = requests.post(f"{API}/users/{member_a['id']}/inbox/read-all", timeout=30)
ok_all = r.status_code == 200
inbox_final = get_inbox(member_a["id"])
final_unread = inbox_final.get("unread")
R.add(
    "C18 read-all clears all unread",
    ok_all and final_unread == 0,
    f"resp={_short(r, 120)} unread_after={final_unread}",
)


# ---------- Final summary ----------
failed = R.summary()
exit(0 if failed == 0 else 1)
