"""Emergency password reset for an admin account.

Bypasses the email flow entirely — useful when the reset email isn't delivered
(e.g. same-domain Gmail routing, missing SMTP config) or when the account is
locked out and you need to get back in NOW.

Usage (run from /app/backend on the production server):
  python scripts/admin_reset_password.py <email> [<new_password>] [--force-reset]

If <new_password> is omitted, a strong random one is generated and printed once.
By default the new password works immediately (no further reset required).
Pass --force-reset to ALSO require the user to change their password on first
login (sets force_password_reset=true).

On success the script:
  - upserts the admin record (creates a super_admin if missing)
  - clears failed_logins, locked_until, lock_round
  - clears force_password_reset (unless --force-reset is passed)
  - invalidates all outstanding password reset tokens for this admin
  - kills all active admin sessions (force re-login on every device)
  - writes an audit log entry under action='admin_password_reset.cli_emergency'
"""
import asyncio
import datetime as dt
import hashlib
import os
import secrets
import string
import sys
from pathlib import Path

# Make /app/backend importable when this script is run as `python scripts/...`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(ROOT / ".env")

from admin import hash_password, write_audit  # noqa: E402

RESET_TOKENS_COLL = "admin_password_reset_tokens"
SESSIONS_COLL = "admin_sessions"


def _strong_random_password(n: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if (any(c.isupper() for c in pw)
                and any(c.islower() for c in pw)
                and any(c.isdigit() for c in pw)):
            return pw


def _validate(pw: str) -> str | None:
    if len(pw) < 10:
        return "Password must be at least 10 characters"
    if pw.lower() == pw or pw.upper() == pw:
        return "Password must include both upper- and lower-case letters"
    if not any(c.isdigit() for c in pw):
        return "Password must include at least one number"
    return None


async def main(email: str, new_password: str | None, force_reset: bool = False) -> int:
    email = email.strip().lower()
    if "@" not in email:
        print(f"❌ Invalid email: {email!r}")
        return 2

    if new_password is None:
        new_password = _strong_random_password(16)
        print(f"🔑 Generated random password: {new_password}")
        print("   (copy it now — it will not be shown again)")
    err = _validate(new_password)
    if err:
        print(f"❌ Weak password: {err}")
        return 2

    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("❌ MONGO_URL not set in environment")
        return 3
    db_name = os.environ.get("DB_NAME", "test_database")
    print(f"🔗 Connecting to db={db_name}")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    now_iso = dt.datetime.utcnow().isoformat()
    pw_hash = hash_password(new_password)

    existing = await db.admins.find_one({"email": email}, {"_id": 0})
    if existing:
        admin_id = existing["id"]
        await db.admins.update_one(
            {"id": admin_id},
            {"$set": {
                "password_hash": pw_hash,
                "failed_logins": 0,
                "locked_until": None,
                "lock_round": 0,
                "force_password_reset": bool(force_reset),
                "is_active": True,
                "password_updated_at": now_iso,
            }},
        )
        print(f"✅ Updated existing admin id={admin_id} role={existing.get('role')}")
    else:
        admin_id = "ad_" + hashlib.sha256(email.encode()).hexdigest()[:10]
        await db.admins.insert_one({
            "id": admin_id,
            "email": email,
            "name": email.split("@")[0].title(),
            "role": "super_admin",
            "password_hash": pw_hash,
            "is_active": True,
            "failed_logins": 0,
            "locked_until": None,
            "lock_round": 0,
            "force_password_reset": bool(force_reset),
            "password_updated_at": now_iso,
            "created_at": now_iso,
        })
        print(f"✅ Created new super_admin id={admin_id}")

    # Invalidate any outstanding reset tokens.
    rt = await db[RESET_TOKENS_COLL].update_many(
        {"admin_id": admin_id, "used_at": None},
        {"$set": {"used_at": now_iso}},
    )
    if rt.modified_count:
        print(f"🧹 Invalidated {rt.modified_count} outstanding reset token(s)")

    # Kill all active admin sessions (force re-login on every device).
    s = await db[SESSIONS_COLL].delete_many({"admin_id": admin_id})
    if s.deleted_count:
        print(f"🧹 Killed {s.deleted_count} active session(s)")

    try:
        await write_audit(
            db,
            admin_id="system",
            admin_email="system",
            action="admin_password_reset.cli_emergency",
            target_type="admin",
            target_id=admin_id,
            payload={"email": email, "force_password_reset": bool(force_reset)},
        )
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  audit log write failed: {e}")

    print("")
    print("✨ Done. Sign in at https://www.getsquadpay.com/admin/login with:")
    print(f"   email:    {email}")
    print(f"   password: {new_password}")
    if force_reset:
        print("   You will be prompted to change the password on first login (force_password_reset=True).")
    else:
        print("   This password works immediately. Pass --force-reset if you want to require a change on first login.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    force_reset = False
    if "--force-reset" in args:
        force_reset = True
        args = [a for a in args if a != "--force-reset"]
    if not args:
        print("Usage: python scripts/admin_reset_password.py <email> [<new_password>] [--force-reset]")
        sys.exit(1)
    email_arg = args[0]
    pw_arg = args[1] if len(args) > 1 else None
    sys.exit(asyncio.run(main(email_arg, pw_arg, force_reset=force_reset)))
