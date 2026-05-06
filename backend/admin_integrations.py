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


class SignalWireSettingsIn(BaseModel):
    enabled: bool
    project_id: Optional[str] = None
    api_token: Optional[str] = None
    space_url: Optional[str] = None
    from_number: Optional[str] = None


class SmsRoutingIn(BaseModel):
    primary: Literal["twilio", "signalwire"] = "twilio"
    fallback: Optional[Literal["twilio", "signalwire"]] = None


class ReminderSettingsIn(BaseModel):
    enabled: bool
    schedule_hours: List[int] = Field(default_factory=lambda: [24, 72, 168])
    max_reminders_per_user: int = Field(3, ge=1, le=10)
    send_via_sms: bool = True


class IssuingSettingsIn(BaseModel):
    enabled: Optional[bool] = None
    cardholder_name: Optional[str] = None
    card_disable_mode: Optional[Literal["auto", "manual"]] = None
    require_otp_for_card_reveal: Optional[bool] = None
    reveal_ttl_seconds: Optional[int] = None
    webhook_secret: Optional[str] = None  # Phase F2.1 — Stripe Issuing webhook signing
    require_lead_kyc: Optional[bool] = None  # Phase G3 — per-lead cardholder mode
    apple_pay_enrolled: Optional[bool] = None  # Phase G4 — push-provisioning gating
    google_pay_enrolled: Optional[bool] = None  # Phase G4 — push-provisioning gating


class FeatureTogglesIn(BaseModel):
    credits_enabled: Optional[bool] = None
    invite_friends_enabled: Optional[bool] = None


class TestSmsIn(BaseModel):
    to_number: str
    body: Optional[str] = None


