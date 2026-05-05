"""Admin endpoints for integrations (Phase D): Stripe + Twilio + Reminders."""
import datetime as dt
from typing import Optional, List, Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from admin import write_audit, require_role
from integrations import (
    encrypt_secret,
    get_integrations_doc,
    project_integrations_for_admin,
    send_sms_via_twilio,
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class StripeSettingsIn(BaseModel):
    enabled: bool
    mode: Literal["test", "live"] = "test"
    publishable_key: Optional[str] = None
    secret_key: Optional[str] = None  # write-only; only persisted if non-empty
    webhook_secret: Optional[str] = None


class TwilioSettingsIn(BaseModel):
    enabled: bool
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    from_number: Optional[str] = None


class ReminderSettingsIn(BaseModel):
    enabled: bool
    schedule_hours: List[int] = Field(default_factory=lambda: [24, 72, 168])
    max_reminders_per_user: int = Field(3, ge=1, le=10)
    send_via_sms: bool = True


class TestSmsIn(BaseModel):
    to_number: str
    body: Optional[str] = None


def attach_integrations_routes(router: APIRouter, db, attach_admin):

    @router.get("/integrations")
    async def get_integrations(admin=Depends(attach_admin)):
        rec = await get_integrations_doc(db)
        return project_integrations_for_admin(rec)

    # ===== STRIPE =====
    @router.post("/integrations/stripe")
    async def set_stripe(
        body: StripeSettingsIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        rec = await get_integrations_doc(db)
        s = dict(rec.get("stripe") or {})
        s["enabled"] = bool(body.enabled)
        s["mode"] = body.mode
        if body.publishable_key is not None:
            s["publishable_key"] = body.publishable_key.strip() or None
        if body.secret_key:
            s["secret_key_enc"] = encrypt_secret(body.secret_key.strip())
        if body.webhook_secret:
            s["webhook_secret_enc"] = encrypt_secret(body.webhook_secret.strip())
        s["updated_at"] = _now()
        s["updated_by"] = admin["email"]
        await db.app_settings.update_one(
            {"key": "integrations"}, {"$set": {"stripe": s}}, upsert=True
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.update_stripe_settings",
            target_type="settings",
            target_id="integrations.stripe",
            payload={
                "enabled": s["enabled"],
                "mode": s["mode"],
                "publishable_key_set": bool(s.get("publishable_key")),
                "secret_key_changed": bool(body.secret_key),
                "webhook_secret_changed": bool(body.webhook_secret),
            },
            request=request,
        )
        rec = await get_integrations_doc(db)
        return project_integrations_for_admin(rec)

    # ===== TWILIO =====
    @router.post("/integrations/twilio")
    async def set_twilio(
        body: TwilioSettingsIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        rec = await get_integrations_doc(db)
        t = dict(rec.get("twilio") or {})
        t["enabled"] = bool(body.enabled)
        if body.account_sid:
            t["account_sid_enc"] = encrypt_secret(body.account_sid.strip())
        if body.auth_token:
            t["auth_token_enc"] = encrypt_secret(body.auth_token.strip())
        if body.from_number is not None:
            t["from_number"] = body.from_number.strip() or None
        t["updated_at"] = _now()
        t["updated_by"] = admin["email"]
        await db.app_settings.update_one(
            {"key": "integrations"}, {"$set": {"twilio": t}}, upsert=True
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.update_twilio_settings",
            target_type="settings",
            target_id="integrations.twilio",
            payload={
                "enabled": t["enabled"],
                "from_number": t.get("from_number"),
                "sid_changed": bool(body.account_sid),
                "token_changed": bool(body.auth_token),
            },
            request=request,
        )
        rec = await get_integrations_doc(db)
        return project_integrations_for_admin(rec)

    @router.post("/integrations/twilio/test")
    async def test_twilio(
        body: TestSmsIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin", "manager")),
    ):
        msg = body.body or f"GroupPay Admin test SMS at {_now()}"
        sent_real, info = await send_sms_via_twilio(db, body.to_number, msg)
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.test_twilio",
            target_type="settings",
            target_id="integrations.twilio",
            payload={"to": body.to_number, "sent_real": sent_real, "info": info},
            request=request,
        )
        return {"sent_real": sent_real, "info": info}

    # ===== REMINDERS =====
    @router.post("/integrations/reminders")
    async def set_reminders(
        body: ReminderSettingsIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin", "manager")),
    ):
        # Validate schedule_hours
        sched = sorted({int(h) for h in body.schedule_hours if int(h) > 0})[:10]
        if not sched:
            sched = [24, 72, 168]
        r = {
            "enabled": bool(body.enabled),
            "schedule_hours": sched,
            "max_reminders_per_user": int(body.max_reminders_per_user),
            "send_via_sms": bool(body.send_via_sms),
            "updated_at": _now(),
            "updated_by": admin["email"],
        }
        await db.app_settings.update_one(
            {"key": "integrations"}, {"$set": {"reminders": r}}, upsert=True
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.update_reminder_settings",
            target_type="settings",
            target_id="integrations.reminders",
            payload=r,
            request=request,
        )
        rec = await get_integrations_doc(db)
        return project_integrations_for_admin(rec)

    @router.post("/integrations/reminders/run-now")
    async def reminders_run_now(
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin", "manager")),
    ):
        from reminders import run_reminder_pass
        result = await run_reminder_pass(db, force=True)
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.run_reminders_now",
            target_type="settings",
            target_id="integrations.reminders",
            payload=result,
            request=request,
        )
        return result
