"""Scaffold charge adapters (Square / Adyen / Flutterwave) — Phase 4.

Defence-in-depth: even if the gateway-activation guard is somehow bypassed
(manual mongo edit, future refactor mistake), these adapters will raise
HTTP 501 on EVERY method call. No real money will ever route through a
non-shipped integration silently.

To "ship" one of these, replace the body of each method with a real
implementation that conforms to ChargeAdapter, mark it as `status:
production` in gateway_config.GATEWAY_PROVIDERS, and add a unit-test.
"""
from __future__ import annotations
from typing import Dict, List, Optional

from fastapi import HTTPException

from .base import ChargeAdapter, CheckoutSession, CheckoutStatus, WebhookEvent


def _not_shipped(provider: str) -> HTTPException:
    return HTTPException(
        status_code=501,
        detail=(
            f"{provider} charge adapter is not yet implemented. "
            "Credentials may be saved via the admin UI but live charges "
            "will only route here once the adapter ships in a future release."
        ),
    )


class _ScaffoldChargeAdapter(ChargeAdapter):
    """Base scaffold — every method raises 501."""

    slug = "scaffold"
    display_name = "Scaffold Charge Provider"

    async def create_checkout_session(self, **kwargs) -> CheckoutSession:  # noqa: D401
        raise _not_shipped(self.display_name)

    async def retrieve_session(self, session_id: str) -> CheckoutStatus:
        raise _not_shipped(self.display_name)

    async def verify_webhook(self, body: bytes, signature: Optional[str]) -> WebhookEvent:
        raise _not_shipped(self.display_name)


class SquareChargeAdapter(_ScaffoldChargeAdapter):
    slug = "square"
    display_name = "Square"


class AdyenChargeAdapter(_ScaffoldChargeAdapter):
    slug = "adyen"
    display_name = "Adyen"


class FlutterwaveChargeAdapter(_ScaffoldChargeAdapter):
    slug = "flutterwave"
    display_name = "Flutterwave"
