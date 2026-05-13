"""Adapter registry — resolves the live charge/payout adapter at request time.

The active provider for each group lives in db.gateway_config (cached in
``gateway_config._ACTIVE_BY_GROUP``). This module reads that cache and
returns the matching adapter instance.

NEVER cache adapter instances across requests for too long — they may hold
provider credentials in memory. We rebuild each adapter from gateway_config
on every resolution for correctness; the cost is negligible (object construction).
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from fastapi import HTTPException

from gateway_config import get_active_provider, PROVIDER_BY_SLUG

from .base import ChargeAdapter
from .charge_stripe import StripeChargeAdapter
from .charge_scaffolds import (
    SquareChargeAdapter,
    AdyenChargeAdapter,
    FlutterwaveChargeAdapter,
)
from .payout_base import PayoutAdapter
from .payout_astra import AstraPayoutAdapter
from .payout_stripe_connect import StripeConnectPayoutAdapter
from .payout_scaffolds import BranchPayoutAdapter, WisePayoutAdapter

logger = logging.getLogger(__name__)


# Static slug → adapter class map. New adapters land here.
_CHARGE_REGISTRY = {
    "stripe": StripeChargeAdapter,
    "square": SquareChargeAdapter,
    "adyen": AdyenChargeAdapter,
    "flutterwave": FlutterwaveChargeAdapter,
}

_PAYOUT_REGISTRY = {
    "stripe_connect": StripeConnectPayoutAdapter,
    "astra": AstraPayoutAdapter,
    "branch": BranchPayoutAdapter,
    "wise": WisePayoutAdapter,
}


async def _resolve_credentials(db, group: str, slug: str) -> dict:
    """Pull decrypted credentials for the (group, slug) from db.gateway_config.

    Returns an empty dict if no row exists (e.g. fresh DB before admin saves keys).
    Secrets are decrypted; non-secret fields returned as plain text.
    """
    from integrations import decrypt_secret  # local import to avoid cycles

    cfg = await db.gateway_config.find_one(
        {"group": group, "provider_slug": slug}, {"_id": 0}
    )
    if not cfg:
        return {}
    catalog = PROVIDER_BY_SLUG.get(slug, {})
    out: dict = {}
    creds_in = cfg.get("credentials_enc") or {}
    for field in catalog.get("fields", []):
        key = field["key"]
        val = creds_in.get(key)
        if val is None:
            continue
        if field["kind"] == "secret":
            try:
                out[key] = decrypt_secret(val)
            except Exception:
                out[key] = None
        else:
            out[key] = val
    return out


async def get_charge_adapter(db) -> ChargeAdapter:
    """Resolve and instantiate the currently-active charge adapter.

    Falls back to Stripe (env-key) if no active provider is set — keeps the
    existing setup working on first boot.
    """
    slug = get_active_provider("charge") or "stripe"
    cls = _CHARGE_REGISTRY.get(slug)
    if not cls:
        raise HTTPException(500, f"Unknown active charge provider: {slug}")

    if slug == "stripe":
        creds = await _resolve_credentials(db, "charge", "stripe")
        # Prefer admin-configured key; fall back to env (legacy bootstrap).
        api_key = creds.get("secret_key") or os.environ.get("STRIPE_API_KEY") or "sk_test_emergent"
        return StripeChargeAdapter(api_key=api_key)

    # Scaffolds — credentials may or may not be set; their methods raise 501 anyway.
    return cls()


async def get_payout_adapter(db) -> PayoutAdapter:
    """Resolve and instantiate the currently-active payout adapter.

    Returns None semantics not possible (HTTPException raised) — callers can
    assume an adapter is always returned (or 503 if no active provider).
    """
    slug = get_active_provider("payout")
    if not slug:
        raise HTTPException(
            503,
            "No active payout provider. Configure one in Admin → Payment Gateways → Payout.",
        )
    cls = _PAYOUT_REGISTRY.get(slug)
    if not cls:
        raise HTTPException(500, f"Unknown active payout provider: {slug}")

    if slug == "astra":
        creds = await _resolve_credentials(db, "payout", "astra")
        return AstraPayoutAdapter(
            client_id=creds.get("client_id"),
            client_secret=creds.get("client_secret"),
            webhook_secret=creds.get("webhook_secret"),
            environment=creds.get("environment") or "sandbox",
        )

    if slug == "stripe_connect":
        creds = await _resolve_credentials(db, "payout", "stripe_connect")
        api_key = creds.get("api_key") or os.environ.get("STRIPE_API_KEY") or "sk_test_emergent"
        return StripeConnectPayoutAdapter(
            api_key=api_key,
            webhook_secret=creds.get("webhook_secret") or "",
        )

    return cls()
