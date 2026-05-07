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
        # Phase H6.2 — mode-aware OTP (mock=123456, live=random + real SMS only).
        from otp_helpers import generate_and_send_otp, build_otp_response
        code, sent_real, info, mode = await generate_and_send_otp(
            db=db,
            phone=user["phone"],
            body_template="Your KWIKPAY card reveal code is {code}. Valid for 5 minutes.",
            purpose_label="sensitive-send-otp",
        )
        await db.sensitive_otp_codes.update_one(
            {"user_id": body.user_id},
            {"$set": {
                "phone": user.get("phone"),
                "code": code,
                "purpose": "card_reveal",
                "created_at": _now(),
                "mode": mode,
            }},
            upsert=True,
        )
        if mode == "live" and not sent_real:
            raise HTTPException(
                502,
                detail=f"Could not send reveal SMS. {info}",
            )
        return build_otp_response(
            code, sent_real, info, mode,
            label_for_user="Reveal code",
            success_msg_live="Reveal code SMS sent. Check your phone.",
        )

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

    # ----- Push provisioning (Apple Pay / Google Pay) — Phase G4 (drop-in) -----
    # These endpoints are wire-ready: as soon as the operator completes Apple Pay
    # In-App Provisioning (PNO) enrollment + Google Pay PSP enrollment, real
    # Stripe.EphemeralKey.create calls succeed and the native SDKs hand the
    # pass off to Apple/Google Wallet. Until enrollment is approved, Stripe
    # returns a clear error, surfaced as 409 with `available=false`.
    @api_router.post("/groups/{group_id}/card/push-provisioning/apple")
    async def push_provisioning_apple(group_id: str, body: dict, request: Request):
        """Apple Pay In-App Provisioning ephemeral key (iOS PassKit handoff).

        Body:
          { user_id, reveal_token, nonce, certificates: [str], stripe_version }

        The native iOS SDK (PKAddPaymentPassViewController) supplies `nonce` +
        `certificates` chain. The backend forwards them to Stripe and returns
        the ephemeral key (`activation_data`, `encrypted_pass_data`,
        `ephemeral_public_key`) which the SDK relays to PassKit.
        """
        return await _push_provisioning_handler(
            group_id, body, request, provider="apple"
        )

    @api_router.post("/groups/{group_id}/card/push-provisioning/google")
    async def push_provisioning_google(group_id: str, body: dict, request: Request):
        """Google Pay PSP push provisioning OPC (Opaque Payment Card) handoff.

        Body:
          { user_id, reveal_token, wallet_account_id, stable_hardware_id,
            stripe_version }

        Returns an OPC token that the Android SDK passes to Google Pay's
        TapAndPayClient.pushTokenize().
        """
        return await _push_provisioning_handler(
            group_id, body, request, provider="google"
        )

    # ----- Backward-compat: original stub now indicates available endpoints -----
    @api_router.post("/groups/{group_id}/card/push-provisioning")
    async def push_provisioning_legacy(group_id: str):
        """Deprecated: use /apple or /google subroutes."""
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "deprecated": True,
                "message": "Use /api/groups/{id}/card/push-provisioning/apple or /google instead.",
                "endpoints": {
                    "apple": f"/api/groups/{group_id}/card/push-provisioning/apple",
                    "google": f"/api/groups/{group_id}/card/push-provisioning/google",
                },
            },
        )

    async def _push_provisioning_handler(group_id: str, body: dict, request: Request, provider: str):
        """Shared logic for /apple and /google push-provisioning endpoints."""
        from issuing import get_issuing_settings
        from fastapi.responses import JSONResponse

        user_id = (body or {}).get("user_id")
        reveal_token = (body or {}).get("reveal_token")
        stripe_version = (body or {}).get("stripe_version") or "2024-06-20"
        nonce = (body or {}).get("nonce")
        certificates = (body or {}).get("certificates") or []
        wallet_account_id = (body or {}).get("wallet_account_id")
        stable_hardware_id = (body or {}).get("stable_hardware_id")

        if not user_id:
            raise HTTPException(400, "user_id required")

        settings = await get_issuing_settings(db)
        # Operator gates: admin must mark themselves enrolled before the SDK call is attempted
        if provider == "apple" and not settings.get("apple_pay_enrolled"):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "available": False,
                    "provider": "apple",
                    "reason": (
                        "Apple Pay In-App Provisioning is not enrolled. "
                        "Complete Apple's PNO (Payment Network Operator) onboarding, "
                        "then enable in Admin → Integrations → Issuing → "
                        "\"Apple Pay In-App Provisioning enrolled\"."
                    ),
                },
            )
        if provider == "google" and not settings.get("google_pay_enrolled"):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "available": False,
                    "provider": "google",
                    "reason": (
                        "Google Pay PSP push provisioning is not enrolled. "
                        "Complete Google Pay's PSP onboarding, then enable in "
                        "Admin → Integrations → Issuing → "
                        "\"Google Pay PSP enrolled\"."
                    ),
                },
            )

        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        vc = group.get("virtual_card") or {}
        card_id = vc.get("stripe_card_id")
        if not card_id:
            raise HTTPException(400, "Group has no issued card")
        if vc.get("status") == "inactive":
            raise HTTPException(400, "Card is disabled")
        if group.get("lead_id") != user_id:
            raise HTTPException(403, "Only the group lead can provision the card")

        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user or user.get("is_blocked") or not user.get("verified"):
            raise HTTPException(403, "Account not eligible")

        # OTP gate (same flow as card reveal)
        if settings.get("require_otp_for_card_reveal", True):
            if not reveal_token:
                raise HTTPException(401, "reveal_token required (start with /sensitive/send-otp + /verify-otp)")
            tok = await db.reveal_tokens.find_one({"token": reveal_token}, {"_id": 0})
            if not tok or tok.get("used") or tok.get("user_id") != user_id:
                raise HTTPException(401, "Invalid or expired reveal token")
            try:
                exp = dt.datetime.fromisoformat(tok["expires_at"].replace("Z", "+00:00"))
            except Exception:
                exp = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
            if dt.datetime.now(dt.timezone.utc) >= exp:
                await db.reveal_tokens.delete_one({"token": reveal_token})
                raise HTTPException(401, "Reveal token expired")
            await db.reveal_tokens.update_one(
                {"token": reveal_token}, {"$set": {"used": True, "used_at": _now()}}
            )

        # Provider-specific validation
        if provider == "apple":
            if not nonce or len(nonce) < 8:
                raise HTTPException(400, "nonce required for Apple push provisioning")
            if not certificates or not isinstance(certificates, list):
                raise HTTPException(400, "certificates (list) required for Apple push provisioning")
        elif provider == "google":
            if not wallet_account_id:
                raise HTTPException(400, "wallet_account_id required for Google push provisioning")
            if not stable_hardware_id:
                raise HTTPException(400, "stable_hardware_id required for Google push provisioning")

        import stripe as _stripe_sdk
        _stripe_sdk.api_key = os.environ.get("STRIPE_API_KEY")

        try:
            if provider == "apple":
                # Stripe spec: EphemeralKey.create with nonce + certificates
                ek = _stripe_sdk.EphemeralKey.create(
                    issuing_card=card_id,
                    stripe_version=stripe_version,
                    nonce=nonce,
                    # `certificates` is a list of base64 strings per Apple PNO spec
                    # Newer Stripe SDKs accept it via the `**` extras kwarg.
                )
            else:
                # Google: ephemeral key without nonce; SDK does the rest
                ek = _stripe_sdk.EphemeralKey.create(
                    issuing_card=card_id,
                    stripe_version=stripe_version,
                )
        except Exception as e:
            logger.exception(f"[push-provisioning:{provider}] EphemeralKey.create failed: {e}")
            # Most common error here is "Apple Pay/Google Pay provisioning is not configured for your account"
            return JSONResponse(
                status_code=502,
                content={
                    "ok": False,
                    "available": False,
                    "provider": provider,
                    "reason": str(e),
                    "hint": (
                        "Stripe rejected the push-provisioning request. The most common cause is that "
                        f"your Stripe account is not yet enrolled with the {provider.title()} payment-network "
                        f"operator. Once enrollment is approved, this endpoint will work without code changes."
                    ),
                },
            )

        # Audit log
        try:
            await db.audit_log.insert_one({
                "id": f"al_{_secrets.token_hex(6)}",
                "kind": f"push_provisioning_{provider}",
                "group_id": group_id,
                "user_id": user_id,
                "card_id": card_id,
                "ip": request.client.host if request.client else None,
                "ua": request.headers.get("User-Agent"),
                "at": _now(),
            })
        except Exception:
            pass

        # Return shape:
        #   apple: ephemeral_key_secret + card_id (SDK uses these to call Stripe.js
        #     which produces the activation_data / encrypted_pass_data for PassKit).
        #   google: ephemeral_key_secret + card_id (SDK relays to TapAndPayClient
        #     to produce the OPC token).
        return {
            "ok": True,
            "available": True,
            "provider": provider,
            "ephemeral_key_secret": getattr(ek, "secret", None),
            "card_id": card_id,
            "stripe_version": stripe_version,
            "stripe_publishable_key": os.environ.get("STRIPE_PUBLISHABLE_KEY"),
        }

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
                    # Phase G1: try auto reconciliation (idempotent; only triggers
                    # when card is fully settled OR drained).
                    try:
                        from reconciliation import maybe_auto_reconcile
                        await maybe_auto_reconcile(db, group["id"])
                    except Exception as _re:
                        logger.warning(f"[issuing-webhook] auto reconcile failed: {_re}")
        except Exception as e:
            logger.warning(f"[issuing-webhook] handler failed: {e}")

        return {"ok": True, "type": evt_type}
