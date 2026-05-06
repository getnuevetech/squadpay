"""SMS Provider Abstraction (Phase F2.2).

Multi-provider SMS sending with automatic failover. Currently supports:
  - Twilio (REST API)
  - SignalWire (REST API — Twilio-compatible)

Admin can configure either or both. They pick a `primary` and `fallback`. On any
failure of the primary (timeout, 4xx/5xx), we automatically retry with the fallback.
Per-message audit logging records which provider sent each message.

Public API:
  send_sms(db, to_number, body) -> (sent_real: bool, info: str, provider: str | None)

Schema additions to app_settings.integrations:
  signalwire: {
      enabled, project_id_enc, api_token_enc, space_url, from_number,
      updated_at, updated_by
  }
  sms_routing: {
      primary: "twilio" | "signalwire",
      fallback: "twilio" | "signalwire" | null,
  }
"""
from __future__ import annotations
import datetime as dt
import logging
from typing import Optional, Tuple

from integrations import (
    decrypt_secret,
    get_integrations_doc,
    mask_secret,
)

logger = logging.getLogger(__name__)


# ---------- Defaults injected into app_settings.integrations ----------

DEFAULT_SIGNALWIRE = {
    "enabled": False,
    "project_id_enc": None,
    "api_token_enc": None,
    "space_url": None,         # e.g., "your-space.signalwire.com"
    "from_number": None,       # e.g., "+15551234567"
    "updated_at": None,
    "updated_by": None,
}

DEFAULT_SMS_ROUTING = {
    "primary": "twilio",       # twilio | signalwire
    "fallback": None,          # twilio | signalwire | null
    "updated_at": None,
    "updated_by": None,
}


def project_sms_for_admin(rec: dict) -> dict:
    sw = rec.get("signalwire") or {}
    routing = rec.get("sms_routing") or {}
    return {
        "signalwire": {
            "enabled": bool(sw.get("enabled")),
            "project_id_masked": mask_secret(decrypt_secret(sw.get("project_id_enc"))),
            "project_id_set": bool(sw.get("project_id_enc")),
            "api_token_set": bool(sw.get("api_token_enc")),
            "api_token_masked": mask_secret(decrypt_secret(sw.get("api_token_enc"))),
            "space_url": sw.get("space_url") or "",
            "from_number": sw.get("from_number") or "",
            "updated_at": sw.get("updated_at"),
            "updated_by": sw.get("updated_by"),
        },
        "sms_routing": {
            "primary": routing.get("primary") or "twilio",
            "fallback": routing.get("fallback"),
            "updated_at": routing.get("updated_at"),
            "updated_by": routing.get("updated_by"),
        },
    }


# ---------- Provider implementations ----------

async def _send_via_twilio(rec: dict, to: str, body: str) -> Tuple[bool, str]:
    t = rec.get("twilio") or {}
    if not t.get("enabled"):
        return False, "Twilio not enabled"
    sid = decrypt_secret(t.get("account_sid_enc"))
    token = decrypt_secret(t.get("auth_token_enc"))
    from_num = t.get("from_number")
    if not (sid and token and from_num):
        return False, "Twilio credentials incomplete"
    import httpx
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url, data={"To": to, "From": from_num, "Body": body}, auth=(sid, token)
            )
        if resp.status_code in (200, 201):
            return True, f"twilio sid={resp.json().get('sid')}"
        return False, f"twilio {resp.status_code}: {resp.text[:160]}"
    except Exception as e:
        return False, f"twilio exception: {e}"


async def _send_via_signalwire(rec: dict, to: str, body: str) -> Tuple[bool, str]:
    sw = rec.get("signalwire") or {}
    if not sw.get("enabled"):
        return False, "SignalWire not enabled"
    project_id = decrypt_secret(sw.get("project_id_enc"))
    token = decrypt_secret(sw.get("api_token_enc"))
    space = (sw.get("space_url") or "").replace("https://", "").replace("http://", "").rstrip("/")
    from_num = sw.get("from_number")
    if not (project_id and token and space and from_num):
        return False, "SignalWire credentials incomplete"
    # SignalWire's compatibility API mirrors Twilio's:
    #   POST https://{space}/api/laml/2010-04-01/Accounts/{project_id}/Messages.json
    import httpx
    url = f"https://{space}/api/laml/2010-04-01/Accounts/{project_id}/Messages.json"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url, data={"To": to, "From": from_num, "Body": body}, auth=(project_id, token)
            )
        if resp.status_code in (200, 201):
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            return True, f"signalwire sid={data.get('sid', 'ok')}"
        return False, f"signalwire {resp.status_code}: {resp.text[:160]}"
    except Exception as e:
        return False, f"signalwire exception: {e}"


_PROVIDER_FNS = {
    "twilio": _send_via_twilio,
    "signalwire": _send_via_signalwire,
}


# ---------- Public sender with failover ----------

async def send_sms(db, to: str, body: str) -> Tuple[bool, str, Optional[str]]:
    """Send via primary provider; on failure auto-retry with fallback (if configured).

    Returns (sent_real, info_message, provider_used or None).
    Logs result to db.sms_log for audit.
    """
    rec = await get_integrations_doc(db)
    routing = rec.get("sms_routing") or {}
    primary = (routing.get("primary") or "twilio").lower()
    fallback = (routing.get("fallback") or "").lower() or None

    attempts = []
    sent = False
    info = ""
    provider_used: Optional[str] = None

    order = [primary] + ([fallback] if fallback and fallback != primary else [])
    for prov in order:
        fn = _PROVIDER_FNS.get(prov)
        if not fn:
            attempts.append({"provider": prov, "ok": False, "info": "unknown provider"})
            continue
        ok, msg = await fn(rec, to, body)
        attempts.append({"provider": prov, "ok": ok, "info": msg[:240]})
        if ok:
            sent = True
            info = msg
            provider_used = prov
            break

    # If neither configured/worked, log as mock
    if not sent and not attempts:
        logger.info(f"[sms-mock] -> {to}: {body}")
        info = "no provider configured — mocked to console"

    # Audit log entry (best-effort)
    try:
        await db.sms_log.insert_one({
            "to": to,
            "body_preview": body[:80],
            "sent_real": sent,
            "provider_used": provider_used,
            "attempts": attempts,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
    except Exception:
        pass

    if not sent:
        # Compose final info from attempts
        info = " | ".join(f"{a['provider']}={a['info']}" for a in attempts) or info or "send failed"
        logger.warning(f"[sms] all providers failed for {to}: {info}")

    return sent, info, provider_used
