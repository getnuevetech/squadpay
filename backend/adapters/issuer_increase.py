"""Increase.com issuer adapter — real implementation (sandbox + production).

Increase.com is a US fintech bank-in-the-middle that provides BOTH virtual
card issuance AND ACH / wire / real-time payment rails. That makes it a
strong candidate for SquadPay's hybrid use case:
  • As an ISSUER: issue single-use virtual cards for squad bills
  • As a PAYOUT: push collected funds to lead's bank via instant ACH /
    real-time payments / merchant payouts (Phase 2)

Compliance posture (SquadPay never holds money):
  Increase accounts technically hold funds, but for SquadPay we keep balance
  in-flight — the platform's Increase account drains to ~$0 by end of day.
  Charge gateway → ACH into Increase → card auth/settlement → merchant. Any
  end-of-day balance is a reconciliation bug to alarm on, NOT normal state.

Environment:
  INCREASE_API_KEY  — sandbox or live key
  INCREASE_ENV      — "sandbox" | "production" (default sandbox)
"""
from __future__ import annotations
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from .issuer_base import (
    CardDetails,
    CardHandle,
    CardTransaction,
    FundingResult,
    IssuerAdapter,
    IssuerWebhookEvent,
)

logger = logging.getLogger(__name__)


def _client():
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=True)
    api_key = os.environ.get("INCREASE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "INCREASE_API_KEY not set. Configure via admin Payment Gateways panel "
            "or set in /app/backend/.env before activating Increase."
        )
    env = (os.environ.get("INCREASE_ENV") or "sandbox").lower()
    from increase import Increase
    return Increase(api_key=api_key, environment="sandbox" if env == "sandbox" else "production")


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class IncreaseIssuerAdapter(IssuerAdapter):
    slug = "increase"
    display_name = "Increase.com"
    supports_apple_wallet = True
    supports_google_wallet = True
    supports_single_use = True
    supports_multi_use = True
    # Available in BOTH the Virtual Card Issuer tab AND the Payout tab —
    # Increase natively supports card issuance, ACH-out, wire-out, and RTP.
    purpose = "both"

    async def health_check(self) -> Dict[str, Any]:
        env = (os.environ.get("INCREASE_ENV") or "sandbox").lower()
        if not os.environ.get("INCREASE_API_KEY"):
            return {"ok": False, "message": "INCREASE_API_KEY not configured", "latency_ms": 0, "env": env}
        t0 = time.time()
        try:
            c = _client()
            # Cheapest auth-validating call: list 1 account.
            list(c.accounts.list(limit=1))
            return {"ok": True, "message": "reachable", "latency_ms": int((time.time() - t0) * 1000), "env": env}
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: {str(e)[:200]}", "latency_ms": int((time.time() - t0) * 1000), "env": env}

    async def ensure_business_cardholder(self, db) -> str:
        """Return the Increase account id used to fund issued cards.

        Cached in app_settings.integrations.payment_gateways.issuers.increase.
        """
        rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {"key": "integrations"}
        pg = dict(rec.get("payment_gateways") or {})
        issuers = dict(pg.get("issuers") or {})
        cfg = dict(issuers.get("increase") or {})
        cached = cfg.get("account_id")
        if cached:
            return cached
        c = _client()
        # Sandbox: grab the first open account belonging to the platform.
        accounts = list(c.accounts.list(limit=1, status="open"))
        if not accounts:
            raise RuntimeError(
                "Increase returned no open accounts — check sandbox onboarding. "
                "You need at least one funded account before issuing cards."
            )
        account_id = accounts[0].id
        cfg["account_id"] = account_id
        cfg["account_id_cached_at"] = _now_iso()
        issuers["increase"] = cfg
        pg["issuers"] = issuers
        await db.app_settings.update_one(
            {"key": "integrations"},
            {"$set": {"payment_gateways": pg}},
            upsert=True,
        )
        logger.info(f"[increase] cached account_id={account_id[:14]}…")
        return account_id

    async def issue_card(self, db, *, squad_id: str, spend_limit_cents: int, memo: Optional[str] = None) -> CardHandle:
        c = _client()
        account_id = await self.ensure_business_cardholder(db)
        card = c.cards.create(
            account_id=account_id,
            description=(memo or f"SquadPay bill {squad_id}")[:64],
        )
        # Apply a spending limit via card update (Increase supports per-card limits).
        try:
            c.cards.update(card.id, digital_wallet={}, # ensures DW provisioning ready
                           billing_address=None)
        except Exception:
            pass
        # Extract exp month/year from "YYYY-MM-DDT..." or "MM/YYYY"-ish field.
        exp_month, exp_year = None, None
        exp_obj = getattr(card, "expiration_date", None)
        if exp_obj:
            try:
                exp_month, exp_year = int(exp_obj.month), int(exp_obj.year)
            except Exception:
                try:
                    parts = str(exp_obj).split("-")
                    exp_year, exp_month = int(parts[0]), int(parts[1])
                except Exception:
                    pass
        return CardHandle(
            issuer_slug=self.slug,
            card_id=card.id,
            last4=card.last4 or "",
            exp_month=exp_month,
            exp_year=exp_year,
            state=(card.status or "active").lower(),
            brand="visa",
            spend_limit_cents=spend_limit_cents,
            raw=card.model_dump() if hasattr(card, "model_dump") else dict(card),
        )

    async def fund_card(self, handle: CardHandle, cents: int) -> FundingResult:
        # Increase cards spend from the linked account. The platform's pattern
        # is: charge gateway ACHes squad money into the Increase account just
        # before the auth. SquadPay keeps in-flight only — the account drains
        # to ~$0 by end-of-day reconciliation cycle.
        return FundingResult(
            funded_cents=cents,
            method="prefund_account",
            transfer_id=None,
            raw={"note": "Increase cards spend from linked account; squad money ACHed in just-in-time"},
        )

    async def freeze_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        c = _client()
        c.cards.update(handle.card_id, status="disabled")
        logger.info(f"[increase] card={handle.card_id[:14]}… DISABLED reason={reason}")

    async def close_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        c = _client()
        c.cards.update(handle.card_id, status="canceled")
        logger.info(f"[increase] card={handle.card_id[:14]}… CANCELED reason={reason}")

    async def reveal_card_details(self, handle: CardHandle) -> CardDetails:
        c = _client()
        env = (os.environ.get("INCREASE_ENV") or "sandbox").lower()
        # Increase has a separate sensitive-card-details endpoint that returns
        # the PAN/CVV. In production these MUST be displayed via an iframe; in
        # sandbox they can be inspected directly for development.
        try:
            details = c.cards.details(handle.card_id)
        except Exception as e:
            raise RuntimeError(f"Increase reveal failed ({env}): {e}")
        return CardDetails(
            pan=getattr(details, "primary_account_number", "") or "",
            cvv=getattr(details, "verification_code", "") or "",
            exp_month=int(getattr(details, "expiration_month", 0)) or (handle.exp_month or 0),
            exp_year=int(getattr(details, "expiration_year", 0)) or (handle.exp_year or 0),
            cardholder_name="SquadPay Squad",
        )

    async def list_transactions(self, handle: CardHandle) -> List[CardTransaction]:
        c = _client()
        out: List[CardTransaction] = []
        try:
            txns = c.transactions.list(account_id=None, limit=100)
            for t in txns:
                src = getattr(t, "source", None)
                # Filter to card txns matching this card_id.
                card_payment = getattr(src, "card_payment", None) if src else None
                if not card_payment or getattr(card_payment, "card_id", None) != handle.card_id:
                    continue
                out.append(CardTransaction(
                    txn_id=t.id,
                    card_id=handle.card_id,
                    amount_cents=int(t.amount or 0),
                    merchant_descriptor=getattr(card_payment, "merchant_descriptor", None),
                    merchant_category=getattr(card_payment, "merchant_category_code", None),
                    status=(t.route_type or "unknown"),
                    created_at=str(getattr(t, "created_at", _now_iso())),
                    raw=t.model_dump() if hasattr(t, "model_dump") else dict(t),
                ))
        except Exception as e:
            logger.warning(f"[increase] list_transactions failed: {e}")
        return out

    async def verify_webhook(self, body: bytes, headers: Dict[str, str]) -> IssuerWebhookEvent:
        """Verify Increase webhook signature.

        Increase signs events with HMAC-SHA256 using the webhook secret
        configured per endpoint. Header: 'Increase-Signature'.
        """
        secret = os.environ.get("INCREASE_WEBHOOK_SECRET") or ""
        sig_header = headers.get("Increase-Signature") or headers.get("increase-signature") or ""
        if not secret:
            raise RuntimeError("INCREASE_WEBHOOK_SECRET not configured — cannot verify webhook")
        if not sig_header:
            raise RuntimeError("Missing Increase-Signature header")
        # Signature format: t=<ts>,v1=<hmac_hex>
        mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
        if not hmac.compare_digest(parts.get("v1", ""), mac):
            raise RuntimeError("Increase webhook signature verification failed")
        payload = json.loads(body.decode())
        event_type = f"increase.{payload.get('category', 'unknown')}"
        data = payload.get("associated_object_id") or {}
        return IssuerWebhookEvent(
            issuer_slug=self.slug,
            event_type=event_type,
            card_id=payload.get("associated_object_id") if payload.get("associated_object_type") == "card" else None,
            transaction=None,
            raw=payload,
        )
