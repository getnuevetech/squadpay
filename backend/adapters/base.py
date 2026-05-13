"""Abstract Charge Adapter contract (Group A — money IN).

Every charge provider (Stripe live; Square/Adyen/Flutterwave scaffolds)
implements this protocol so the rest of the codebase never has to import
provider SDKs directly.

A charge adapter MUST:
  • Create a hosted checkout session given amount + return URLs + idempotency_key
  • Retrieve a session's payment status (for polling)
  • Verify webhook signatures (used by FastAPI webhook routes)

Anything provider-specific (line items, currency conversion, 3DS quirks)
belongs INSIDE the adapter — never leaked back up.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class CheckoutSession:
    """Provider-agnostic checkout session response."""
    session_id: str          # provider's session/intent id (e.g. Stripe cs_test_…)
    url: str                 # hosted checkout URL the user is redirected to
    amount_cents: int
    currency: str
    raw: Dict[str, Any]      # provider's raw response (audit only)


@dataclass
class CheckoutStatus:
    """Provider-agnostic checkout-status snapshot."""
    session_id: str
    status: Optional[str]            # e.g. "complete", "open", "expired"
    payment_status: Optional[str]    # "paid" | "unpaid" | "no_payment_required"
    amount_total_cents: Optional[int]
    currency: Optional[str]
    metadata: Dict[str, Any]
    raw: Dict[str, Any]


@dataclass
class WebhookEvent:
    event_type: str
    session_id: Optional[str]
    payment_status: Optional[str]
    raw: Dict[str, Any]


class ChargeAdapter(ABC):
    """Money-in provider contract. Implementations must be stateless."""

    slug: str = "abstract"
    display_name: str = "Abstract Charge Provider"

    @abstractmethod
    async def create_checkout_session(
        self,
        *,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: Dict[str, str],
        idempotency_key: str,
        line_items: Optional[list] = None,
        product_name: Optional[str] = None,
    ) -> CheckoutSession:
        """Create a hosted checkout session. Must be idempotent on ``idempotency_key``."""
        raise NotImplementedError

    @abstractmethod
    async def retrieve_session(self, session_id: str) -> CheckoutStatus:
        """Fetch latest payment status for a session."""
        raise NotImplementedError

    @abstractmethod
    async def verify_webhook(self, body: bytes, signature: Optional[str]) -> WebhookEvent:
        """Validate webhook signature; raise on failure. Return parsed event."""
        raise NotImplementedError
