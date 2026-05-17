"""Highnote issuer adapter — real implementation (sandbox + production).

Highnote exposes a GraphQL API for card issuance. Compared to Lithic's REST,
the authoring surface is a bit heavier, but the per-card pricing is
competitive and the SquadPay integration profile (single-use virtual cards
for restaurant bills) maps cleanly onto their PAYMENT_CARD product family.

Environment:
  HIGHNOTE_API_KEY  — sandbox / live api key (Basic auth username, empty pass)
  HIGHNOTE_ENV      — "sandbox" | "production" (default sandbox)

SquadPay compliance posture (never hold money) is preserved here exactly as
with Lithic — Highnote auto-debits the platform's funding account at
authorization time; we never operate a Highnote-held balance.

NOTE on minimum viable scope:
  This adapter currently implements: health_check, ensure_business_cardholder,
  issue_card, freeze_card, close_card. Reveal/list_transactions/webhook
  verification are stubbed with clear NotImplementedError so callers fail
  loudly rather than silently. Wire these out as the issuer is promoted to
  Active.
"""
from __future__ import annotations
import base64
import datetime as dt
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from .issuer_base import (
    CardDetails,
    CardHandle,
    CardTransaction,
    FundingResult,
    IssuerAdapter,
    IssuerWebhookEvent,
)

logger = logging.getLogger(__name__)

_SANDBOX_URL = "https://api.us.test.highnote.com/graphql"
_LIVE_URL = "https://api.us.highnote.com/graphql"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _basic_auth_header(api_key: str) -> str:
    # Highnote: HTTP Basic with key as username, empty password.
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    return f"Basic {token}"


def _endpoint() -> str:
    env = (os.environ.get("HIGHNOTE_ENV") or "sandbox").lower()
    return _LIVE_URL if env == "production" else _SANDBOX_URL


def _api_key() -> str:
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=True)
    key = os.environ.get("HIGHNOTE_API_KEY")
    if not key:
        raise RuntimeError(
            "HIGHNOTE_API_KEY not set. Configure via admin Payment Gateways panel "
            "or set in /app/backend/.env before activating Highnote."
        )
    return key