def attach_integrations_routes(router: APIRouter, db, attach_admin):

    @router.get("/integrations")
    async def get_integrations(admin=Depends(attach_admin)):
        rec = await get_integrations_doc(db)
        from sms_providers import project_sms_for_admin
        return {**project_integrations_for_admin(rec), **project_sms_for_admin(rec)}

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

    # ===== SIGNALWIRE (Phase F2.2) =====
    @router.post("/integrations/signalwire")
    async def set_signalwire(
        body: SignalWireSettingsIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        rec = await get_integrations_doc(db)
        sw = dict(rec.get("signalwire") or {})
        sw["enabled"] = bool(body.enabled)
        if body.project_id:
            sw["project_id_enc"] = encrypt_secret(body.project_id.strip())
        if body.api_token:
            sw["api_token_enc"] = encrypt_secret(body.api_token.strip())
        if body.space_url is not None:
            cleaned = (body.space_url or "").strip().replace("https://", "").replace("http://", "").rstrip("/")
            sw["space_url"] = cleaned or None
        if body.from_number is not None:
            sw["from_number"] = body.from_number.strip() or None
        # Phase H5 — UX guard: if everything required is present (project, token,
        # space, from_number) and the admin tried to save with `enabled=false`
        # WHILE leaving creds untouched, that's a strong sign they actually meant
        # "yes, enable". Auto-flip to True so the test/SMS endpoints don't fail
        # with the misleading "SignalWire not enabled". They can still explicitly
        # disable by toggling AND saving a sentinel — done via a separate disable
        # call from the admin UI or by editing the DB.
        if (
            sw.get("project_id_enc")
            and sw.get("api_token_enc")
            and sw.get("space_url")
            and sw.get("from_number")
            and not sw.get("enabled")
            and not body.project_id  # keys didn't change → admin probably forgot the toggle
            and not body.api_token
        ):
            sw["enabled"] = True
        sw["updated_at"] = _now()
        sw["updated_by"] = admin["email"]
        await db.app_settings.update_one(
            {"key": "integrations"}, {"$set": {"signalwire": sw}}, upsert=True
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.update_signalwire_settings",
            target_type="settings",
            target_id="integrations.signalwire",
            payload={
                "enabled": sw["enabled"],
                "space_url": sw.get("space_url"),
                "from_number": sw.get("from_number"),
                "project_changed": bool(body.project_id),
                "token_changed": bool(body.api_token),
            },
            request=request,
        )
        rec = await get_integrations_doc(db)
        from sms_providers import project_sms_for_admin
        return {**project_integrations_for_admin(rec), **project_sms_for_admin(rec)}

    @router.post("/integrations/signalwire/test")
    async def test_signalwire(
        body: TestSmsIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin", "manager")),
    ):
        msg = body.body or f"KWIKPAY SignalWire test SMS at {_now()}"
        from sms_providers import _send_via_signalwire
        rec = await get_integrations_doc(db)
        # Phase H5 — Test SMS UX: if the admin explicitly clicks "Test", we want
        # to try the call even when the integration is currently disabled. Force
        # `enabled=True` on a copy of the record purely for this attempt — DB stays
        # untouched. This way the admin sees the *real* network result (e.g. invalid
        # token, 401 Unauthorized) instead of the misleading "not enabled".
        rec_for_test = dict(rec)
        sw_copy = dict(rec.get("signalwire") or {})
        sw_copy["enabled"] = True
        rec_for_test["signalwire"] = sw_copy
        sent_real, info = await _send_via_signalwire(rec_for_test, body.to_number, msg)
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.test_signalwire",
            target_type="settings",
            target_id="integrations.signalwire",
            payload={"to": body.to_number, "sent_real": sent_real, "info": info},
            request=request,
        )
        return {"sent_real": sent_real, "info": info}

    # ===== SMS ROUTING (primary / fallback) =====
    @router.post("/integrations/sms-routing")
    async def set_sms_routing(
        body: SmsRoutingIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        rec = await get_integrations_doc(db)
        routing = dict(rec.get("sms_routing") or {})
        routing["primary"] = body.primary
        routing["fallback"] = body.fallback if body.fallback != body.primary else None
        routing["updated_at"] = _now()
        routing["updated_by"] = admin["email"]
        await db.app_settings.update_one(
            {"key": "integrations"}, {"$set": {"sms_routing": routing}}, upsert=True
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.update_sms_routing",
            target_type="settings",
            target_id="integrations.sms_routing",
            payload=routing,
            request=request,
        )
        rec = await get_integrations_doc(db)
        from sms_providers import project_sms_for_admin
        return {**project_integrations_for_admin(rec), **project_sms_for_admin(rec)}

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

    # ===== ISSUING (Phase F1) =====
    @router.get("/integrations/issuing")
    async def get_issuing(admin=Depends(attach_admin)):
        from issuing import get_issuing_settings
        s = await get_issuing_settings(db)
        # Never return the raw encrypted blob to the client
        s.pop("webhook_secret_enc", None)
        return s

    @router.post("/integrations/issuing")
    async def set_issuing(
        body: IssuingSettingsIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        from issuing import set_issuing_settings
        patch = {k: v for k, v in body.dict().items() if v is not None}
        new = await set_issuing_settings(db, patch)
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.update_issuing_settings",
            target_type="settings",
            target_id="integrations.issuing",
            payload=patch,
            request=request,
        )
        return new

    @router.post("/groups/{group_id}/disable-card")
    async def admin_disable_group_card(
        group_id: str,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin", "manager")),
    ):
        from issuing import disable_group_card
        try:
            vc = await disable_group_card(
                db, group_id,
                by=admin.get("email") or admin.get("id") or "admin",
                reason="manual admin disable",
            )
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.disable_virtual_card",
            target_type="group",
            target_id=group_id,
            payload={"stripe_card_id": vc.get("stripe_card_id"), "last4": vc.get("last4")},
            request=request,
        )
        return {"ok": True, "virtual_card": vc}

    # ===== FEATURE TOGGLES (app-wide on/off flags) =====
    @router.get("/features")
    async def admin_get_features(admin=Depends(attach_admin)):
        rec = await db.app_settings.find_one({"key": "features"}, {"_id": 0}) or {}
        return {
            "credits_enabled": rec.get("credits_enabled", True),
            "invite_friends_enabled": rec.get("invite_friends_enabled", True),
            "updated_at": rec.get("updated_at"),
            "updated_by": rec.get("updated_by"),
        }

    @router.post("/features")
    async def admin_set_features(
        body: FeatureTogglesIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        patch = {k: v for k, v in body.dict().items() if v is not None}
        patch["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        patch["updated_by"] = admin.get("email")
        await db.app_settings.update_one(
            {"key": "features"},
            {"$set": patch},
            upsert=True,
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.update_features",
            target_type="settings",
            target_id="features",
            payload=patch,
            request=request,
        )
        rec = await db.app_settings.find_one({"key": "features"}, {"_id": 0}) or {}
        return rec
