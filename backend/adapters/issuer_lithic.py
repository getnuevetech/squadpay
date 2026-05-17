"""Lithic issuer adapter — real implementation (sandbox + production).

Lithic is our preferred alternative to Stripe Issuing for SquadPay because:
  • Zero monthly minimum (vs Stripe's $10-20k software fee at our stage)
  • First-class single-use virtual cards (one card per bill = clean accounting)
  • Auto-funding from a connected bank account on each authorization — no
    pre-funding required, which keeps SquadPay's 'never hold money'
    compliance posture intact.
  • Modern, well-documented API.

Environment:
  LITHIC_API_KEY  — sandbox or production key (set in /app/backend/.env)
  LITHIC_ENV      — "sandbox" | "production" (default: sandbox)

Notes on SquadPay 'never hold money' invariant:
  Lithic auto-funds cards from the platform's connected bank account when an
  authorization hits. Squad contributions flow through the charge gateway
  (Stripe Connect) and are immediately remitted to that bank account by the
  end-of-day settlement cycle. SquadPay never operates a Lithic deposit
  account or holds a Lithic balance.
"""
from __future__ import annotations
import datetime as dt
import hmac
import hashlib
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
    """Build a Lithic SDK client lazily so missing keys fail clearly."""
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=True)
    api_key = os.environ.get("LITHIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LITHIC_API_KEY not set. Configure it via the admin Payment Gateways panel "
            "or set it in /app/backend/.env before activating Lithic as the issuer."
        )
    env = (os.environ.get("LITHIC_ENV") or "sandbox").lower()
    from lithic import Lithic
    return Lithic(api_key=api_key, environment="sandbox" if env == "sandbox" else "production")


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class LithicIssuerAdapter(IssuerAdapter):
    slug = "lithic"
    display_name = "Lithic"
    supports_apple_wallet = True
    supports_google_wallet = True
    supports_single_use = True
    supports_multi_use = True

    async def health_check(self) -> Dict[str, Any]:
        api_key = os.environ.get("LITHIC_API_KEY")
        env = (os.environ.get("LITHIC_ENV") or "sandbox").lower()
        if not api_key:
            return {"ok": False, "message": "LITHIC_API_KEY not configured", "latency_ms": 0, "env": env}
        t0 = time.time()
        try:
            c = _client()
            # Cheapest auth-validating call: list 1 card.
            list(c.cards.list(page_size=1))
            return {"ok": True, "message": "reachable", "latency_ms": int((time.time() - t0) * 1000), "env": env}
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: {str(e)[:200]}", "latency_ms": int((time.time() - t0) * 1000), "env": env}

    async def ensure_business_cardholder(self, db) -> str:
        """Lithic uses 'account_token' as the business-level entity.

        Sandbox auto-provisions one for each API key on first use — we cache
        it in `app_settings.integrations.payment_gateways.issuers.lithic`.
        """
        rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {"key": "integrations"}
        pg = dict(rec.get("payment_gateways") or {})
        issuers = dict(pg.get("issuers") or {})
        lithic_cfg = dict(issuers.get("lithic") or {})
        cached = lithic_cfg.get("account_token")
        if cached:
            return cached
        c = _client()
        # Sandbox: list accounts and grab the first (the API key's owning account).
        accounts = list(c.accounts.list(page_size=1))
        if not accounts:
            raise RuntimeError("Lithic returned no accounts — check API key + sandbox onboarding")
        token = accounts[0].token
        lithic_cfg["account_token"] = token
        lithic_cfg["account_token_cached_at"] = _now_iso()
        issuers["lithic"] = lithic_cfg
        pg["issuers"] = issuers
        await db.app_settings.update_one(
            {"key": "integrations"},
            {"$set": {"payment_gateways": pg}},
            upsert=True,
        )
        logger.info(f"[lithic] cached account_token={token[:8]}…")
        return token

    async def issue_card(self, db, *, squad_id: str, spend_limit_cents: int, memo: Optional[str] = None) -> CardHandle:
        c = _client()
        # SINGLE_USE: card auto-closes after first successful auth + capture.
        # spend_limit + spend_limit_duration='TRANSACTION' = single bill cap.
        card = c.cards.create(
            type="SINGLE_USE",
            spend_limit=spend_limit_cents,
            spend_limit_duration="TRANSACTION",
            state="OPEN",
            memo=(memo or f"SquadPay bill {squad_id}")[:50],
        )
        return CardHandle(
            issuer_slug=self.slug,
            card_id=card.token,
            last4=card.last_four,
            exp_month=int(card.exp_month) if card.exp_month else None,
            exp_year=int(card.exp_year) if card.exp_year else None,
            state=(card.state or "OPEN").lower(),
            brand=getattr(card, "funding", {}).get("type") if isinstance(getattr(card, "funding", None), dict) else None,
            spend_limit_cents=spend_limit_cents,
            raw=card.model_dump() if hasattr(card, "model_dump") else dict(card),
        )

    async def fund_card(self, handle: CardHandle, cents: int) -> FundingResult:
        # Lithic auto-funds from the connected bank account on each auth.
        # No explicit transfer needed — the platform's bank account is debited
        # at settlement time. This keeps the 'never hold money' invariant
        # cleanly: squad money flows charge gateway → bank → Lithic settlement
        # all in a continuous in-flight pipeline.
        return FundingResult(
            funded_cents=cents,
            method="auto_from_bank",
            transfer_id=None,
            raw={"note": "Lithic auto-funds from connected bank at auth-time"},
        )

    async def freeze_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        c = _client()
        c.cards.update(card_token=handle.card_id, state="PAUSED")
        logger.info(f"[lithic] card={handle.card_id[:8]}… PAUSED reason={reason}")

    async def close_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        c = _client()
        c.cards.update(card_token=handle.card_id, state="CLOSED")
        logger.info(f"[lithic] card={handle.card_id[:8]}… CLOSED reason={reason}")

    async def reveal_card_details(self, handle: CardHandle) -> CardDetails:
        c = _client()
        # In sandbox, cards.retrieve returns PAN + CVV directly.
        # In production, you MUST use Lithic's PCI-compliant embed URL via
        # cards.embed() instead — raw PAN never touches your servers.
        env = (os.environ.get("LITHIC_ENV") or "sandbox").lower()
        if env != "sandbox":
            raise NotImplementedError(
                "Production reveal must use Lithic embed URL (cards.embed) — "
                "raw PAN MUST NOT pass through SquadPay servers in production."
            )
        card = c.cards.retrieve(card_token=handle.card_id)
        return CardDetails(
            pan=card.pan or "",
            cvv=card.cvv or "",
            exp_month=int(card.exp_month),
            exp_year=int(card.exp_year),
            cardholder_name="SquadPay Squad",
        )

    async def list_transactions(self, handle: CardHandle) -> List[CardTransaction]:
        c = _client()
        out: List[CardTransaction] = []
        try:
            txns = c.transactions.list(card_token=handle.card_id, page_size=100)
            for t in txns:
                # Lithic uses major-unit amounts? No — they use cents (integer).
                out.append(CardTransaction(
                    txn_id=t.token,
                    card_id=handle.card_id,
                    amount_cents=int(t.amount or 0),
                    merchant_descriptor=(t.merchant.descriptor if t.merchant else None),
                    merchant_category=(t.merchant.mcc if t.merchant else None),
                    status=(t.status or "unknown").lower(),
                    created_at=str(t.created or _now_iso()),
                    raw=t.model_dump() if hasattr(t, "model_dump") else dict(t),
                ))
        except Exception as e:
            logger.warning(f"[lithic] list_transactions failed: {e}")
        return out

    async def verify_webhook(self, body: bytes, headers: Dict[str, str]) -> IssuerWebhookEvent:
        """Verify Lithic webhook signature.

        Lithic signs webhooks with HMAC-SHA256 using the webhook secret
        configured per endpoint. Header: 'webhook-signature'.
        """
        secret = os.environ.get("LITHIC_WEBHOOK_SECRET") or ""
        sig_header = headers.get("webhook-signature") or headers.get("Webhook-Signature") or ""
        if not secret:
            raise RuntimeError("LITHIC_WEBHOOK_SECRET not configured — cannot verify webhook")
        if not sig_header:
            raise RuntimeError("Missing webhook-signature header")
        # Lithic's signature format follows Svix: t=<ts>,v1=<sig>
        # We use their SDK's built-in verifier for safety.
        try:
            from lithic.lib.webhooks import verify_webhook_signature  # type: ignore
            verify_webhook_signature(payload=body, headers=headers, secret=secret)
        except ImportError:
            # Fallback: manual HMAC if SDK helper isn't available.
            mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            if not any(hmac.compare_digest(mac, part.split("=", 1)[1]) for part in sig_header.split(",") if part.startswith("v1=")):
                raise RuntimeError("Lithic webhook signature verification failed")
        payload = json.loads(body.decode())
        event_type = f"lithic.{payload.get('type', 'unknown')}"
        data = payload.get("data") or {}
        card_id = (data.get("card_token") or data.get("token"))
        txn = None
        if "transaction" in (payload.get("type") or ""):
            txn = CardTransaction(
                txn_id=data.get("token", ""),
                card_id=card_id or "",
                amount_cents=int(data.get("amount") or 0),
                merchant_descriptor=((data.get("merchant") or {}).get("descriptor")),
                merchant_category=((data.get("merchant") or {}).get("mcc")),
                status=(data.get("status") or "unknown").lower(),
                created_at=str(data.get("created") or _now_iso()),
                raw=data,
            )
        return IssuerWebhookEvent(
            issuer_slug=self.slug,
            event_type=event_type,
            card_id=card_id,
            transaction=txn,
            raw=payload,
        )
