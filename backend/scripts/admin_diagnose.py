"""Diagnose why an admin account can't sign in or isn't getting reset emails.

Usage (run from /app/backend on the production server):
  python scripts/admin_diagnose.py <email>

Prints (read-only — makes no changes):
  - Whether the admin record exists, role, is_active, failed_logins, locked_until,
    force_password_reset, password_updated_at
  - Recent reset-token requests in this admin (last 10) with hashed token preview
    and used/unused state
  - Recent audit log entries for password reset / login (last 15) covering
    action='admin_password_reset.email_sent', 'email_skipped', 'email_failed',
    'login_success', 'login_failed', 'login_locked'
  - Effective EMAIL_* env config (sender, host, port — password redacted)
  - Whether the recipient is on the same domain as EMAIL_FROM (Gmail same-domain
    routing is a common source of "sent but never received" issues)
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(ROOT / ".env")

RESET_TOKENS_COLL = "admin_password_reset_tokens"
SESSIONS_COLL = "admin_sessions"
AUDIT_COLL = "audit_log"


def _redact(s: str | None) -> str:
    if not s:
        return "<unset>"
    if len(s) <= 4:
        return "***"
    return s[:2] + "…" + s[-2:]


async def main(email: str) -> int:
    email = email.strip().lower()
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("❌ MONGO_URL not set in environment")
        return 3
    db_name = os.environ.get("DB_NAME", "test_database")

    print("=" * 72)
    print(f" SquadPay admin diagnostics  —  {email}")
    print("=" * 72)
    print(f" MONGO_URL: {_redact(mongo_url)}")
    print(f" DB_NAME:   {db_name}")
    print("")

    # ---------- 1. EMAIL/SMTP env ----------
    email_user = os.environ.get("EMAIL_USER")
    email_from = os.environ.get("EMAIL_FROM") or email_user
    email_host = os.environ.get("EMAIL_HOST")
    email_port = os.environ.get("EMAIL_PORT") or "587"
    email_pw = os.environ.get("EMAIL_PASSWORD")
    print("✉️  Email/SMTP config")
    print(f"   EMAIL_HOST:     {email_host or '<unset>'}")
    print(f"   EMAIL_PORT:     {email_port}")
    print(f"   EMAIL_USER:     {email_user or '<unset>'}")
    print(f"   EMAIL_PASSWORD: {'<set, ' + str(len(email_pw or '')) + ' chars>' if email_pw else '<UNSET — no email will send>'}")
    print(f"   EMAIL_FROM:     {email_from or '<unset>'}")
    if email_from and email and "@" in email_from and "@" in email:
        sender_domain = email_from.split("@", 1)[1].lower()
        recipient_domain = email.split("@", 1)[1].lower()
        if sender_domain == recipient_domain:
            print(f"   ⚠️  SAME-DOMAIN routing: sender and recipient are both on '{sender_domain}'.")
            print("      Gmail Workspace often routes domain-internal mail to All Mail or Spam,")
            print("      bypassing the Inbox. Check the recipient's Spam + All Mail labels,")
            print("      or switch EMAIL_FROM to a different domain.")
    print("")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # ---------- 2. Admin record ----------
    admin = await db.admins.find_one({"email": email}, {"_id": 0, "password_hash": 0})
    print("👤 Admin record")
    if not admin:
        print(f"   ❌ No admin found with email={email!r}")
        print("      → forgot-password silently returns 200 (anti-enumeration), no email is sent.")
        print("      → Login will always 401.")
        print("      Fix: run scripts/admin_reset_password.py to seed/update this admin.")
        # Still try to print audit log entries that match by email — might catch typos.
        admin_id = None
    else:
        admin_id = admin["id"]
        print(f"   id:                    {admin_id}")
        print(f"   role:                  {admin.get('role')}")
        print(f"   is_active:             {admin.get('is_active')}")
        print(f"   failed_logins:         {admin.get('failed_logins', 0)}")
        print(f"   locked_until:          {admin.get('locked_until')}")
        print(f"   lock_round:            {admin.get('lock_round', 0)}")
        print(f"   force_password_reset:  {admin.get('force_password_reset', False)}")
        print(f"   password_updated_at:   {admin.get('password_updated_at') or admin.get('updated_at')}")
        print(f"   created_at:            {admin.get('created_at')}")
        if not admin.get("is_active", True):
            print("   ⚠️  is_active=False → forgot-password silently returns 200, no email sent.")
        if admin.get("locked_until"):
            print("   ⚠️  Account is locked. Login will return 423 until locked_until passes.")
    print("")

    # ---------- 3. Recent reset tokens ----------
    print("🔑 Recent reset-token requests (last 10)")
    if admin_id:
        cursor = db[RESET_TOKENS_COLL].find(
            {"admin_id": admin_id}, {"_id": 0, "token_hash": 1, "created_at": 1, "expires_at": 1, "used_at": 1}
        ).sort("created_at", -1).limit(10)
        rows = await cursor.to_list(length=10)
        if not rows:
            print("   (none)")
        for r in rows:
            th = r.get("token_hash", "")
            th_short = th[:6] + "…" + th[-4:] if th else "-"
            used = "✅ used" if r.get("used_at") else "⚫ unused"
            print(f"   {r.get('created_at')}  hash={th_short}  exp={r.get('expires_at')}  {used}")
    else:
        print("   (skipped — admin not found)")
    print("")

    # ---------- 4. Recent audit log ----------
    print("📒 Recent audit log entries (last 15) for this admin")
    q: dict = {"$or": [{"target_id": admin_id}, {"payload.email": email}]} if admin_id else {"payload.email": email}
    cursor = db[AUDIT_COLL].find(q, {"_id": 0}).sort("at", -1).limit(15)
    rows = await cursor.to_list(length=15)
    if not rows:
        print("   (none)")
    for r in rows:
        action = r.get("action", "?")
        when = r.get("at", "?")
        actor = r.get("admin_email") or r.get("admin_id") or "-"
        payload = r.get("payload") or {}
        # Compact relevant payload fields for the most common actions.
        extra = ""
        if "reason" in payload:
            extra = f" reason={payload['reason']}"
        elif "error" in payload:
            extra = f" error={str(payload['error'])[:80]}"
        elif "attempts" in payload:
            extra = f" attempts={payload['attempts']}"
        marker = ""
        if action.endswith("email_sent"):
            marker = " ✅"
        elif action.endswith("email_skipped") or action.endswith("email_failed"):
            marker = " ⚠️"
        elif action.endswith("login_locked"):
            marker = " 🔒"
        print(f"   {when}  by={actor}  action={action}{marker}{extra}")
    print("")

    # ---------- 5. Active sessions ----------
    if admin_id:
        sess_count = await db[SESSIONS_COLL].count_documents({"admin_id": admin_id})
        print(f"📝 Active admin sessions: {sess_count}")
    print("")
    print("=" * 72)
    if not admin:
        print("NEXT STEP: scripts/admin_reset_password.py creates the admin record.")
    elif admin.get("locked_until") or (admin.get("failed_logins") or 0) >= 3:
        print("NEXT STEP: scripts/admin_reset_password.py clears the lockout + sets a new password.")
    else:
        print("Admin record looks healthy. If the reset email isn't arriving, the issue is")
        print("most likely email delivery (check Spam, All Mail, same-domain routing above).")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/admin_diagnose.py <email>")
        sys.exit(1)
    sys.exit(asyncio.run(main(sys.argv[1])))
