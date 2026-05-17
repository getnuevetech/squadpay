"""Stripe Issuing adapter — wraps the existing Stripe-coupled `issuing.py`.

Why a thin wrapper rather than a full refactor:
  The original `issuing.py` is heavily integrated with admin settings, KYC,
  cardholder lookup, push-provisioning flags, etc. Moving every Stripe call
  into this adapter today would risk breaking many call sites. Instead, this
  adapter delegates to the existing functions — the contract is satisfied,
  the surface is normalised, and the legacy module keeps working unchanged.

When Lithic / Highnote / Unit become the primary issuer, this adapter simply
stops being called — the registry routes everything to the active one. Stripe
code stays warm in case we ever return to it.
"""
from __future__ import annotations
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


def _stripe():
    import stripe as _s
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=True)
    _s.api_key = os.environ.get("STRIPE_API_KEY")
    return _s


class StripeIssuerAdapter(IssuerAdapter):
    slug = "stripe"
    display_name = "Stripe Issuing"
    supports_apple_wallet = True
    supports_google_wallet = True
    supports_single_use = True
    supports_multi_use = True

    async def health_check(self) -> Dict[str, Any]:
        """Ping Stripe by listing 1 cardholder — cheap + auth-validating."""
        api_key = os.environ.get("STRIPE_API_KEY")
        if not api_key:
            return {"ok": False, "message": "STRIPE_API_KEY not set in .env", "latency_ms": 0, "env": "missing"}
        env = "sandbox" if api_key.startswith("sk_test_") else "live"
        t0 = time.time()
        try:
            s = _stripe()
            s.issuing.Cardholder.list(limit=1)
            return {"ok": True, "message": "reachable", "latency_ms": int((time.time() - t0) * 1000), "env": env}
        except Exception as e:
            return {"ok": False, "message": str(e)[:200], "latency_ms": int((time.time() - t0) * 1000), "env": env}

    async def ensure_business_cardholder(self, db) -> str:
        from issuing import get_or_create_business_cardholder
        return await get_or_create_business_cardholder(db)

    async def issue_card(self, db, *, squad_id: str, spend_limit_cents: int, memo: Optional[str] = None) -> CardHandle:
        from issuing import issue_group_card
        group = await db.groups.find_one({"id": squad_id}, {"_id": 0})
        if not group:
            raise ValueError(f"Squad {squad_id} not found")
        result = await issue_group_card(db, group)
        if not result:
            raise RuntimeError("Stripe Issuing returned no card payload")
        return CardHandle(
            issuer_slug=self.slug,
            card_id=result.get("stripe_card_id") or result.get("id") or "",
            last4=result.get("last4", ""),
            exp_month=result.get("exp_month"),
            exp_year=result.get("exp_year"),
            state=result.get("status", "active"),
            brand=result.get("brand"),
            spend_limit_cents=spend_limit_cents,
            raw=result,
        )

    async def fund_card(self, handle: CardHandle, cents: int) -> FundingResult:
        # Stripe Issuing draws from Stripe balance — the platform owner pre-funds.
        # Squad contributions land in Stripe balance via charge gateway; no explicit
        # per-card transfer is needed.
        return FundingResult(funded_cents=cents, method="prefund_balance", transfer_id=None, raw={"note": "stripe issuing draws from platform balance"})

    async def freeze_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        s = _stripe()
        s.issuing.Card.modify(handle.card_id, status="inactive", metadata={"freeze_reason": reason})

    async def close_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        s = _stripe()
        s.issuing.Card.modify(handle.card_id, status="canceled", metadata={"close_reason": reason})

    async def reveal_card_details(self, handle: CardHandle) -> CardDetails:
        # Stripe's reveal goes via PCI-compliant Stripe.js — backend should NOT
        # return raw PAN. We surface a stub here; the real reveal happens in
        # the existing /api/issuing/reveal route which returns an ephemeral key.
        raise NotImplementedError(
            "Stripe Issuing reveal must be performed via Stripe.js + ephemeral key. "
            "Use the /api/issuing/reveal route, not adapter.reveal_card_details()."
        )

    async def list_transactions(self, handle: CardHandle) -> List[CardTransaction]:
        s = _stripe()
        out: List[CardTransaction] = []
        try:
            txns = s.issuing.Transaction.list(card=handle.card_id, limit=100)
            for t in txns.auto_paging_iter():
                out.append(CardTransaction(
                    txn_id=t["id"],
                    card_id=handle.card_id,
                    amount_cents=int(t.get("amount", 0)),
                    merchant_descriptor=(t.get("merchant_data") or {}).get("name"),
                    merchant_category=(t.get("merchant_data") or {}).get("category"),
                    status=t.get("type", "unknown"),
                    created_at=str(t.get("created", "")),
                    raw=dict(t),
                ))
        except Exception as e:
            logger.warning(f"[stripe_issuer] list_transactions failed: {e}")
        return out

    async def verify_webhook(self, body: bytes, headers: Dict[str, str]) -> IssuerWebhookEvent:
        # Delegated to the existing /app/backend/stripe_webhooks.py which already
        # handles signature verification for inbound issuing events.
        raise NotImplementedError("Stripe webhooks are handled by stripe_webhooks.py, not the adapter")
