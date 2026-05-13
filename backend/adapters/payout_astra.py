"""Astra payout adapter — sandbox + production (Phase 5a, revised June 2025).

Astra (https://docs.astra.finance) uses a **3-legged OAuth flow** for any
user-bound action (linking cards, pushing money). Server-only OAuth
(client_credentials) is NOT accepted for transfers — Astra requires per-user
consent.

Integration model (revised after sandbox 400-response inspection):

  1. SquadPay generates an Astra "authorize" URL:
       https://sandbox.astra.finance/oauth/authorize
         ?response_type=code
         &client_id=...
         &redirect_uri=<deep-link-back-to-our-app>
         &scope=transfers:write cards:read
         &state=<random>

  2. WebView (mobile) or browser tab (web) loads the URL → user logs into
     Astra → grants consent → Astra redirects back to our redirect_uri with
     ?code=...&state=...

  3. Frontend deep-link handler POSTs the code+state to
     /api/payout/oauth-callback. Backend exchanges code → access_token +
     refresh_token, stores them per user in db.astra_user_tokens.

  4. Backend lists the user's linked cards via GET /v1/cards and presents
     them in the UI.

  5. Lead picks a card → POST /api/payout/push-to-card with that card_id
     → backend posts to Astra POST /v1/transfers using the user's access
     token, writes ledger entries.

PCI scope = zero. Astra hosts all card management; we only ever see card_id
+ brand + last4 + display_name. The user's access_token is a session-scoped
secret stored encrypted.

Sandbox base URL is ``sandbox.astra.finance`` — single URL, no /v1 prefix
on the OAuth endpoints; /v1 prefix on API resources.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from .payout_base import (
    PayoutAdapter,
    CardCaptureSession,
    CardToken,
    PushToCardResult,
    PayoutWebhookEvent,
)

logger = logging.getLogger(__name__)

_SANDBOX_AUTH_BASE = "https://sandbox.astra.finance"
_PROD_AUTH_BASE = "https://app.astra.finance"


class AstraPayoutAdapter(PayoutAdapter):
    slug = "astra"
    display_name = "Astra"

    DEFAULT_SCOPES = "transfers:write cards:read user:read"

    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        environment: str = "sandbox",
    ):
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.webhook_secret = webhook_secret or ""
        self.environment = (environment or "sandbox").lower()
        self.auth_base = _SANDBOX_AUTH_BASE if self.environment != "production" else _PROD_AUTH_BASE
        self.api_base = f"{self.auth_base}/v1"

    # ─────────────────────────────────────────────────────────────────────
    # OAuth — authorization_code flow
    # ─────────────────────────────────────────────────────────────────────

    def build_authorize_url(self, *, redirect_uri: str, state: str, scopes: Optional[str] = None) -> str:
        if not self.client_id:
            raise HTTPException(503, "Astra client_id not configured")
        q = urlencode({
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes or self.DEFAULT_SCOPES,
            "state": state,
        })
        return f"{self.auth_base}/oauth/authorize?{q}"

    async def exchange_authorization_code(
        self, *, code: str, redirect_uri: str
    ) -> Dict[str, Any]:
        """Exchange the auth code returned by Astra → {access_token, refresh_token, expires_in, ...}."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.post(
                    f"{self.api_base}/oauth/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "redirect_uri": redirect_uri,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as e:
                logger.exception(f"[astra] code exchange network error: {e}")
                raise HTTPException(502, f"Astra unreachable: {e}")
        if resp.status_code != 200:
            logger.error(f"[astra] code exchange {resp.status_code}: {resp.text[:300]}")
            raise HTTPException(502, f"Astra OAuth failed (status {resp.status_code}). {resp.text[:200]}")
        return resp.json() or {}

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self.api_base}/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code != 200:
            logger.error(f"[astra] refresh {resp.status_code}: {resp.text[:300]}")
            raise HTTPException(502, f"Astra refresh failed (status {resp.status_code})")
        return resp.json() or {}

    # ─────────────────────────────────────────────────────────────────────
    # API helpers (per-user access tokens — passed in explicitly)
    # ─────────────────────────────────────────────────────────────────────

    async def _user_request(
        self, method: str, path: str, *, access_token: str, idempotency_key: Optional[str] = None, **kwargs
    ) -> httpx.Response:
        headers = kwargs.pop("headers", {}) or {}
        headers["Authorization"] = f"Bearer {access_token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.request(method, f"{self.api_base}{path}", headers=headers, **kwargs)
            except httpx.HTTPError as e:
                logger.exception(f"[astra] {method} {path} network: {e}")
                raise HTTPException(502, f"Astra unreachable: {e}")
        return resp

    async def list_user_cards(self, *, access_token: str) -> List[Dict[str, Any]]:
        resp = await self._user_request("GET", "/cards", access_token=access_token)
        if resp.status_code >= 400:
            logger.error(f"[astra] list_user_cards {resp.status_code}: {resp.text[:300]}")
            raise HTTPException(502, f"Astra cards list failed (status {resp.status_code})")
        data = resp.json() or {}
        return data.get("data") or data.get("cards") or []

    async def create_transfer(
        self,
        *,
        access_token: str,
        amount_cents: int,
        currency: str,
        card_id: str,
        idempotency_key: str,
        metadata: Dict[str, str],
    ) -> Dict[str, Any]:
        body = {
            "amount": amount_cents,
            "currency": currency.upper(),
            "destination": {"type": "card", "card_id": card_id},
            "type": "push",
            "metadata": metadata or {},
        }
        resp = await self._user_request(
            "POST", "/transfers", access_token=access_token, idempotency_key=idempotency_key, json=body,
        )
        if resp.status_code >= 400:
            logger.error(f"[astra] transfer {resp.status_code}: {resp.text[:500]}")
            try:
                detail = resp.json().get("description") or resp.json().get("error") or resp.text[:200]
            except Exception:
                detail = resp.text[:200]
            raise HTTPException(502, f"Astra transfer failed: {detail}")
        return resp.json() or {}

    # ─────────────────────────────────────────────────────────────────────
    # PayoutAdapter contract methods
    # ─────────────────────────────────────────────────────────────────────

    async def create_card_capture_session(
        self,
        *,
        user_id: str,
        return_url: str,
        cancel_url: str,
        metadata: Dict[str, str],
    ) -> CardCaptureSession:
        """For Astra, 'capture session' = the OAuth authorize URL.

        Caller (route) passes ``return_url`` which Astra redirects to with
        ?code=...&state=... after consent. ``state`` is encoded inside the
        return_url's query string by the caller before invoking us.
        """
        state = metadata.get("state") or user_id
        url = self.build_authorize_url(redirect_uri=return_url, state=state)
        return CardCaptureSession(
            capture_id=state,  # we use `state` as our correlation id
            url=url,
            expires_at=None,
            raw={"redirect_uri": return_url, "state": state, "kind": "oauth_authorize"},
        )

    async def retrieve_card_token(self, capture_id: str) -> Optional[CardToken]:
        """N/A for Astra — tokens flow via /payout/oauth-callback, not pull."""
        return None

    async def push_to_card(
        self,
        *,
        amount_cents: int,
        currency: str,
        card_token: str,
        idempotency_key: str,
        metadata: Dict[str, str],
    ) -> PushToCardResult:
        """For Astra, ``card_token`` here is encoded as ``"{access_token}|{card_id}"``.

        We accept it this way to keep the abstract PayoutAdapter contract
        unchanged; the payout route builds this combo string from
        db.astra_user_tokens + db.astra_user_cards.
        """
        if "|" not in card_token:
            raise HTTPException(500, "Astra push_to_card: card_token must be '<access_token>|<card_id>'")
        access_token, card_id = card_token.split("|", 1)
        data = await self.create_transfer(
            access_token=access_token,
            amount_cents=amount_cents,
            currency=currency,
            card_id=card_id,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )
        return PushToCardResult(
            provider_payout_id=data.get("id") or "",
            status=(data.get("status") or "pending").lower(),
            amount_cents=int(data.get("amount") or amount_cents),
            currency=(data.get("currency") or currency).lower(),
            fee_cents=data.get("fee"),
            raw=data,
        )

    async def verify_webhook(self, body: bytes, signature: Optional[str]) -> PayoutWebhookEvent:
        if not self.webhook_secret:
            raise HTTPException(503, "Astra webhook secret not configured")
        if not signature:
            raise HTTPException(400, "Missing Astra signature header")
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature.strip()):
            raise HTTPException(400, "Astra webhook signature mismatch")
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            raise HTTPException(400, "Astra webhook body is not valid JSON")
        payout_id = (data.get("data") or {}).get("id") or data.get("id")
        return PayoutWebhookEvent(
            event_type=data.get("type") or data.get("event") or "unknown",
            provider_payout_id=payout_id,
            status=(data.get("data") or {}).get("status") or data.get("status"),
            raw=data,
        )
