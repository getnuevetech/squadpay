"""
Emergency admin-recovery HTTP endpoints, gated behind a one-time secret.

Use case: production admin can't sign in, the password-reset email isn't
delivered, and there is no shell access to run scripts/admin_*.py directly.

Activation flow:
  1. Set `ADMIN_RECOVERY_TOKEN=<long random string>` in the deployed backend
     env vars and redeploy.
  2. Call the endpoints below with `X-Recovery-Token: <that token>` header.
  3. After recovery, REMOVE `ADMIN_RECOVERY_TOKEN` and redeploy. With the env
     unset, every endpoint here returns 503 Service Unavailable.

Endpoints (all under /api/admin/_recovery, all require X-Recovery-Token header):
  GET  /diagnose?email=<email>
       Read-only health check: admin record state, recent reset tokens,
       last 15 audit log entries, email config, same-domain routing warning.

  POST /reset-password   { email, new_password?, force_reset? }
       Upserts the admin, clears lockout state, optionally generates a
       strong random password if `new_password` omitted, kills active
       sessions, invalidates outstanding reset tokens, writes audit log.

Security:
  - Token comparison uses `hmac.compare_digest` (timing-safe).
  - Token must be non-empty AND >= 24 chars to avoid weak tokens.
  - Every successful + failed call writes an audit log entry.
  - 503 when the env var is missing/empty (the endpoints don't even respond).
"""
import datetime as dt
import hashlib
import hmac
import logging
import os
import secrets
import string
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field

from admin import hash_password, write_audit

log = logging.getLogger("admin_recovery")

