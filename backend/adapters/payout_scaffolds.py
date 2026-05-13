"""Scaffold payout adapters (Branch / Wise) — Phase 5a.

Defence-in-depth: every method raises HTTPException(501) so live money can
never accidentally route here before the integration ships.
"""
from __future__ import annotations
from typing import Dict, Optional

from fastapi import HTTPException

from .payout_base import (
    PayoutAdapter,
    CardCaptureSession,
    CardToken,
    PushToCardResult,
    PayoutWebhookEvent,
)


def _not_shipped(provider: str) -> HTTPException:
    return HTTPException(
        status_code=501,
        detail=(
            f"{provider} payout adapter is not yet implemented. "
            "Credentials may be saved via the admin UI but live payouts "
            "will only route here once the adapter ships in a future release."
        ),
    )


class _ScaffoldPayoutAdapter(PayoutAdapter):
    slug = "scaffold"
    display_name = "Scaffold Payout Provider"

    async def create_card_capture_session(self, **kwargs) -> CardCaptureSession:
        raise _not_shipped(self.display_name)

    async def retrieve_card_token(self, capture_id: str) -> Optional[CardToken]:
        raise _not_shipped(self.display_name)

    async def push_to_card(self, **kwargs) -> PushToCardResult:
        raise _not_shipped(self.display_name)

    async def verify_webhook(self, body: bytes, signature: Optional[str]) -> PayoutWebhookEvent:
        raise _not_shipped(self.display_name)


class BranchPayoutAdapter(_ScaffoldPayoutAdapter):
    slug = "branch"
    display_name = "Branch"


class WisePayoutAdapter(_ScaffoldPayoutAdapter):
    slug = "wise"
    display_name = "Wise"
