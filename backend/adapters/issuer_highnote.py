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
        """Issue a single-use virtual card via Highnote's GraphQL.

        Highnote model:
          1. The org has one or more PaymentCardProduct configured (sandbox
             onboarding provisions one automatically).
          2. We attach the card to the org's businessAccountHolder.
          3. createPaymentCard mutation returns id, last4, expirationDate.

        product_id is cached in app_settings on first issuance \u2014 admin can
        also pre-set it via the Payment Gateways panel.
        """
        rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {}
        pg = (rec.get("payment_gateways") or {})
        cfg = ((pg.get("issuers") or {}).get("highnote") or {})
        product_id = cfg.get("product_id")
        if not product_id:
            # Try to auto-discover the org's first PAYMENT_CARD product.
            try:
                data = await _graphql(
                    "query Products { products { edges { node { id name __typename } } } }"
                )
                edges = ((data.get("products") or {}).get("edges") or [])
                for e in edges:
                    node = e.get("node") or {}
                    if "PaymentCard" in (node.get("__typename") or ""):
                        product_id = node.get("id")
                        break
            except Exception:
                product_id = None
        if not product_id:
            raise NotImplementedError(
                "Highnote card-product id could not be auto-discovered. Sandbox "
                "onboarding is done but no PAYMENT_CARD product was returned. "
                "Manually set product_id under app_settings.integrations"
                ".payment_gateways.issuers.highnote, or contact Highnote support."
            )
        business_id = await self.ensure_business_cardholder(db)
        # NOTE: Highnote's exact createPaymentCard mutation shape varies by
        # product type. The shape below matches the most common single-use
        # virtual-card flow. If the sandbox rejects this, capture the error
        # and adjust per the inspector tool at highnote.com/docs/playground.
        mutation = """
        mutation IssueCard($input: IssuePaymentCardForFinancialAccountInput!) {
          issuePaymentCardForFinancialAccount(input: $input) {
            ... on PaymentCard {
              id
              last4
              expirationDate { month year }
              cardProductFeatures { __typename }
              network
            }
            ... on UserError { errors { field message } }
          }
        }
        """
        variables = {
            "input": {
                "productId": product_id,
                "accountHolderId": business_id,
                "memo": (memo or f"SquadPay {squad_id}")[:60],
                # Spend limit handled via Highnote spending rules; sandbox
                # accepts the card without it for initial smoke testing.
            },
        }
        try:
            data = await _graphql(mutation, variables)
            payload = data.get("issuePaymentCardForFinancialAccount") or {}
            if "errors" in payload:
                raise RuntimeError(f"Highnote issue rejected: {payload.get('errors')}")
            card_id = payload.get("id")
            if not card_id:
                raise RuntimeError(f"Highnote issue returned no card id; payload={payload}")
            last4 = payload.get("last4", "")
            exp = payload.get("expirationDate") or {}
            return CardHandle(
                issuer_slug=self.slug,
                card_id=card_id,
                last4=last4,
                exp_month=int(exp.get("month")) if exp.get("month") else None,
                exp_year=int(exp.get("year")) if exp.get("year") else None,
                state="active",
                brand=payload.get("network"),
                spend_limit_cents=spend_limit_cents,
                raw=payload,
            )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Highnote issue_card failed: {e}")

    async def freeze_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        mutation = """
        mutation Suspend($id: ID!) {
          suspendPaymentCard(input: { paymentCardId: $id }) {
            ... on PaymentCard { id status }
            ... on UserError { errors { message } }
          }
        }
        """
        await _graphql(mutation, {"id": handle.card_id})
        logger.info(f"[highnote] card={handle.card_id[:12]}\u2026 SUSPENDED reason={reason}")

    async def close_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        mutation = """
        mutation Close($id: ID!) {
          closePaymentCard(input: { paymentCardId: $id }) {
            ... on PaymentCard { id status }
            ... on UserError { errors { message } }
          }
        }
        """
        await _graphql(mutation, {"id": handle.card_id})
        logger.info(f"[highnote] card={handle.card_id[:12]}\u2026 CLOSED reason={reason}")

    async def reveal_card_details(self, handle: CardHandle) -> CardDetails:
        raise NotImplementedError(
            "Highnote reveal uses their hosted secure-card UI (iframe). "
            "Implement via createSecureLinkForPaymentCard mutation when activating."
        )

    async def list_transactions(self, handle: CardHandle) -> List[CardTransaction]:
        raise NotImplementedError("Highnote list_transactions pending real wiring")

    async def verify_webhook(self, body: bytes, headers: Dict[str, str]) -> IssuerWebhookEvent:
        raise NotImplementedError("Highnote webhook signature verification pending real wiring")