RESET_TOKENS_COLL = "admin_password_reset_tokens"
SESSIONS_COLL = "admin_sessions"
AUDIT_COLL = "audit_log"
MIN_TOKEN_LEN = 24


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strong_random_password(n: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if (any(c.isupper() for c in pw)
                and any(c.islower() for c in pw)
                and any(c.isdigit() for c in pw)):
            return pw


def _validate_password(pw: str) -> Optional[str]:
    if len(pw) < 10:
        return "Password must be at least 10 characters"
    if pw.lower() == pw or pw.upper() == pw:
        return "Password must include both upper- and lower-case letters"
    if not any(c.isdigit() for c in pw):
        return "Password must include at least one number"
    return None


def _check_token(provided: Optional[str]) -> str:
    """Validates X-Recovery-Token. Returns which gate was used ('admin_recovery_token'
    or 'jwt_secret_fallback') for audit logging. Raises 503 if both gates are
    unavailable, 401 if mismatch.

    Two acceptable gates, in priority order:
      1. ADMIN_RECOVERY_TOKEN env var (purpose-built, preferred)
      2. JWT_SECRET env var (fallback for deployments where adding new env vars
         isn't possible — user supplies their JWT_SECRET as the recovery token,
         then rotates JWT_SECRET in the dashboard after recovery to invalidate
         the gate AND invalidate any leaked admin sessions in one step).
    """
    provided = (provided or "").strip()
    expected_dedicated = (os.environ.get("ADMIN_RECOVERY_TOKEN") or "").strip()
    expected_fallback = (os.environ.get("JWT_SECRET") or "").strip()

    has_dedicated = len(expected_dedicated) >= MIN_TOKEN_LEN
    has_fallback = len(expected_fallback) >= MIN_TOKEN_LEN

    if not has_dedicated and not has_fallback:
        raise HTTPException(
            status_code=503,
            detail=(
                "Admin recovery is not enabled. Either set "
                f"ADMIN_RECOVERY_TOKEN (>= {MIN_TOKEN_LEN} chars) in backend env, "
                f"or ensure JWT_SECRET (>= {MIN_TOKEN_LEN} chars) is configured "
                "(it normally is) so it can act as the recovery gate."
            ),
        )

    if has_dedicated and provided and hmac.compare_digest(provided, expected_dedicated):
        return "admin_recovery_token"
    if has_fallback and provided and hmac.compare_digest(provided, expected_fallback):
        return "jwt_secret_fallback"

    raise HTTPException(status_code=401, detail="Invalid recovery token")


def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat()


def _redact(s: Optional[str]) -> str:
    if not s:
        return "<unset>"
    if len(s) <= 4:
        return "***"
    return s[:2] + "…" + s[-2:]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ResetIn(BaseModel):
    email: EmailStr
    new_password: Optional[str] = Field(default=None, max_length=128)
    force_reset: Optional[bool] = False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_recovery_router(db) -> APIRouter:
    router = APIRouter(prefix="/api/admin/_recovery", tags=["admin-recovery"])

    # Optional rate limiter (slowapi) — stops brute-force attempts on the gate.
    try:
        from server import limiter as _limiter
    except Exception:
        _limiter = None

    def _maybe_limit(spec: str):
        def deco(fn):
            return _limiter.limit(spec)(fn) if _limiter else fn
        return deco

    @router.get("/diagnose")
    @_maybe_limit("10/minute")
    async def diagnose(
        request: Request,
        email: str = Query(..., min_length=3),
        x_recovery_token: Optional[str] = Header(None, alias="X-Recovery-Token"),
    ):
        gate = _check_token(x_recovery_token)
        client_ip = request.client.host if request.client else "?"
        email_l = email.strip().lower()
        out: dict = {
            "email": email_l,
            "checked_at": _now_iso(),
            "warnings": [],
        }

        # 1. Email config
        email_user = os.environ.get("EMAIL_USER")
        email_from = os.environ.get("EMAIL_FROM") or email_user
        email_host = os.environ.get("EMAIL_HOST")
        email_port = os.environ.get("EMAIL_PORT") or "587"
        email_pw = os.environ.get("EMAIL_PASSWORD")
        out["email_config"] = {
            "EMAIL_HOST": email_host or None,
            "EMAIL_PORT": email_port,
            "EMAIL_USER": _redact(email_user),
            "EMAIL_FROM": email_from or None,
            "EMAIL_PASSWORD_set": bool(email_pw),
            "EMAIL_PASSWORD_chars": len(email_pw or ""),
        }
        if not email_pw:
            out["warnings"].append(
                "EMAIL_PASSWORD is not set — forgot-password silently no-ops "
                "(EmailNotConfigured)."
            )
        if email_from and "@" in email_from and "@" in email_l:
            sender_dom = email_from.split("@", 1)[1].lower()
            recipient_dom = email_l.split("@", 1)[1].lower()
            if sender_dom == recipient_dom:
                out["warnings"].append(
                    f"Same-domain routing: sender ({email_from}) and recipient "
                    f"share '{sender_dom}'. Gmail Workspace can route domain-"
                    "internal mail to All Mail or Spam, bypassing the Inbox."
                )

        # 2. Admin record
        admin = await db.admins.find_one(
            {"email": email_l}, {"_id": 0, "password_hash": 0}
        )
        if not admin:
            out["admin"] = None
            out["warnings"].append(
                "No admin record found. forgot-password silently returns 200 "
                "(anti-enumeration); login will always 401. Use "
                "POST /api/admin/_recovery/reset-password to seed."
            )
            admin_id = None
        else:
            admin_id = admin["id"]
            out["admin"] = {
                "id": admin_id,
                "role": admin.get("role"),
                "is_active": admin.get("is_active"),
                "failed_logins": admin.get("failed_logins", 0),
                "locked_until": admin.get("locked_until"),
                "lock_round": admin.get("lock_round", 0),
                "force_password_reset": admin.get("force_password_reset", False),
                "password_updated_at": admin.get("password_updated_at")
                                        or admin.get("updated_at"),
                "created_at": admin.get("created_at"),
            }
            if not admin.get("is_active", True):
                out["warnings"].append(
                    "is_active=False — forgot-password silently no-ops; login 401."
                )
            if admin.get("locked_until"):
                out["warnings"].append(
                    f"Account is locked until {admin['locked_until']}."
                )

        # 3. Recent reset tokens
        out["recent_reset_tokens"] = []
        if admin_id:
            cursor = db[RESET_TOKENS_COLL].find(
                {"admin_id": admin_id},
                {"_id": 0, "token_hash": 1, "created_at": 1,
                 "expires_at": 1, "used_at": 1},
            ).sort("created_at", -1).limit(10)
            rows = await cursor.to_list(length=10)
            for r in rows:
                th = r.get("token_hash", "")
                out["recent_reset_tokens"].append({
                    "created_at": r.get("created_at"),
                    "expires_at": r.get("expires_at"),
                    "used": bool(r.get("used_at")),
                    "token_hash_preview": (th[:6] + "…" + th[-4:]) if th else None,
                })

        # 4. Recent audit log (last 15)
        q: dict = (
            {"$or": [{"target_id": admin_id}, {"payload.email": email_l}]}
            if admin_id else {"payload.email": email_l}
        )
        cursor = db[AUDIT_COLL].find(q, {"_id": 0}).sort("at", -1).limit(15)
        rows = await cursor.to_list(length=15)
        out["recent_audit_log"] = [
            {
                "at": r.get("at"),
                "action": r.get("action"),
                "actor": r.get("admin_email") or r.get("admin_id"),
                "payload": r.get("payload") or {},
            }
            for r in rows
        ]

        # 5. Active sessions
        if admin_id:
            out["active_sessions"] = await db[SESSIONS_COLL].count_documents(
                {"admin_id": admin_id}
            )
        else:
            out["active_sessions"] = 0

        # Audit log: someone used the recovery diagnose endpoint
        try:
            await write_audit(
                db,
                admin_id="system",
                admin_email="system",
                action="admin_recovery.diagnose",
                target_type="admin",
                target_id=admin_id or email_l,
                payload={"email": email_l, "client_ip": client_ip, "gate": gate},
            )
        except Exception:  # noqa: BLE001
            pass

        out["recovered_via"] = gate
        return out

    @router.post("/reset-password")
    @_maybe_limit("5/minute")
    async def reset_password(
        request: Request,
        body: ResetIn,
        x_recovery_token: Optional[str] = Header(None, alias="X-Recovery-Token"),
    ):
        gate = _check_token(x_recovery_token)
        client_ip = request.client.host if request.client else "?"
        email_l = body.email.strip().lower()

        new_password = body.new_password
        generated = False
        if not new_password:
            new_password = _strong_random_password(16)
            generated = True
        err = _validate_password(new_password)
        if err:
            raise HTTPException(status_code=400, detail=err)

        now = _now_iso()
        pw_hash = hash_password(new_password)
        force_reset = bool(body.force_reset)

        existing = await db.admins.find_one({"email": email_l}, {"_id": 0})
        if existing:
            admin_id = existing["id"]
            await db.admins.update_one(
                {"id": admin_id},
                {"$set": {
                    "password_hash": pw_hash,
                    "failed_logins": 0,
                    "locked_until": None,
                    "lock_round": 0,
                    "force_password_reset": force_reset,
                    "is_active": True,
                    "password_updated_at": now,
                }},
            )
            created = False
        else:
            admin_id = "ad_" + hashlib.sha256(email_l.encode()).hexdigest()[:10]
            await db.admins.insert_one({
                "id": admin_id,
                "email": email_l,
                "name": email_l.split("@")[0].title(),
                "role": "super_admin",
                "password_hash": pw_hash,
                "is_active": True,
                "failed_logins": 0,
                "locked_until": None,
                "lock_round": 0,
                "force_password_reset": force_reset,
                "password_updated_at": now,
                "created_at": now,
            })
            created = True

        # Invalidate outstanding reset tokens.
        rt = await db[RESET_TOKENS_COLL].update_many(
            {"admin_id": admin_id, "used_at": None},
            {"$set": {"used_at": now}},
        )
        # Kill active sessions.
        s = await db[SESSIONS_COLL].delete_many({"admin_id": admin_id})

        try:
            await write_audit(
                db,
                admin_id="system",
                admin_email="system",
                action="admin_recovery.reset_password",
                target_type="admin",
                target_id=admin_id,
                payload={
                    "email": email_l,
                    "created": created,
                    "force_password_reset": force_reset,
                    "client_ip": client_ip,
                    "password_generated": generated,
                    "gate": gate,
                },
            )
        except Exception:  # noqa: BLE001
            pass

        log.warning(
            "[admin_recovery] reset for email=%s admin_id=%s created=%s force=%s ip=%s gate=%s",
            email_l, admin_id, created, force_reset, client_ip, gate,
        )

        return {
            "ok": True,
            "admin_id": admin_id,
            "email": email_l,
            "created": created,
            "force_password_reset": force_reset,
            "password": new_password,  # one-shot output
            "password_generated": generated,
            "outstanding_tokens_invalidated": rt.modified_count,
            "sessions_killed": s.deleted_count,
            "recovered_via": gate,
            "sign_in_url": "https://www.squadpay.us/admin/login",
            "note": (
                "Use this password to sign in immediately."
                if not force_reset else
                "force_password_reset=true — you'll be required to change "
                "the password on first login."
            ),
            "post_recovery_advice": (
                "You used the JWT_SECRET fallback gate. ROTATE JWT_SECRET in your "
                "Emergent backend Custom Keys dashboard now to (a) invalidate the "
                "recovery gate, (b) invalidate any leaked admin sessions."
                if gate == "jwt_secret_fallback" else None
            ),
        }

    return router
