"""Provider integration helpers (Phase D).

- At-rest encryption for secrets is delegated to crypto_kms (Phase G2).
- Stripe / Twilio / Reminders config persisted in db.app_settings (key: 'integrations').
- Twilio sender abstraction: if enabled & keys present, sends real SMS; else logs to console.
"""
from __future__ import annotations
import logging
import os
from typing import Optional, Tuple

# Phase G2: at-rest encryption is now centralized in crypto_kms (single source
# of truth, supports KMS_MASTER_KEY + legacy/derived fallback so existing
# ciphertexts stay readable).
from crypto_kms import encrypt as _kms_encrypt, decrypt as _kms_decrypt

logger = logging.getLogger(__name__)


def encrypt_secret(plain: Optional[str]) -> Optional[str]:
    if not plain:
        return None
    return _kms_encrypt(plain)


def decrypt_secret(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    return _kms_decrypt(token)


def mask_secret(plain: Optional[str], visible: int = 4) -> str:
    if not plain:
        return ""
    if len(plain) <= visible:
        return "*" * len(plain)
    return ("*" * (len(plain) - visible)) + plain[-visible:]


# ---------- defaults ----------

DEFAULT_INTEGRATIONS = {
    "stripe": {
        "enabled": False,
        "mode": "test",  # test | live
        "publishable_key": None,  # plaintext (public)
        "secret_key_enc": None,  # encrypted
        "webhook_secret_enc": None,  # encrypted
        "updated_at": None,
        "updated_by": None,
    },
    "twilio": {
        "enabled": False,
        "account_sid_enc": None,
        "auth_token_enc": None,
        "from_number": None,
        "updated_at": None,
        "updated_by": None,
    },
    "reminders": {
        "enabled": False,
        "schedule_hours": [24, 72, 168],  # default: 1d, 3d, 7d after bill creation
        "max_reminders_per_user": 3,
        "send_via_sms": True,  # uses twilio config if enabled
        "updated_at": None,
        "updated_by": None,
    },
    # Phase F2.2 — SignalWire (Twilio-compatible secondary provider)
    "signalwire": {
        "enabled": False,
        "project_id_enc": None,
        "api_token_enc": None,
        "space_url": None,         # e.g. "your-space.signalwire.com"
        "from_number": None,       # e.g. "+15551234567"
        "updated_at": None,
        "updated_by": None,
    },
    # Phase F2.2 — SMS routing (primary + optional fallback)
    "sms_routing": {
        "primary": "twilio",       # twilio | signalwire
        "fallback": None,          # twilio | signalwire | null
        "updated_at": None,
        "updated_by": None,
    },
}


async def get_integrations_doc(db) -> dict:
    rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0})
    if not rec:
        rec = {"key": "integrations", **DEFAULT_INTEGRATIONS}
        await db.app_settings.insert_one(rec.copy())
    # Ensure shape (forward-compat: add new fields if missing)
    changed = False
    for k, v in DEFAULT_INTEGRATIONS.items():
        if k not in rec:
            rec[k] = v
            changed = True
        else:
            for sk, sv in v.items():
                if sk not in rec[k]:
                    rec[k][sk] = sv
                    changed = True
    if changed:
        await db.app_settings.update_one({"key": "integrations"}, {"$set": rec}, upsert=True)
    return rec


def project_integrations_for_admin(rec: dict) -> dict:
    """Return masked view of integrations for admin display (no plaintext secrets)."""
    s = rec.get("stripe") or {}
    t = rec.get("twilio") or {}
    r = rec.get("reminders") or {}
    return {
        "stripe": {
            "enabled": bool(s.get("enabled")),
            "mode": s.get("mode") or "test",
            "publishable_key": s.get("publishable_key") or "",
            "secret_key_masked": mask_secret(decrypt_secret(s.get("secret_key_enc"))),
            "secret_key_set": bool(s.get("secret_key_enc")),
            "webhook_secret_set": bool(s.get("webhook_secret_enc")),
            "webhook_secret_masked": mask_secret(decrypt_secret(s.get("webhook_secret_enc"))),
            "updated_at": s.get("updated_at"),
            "updated_by": s.get("updated_by"),
        },
        "twilio": {
            "enabled": bool(t.get("enabled")),
            "account_sid_masked": mask_secret(decrypt_secret(t.get("account_sid_enc"))),
            "account_sid_set": bool(t.get("account_sid_enc")),
            "auth_token_set": bool(t.get("auth_token_enc")),
            "auth_token_masked": mask_secret(decrypt_secret(t.get("auth_token_enc"))),
            "from_number": t.get("from_number") or "",
            "updated_at": t.get("updated_at"),
            "updated_by": t.get("updated_by"),
        },
        "reminders": {
            "enabled": bool(r.get("enabled")),
            "schedule_hours": list(r.get("schedule_hours") or [24, 72, 168]),
            "max_reminders_per_user": int(r.get("max_reminders_per_user") or 3),
            "send_via_sms": bool(r.get("send_via_sms")),
            "updated_at": r.get("updated_at"),
            "updated_by": r.get("updated_by"),
        },
    }


# ---------- Twilio sender ----------

async def send_sms_via_twilio(db, to_number: str, body: str) -> Tuple[bool, str]:
    """LEGACY ENTRY-POINT — delegates to the new multi-provider sender (Phase F2.2).

    All callers (OTP send, sensitive OTP, reminders, admin test SMS) now route through
    the abstracted `sms_providers.send_sms` which handles primary + automatic fallback
    across Twilio and SignalWire. Result info is collapsed back to (sent_real, info)
    for backwards compatibility.
    """
    try:
        from sms_providers import send_sms as _multi_send
    except Exception as e:
        logger.warning(f"[sms] multi-provider import failed, falling back to console: {e}")
        logger.info(f"[sms-mock] -> {to_number}: {body}")
        return False, "multi-provider unavailable"
    sent, info, provider = await _multi_send(db, to_number, body)
    if sent:
        return True, f"Sent via {provider} ({info})"
    return False, info or "send failed"
