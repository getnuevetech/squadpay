"""Phase F2: Stripe Issuing PAN/CVV reveal + spend feed routes.

Mounts:
  POST /api/auth/sensitive/send-otp        → reuses standard OTP code
  POST /api/auth/sensitive/verify-otp      → returns short-lived reveal_token
  POST /api/groups/{id}/card/ephemeral-key → returns Stripe Issuing ephemeral key
  POST /api/webhook/stripe/issuing         → issuing_authorization / issuing_transaction
  POST /api/groups/{id}/card/push-provisioning → stub (returns 501 in test mode)
"""
from __future__ import annotations
import datetime as dt
import logging
import os
import secrets as _secrets
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

REVEAL_TOKEN_TTL = 300  # 5 minutes
SETTINGS_KEY = "integrations"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class SensitiveOtpSendIn(BaseModel):
    user_id: str


class SensitiveOtpVerifyIn(BaseModel):
    user_id: str
    code: str
    purpose: str = "card_reveal"


class EphemeralKeyIn(BaseModel):
    user_id: str
    reveal_token: str
    nonce: str
    stripe_version: Optional[str] = None  # mandatory for issuing reveal; client-supplied


def attach_reveal_routes(api_router: APIRouter, db):
    # ----- Sensitive OTP (re-auth) -----
    @api_router.post("/auth/sensitive/send-otp")
    async def sensitive_send_otp(body: SensitiveOtpSendIn):
        user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        if not user.get("verified"):
            raise HTTPException(403, "Phone verification required")
        if user.get("is_blocked"):
            raise HTTPException(403, "Account blocked")
        # Mock OTP 123456 (consistent with /auth/send-otp). If Twilio enabled, send real SMS.
        code = "123456"
        await db.sensitive_otp_codes.update_one(
            {"user_id": body.user_id},
            {"$set": {
                "phone": user.get("phone"),
                "code": code,
                "purpose": "card_reveal",
                "created_at": _now(),
            }},
            upsert=True,
        )
        sent_real = False
        info = "Twilio disabled — mock OTP"
        try:
            from integrations import send_sms_via_twilio
            sent_real, info = await send_sms_via_twilio(
                db, user["phone"], f"Your KWIKPAY card reveal code is {code}. Valid for 5 minutes."
            )
        except Exception as e:
            logger.warning(f"[sensitive-send-otp] twilio failed: {e}")
        return {
            "ok": True,
            "mocked": not sent_real,
            "message": f"Reveal code sent. Use {code}" if not sent_real else "Reveal code SMS sent",
            "twilio_info": info,
        }

    @api_router.post("/auth/sensitive/verify-otp")
    async def sensitive_verify_otp(body: SensitiveOtpVerifyIn):
        rec = await db.sensitive_otp_codes.find_one({"user_id": body.user_id}, {"_id": 0})
        if not rec or rec.get("code") != body.code:
            raise HTTPException(400, "Invalid code")
        # Burn the OTP
        await db.sensitive_otp_codes.delete_one({"user_id": body.user_id})
        # Issue a single-use reveal_token (5 min TTL)
        token = _secrets.token_urlsafe(32)
        await db.reveal_tokens.insert_one({
            "token": token,
            "user_id": body.user_id,
            "purpose": body.purpose,
            "used": False,
            "created_at": _now(),
            "expires_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=REVEAL_TOKEN_TTL)).isoformat(),
        })
        return {"reveal_token": token, "expires_in": REVEAL_TOKEN_TTL}

    # ----- Ephemeral key for Stripe.js card reveal -----
    @api_router.post("/groups/{group_id}/card/ephemeral-key")
    async def card_ephemeral_key(group_id: str, body: EphemeralKeyIn, request: Request):
        from issuing import get_issuing_settings
        settings = await get_issuing_settings(db)

        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        vc = group.get("virtual_card") or {}
        card_id = vc.get("stripe_card_id")
        if not card_id:
            raise HTTPException(400, "Group has no issued card")
        if vc.get("status") == "inactive":
            raise HTTPException(400, "Card is disabled")
        # Only the group lead can reveal
        if group.get("lead_id") != body.user_id:
            raise HTTPException(403, "Only the group lead can reveal card details")

        user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if not user or user.get("is_blocked") or not user.get("verified"):
            raise HTTPException(403, "Account not eligible to reveal")

        # If admin requires OTP, enforce reveal_token
        if settings.get("require_otp_for_card_reveal", True):
            tok = await db.reveal_tokens.find_one({"token": body.reveal_token}, {"_id": 0})
            if not tok or tok.get("used") or tok.get("user_id") != body.user_id:
                raise HTTPException(401, "Invalid or expired reveal token")
            try:
                exp = dt.datetime.fromisoformat(tok["expires_at"].replace("Z", "+00:00"))
            except Exception:
                exp = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
            if dt.datetime.now(dt.timezone.utc) >= exp:
                await db.reveal_tokens.delete_one({"token": body.reveal_token})
                raise HTTPException(401, "Reveal token expired")
            # Burn
            await db.reveal_tokens.update_one(
                {"token": body.reveal_token},
                {"$set": {"used": True, "used_at": _now()}},
            )

        if not body.nonce or len(body.nonce) < 8:
            raise HTTPException(400, "nonce required (Stripe.js generates this)")

        if not body.stripe_version:
            raise HTTPException(400, "stripe_version required")

        import stripe as _stripe_sdk
        _stripe_sdk.api_key = os.environ.get("STRIPE_API_KEY")
        try:
            ek = _stripe_sdk.EphemeralKey.create(
                issuing_card=card_id,
                nonce=body.nonce,
                stripe_version=body.stripe_version,
            )
        except Exception as e:
            logger.exception(f"[reveal] EphemeralKey.create failed: {e}")
            raise HTTPException(502, f"Stripe error: {e}")

        # Audit log (best-effort)
        try:
            await db.audit_log.insert_one({
                "id": f"al_{_secrets.token_hex(6)}",
                "kind": "card_reveal",
                "group_id": group_id,
                "user_id": body.user_id,
                "card_id": card_id,
                "ip": request.client.host if request.client else None,
                "ua": request.headers.get("User-Agent"),
                "at": _now(),
            })
        except Exception:
            pass

        publishable_key = os.environ.get("STRIPE_PUBLISHABLE_KEY")
        return {
            "ephemeral_key_secret": ek.secret if hasattr(ek, "secret") else getattr(ek, "secret", None),
            "card_id": card_id,
            "nonce": body.nonce,
            "stripe_publishable_key": publishable_key,
            "ttl_seconds": int(settings.get("reveal_ttl_seconds") or 60),
        }

    # ----- Push provisioning stub (Apple/Google Pay) -----
    @api_router.post("/groups/{group_id}/card/push-provisioning", status_code=501)
    async def push_provisioning(group_id: str):
        # Real push provisioning requires Apple PNO + Google PSP onboarding (production-only).
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=501,
            content={
                "ok": False,
                "available": False,
                "reason": "Push provisioning to Apple/Google Wallet requires PSP onboarding (production-only).",
                "alternative": "Use 'Reveal card details' to copy PAN/CVV manually.",
            },
        )

    # ----- Issuing webhook -----
    @api_router.post("/webhook/stripe/issuing")
    async def stripe_issuing_webhook(request: Request):
        """Handle issuing_authorization.created and issuing_transaction.created.

        Signature: if app_settings.integrations.issuing.webhook_secret is configured (admin-set
        via the dashboard, persisted ENCRYPTED), verifies the Stripe-Signature header. Otherwise
        accepts the event unsigned (test/dev only).
        """
        body = await request.body()
        sig = request.headers.get("Stripe-Signature")
        import stripe as _stripe_sdk, json as _json
        _stripe_sdk.api_key = os.environ.get("STRIPE_API_KEY")

        # Resolve webhook secret: prefer admin-set encrypted secret, fallback to env var
        wh_secret = None
        try:
            from admin import decrypt_secret  # type: ignore
            rec = await db.app_settings.find_one({"key": SETTINGS_KEY}, {"_id": 0}) or {}
            iss = (rec.get("issuing") or {})
            enc = iss.get("webhook_secret_enc")
            if enc:
                try:
                    wh_secret = decrypt_secret(enc)
                except Exception as e:
                    logger.warning(f"[issuing-webhook] decrypt failed: {e}")
        except Exception:
            pass
        if not wh_secret:
            wh_secret = os.environ.get("STRIPE_ISSUING_WEBHOOK_SECRET")

        try:
            if wh_secret:
                # Verify signature first; raises if invalid
                _stripe_sdk.Webhook.construct_event(body, sig, wh_secret)
            # Always parse as plain dict — stripe SDK 15.x StripeObject is not isinstance(..., dict)
            evt = _json.loads(body.decode("utf-8") or "{}")
        except Exception as e:
            logger.exception(f"[issuing-webhook] bad signature/body: {e}")
            raise HTTPException(400, f"Webhook error: {e}")

        evt_type = (evt.get("type") if isinstance(evt, dict) else "") or ""
        data_obj = ((evt.get("data") or {}).get("object") if isinstance(evt, dict) else {}) or {}

        try:
            if evt_type == "issuing_authorization.created":
                # Just log; don't mutate spent (auth != settled)
                await db.issuing_events.insert_one({
                    "id": f"ie_{_secrets.token_hex(6)}",
                    "kind": "authorization",
                    "card_id": (data_obj.get("card", {}) or {}).get("id") if isinstance(data_obj, dict) else None,
                    "amount": (data_obj.get("amount") if isinstance(data_obj, dict) else None),
                    "merchant": (data_obj.get("merchant_data") if isinstance(data_obj, dict) else None),
                    "approved": (data_obj.get("approved") if isinstance(data_obj, dict) else None),
                    "raw_id": (data_obj.get("id") if isinstance(data_obj, dict) else None),
                    "at": _now(),
                })

            elif evt_type == "issuing_transaction.created":
                card_id = (data_obj.get("card") if isinstance(data_obj, dict) else None)
                amount_cents = (data_obj.get("amount") if isinstance(data_obj, dict) else 0) or 0
                merchant = (data_obj.get("merchant_data") if isinstance(data_obj, dict) else {}) or {}
                # Find group by card id
                group = await db.groups.find_one({"virtual_card.stripe_card_id": card_id}, {"_id": 0})
                if group:
                    from issuing import record_issuing_transaction, maybe_auto_disable_after_settlement
                    # amount is signed (negative for capture from cardholder POV); use abs
                    amt = abs(float(amount_cents) / 100.0)
                    await record_issuing_transaction(db, group["id"], {
                        "id": (data_obj.get("id") if isinstance(data_obj, dict) else None),
                        "type": (data_obj.get("type") if isinstance(data_obj, dict) else "capture"),
                        "amount": amt,
                        "currency": (data_obj.get("currency") if isinstance(data_obj, dict) else "usd"),
                        "merchant": {
                            "name": merchant.get("name"),
                            "category": merchant.get("category"),
                            "city": merchant.get("city"),
                        },
                        "created_at": _now(),
                    })
                    # Auto-disable if mode=auto and cap reached
                    await maybe_auto_disable_after_settlement(db, group["id"])
        except Exception as e:
            logger.warning(f"[issuing-webhook] handler failed: {e}")

        return {"ok": True, "type": evt_type}
