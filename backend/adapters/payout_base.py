"""Abstract Payout Adapter contract (Group B — money OUT to user debit cards).

Every payout provider (Astra live; Branch/Wise scaffolds) implements this so
the rest of the codebase never imports provider SDKs directly.

A payout adapter MUST:
  • Issue a one-shot card-capture session URL (provider-hosted iframe).
    SquadPay NEVER touches the PAN — we receive only a token.
  • Push money to that token (debit card credit).
  • Verify webhook signatures.

PCI scope = zero. We store only tokens (provider-side reference) and the
last-4 / brand of the destination card (informational only).
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class CardCaptureSession:
    """Provider-agnostic card-capture iframe handle."""
    capture_id: str            # provider's reference for this capture flow
    url: str                   # hosted iframe URL (loaded in our WebView)
    expires_at: Optional[str]  # ISO timestamp when the URL stops working
    raw: Dict[str, Any]


@dataclass
class CardToken:
    """Tokenised destination card returned after a successful capture."""
    token: str                  # provider opaque token (NOT the PAN)
    brand: Optional[str]        # visa | mastercard | amex | discover
    last4: Optional[str]
    raw: Dict[str, Any]


@dataclass
class PushToCardResult:
    """Provider response after attempting a push-to-card payout."""
    provider_payout_id: str    # provider's id we'll receive in webhooks
    status: str                # "pending" | "succeeded" | "failed"
    amount_cents: int
    currency: str
    fee_cents: Optional[int]   # provider fee (if returned synchronously)
    raw: Dict[str, Any]


@dataclass
class PayoutWebhookEvent:
    event_type: str            # provider event name (provider_payout_succeeded, etc.)
    provider_payout_id: Optional[str]
    status: Optional[str]      # mapped to our internal status
    raw: Dict[str, Any]


class PayoutAdapter(ABC):
    """Money-out provider contract."""

    slug: str = "abstract"
    display_name: str = "Abstract Payout Provider"

    @abstractmethod
    async def create_card_capture_session(
        self,
        *,
        user_id: str,
        return_url: str,
        cancel_url: str,
        metadata: Dict[str, str],
    ) -> CardCaptureSession:
        """Generate the hosted iframe URL the user will load in a WebView."""
        raise NotImplementedError

    @abstractmethod
    async def retrieve_card_token(self, capture_id: str) -> Optional[CardToken]:
        """After the iframe redirects back, fetch the resulting token (or None if pending)."""
        raise NotImplementedError

    @abstractmethod
    async def push_to_card(
        self,
        *,
        amount_cents: int,
        currency: str,
        card_token: str,
        idempotency_key: str,
        metadata: Dict[str, str],
    ) -> PushToCardResult:
        """Send money to the tokenised destination card."""
        raise NotImplementedError

    @abstractmethod
    async def verify_webhook(self, body: bytes, signature: Optional[str]) -> PayoutWebhookEvent:
        """Validate webhook signature; raise on failure. Return parsed event."""
        raise NotImplementedError
