"""Abstract Issuer Adapter contract — provider-agnostic virtual card issuance.

Design rule (June 2025 founder spec):
  Only ONE issuer is active at any time. The active issuer owns ALL flows for
  every squad created while it is active: card issuance, funding model,
  tokenization (Apple/Google Wallet), webhook handling, freeze/close.

  Mixing providers per-squad is explicitly forbidden — it adds complexity
  without benefit and complicates accounting reconciliation.

Switching providers is a runtime config change (admin panel). The adapter
code itself is deploy-time — we only enable/disable already-integrated
adapters.

Provider-specific concerns (KYC bootstrapping, Apple Pay tokenization SDK,
funding source, webhook signature scheme) all live inside the adapter and
are never leaked back up to the routes layer.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CardHandle:
    """Provider-agnostic reference to an issued virtual card."""
    issuer_slug: str               # "stripe" | "lithic" | "highnote" | "unit"
    card_id: str                   # provider's card token / id
    last4: str
    exp_month: Optional[int]       # may be None until card is funded/activated
    exp_year: Optional[int]
    state: str                     # "active" | "paused" | "closed"
    brand: Optional[str] = None    # "visa" | "mastercard"
    spend_limit_cents: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)   # provider's raw payload (audit)


@dataclass
class CardDetails:
    """Sensitive card details — returned ONLY via authenticated reveal flow.

    Never persisted to our DB. Held in memory just long enough to surface
    in the reveal UI (with TTL).
    """
    pan: str
    cvv: str
    exp_month: int
    exp_year: int
    cardholder_name: Optional[str] = None


@dataclass
class FundingResult:
    """Result of funding a card up to the squad's pooled amount.

    Some providers (Stripe Issuing) require an explicit prefund call.
    Others (Lithic, Highnote) auto-fund from a linked bank on each auth.
    Adapters return a uniform shape so callers don't need to know.
    """
    funded_cents: int
    method: str                    # "prefund_balance" | "auto_from_bank" | "none"
    transfer_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CardTransaction:
    """Provider-agnostic view of an authorization/settlement on a card."""
    txn_id: str
    card_id: str
    amount_cents: int              # positive = debit (auth), negative = refund
    merchant_descriptor: Optional[str]
    merchant_category: Optional[str]
    status: str                    # "pending" | "settled" | "reversed" | "declined"
    created_at: str                # ISO 8601
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WalletProvisioningPayload:
    """Opaque payload the mobile app passes to PKAddPaymentPass /
    Google Pay TapAndPay APIs to add the card to the device wallet.

    Stripe's `create_push_provisioning_data` returns a specific shape;
    Lithic / Highnote / Unit each have their own. The mobile SDK adapter
    on the frontend reads `provider` to know which native flow to drive.
    """
    provider: str                  # mirror of issuer slug
    platform: str                  # "apple" | "google"
    payload: Dict[str, Any]


@dataclass
class IssuerWebhookEvent:
    """Normalized webhook event from any issuer."""
    issuer_slug: str
    event_type: str                # provider-prefixed: "lithic.card.created" etc.
    card_id: Optional[str]
    transaction: Optional[CardTransaction]
    raw: Dict[str, Any] = field(default_factory=dict)


class IssuerAdapter(ABC):
    """Pluggable virtual-card issuer contract.

    Implementations MUST be stateless — load config from db/env on each call.
    Concurrent calls across squads must be safe.
    """

    slug: str = "abstract"
    display_name: str = "Abstract Issuer"

    # ---- capability flags (let callers fail fast on unsupported features) ----
    supports_apple_wallet: bool = False
    supports_google_wallet: bool = False
    supports_single_use: bool = False     # one card per bill (preferred for SquadPay)
    supports_multi_use: bool = True

    # ---- health / readiness ----
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Return {ok: bool, message: str, latency_ms: int, env: str}.

        Used by the admin panel to verify a provider is reachable BEFORE the
        admin flips it to primary.
        """
        raise NotImplementedError

    # ---- cardholder / business onboarding (one-time per env) ----
    @abstractmethod
    async def ensure_business_cardholder(self, db) -> str:
        """Idempotent: create or fetch the business-level cardholder id.

        Cached in `app_settings.integrations.issuer.<slug>.cardholder_id`.
        """
        raise NotImplementedError

    # ---- card lifecycle ----
    @abstractmethod
    async def issue_card(
        self,
        db,
        *,
        squad_id: str,
        spend_limit_cents: int,
        memo: Optional[str] = None,
    ) -> CardHandle:
        """Issue a NEW single-use (or single-bill scoped) card for this squad.

        spend_limit_cents = bill total + any allowed overage buffer.
        """
        raise NotImplementedError

    @abstractmethod
    async def fund_card(self, handle: CardHandle, cents: int) -> FundingResult:
        """Ensure the card has at least `cents` available.

        Adapters that auto-fund return method='auto_from_bank' with funded_cents=cents.
        Adapters that prefund a balance return method='prefund_balance' + transfer_id.
        """
        raise NotImplementedError

    @abstractmethod
    async def freeze_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        """Pause the card (reversible)."""
        raise NotImplementedError

    @abstractmethod
    async def close_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        """Permanently close the card (irreversible)."""
        raise NotImplementedError

    @abstractmethod
    async def reveal_card_details(self, handle: CardHandle) -> CardDetails:
        """Return PAN/CVV — caller MUST gate behind OTP + TTL."""
        raise NotImplementedError

    @abstractmethod
    async def list_transactions(self, handle: CardHandle) -> List[CardTransaction]:
        """Get all txns for this card (auths, settlements, refunds)."""
        raise NotImplementedError

    # ---- wallet provisioning (Apple Pay / Google Pay) ----
    async def provision_to_apple_wallet(self, handle: CardHandle) -> WalletProvisioningPayload:
        if not self.supports_apple_wallet:
            raise NotImplementedError(f"{self.slug} adapter does not support Apple Wallet")
        raise NotImplementedError

    async def provision_to_google_wallet(self, handle: CardHandle) -> WalletProvisioningPayload:
        if not self.supports_google_wallet:
            raise NotImplementedError(f"{self.slug} adapter does not support Google Wallet")
        raise NotImplementedError

    # ---- webhooks ----
    @abstractmethod
    async def verify_webhook(self, body: bytes, headers: Dict[str, str]) -> IssuerWebhookEvent:
        """Validate webhook signature, parse + normalize. Raise on failure."""
        raise NotImplementedError
