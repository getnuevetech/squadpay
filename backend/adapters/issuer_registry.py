"""Active-issuer registry — single point of truth for which provider is live.

Design:
  • Admin selects ONE active issuer via /api/admin/payment-gateways.
  • The active slug is stored in app_settings.integrations.payment_gateways.active_issuer.
  • Every code path that touches virtual cards calls get_active_issuer(db).
  • Only adapters with both `enabled=true` AND credentials configured are selectable.

Integration vs activation:
  • An adapter is INTEGRATED if we shipped its code (this is a deploy-time fact).
  • An adapter is ENABLED if admin toggled it on (configured credentials).
  • Exactly one enabled adapter is ACTIVE at any time.
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional, Type

from .issuer_base import IssuerAdapter
from .issuer_stripe import StripeIssuerAdapter
from .issuer_lithic import LithicIssuerAdapter
from .issuer_highnote import HighnoteIssuerAdapter
from .issuer_unit import UnitIssuerAdapter

logger = logging.getLogger(__name__)

# Integrated adapters — single source of truth.
# To add a new provider:
#   1. Implement adapters/issuer_<slug>.py against IssuerAdapter
#   2. Add an entry here
#   3. Deploy
#   Admin can then enable + activate it via the admin panel.
_INTEGRATED: Dict[str, Type[IssuerAdapter]] = {
    "stripe":   StripeIssuerAdapter,
    "lithic":   LithicIssuerAdapter,
    "highnote": HighnoteIssuerAdapter,
    "unit":     UnitIssuerAdapter,
}

# Default active when nothing is configured yet (preserves pre-refactor
# behavior for legacy installations).
_FALLBACK_ACTIVE = "stripe"


def list_integrated_slugs() -> List[str]:
    """Return slugs of all adapters present in this build."""
    return list(_INTEGRATED.keys())


def list_integrated_adapters() -> List[IssuerAdapter]:
    return [_INTEGRATED[s]() for s in _INTEGRATED]


async def _read_settings(db) -> Dict:
    rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {}
    pg = dict(rec.get("payment_gateways") or {})
    pg.setdefault("active_issuer", _FALLBACK_ACTIVE)
    pg.setdefault("issuers", {})
    return pg


async def get_active_slug(db) -> str:
    """Return the slug of the currently active issuer."""
    pg = await _read_settings(db)
    slug = pg.get("active_issuer") or _FALLBACK_ACTIVE
    if slug not in _INTEGRATED:
        logger.warning(f"[issuer_registry] active_issuer={slug!r} not integrated; falling back to {_FALLBACK_ACTIVE}")
        slug = _FALLBACK_ACTIVE
    return slug


async def get_active_issuer(db) -> IssuerAdapter:
    """Return an instance of the currently active issuer adapter.

    Stateless — safe to call on every request.
    """
    slug = await get_active_slug(db)
    return _INTEGRATED[slug]()


async def get_issuer_by_slug(slug: str) -> IssuerAdapter:
    if slug not in _INTEGRATED:
        raise ValueError(f"Issuer {slug!r} is not integrated in this build")
    return _INTEGRATED[slug]()


async def set_active_slug(db, slug: str, changed_by: str) -> Dict:
    """Switch the active issuer. Returns the updated payment_gateways block.

    The new issuer MUST already be enabled with credentials configured;
    otherwise the admin route should refuse the call upstream.
    """
    if slug not in _INTEGRATED:
        raise ValueError(f"Issuer {slug!r} is not integrated")
    rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {"key": "integrations"}
    pg = dict(rec.get("payment_gateways") or {})
    pg["active_issuer"] = slug
    pg["active_issuer_changed_by"] = changed_by
    pg["active_issuer_changed_at"] = _now_iso()
    await db.app_settings.update_one(
        {"key": "integrations"},
        {"$set": {"payment_gateways": pg}},
        upsert=True,
    )
    logger.info(f"[issuer_registry] active issuer set to {slug!r} by {changed_by}")
    return pg


def _now_iso() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat()
