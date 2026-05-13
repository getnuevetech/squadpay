"""Push notification dispatcher via Expo Push API (June 2025).

We use Expo's hosted push relay (https://exp.host/--/api/v2/push/send) so
both iOS (APNs) and Android (FCM) are handled by Expo's infrastructure.

Tokens are collected by the FE via expo-notifications and stored in
`users.expo_push_tokens: [{ token, platform, last_seen_at }]`.

Honors the admin Notification Config (notification_config.py): if an
event's channel is "off" or "sms" only, push is silently skipped.

Mock mode: when no token exists for a user, we log the would-be push
and tag delivered_via="push_no_token" — same pattern as SMS.
"""
from __future__ import annotations
import logging
from typing import Any
from exponent_server_sdk import (
    PushClient, PushMessage, PushServerError, PushTicketError,
)
from requests.exceptions import ConnectionError, HTTPError

from notification_config import should_send_push

logger = logging.getLogger("push_provider")
_client = PushClient()


async def get_user_push_tokens(db: Any, user_id: str) -> list[str]:
    """Return all currently-active Expo push tokens for the user."""
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "expo_push_tokens": 1})
    tokens = (u or {}).get("expo_push_tokens") or []
    out: list[str] = []
    for t in tokens:
        tk = t.get("token") if isinstance(t, dict) else t
        if isinstance(tk, str) and tk.startswith("ExponentPushToken[") and tk.endswith("]"):
            out.append(tk)
    return out


async def send_push_to_user(
    db: Any, user_id: str, *, title: str, body: str, event_key: str | None = None,
    data: dict | None = None,
) -> str:
    """Send a push to all of user's active devices. Returns delivery_via tag.

    Honors the admin Notification Config — if event_key is set and the
    admin disabled push for that event (or globally), returns
    "push_disabled_by_admin" without dispatching.
    """
    if event_key:
        try:
            if not await should_send_push(db, event_key):
                return "push_disabled_by_admin"
        except Exception:
            return "push_disabled_by_admin"

    tokens = await get_user_push_tokens(db, user_id)
    if not tokens:
        return "push_no_token"

    ok_count = 0
    err_count = 0
    for tk in tokens:
        try:
            response = _client.publish(
                PushMessage(
                    to=tk,
                    title=title,
                    body=body,
                    data=data or {},
                    sound="default",
                    priority="high",
                )
            )
            response.validate_response()
            ok_count += 1
        except (PushServerError, PushTicketError, ConnectionError, HTTPError) as e:
            err_count += 1
            logger.warning("[push] dispatch error to=%s: %s", tk[:30], e)
        except Exception as e:
            err_count += 1
            logger.warning("[push] unexpected error to=%s: %s", tk[:30], e)

    if ok_count and not err_count:
        return "push_expo"
    if ok_count and err_count:
        return "push_partial"
    return "push_failed"


async def register_push_token(
    db: Any, user_id: str, *, token: str, platform: str | None = None
) -> dict:
    """Upsert an Expo push token onto a user. Idempotent by token."""
    if not (isinstance(token, str) and token.startswith("ExponentPushToken[") and token.endswith("]")):
        raise ValueError("Invalid Expo push token format")
    from core import now_iso
    now = now_iso()
    # Pull-then-push pattern: remove any old entry for this token, then push fresh.
    await db.users.update_one(
        {"id": user_id},
        {"$pull": {"expo_push_tokens": {"token": token}}},
    )
    await db.users.update_one(
        {"id": user_id},
        {"$push": {"expo_push_tokens": {
            "token": token,
            "platform": (platform or "unknown")[:16],
            "last_seen_at": now,
        }}},
    )
    return {"ok": True, "token_tail": token[-10:], "platform": platform}


async def unregister_push_token(db: Any, user_id: str, token: str) -> dict:
    res = await db.users.update_one(
        {"id": user_id},
        {"$pull": {"expo_push_tokens": {"token": token}}},
    )
    return {"ok": True, "removed": int(res.modified_count)}
