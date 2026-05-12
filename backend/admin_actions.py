"""
Admin actions targeting other admins / users:
  - POST   /api/admin/admins/{admin_id}/send-password-reset
  - PATCH  /api/admin/admins/{admin_id}/role
  - POST   /api/admin/users/{user_id}/send-otp

All endpoints require role=super_admin (except /send-otp which any active admin
can call). Every action writes an audit-log entry.
"""
import datetime as dt
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from admin import require_role, write_audit
from admin_modules import require_module
from admin_password_reset import (
    COLL as RESET_TOKENS_COLL,
    TOKEN_LIFETIME_MIN,
    _build_reset_url,
    _hash_token,
    _iso,
    _now,
)
from email_service import EmailNotConfigured, render_admin_reset_email, send_email

log = logging.getLogger("admin_actions")

# Roles must stay in sync with admin.py:: Role = Literal["super_admin","manager","support"].
ALLOWED_ROLES = ("super_admin", "manager", "support")


class PushPasswordResetIn(BaseModel):
    """Optional alternate email — useful when the registered admin email
    is non-deliverable (e.g. same-domain Gmail routing). When set, the
    reset link is emailed to alternate_email instead of the registered one,
    but the token is still bound to the original admin account."""
    alternate_email: Optional[EmailStr] = None
    return_link: bool = Field(
        default=False,
        description=(
            "If true, also include the raw reset URL in the response body so "
            "the calling super-admin can copy it (useful when SMTP is broken). "
            "The link is one-shot and only meant for direct hand-off."
        ),
    )


class ChangeRoleIn(BaseModel):
    role: str = Field(..., description="One of: super_admin, admin, viewer")


class SendOtpToUserIn(BaseModel):
    phone: Optional[str] = Field(
        default=None,
        description="Override phone. If omitted, uses the user's registered phone.",
    )