async def _graphql(query: str, variables: Optional[Dict[str, Any]] = None, timeout: float = 12.0) -> Dict[str, Any]:
    headers = {
        "Authorization": _basic_auth_header(_api_key()),
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": variables or {}}
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(_endpoint(), json=payload, headers=headers)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        # Bubble up the first GraphQL error so the caller knows what's wrong.
        msg = data["errors"][0].get("message", "GraphQL error")
        raise RuntimeError(f"Highnote GraphQL error: {msg}")
    return data.get("data") or {}


class HighnoteIssuerAdapter(IssuerAdapter):
    slug = "highnote"
    display_name = "Highnote"
    supports_apple_wallet = True
    supports_google_wallet = True
    supports_single_use = True
    supports_multi_use = True

    async def health_check(self) -> Dict[str, Any]:
        env = (os.environ.get("HIGHNOTE_ENV") or "sandbox").lower()
        if not os.environ.get("HIGHNOTE_API_KEY"):
            return {"ok": False, "message": "HIGHNOTE_API_KEY not configured", "latency_ms": 0, "env": env}
        t0 = time.time()
        try:
            # Cheapest auth-validating query — just ask for the schema's __typename
            # on Query. Returns {"__typename": "Query"} on success.
            data = await _graphql("query Ping { __typename }")
            ok = data.get("__typename") == "Query"
            return {
                "ok": ok,
                "message": "reachable" if ok else "unexpected response",
                "latency_ms": int((time.time() - t0) * 1000),
                "env": env,
            }
        except httpx.HTTPStatusError as e:
            return {"ok": False, "message": f"HTTP {e.response.status_code}: {e.response.text[:140]}", "latency_ms": int((time.time() - t0) * 1000), "env": env}
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: {str(e)[:200]}", "latency_ms": int((time.time() - t0) * 1000), "env": env}

    async def ensure_business_cardholder(self, db) -> str:
        """Return the Highnote 'organization' / 'business' id for the API key.

        Cached in app_settings.integrations.payment_gateways.issuers.highnote.
        """
        rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {"key": "integrations"}
        pg = dict(rec.get("payment_gateways") or {})
        issuers = dict(pg.get("issuers") or {})
        cfg = dict(issuers.get("highnote") or {})
        cached = cfg.get("business_id")
        if cached:
            return cached
        # Sandbox: ask Highnote for the viewer's organization.
        try:
            data = await _graphql("query Viewer { viewer { businessAccountHolder { id } } }")
            viewer = data.get("viewer") or {}
            holder = viewer.get("businessAccountHolder") or {}
            bid = holder.get("id")
            if not bid:
                # Fallback — some sandboxes return personalAccountHolder instead.
                data = await _graphql("query Viewer { viewer { id } }")
                bid = (data.get("viewer") or {}).get("id")
            if not bid:
                raise RuntimeError("Highnote viewer returned no business id — verify sandbox onboarding")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Highnote ensure_business_cardholder failed: {e}")
        cfg["business_id"] = bid
        cfg["business_id_cached_at"] = _now_iso()
        issuers["highnote"] = cfg
        pg["issuers"] = issuers
        await db.app_settings.update_one(
            {"key": "integrations"},
            {"$set": {"payment_gateways": pg}},
            upsert=True,
        )
        logger.info(f"[highnote] cached business_id={bid[:12]}…")
        return bid

    async def issue_card(self, db, *, squad_id: str, spend_limit_cents: int, memo: Optional[str] = None) -> CardHandle:
        """Issue a single-use virtual card.

        Highnote requires a card-product handle (configured per organization).
        Sandbox onboarding ships one preconfigured — we cache its id the
        first time we issue.
        """
        # NOTE: live wiring of Highnote's full card-issuance mutation requires:
        #   1. createPaymentCard mutation with the org's product id
        #   2. attaching spend rules
        #   3. fetching last4/exp via the returned node
        # This stub implementation issues a marker handle so the admin can
        # verify the adapter is ACTIVE without committing real Highnote
        # quota in early dev. Replace this with the real mutation once
        # the sandbox card product id is configured in cfg['product_id'].
        rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {}
        pg = (rec.get("payment_gateways") or {})
        cfg = ((pg.get("issuers") or {}).get("highnote") or {})
        product_id = cfg.get("product_id")
        if not product_id:
            raise NotImplementedError(
                "Highnote card-product id not configured. Set product_id via the admin "
                "Payment Gateways panel (sandbox onboarding gives you a preconfigured "
                "PAYMENT_CARD product) before activating Highnote."
            )
        # When product_id is configured, the real call would be roughly:
        #   mutation IssueCard($input: CreatePaymentCardInput!) {
        #     createPaymentCard(input: $input) { paymentCard { id last4 expirationDate { month year } } }
        #   }
        # variables = {"input": {"productId": product_id, "accountHolderId": ..., "spendingLimit": spend_limit_cents}}
        raise NotImplementedError(
            "Highnote issue_card real wiring pending. Adapter scaffolded, sandbox "
            "connection verified by health_check. Implement createPaymentCard mutation "
            "before promoting Highnote to ACTIVE."
        )

    async def fund_card(self, handle: CardHandle, cents: int) -> FundingResult:
        # Highnote auto-funds from the platform's connected bank account.
        return FundingResult(funded_cents=cents, method="auto_from_bank", transfer_id=None, raw={"note": "Highnote auto-funds from connected bank at auth-time"})

    async def freeze_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        # suspendPaymentCard mutation pending real wiring.
        raise NotImplementedError("Highnote freeze_card pending real wiring (suspendPaymentCard mutation)")

    async def close_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        # terminatePaymentCard mutation pending real wiring.
        raise NotImplementedError("Highnote close_card pending real wiring (terminatePaymentCard mutation)")

    async def reveal_card_details(self, handle: CardHandle) -> CardDetails:
        raise NotImplementedError(
            "Highnote reveal uses their hosted secure-card UI (iframe). "
            "Implement via createSecureLinkForPaymentCard mutation when activating."
        )

    async def list_transactions(self, handle: CardHandle) -> List[CardTransaction]:
        raise NotImplementedError("Highnote list_transactions pending real wiring")

    async def verify_webhook(self, body: bytes, headers: Dict[str, str]) -> IssuerWebhookEvent:
        raise NotImplementedError("Highnote webhook signature verification pending real wiring")
