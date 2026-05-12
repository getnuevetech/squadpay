"""
Backend tests — Batch June 2025 review request:
  1) Contact Us + Customer Service tickets (/app/backend/routes/contact_routes.py)
  2) Admin global search        (/app/backend/routes/admin_search.py)
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE = os.environ.get("BACKEND_URL", "https://joint-pay-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

PASSES: List[str] = []
FAILS: List[Tuple[str, str]] = []


def _ok(name: str):
    PASSES.append(name)
    print(f"  ✅ {name}")


def _fail(name: str, detail: str):
    FAILS.append((name, detail))
    print(f"  ❌ {name}\n      → {detail}")


def _shortdump(r: requests.Response) -> str:
    try:
        return f"HTTP {r.status_code} {json.dumps(r.json())[:600]}"
    except Exception:
        return f"HTTP {r.status_code} {r.text[:600]}"


def admin_login() -> str:
    r = requests.post(
        f"{API}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    if r.status_code != 200:
        raise SystemExit(f"Admin login failed: {_shortdump(r)}")
    tok = r.json().get("token")
    if not tok:
        raise SystemExit(f"Admin login missing token: {r.json()}")
    return tok


# ---------------------------------------------------------------------------
# 1. Contact Us + Customer Service
# ---------------------------------------------------------------------------

def _register_user(name: str, phone: str) -> Optional[str]:
    """Create a fully-verified user (mock OTP env) so we can attach user_id+phone."""
    try:
        # /auth/register
        r = requests.post(f"{API}/auth/register", json={"name": name}, timeout=15)
        if r.status_code != 200:
            return None
        uid = r.json().get("id") or r.json().get("user", {}).get("id")
        # /auth/send-otp
        r = requests.post(f"{API}/auth/send-otp", json={"user_id": uid, "phone": phone}, timeout=15)
        if r.status_code != 200:
            return uid  # may still work for non-phone test cases
        # /auth/verify-otp
        r = requests.post(
            f"{API}/auth/verify-otp",
            json={"user_id": uid, "phone": phone, "code": "123456"},
            timeout=15,
        )
        if r.status_code != 200:
            return uid
        # OTP collapse can return a different id
        return r.json().get("id") or uid
    except Exception:
        return None


def test_contact(admin_token: str):
    print("\n=== Contact Us + Customer Service ===\n")
    headers = {"Authorization": f"Bearer {admin_token}"}
    ts = int(time.time())

    # ---------- POST /api/contact ----------

    # 1) Missing name — pydantic min_length=1 → 422 (or 400)
    r = requests.post(
        f"{API}/contact",
        json={
            "name": "",
            "email": "jane.doe+missingname@example.com",
            "subject": "general_enquiry",
            "message": "Hi team, just kicking the tires.",
        },
        timeout=15,
    )
    if r.status_code in (400, 422):
        _ok("Case 1 missing name → 4xx")
    else:
        _fail("Case 1 missing name", _shortdump(r))

    # 2) Bad email format
    r = requests.post(
        f"{API}/contact",
        json={
            "name": "Maya Patel",
            "email": "not-an-email",
            "subject": "general_enquiry",
            "message": "Testing the contact form please.",
        },
        timeout=15,
    )
    if r.status_code in (400, 422):
        _ok("Case 2 bad email → 4xx")
    else:
        _fail("Case 2 bad email", _shortdump(r))

    # 3) Empty message (min_length=4 enforced by pydantic)
    r = requests.post(
        f"{API}/contact",
        json={
            "name": "Maya Patel",
            "email": "maya@example.com",
            "subject": "general_enquiry",
            "message": "",
        },
        timeout=15,
    )
    if r.status_code in (400, 422):
        _ok("Case 3 empty message → 4xx")
    else:
        _fail("Case 3 empty message", _shortdump(r))

    # 4) Subject not in whitelist
    r = requests.post(
        f"{API}/contact",
        json={
            "name": "Maya Patel",
            "email": "maya@example.com",
            "subject": "marketing_spam",
            "message": "I want to send you a billion newsletters.",
        },
        timeout=15,
    )
    if r.status_code == 400:
        _ok("Case 4 invalid subject → 400")
    else:
        _fail("Case 4 invalid subject", _shortdump(r))

    # 5) Happy path — should return ok, ticket_id, email_dispatched (bool)
    happy_payload = {
        "name": f"Aaron Sanchez {ts}",
        "email": f"aaron+{ts}@example.com",
        "subject": "technical_support",
        "message": "My SquadPay group total is wrong after switching split mode.",
    }
    r = requests.post(f"{API}/contact", json=happy_payload, timeout=20)
    happy_ticket: Optional[str] = None
    if r.status_code == 200:
        body = r.json()
        if body.get("ok") is True and body.get("ticket_id") and "email_dispatched" in body:
            _ok(f"Case 5 happy path 200 (email_dispatched={body['email_dispatched']})")
            happy_ticket = body["ticket_id"]
        else:
            _fail("Case 5 happy path shape", _shortdump(r))
    else:
        _fail("Case 5 happy path", _shortdump(r))

    # Persistence check via admin GET single
    if happy_ticket:
        r = requests.get(
            f"{API}/admin/contact-messages/{happy_ticket}",
            headers=headers,
            timeout=15,
        )
        if r.status_code == 200 and r.json().get("status") == "new":
            _ok("Case 5b ticket persisted with status='new'")
        else:
            _fail("Case 5b ticket persisted", _shortdump(r))

    # 6) user_id + user_phone — register a verified user and submit with user_id
    phone = f"+1832{ts % 10000000:07d}"
    name = f"Lana Sun {ts}"
    uid = _register_user(name, phone)
    if not uid:
        _fail("Case 6 setup register user", "could not register/verify a test user")
    else:
        r = requests.post(
            f"{API}/contact",
            json={
                "name": name,
                "email": f"lana+{ts}@example.com",
                "subject": "account_refund",
                "message": "Hi, I'd love to chat about a refund for my last bill.",
                "user_id": uid,
            },
            timeout=20,
        )
        if r.status_code == 200 and r.json().get("ticket_id"):
            tid = r.json()["ticket_id"]
            r2 = requests.get(
                f"{API}/admin/contact-messages/{tid}",
                headers=headers,
                timeout=15,
            )
            if r2.status_code == 200:
                doc = r2.json()
                if doc.get("user_phone") == phone and doc.get("user_id") == uid:
                    _ok("Case 6 user_phone populated from db.users")
                else:
                    _fail(
                        "Case 6 user_phone populated",
                        f"expected phone={phone} uid={uid}, got phone={doc.get('user_phone')} uid={doc.get('user_id')}",
                    )
            else:
                _fail("Case 6 fetch ticket", _shortdump(r2))
        else:
            _fail("Case 6 submit with user_id", _shortdump(r))

    # ---------- Admin list ----------

    # 7) Auth: no token → 401
    r = requests.get(f"{API}/admin/contact-messages", timeout=15)
    if r.status_code in (401, 403):
        _ok(f"Case 7 unauthenticated admin list → {r.status_code}")
    else:
        _fail("Case 7 unauthenticated admin list", _shortdump(r))

    # 8) ?status=new — every returned item must have status='new'
    r = requests.get(
        f"{API}/admin/contact-messages?status=new&page_size=50",
        headers=headers,
        timeout=15,
    )
    if r.status_code == 200:
        items = r.json().get("items", [])
        if all(it.get("status") == "new" for it in items):
            _ok(f"Case 8 filter status=new ({len(items)} items, all status=new)")
        else:
            offending = [it.get("status") for it in items if it.get("status") != "new"]
            _fail("Case 8 filter status=new", f"offending statuses: {offending[:5]}")
    else:
        _fail("Case 8 filter status=new", _shortdump(r))

    # Seed a 4th "others" ticket so we can assert filter by subject
    other_payload = {
        "name": f"Theo Wu {ts}",
        "email": f"theo+{ts}@example.com",
        "subject": "others",
        "message": "Something else not in the dropdown options came up today.",
    }
    requests.post(f"{API}/contact", json=other_payload, timeout=15)

    # 9) ?subject=others — every returned item subject must be 'others'
    r = requests.get(
        f"{API}/admin/contact-messages?subject=others&page_size=50",
        headers=headers,
        timeout=15,
    )
    if r.status_code == 200:
        items = r.json().get("items", [])
        if items and all(it.get("subject") == "others" for it in items):
            _ok(f"Case 9 filter subject=others ({len(items)} items)")
        else:
            _fail(
                "Case 9 filter subject=others",
                f"items={len(items)}, subjects={[it.get('subject') for it in items[:5]]}",
            )
    else:
        _fail("Case 9 filter subject=others", _shortdump(r))

    # 10) ?q=email-fragment — use the alphanumeric trailing digits so we don't
    # accidentally trip regex metacharacters (the contact route uses q as a
    # raw regex; that's a separate concern flagged below).
    frag = happy_payload["email"].split("@")[0].split("+")[-1]
    r = requests.get(
        f"{API}/admin/contact-messages?q={frag}&page_size=10",
        headers=headers,
        timeout=15,
    )
    if r.status_code == 200:
        items = r.json().get("items", [])
        if items and any(frag in (it.get("email") or "") for it in items):
            _ok(f"Case 10 fuzzy q matched {len(items)} items")
        else:
            _fail("Case 10 fuzzy q", f"no match found for fragment '{frag}', items={len(items)}")
    else:
        _fail("Case 10 fuzzy q", _shortdump(r))

    # 11) Pagination
    r1 = requests.get(
        f"{API}/admin/contact-messages?page=1&page_size=2",
        headers=headers,
        timeout=15,
    )
    r2 = requests.get(
        f"{API}/admin/contact-messages?page=2&page_size=2",
        headers=headers,
        timeout=15,
    )
    if r1.status_code == 200 and r2.status_code == 200:
        items1 = r1.json().get("items", [])
        items2 = r2.json().get("items", [])
        ids1 = {it.get("id") for it in items1}
        ids2 = {it.get("id") for it in items2}
        if len(items1) <= 2 and len(items2) <= 2 and ids1.isdisjoint(ids2):
            _ok(f"Case 11 pagination page=1 ({len(items1)}) ∩ page=2 ({len(items2)}) = ∅")
        else:
            _fail(
                "Case 11 pagination",
                f"page1={len(items1)}, page2={len(items2)}, overlap={ids1 & ids2}",
            )
    else:
        _fail("Case 11 pagination", f"page1={_shortdump(r1)}; page2={_shortdump(r2)}")

    # 12) Counters dict
    r = requests.get(f"{API}/admin/contact-messages", headers=headers, timeout=15)
    if r.status_code == 200:
        c = r.json().get("counters")
        if isinstance(c, dict) and {"new", "open", "resolved", "closed"}.issubset(c.keys()):
            _ok(f"Case 12 counters dict present: {c}")
        else:
            _fail("Case 12 counters dict", f"counters={c}")
    else:
        _fail("Case 12 counters dict", _shortdump(r))

    # ---------- Admin patch ----------

    # 13) PATCH status=open
    if happy_ticket:
        r = requests.patch(
            f"{API}/admin/contact-messages/{happy_ticket}",
            headers=headers,
            json={"status": "open"},
            timeout=15,
        )
        if r.status_code == 200 and r.json().get("status") == "open":
            _ok("Case 13 PATCH status=open returns updated doc")
        else:
            _fail("Case 13 PATCH status=open", _shortdump(r))

    # 14) PATCH invalid status
    if happy_ticket:
        r = requests.patch(
            f"{API}/admin/contact-messages/{happy_ticket}",
            headers=headers,
            json={"status": "invalid_state"},
            timeout=15,
        )
        if r.status_code == 400:
            _ok("Case 14 PATCH invalid status → 400")
        else:
            _fail("Case 14 PATCH invalid status", _shortdump(r))

    # 15) POST notes
    if happy_ticket:
        r = requests.post(
            f"{API}/admin/contact-messages/{happy_ticket}/notes",
            headers=headers,
            json={"note": "Reached out to Aaron, awaiting their reply."},
            timeout=15,
        )
        if r.status_code == 200:
            doc = r.json()
            notes = doc.get("notes") or []
            if (
                notes
                and notes[-1].get("note", "").startswith("Reached out to Aaron")
                and notes[-1].get("author_email") == ADMIN_EMAIL
            ):
                _ok("Case 15 POST notes appended with author_email")
            else:
                _fail("Case 15 POST notes", f"notes tail={notes[-1] if notes else 'EMPTY'}")
        else:
            _fail("Case 15 POST notes", _shortdump(r))


# ---------------------------------------------------------------------------
# 2. Admin global search
# ---------------------------------------------------------------------------

def test_admin_search(admin_token: str):
    print("\n=== Admin global search ===\n")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1) Auth — 401 without token
    r = requests.get(f"{API}/admin/search?q=ad", timeout=15)
    if r.status_code in (401, 403):
        _ok(f"Search Case 1 unauthenticated → {r.status_code}")
    else:
        _fail("Search Case 1 unauthenticated", _shortdump(r))

    # 2) Empty q → items=[]
    r = requests.get(f"{API}/admin/search?q=", headers=headers, timeout=15)
    if r.status_code == 200 and r.json().get("items") == []:
        _ok("Search Case 2 empty q → items=[]")
    else:
        _fail("Search Case 2 empty q", _shortdump(r))

    # 3) q='ad' — should match admin user 'admin@squadpay.us' (substring 'ad')
    r = requests.get(f"{API}/admin/search?q=ad", headers=headers, timeout=15)
    if r.status_code != 200:
        _fail("Search Case 3 q=ad request", _shortdump(r))
        return
    body = r.json()
    items = body.get("items", [])
    if not items:
        _fail("Search Case 3 q=ad results", f"empty items list: {_shortdump(r)}")
        return
    required_keys = {"category", "label", "sub", "href", "id"}
    bad = [it for it in items if not required_keys.issubset(set(it.keys()))]
    if bad:
        _fail(
            "Search Case 3 item shape",
            f"{len(bad)} items missing keys; first={bad[0]}",
        )
    else:
        _ok(f"Search Case 3 q=ad returned {len(items)} items with full shape")

    # 4) categories ⊆ allowed
    allowed = {"users", "squads", "admins", "audit", "tickets"}
    cats = {it.get("category") for it in items}
    if cats.issubset(allowed):
        _ok(f"Search Case 4 categories ⊆ allowed (got {cats})")
    else:
        _fail("Search Case 4 categories", f"unexpected categories: {cats - allowed}")

    # All hrefs should start with /admin/
    bad_href = [it for it in items if not (it.get("href") or "").startswith("/admin/")]
    if not bad_href:
        _ok("Search Case 4b all href values start with /admin/")
    else:
        _fail(
            "Search Case 4b admin hrefs",
            f"{len(bad_href)} hrefs don't start with /admin/; first={bad_href[0]}",
        )

    # 5) limit caps each category at ≤ 10
    r = requests.get(f"{API}/admin/search?q=a&limit=2", headers=headers, timeout=15)
    if r.status_code == 200:
        cat_counts: Dict[str, int] = {}
        for it in r.json().get("items", []):
            cat_counts[it["category"]] = cat_counts.get(it["category"], 0) + 1
        if all(c <= 10 for c in cat_counts.values()) and all(c <= 2 for c in cat_counts.values()):
            _ok(f"Search Case 5 limit=2 honoured per category ({cat_counts})")
        else:
            _fail(
                "Search Case 5 limit cap",
                f"category counts exceeded 2: {cat_counts}",
            )
    else:
        _fail("Search Case 5 limit request", _shortdump(r))


# ---------------------------------------------------------------------------
def main():
    print(f"Backend tests against {API}")
    token = admin_login()
    print(f"Admin token acquired ({token[:18]}…)")
    test_contact(token)
    test_admin_search(token)

    total = len(PASSES) + len(FAILS)
    print("\n" + "=" * 60)
    print(f"RESULT: {len(PASSES)} PASS / {len(FAILS)} FAIL  (of {total})")
    if FAILS:
        print("\nFAILURES:")
        for name, detail in FAILS:
            print(f"  - {name}\n      {detail}")
        sys.exit(1)
    print("All cases passed.")


if __name__ == "__main__":
    main()