def attach_admin_actions_routes(router: APIRouter, db, _attach_admin):
    """Mount admin-actions routes on an existing /api/admin router."""

    # ----- Push password reset to another admin -----
    @router.post("/admins/{admin_id}/send-password-reset")
    async def push_password_reset(
        admin_id: str,
        body: PushPasswordResetIn,
        request: Request,
        actor=Depends(_attach_admin),
        _check=Depends(require_module("admins")),
    ):
        target = await db.admins.find_one({"id": admin_id}, {"_id": 0, "password_hash": 0})
        if not target:
            raise HTTPException(404, "Admin not found")
        if not target.get("is_active", True):
            raise HTTPException(400, "Cannot send reset link to a deactivated admin")

        # Mint a token (same shape as the self-service /forgot-password flow).
        raw_token = secrets.token_urlsafe(32)
        await db[RESET_TOKENS_COLL].insert_one({
            "token_hash": _hash_token(raw_token),
            "admin_id": target["id"],
            "email": target["email"],
            "expires_at": _iso(_now() + dt.timedelta(minutes=TOKEN_LIFETIME_MIN)),
            "used_at": None,
            "created_at": _iso(_now()),
            "issued_by_admin_id": actor["id"],
            "issued_by_admin_email": actor["email"],
        })
        reset_url = _build_reset_url(raw_token)

        deliver_to = (body.alternate_email or target["email"]).strip().lower()
        text_body, html_body = render_admin_reset_email(reset_url, admin_name=target.get("name") or "Admin")
        email_status = "sent"
        email_error: Optional[str] = None
        try:
            send_email(
                to=deliver_to,
                subject="Reset your SquadPay admin password",
                text_body=text_body,
                html_body=html_body,
            )
        except EmailNotConfigured:
            email_status = "skipped"
            email_error = "EmailNotConfigured"
            log.error("[admin-actions] push reset: EMAIL_* env vars missing for admin_id=%s", target["id"])
        except Exception as e:  # noqa: BLE001
            email_status = "failed"
            email_error = str(e)[:200]
            log.exception("[admin-actions] push reset: SMTP failed for admin_id=%s", target["id"])

        await write_audit(
            db,
            admin_id=actor["id"],
            admin_email=actor["email"],
            action="admin_password_reset.pushed_by_admin",
            target_type="admin",
            target_id=target["id"],
            payload={
                "target_email": target["email"],
                "delivered_to": deliver_to,
                "alternate_email_used": bool(body.alternate_email),
                "email_status": email_status,
                "email_error": email_error,
                "expires_in_minutes": TOKEN_LIFETIME_MIN,
            },
            request=request,
        )

        out: dict = {
            "ok": True,
            "delivered_to": deliver_to,
            "email_status": email_status,
            "expires_in_minutes": TOKEN_LIFETIME_MIN,
        }
        if email_error:
            out["email_error"] = email_error
        # Only include the raw link when explicitly requested (default false)
        # OR when email failed (so the super-admin has a fallback).
        if body.return_link or email_status != "sent":
            out["reset_url"] = reset_url
            out["link_note"] = (
                "One-shot link, valid for 30 minutes. Hand-deliver carefully."
            )
        return out

    # ----- Change admin role -----
    @router.patch("/admins/{admin_id}/role")
    async def change_admin_role(
        admin_id: str,
        body: ChangeRoleIn,
        request: Request,
        actor=Depends(_attach_admin),
        _check=Depends(require_module("admins")),
    ):
        new_role = (body.role or "").strip().lower()
        if new_role not in ALLOWED_ROLES:
            raise HTTPException(400, f"role must be one of: {', '.join(ALLOWED_ROLES)}")

        target = await db.admins.find_one({"id": admin_id}, {"_id": 0, "password_hash": 0})
        if not target:
            raise HTTPException(404, "Admin not found")
        if target["id"] == actor["id"] and new_role != "super_admin":
            raise HTTPException(400, "You cannot demote your own super_admin account")

        old_role = target.get("role")
        if old_role == new_role:
            return {"ok": True, "role": new_role, "unchanged": True}

        # Last-super-admin protection: refuse to demote if this is the only
        # remaining active super_admin.
        if old_role == "super_admin" and new_role != "super_admin":
            other_supers = await db.admins.count_documents({
                "role": "super_admin",
                "is_active": True,
                "id": {"$ne": target["id"]},
            })
            if other_supers == 0:
                raise HTTPException(
                    400,
                    "Cannot demote the last active super_admin. Create another "
                    "super_admin first, then retry.",
                )

        await db.admins.update_one(
            {"id": admin_id},
            {"$set": {"role": new_role, "role_updated_at": _iso(_now())}},
        )
        await write_audit(
            db,
            admin_id=actor["id"],
            admin_email=actor["email"],
            action="admin_role.changed",
            target_type="admin",
            target_id=target["id"],
            payload={"from": old_role, "to": new_role, "target_email": target["email"]},
            request=request,
        )
        return {"ok": True, "admin_id": target["id"], "role": new_role, "previous_role": old_role}

    # ----- Push verification code (OTP) to a user -----
    @router.post("/users/{user_id}/send-otp")
    async def push_user_otp(
        user_id: str,
        body: SendOtpToUserIn,
        request: Request,
        actor=Depends(_attach_admin),
    ):
        # Any active admin (including viewer) — we let viewer trigger because
        # this is a customer-support action, not a privileged config change.
        # Audit log records who did it.
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        phone = (body.phone or user.get("phone") or "").strip()
        if not phone:
            raise HTTPException(400, "User has no phone on file. Pass `phone` explicitly to override.")
        if user.get("blocked") or user.get("is_blocked"):
            raise HTTPException(400, "User account is blocked.")

        from otp_helpers import generate_and_send_otp, build_otp_response
        try:
            code, sent_real, info, mode = await generate_and_send_otp(
                db=db,
                phone=phone,
                body_template="Your SquadPay verification code is {code}. Valid for 5 minutes.",
                purpose_label="admin-push-otp",
            )
        except Exception as e:  # noqa: BLE001
            await write_audit(
                db,
                admin_id=actor["id"],
                admin_email=actor["email"],
                action="user_otp.pushed_failed",
                target_type="user",
                target_id=user_id,
                payload={"phone": phone, "error": str(e)[:200]},
                request=request,
            )
            raise HTTPException(502, f"Failed to send OTP: {e}")

        # Persist the code as if the user had requested it themselves, so the
        # /auth/verify-otp endpoint can validate it on the next user action.
        from core import now_iso  # local helper used elsewhere
        await db.otp_codes.update_one(
            {"user_id": user_id},
            {"$set": {"phone": phone, "code": code, "created_at": now_iso(), "mode": mode}},
            upsert=True,
        )

        await write_audit(
            db,
            admin_id=actor["id"],
            admin_email=actor["email"],
            action="user_otp.pushed_by_admin",
            target_type="user",
            target_id=user_id,
            payload={
                "phone": phone,
                "mode": mode,
                "sent_real": sent_real,
                "info": info,
            },
            request=request,
        )

        out = build_otp_response(
            code, sent_real, info, mode,
            label_for_user="OTP",
            success_msg_live="OTP sent via SMS. Tell the user to check their phone.",
        )
        # If the code couldn't actually be sent in live mode, surface a 502 so
        # the admin UI can show an error rather than a fake success.
        if mode == "live" and not sent_real:
            raise HTTPException(502, detail=f"OTP generated but SMS send failed. {info}")
        return out
