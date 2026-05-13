"""Stripe Connect Express payout adapter (Phase 5a — June 2025).

Uses Stripe Connect Express + Instant Payouts to push money to a Lead's
external debit card.

Onboarding model — far simpler than Astra OAuth:

  1. We create a Stripe Connect Express account for the user once
     (``stripe.Account.create(type="express", ...)``) and persist
     ``acct_xxx`` on ``db.connect_user_accounts``.

  2. We mint a one-shot Account Link via
     ``stripe.AccountLink.create(account=acct_xxx, return_url=..., refresh_url=..., type="account_onboarding")``
     The user loads this URL in our WebView; Stripe handles all KYC +
     external-account (debit card) collection on its own hosted pages.

  3. Stripe redirects to ``return_url`` (we don't get a code — Stripe
     account links aren't OAuth). The frontend just pings us to
     re-sync.

  4. We call ``stripe.Account.retrieve(acct_xxx)`` to confirm
     ``details_submitted == True`` and ``payouts_enabled == True`` and
     list ``external_accounts.cards`` (we cache these in
     ``db.connect_user_cards`` for the UI).

  5. To cash out, we call
     ``stripe.Payout.create(amount, currency, destination=card_id,
                            method="instant", stripe_account=acct_xxx,
                            idempotency_key=txn_id)``
     Funds land on the Lead's debit card in seconds (Visa Direct).

We NEVER see raw card PAN — Stripe collects it on its own hosted pages.
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional

import stripe as _stripe_sdk
from fastapi import HTTPException

from .payout_base import (
    PayoutAdapter,
    CardCaptureSession,
    CardToken,
    PushToCardResult,
    PayoutWebhookEvent,
)

logger = logging.getLogger(__name__)


class StripeConnectPayoutAdapter(PayoutAdapter):
    slug = "stripe_connect"
    display_name = "Stripe Connect (Instant Payouts)"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        platform_country: str = "US",
    ):
        self.api_key = api_key or os.environ.get("STRIPE_API_KEY") or ""
        self.webhook_secret = webhook_secret or ""
        self.platform_country = platform_country
        _stripe_sdk.api_key = self.api_key

    # ─────────────────────────────────────────────────────────────────────
    # Higher-level helpers used by payout_routes for the Connect flow
    # ─────────────────────────────────────────────────────────────────────

    async def ensure_connected_account(
        self, *, email: Optional[str], user_id: str, business_type: str = "individual"
    ) -> str:
        """Idempotently create a Stripe Connect Express account for the user.

        Returns the ``acct_xxx`` id. Caller is responsible for persisting
        the (user_id → acct_xxx) mapping.
        """
        try:
            acct = _stripe_sdk.Account.create(
                type="express",
                country=self.platform_country,
                email=email or None,
                business_type=business_type,
                capabilities={
                    "card_payments": {"requested": False},  # we don't need them to CHARGE
                    "transfers": {"requested": True},        # we need to TRANSFER to them
                },
                metadata={"squadpay_user_id": user_id},
            )
        except Exception as e:
            logger.exception(f"[stripe-connect] Account.create failed: {e}")
            raise HTTPException(502, f"Stripe Connect error creating account: {e}")
        return acct.id

    async def create_account_link(
        self,
        *,
        account_id: str,
        return_url: str,
        refresh_url: str,
    ) -> str:
        try:
            link = _stripe_sdk.AccountLink.create(
                account=account_id,
                return_url=return_url,
                refresh_url=refresh_url,
                type="account_onboarding",
                collect="eventually_due",
            )
        except Exception as e:
            logger.exception(f"[stripe-connect] AccountLink.create failed: {e}")
            raise HTTPException(502, f"Stripe Connect error creating onboarding link: {e}")
        return link.url

    async def retrieve_account(self, account_id: str) -> Dict[str, Any]:
        try:
            a = _stripe_sdk.Account.retrieve(account_id)
        except Exception as e:
            logger.exception(f"[stripe-connect] Account.retrieve failed: {e}")
            raise HTTPException(502, f"Stripe Connect error retrieving account: {e}")
        return {
            "id": a.id,
            "details_submitted": bool(getattr(a, "details_submitted", False)),
            "payouts_enabled": bool(getattr(a, "payouts_enabled", False)),
            "charges_enabled": bool(getattr(a, "charges_enabled", False)),
            "requirements": (a.requirements.to_dict() if getattr(a, "requirements", None) else {}),
            "email": getattr(a, "email", None),
        }

    async def list_external_cards(self, account_id: str) -> List[Dict[str, Any]]:
        """Return the user's external_accounts that are CARDS (debit cards)."""
        try:
            ext = _stripe_sdk.Account.list_external_accounts(account_id, object="card", limit=20)
        except Exception as e:
            logger.exception(f"[stripe-connect] list_external_accounts(card) failed: {e}")
            raise HTTPException(502, f"Stripe Connect error listing cards: {e}")
        out: List[Dict[str, Any]] = []
        for c in (ext.data or []):
            out.append({
                "id": c.id,
                "brand": getattr(c, "brand", None),
                "last4": getattr(c, "last4", None),
                "exp_month": getattr(c, "exp_month", None),
                "exp_year": getattr(c, "exp_year", None),
                "is_default": bool(getattr(c, "default_for_currency", False)),
                "currency": getattr(c, "currency", None),
                "fingerprint": getattr(c, "fingerprint", None),
            })
        return out

    # ─────────────────────────────────────────────────────────────────────
    # PayoutAdapter contract
    # ─────────────────────────────────────────────────────────────────────

    async def create_card_capture_session(
        self,
        *,
        user_id: str,
        return_url: str,
        cancel_url: str,
        metadata: Dict[str, str],
    ) -> CardCaptureSession:
        """For Stripe Connect, the "capture session" is an Account Link.

        ``metadata`` MUST include ``account_id`` (server-side resolved
        before invocation). ``cancel_url`` is mapped to ``refresh_url``
        (Stripe re-issues a fresh link if the user bails mid-onboarding).
        """
        account_id = metadata.get("account_id")
        if not account_id:
            raise HTTPException(500, "Stripe Connect: account_id missing in metadata")
        url = await self.create_account_link(
            account_id=account_id,
            return_url=return_url,
            refresh_url=cancel_url,
        )
        return CardCaptureSession(
            capture_id=account_id,
            url=url,
            expires_at=None,
            raw={"account_id": account_id, "type": "account_onboarding"},
        )

    async def retrieve_card_token(self, capture_id: str) -> Optional[CardToken]:
        """Treat ``capture_id`` as the Connect account_id.

        Returns the user's default-for-currency card (if any) as a
        ``CardToken`` whose ``token`` is encoded as
        ``"{account_id}|{card_id}"`` — the same shape the rest of the
        adapter pipeline already uses.
        """
        cards = await self.list_external_cards(capture_id)
        if not cards:
            return None
        chosen = next((c for c in cards if c.get("is_default")), cards[0])
        return CardToken(
            token=f"{capture_id}|{chosen['id']}",
            brand=chosen.get("brand"),
            last4=chosen.get("last4"),
            raw=chosen,
        )

    async def push_to_card(
        self,
        *,
        amount_cents: int,
        currency: str,
        card_token: str,
        idempotency_key: str,
        metadata: Dict[str, str],
    ) -> PushToCardResult:
        """card_token MUST be ``"{acct_xxx}|{card_xxxx}"``.

        Issues a Transfer (platform → connected account) followed by an
        Instant Payout (connected account → card). The Transfer is the
        mechanism Stripe Connect uses to move platform funds into a
        connected balance; the Payout pushes them out to the chosen card.
        """
        if "|" not in card_token:
            raise HTTPException(500, "Stripe Connect push_to_card: card_token must be 'acct_xxx|card_xxx'")
        account_id, card_id = card_token.split("|", 1)

        meta_str = {k: str(v) for k, v in (metadata or {}).items()}

        # 1. Transfer from platform → connected account
        try:
            transfer = _stripe_sdk.Transfer.create(
                amount=int(amount_cents),
                currency=currency.lower(),
                destination=account_id,
                metadata=meta_str,
                idempotency_key=f"{idempotency_key}_xfer",
            )
        except Exception as e:
            logger.exception(f"[stripe-connect] Transfer.create failed: {e}")
            raise HTTPException(502, f"Stripe Connect transfer failed: {e}")

        # 2. Instant Payout from connected account → card
        try:
            payout = _stripe_sdk.Payout.create(
                amount=int(amount_cents),
                currency=currency.lower(),
                destination=card_id,
                method="instant",
                metadata={**meta_str, "transfer_id": transfer.id},
                stripe_account=account_id,
                idempotency_key=f"{idempotency_key}_payout",
            )
        except Exception as e:
            logger.exception(f"[stripe-connect] Payout.create failed: {e}")
            # If payout fails we ALREADY moved funds via Transfer. They sit in the
            # connected account balance and need manual reversal — admin tooling job.
            # Re-raise so caller surfaces the error.
            raise HTTPException(
                502,
                f"Funds moved to connected account but Instant Payout failed: {e}. "
                "Funds are safely held in the user's Stripe Connect balance.",
            )

        status_map = {"paid": "succeeded", "pending": "pending", "in_transit": "pending", "failed": "failed"}
        return PushToCardResult(
            provider_payout_id=payout.id,
            status=status_map.get(getattr(payout, "status", "pending"), "pending"),
            amount_cents=int(getattr(payout, "amount", amount_cents)),
            currency=(getattr(payout, "currency", currency) or currency).lower(),
            fee_cents=None,  # Stripe charges Instant Payout fee on the merchant side; reported async via BalanceTransaction
            raw={"transfer_id": transfer.id, "payout_id": payout.id, "status": getattr(payout, "status", None)},
        )

    async def verify_webhook(self, body: bytes, signature: Optional[str]) -> PayoutWebhookEvent:
        if not signature:
            raise HTTPException(400, "Missing Stripe-Signature header")
        if not self.webhook_secret:
            raise HTTPException(503, "Stripe Connect webhook secret not configured")
        try:
            evt = _stripe_sdk.Webhook.construct_event(body, signature, self.webhook_secret)
        except Exception as e:
            logger.exception(f"[stripe-connect-webhook] signature verify failed: {e}")
            raise HTTPException(400, f"Stripe Connect webhook signature mismatch: {e}")
        # Pull the inner object — for `payout.*` events the object is a Payout
        obj = (evt.get("data") or {}).get("object") or {}
        return PayoutWebhookEvent(
            event_type=evt.get("type") or "unknown",
            provider_payout_id=obj.get("id"),
            status=obj.get("status"),
            raw=evt,
        )
