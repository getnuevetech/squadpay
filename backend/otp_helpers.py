"""OTP helpers — Phase H6.2.

Centralises the logic for generating + sending OTP codes across all flows
(/auth/send-otp, /auth/sensitive/send-otp, etc.) so they consistently
respect the global SMS Mode (mock | live):

  • mode=mock  → code "123456", no provider call, response includes the code so
                 demo/dev can log in without an SMS receipt.
  • mode=live  → cryptographically random 6-digit code, real SMS via configured
                 provider (Twilio/SignalWire), and the code IS NEVER returned in
                 the API response — users MUST see the SMS.

We always use the multi-provider `send_sms()` from sms_providers.py so the admin's
configured primary/fallback chain (Twilio → SignalWire or vice-versa) is honored.
"""
from __future__ import annotations
import logging
import secrets
from typing import Tuple

logger = logging.getLogger(__name__)


async def get_sms_mode(db) -> str:
    """Return current SMS mode from app_settings.integrations.sms_routing.mode.
    Defaults to 'mock' if unset."""
    try:
        rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0})
        return ((rec or {}).get("sms_routing") or {}).get("mode") or "mock"
    except Exception:
        return "mock"


async def generate_and_send_otp(
    db,
    phone: str,
    body_template: str,
    purpose_label: str = "OTP",
) -> Tuple[str, bool, str, str]:
    """Generate an OTP code, attempt SMS, return (code, sent_real, info, mode).

    Args:
      phone: E.164-ish phone number (will be normalized inside provider).
      body_template: SMS body, must contain "{code}" placeholder.
      purpose_label: short label for logs/info (e.g. "OTP", "card-reveal").

    Returns:
      code: the 6-digit OTP that should be stored in the OTP table for verify.
      sent_real: True if a real SMS was queued by Twilio/SignalWire.
      info: provider info string for logs / debug response.
      mode: 'mock' | 'live' — what mode generated this code.
    """
    mode = await get_sms_mode(db)

    if mode == "live":
        # Real, secure 6-digit code. Use secrets module for cryptographic randomness.
        code = f"{secrets.randbelow(1_000_000):06d}"
    else:
        # Mock-mode demo code — same value forever for QA/dev convenience.
        code = "123456"

    body = body_template.replace("{code}", code)
    sent_real, info = False, "send_sms unavailable"
    try:
        from sms_providers import send_sms
        sent_real, info, _provider = await send_sms(db, phone, body)
    except Exception as e:
        logger.warning(f"[{purpose_label}] send_sms exception: {e}")
        info = f"exception: {e}"

    if mode == "live" and not sent_real:
        # IMPORTANT — in live mode we MUST never expose the code if the SMS failed
        # to send. The caller can decide whether to surface a "please retry" error.
        logger.warning(
            f"[{purpose_label}] LIVE-mode SMS send failed for {phone}: {info}. "
            "Code generated but not delivered."
        )

    return code, sent_real, info, mode


def build_otp_response(
    code: str,
    sent_real: bool,
    info: str,
    mode: str,
    *,
    label_for_user: str = "OTP",
    success_msg_live: str = "Code sent via SMS",
) -> dict:
    """Build a consistent API response for OTP-send endpoints.

    Crucially: in live mode we NEVER include the code in the message, even if
    the SMS send failed. Mock mode gets the code-in-response for dev convenience.
    """
    if mode == "live":
        if sent_real:
            return {
                "ok": True,
                "mocked": False,
                "live": True,
                "message": success_msg_live,
                "info": info,
            }
        else:
            # Live mode but SMS failed (provider 4xx/5xx, no creds, etc.).
            # The code is generated but not delivered. Return an error so the
            # client can show "Could not send code, please try again" without
            # leaking the code itself.
            return {
                "ok": False,
                "mocked": False,
                "live": True,
                "message": "Could not send SMS. Please try again or contact support.",
                "info": info,
            }
    # Mock mode — code is intentionally surfaced so devs/demo testers can log in.
    return {
        "ok": True,
        "mocked": True,
        "live": False,
        "message": f"{label_for_user} sent. Use {code} (mock mode)",
        "info": info,
    }
