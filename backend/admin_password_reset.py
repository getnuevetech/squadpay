"""
Admin password reset routes (factory-style, matches the rest of /backend).

Flow:
  POST /api/admin/auth/forgot-password { email }      → emails a reset link (idempotent, always 200)
  GET  /api/admin/auth/reset-password/validate?token   → cheap pre-check for the reset page
  POST /api/admin/auth/reset-password  { token, new_password }  → consumes token, sets new password

Tokens are stored in `admin_password_reset_tokens` with:
  - token_hash, admin_id, email, expires_at, used_at, created_at

Security:
  - Always returns 200 from `forgot-password` even on unknown emails (enumeration defense).
  - Per-admin rate limit: 3 reset requests / 15 min.
  - Tokens are hashed at rest. Raw token only ever exists in the email link.
  - On reset, all outstanding tokens for the admin are invalidated AND any active
    sessions are killed (force re-login on every device).
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
# Factory
# ---------------------------------------------------------------------------

def build_password_reset_router(db) -> APIRouter:
    router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth-reset"])

    @router.post("/forgot-password")
    async def forgot_password(payload: ForgotPasswordIn, request: Request):
        email = payload.email.strip().lower()

        # Always-200 envelope (defense against email enumeration).
        generic_ok = {"ok": True, "message": "If that email is an admin, a reset link is on its way."}

        admin = await db.admins.find_one({"email": email}, {"_id": 0})
        if not admin or not admin.get("is_active", True):
            log.info("[reset] forgot-password unknown/inactive email=%s — generic ok", email)
            return generic_ok

        # Per-admin rate limit
        window_start = _now() - dt.timedelta(minutes=RATE_LIMIT_WINDOW_MIN)
        recent = await db[COLL].count_documents({
            "admin_id": admin["id"],
            "created_at": {"$gte": _iso(window_start)},
        })
        if recent >= RATE_LIMIT_MAX:
            log.warning("[reset] rate limit hit for admin_id=%s recent=%s", admin["id"], recent)
            return generic_ok

        raw_token = secrets.token_urlsafe(32)
        await db[COLL].insert_one({
            "token_hash": _hash_token(raw_token),
            "admin_id": admin["id"],
            "email": email,
            "expires_at": _iso(_now() + dt.timedelta(minutes=TOKEN_LIFETIME_MIN)),
            "used_at": None,
            "created_at": _iso(_now()),
        })

        reset_url = _build_reset_url(raw_token)
        text_body, html_body = render_admin_reset_email(reset_url, admin_name=admin.get("name") or "Admin")
        try:
            send_email(
                to=email,
                subject="Reset your SquadPay admin password",
                text_body=text_body,
                html_body=html_body,
            )
            await write_audit(db, admin_id="system", admin_email="system", action="admin_password_reset.email_sent",
                              target_type="admin", target_id=admin["id"], payload={"email": email})
        except EmailNotConfigured:
            log.error("[reset] EMAIL_* env vars missing — cannot send reset email")
            await write_audit(db, admin_id="system", admin_email="system", action="admin_password_reset.email_skipped",
                              target_type="admin", target_id=admin["id"], payload={"reason": "EmailNotConfigured"})
        except Exception as e:  # noqa: BLE001
            log.exception("[reset] SMTP send failed: %s", e)
            await write_audit(db, admin_id="system", admin_email="system", action="admin_password_reset.email_failed",
                              target_type="admin", target_id=admin["id"], payload={"error": str(e)[:200]})

        return generic_ok

    @router.get("/reset-password/validate")
    async def validate_reset_token(token: str, request: Request):
        if not token:
            raise HTTPException(status_code=400, detail="Missing token")
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

        await db.admins.update_one(
            {"id": admin_id},
            {"$set": {"password_hash": hash_password(payload.new_password),
                      "password_updated_at": _iso(_now())}}
        )
        # Invalidate ALL outstanding tokens for the admin (single-use + cleanup).
        await db[COLL].update_many(
            {"admin_id": admin_id, "used_at": None},
            {"$set": {"used_at": _iso(_now())}}
        )
        # Kill all admin sessions if the project tracks them server-side.
        try:
            await db.admin_sessions.delete_many({"admin_id": admin_id})
        except Exception:  # noqa: BLE001
            pass

        await write_audit(db, admin_id="system", admin_email="system", action="admin_password_reset.completed",
                          target_type="admin", target_id=admin_id, payload={})
        return {"ok": True, "message": "Password updated. Please sign in with your new password."}

    return router
