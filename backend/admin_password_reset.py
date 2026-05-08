"""
Admin password reset routes.

Flow:
  POST /api/admin/auth/forgot-password { email }      → emails a reset link (idempotent, always 200)
  POST /api/admin/auth/reset-password  { token, new_password }  → consumes token, sets new password

Tokens are stored in `admin_password_reset_tokens` with:
  - token_hash    : sha256 of the URL-safe token (we never store the raw token)
  - admin_id      : id of the admin
  - expires_at    : ISO-8601 UTC, 30 minutes from creation
  - used_at       : ISO-8601 UTC when consumed (single-use)
  - created_at    : ISO-8601 UTC

Security notes:
  - We always return 200 from `forgot-password` even if the email is unknown,
    so we don't leak which emails are admins (enumeration defense).
  - We rate-limit per email to 3 requests / 15 min.
  - We hash the token at rest. The raw token only ever exists in the email link.
  - On successful reset, we invalidate ALL outstanding tokens for that admin and
    also kill any active sessions (forces re-login from all devices).
"""

from __future__ import annotations
import datetime as dt
import hashlib
import logging
import os
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from admin import hash_password, write_audit
from email_service import EmailNotConfigured, render_admin_reset_email, send_email

log = logging.getLogger("admin_password_reset")

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth-reset"])

TOKEN_LIFETIME_MIN = 30
RATE_LIMIT_WINDOW_MIN = 15
RATE_LIMIT_MAX = 3
COLL = "admin_password_reset_tokens"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(d: dt.datetime) -> str:
    return d.isoformat()


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_reset_url(token: str) -> str:
    base = (os.environ.get("ADMIN_RESET_BASE_URL") or "https://www.squadpay.us").rstrip("/")
    return f"{base}/admin/reset-password?token={token}"


def _password_strong_enough(pw: str) -> Optional[str]:
    """Return a friendly error message if the password is weak, else None."""
    if len(pw) < 10:
        return "Password must be at least 10 characters"
    if pw.lower() == pw or pw.upper() == pw:
        return "Password must include both upper- and lower-case letters"
    if not any(c.isdigit() for c in pw):
        return "Password must include at least one number"
    return None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=10, max_length=128)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordIn, request: Request):
    db = request.app.state.db
    email = payload.email.strip().lower()

    # Always-200 response template (defense against email enumeration).
    generic_ok = {"ok": True, "message": "If that email is an admin, a reset link is on its way."}

    admin = await db.admins.find_one({"email": email}, {"_id": 0})
    if not admin or not admin.get("is_active", True):
        # Log but don't leak.
        log.info("[reset] forgot-password for unknown/inactive email=%s — returning generic ok", email)
        return generic_ok

    # Rate-limit: max RATE_LIMIT_MAX requests per RATE_LIMIT_WINDOW_MIN per admin.
    window_start = _now() - dt.timedelta(minutes=RATE_LIMIT_WINDOW_MIN)
    recent = await db[COLL].count_documents({
        "admin_id": admin["id"],
        "created_at": {"$gte": _iso(window_start)},
    })
    if recent >= RATE_LIMIT_MAX:
        log.warning("[reset] rate limit hit for admin_id=%s recent=%s", admin["id"], recent)
        # Still reply with the generic success message (don't leak rate-limit info).
        return generic_ok

    # Generate a fresh token, store its hash.
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = _now() + dt.timedelta(minutes=TOKEN_LIFETIME_MIN)
    await db[COLL].insert_one({
        "token_hash": token_hash,
        "admin_id": admin["id"],
        "email": email,
        "expires_at": _iso(expires_at),
        "used_at": None,
        "created_at": _iso(_now()),
    })

    # Build the email and send it.
    reset_url = _build_reset_url(raw_token)
    text_body, html_body = render_admin_reset_email(reset_url, admin_name=admin.get("name") or "Admin")
    try:
        send_email(
            to=email,
            subject="Reset your SquadPay admin password",
            text_body=text_body,
            html_body=html_body,
        )
    except EmailNotConfigured:
        log.error("[reset] EMAIL_* env vars missing — cannot send reset email")
        # In production we still 200 to avoid leakage, but record the audit so admins notice.
        await write_audit(db, actor_admin_id="system", action="admin_password_reset.email_skipped",
                          target_type="admin", target_id=admin["id"], meta={"reason": "EmailNotConfigured"})
        return generic_ok
    except Exception as e:  # noqa: BLE001
        log.exception("[reset] SMTP send failed: %s", e)
        # Same — don't leak. Operator sees this in logs/audit.
        await write_audit(db, actor_admin_id="system", action="admin_password_reset.email_failed",
                          target_type="admin", target_id=admin["id"], meta={"error": str(e)[:200]})
        return generic_ok

    await write_audit(db, actor_admin_id="system", action="admin_password_reset.email_sent",
                      target_type="admin", target_id=admin["id"], meta={"email": email})
    return generic_ok


@router.get("/reset-password/validate")
async def validate_reset_token(token: str, request: Request):
    """Cheap pre-check used by the reset page to decide whether to show 'link expired'."""
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")
    db = request.app.state.db
    rec = await db[COLL].find_one({"token_hash": _hash_token(token)}, {"_id": 0})
    if not rec or rec.get("used_at"):
        return {"valid": False, "reason": "invalid_or_used"}
    try:
        exp = dt.datetime.fromisoformat(rec["expires_at"])
    except Exception:  # noqa: BLE001
        return {"valid": False, "reason": "invalid"}
    if exp < _now():
        return {"valid": False, "reason": "expired"}
    return {"valid": True}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordIn, request: Request):
    db = request.app.state.db
    pw_err = _password_strong_enough(payload.new_password)
    if pw_err:
        raise HTTPException(status_code=400, detail=pw_err)

    rec = await db[COLL].find_one({"token_hash": _hash_token(payload.token)}, {"_id": 0})
    if not rec or rec.get("used_at"):
        raise HTTPException(status_code=400, detail="This reset link has already been used or is invalid")
    try:
        exp = dt.datetime.fromisoformat(rec["expires_at"])
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid token") from None
    if exp < _now():
        raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new one.")

    admin_id = rec["admin_id"]
    admin = await db.admins.find_one({"id": admin_id}, {"_id": 0})
    if not admin or not admin.get("is_active", True):
        raise HTTPException(status_code=400, detail="Account not found or disabled")

    # Update password.
    await db.admins.update_one(
        {"id": admin_id},
        {"$set": {"password_hash": hash_password(payload.new_password),
                  "password_updated_at": _iso(_now())}}
    )
    # Mark this token used and invalidate every other outstanding token for the same admin.
    await db[COLL].update_many(
        {"admin_id": admin_id, "used_at": None},
        {"$set": {"used_at": _iso(_now())}}
    )
    # Kill all admin sessions so they have to re-login on every device.
    try:
        await db.admin_sessions.delete_many({"admin_id": admin_id})
    except Exception:  # noqa: BLE001
        pass  # collection may not exist if sessions are JWT-only

    await write_audit(db, actor_admin_id="system", action="admin_password_reset.completed",
                      target_type="admin", target_id=admin_id, meta={})
    return {"ok": True, "message": "Password updated. Please sign in with your new password."}
