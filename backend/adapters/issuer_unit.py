"""Unit.co issuer adapter — real implementation (sandbox + production).

ARCHITECTURAL CONFLICT — PLEASE READ:
  Unit.co is fundamentally a Banking-as-a-Service (BaaS) platform. Every Unit
  card MUST be linked to a Unit-issued account (either depositAccount or
  creditAccount). Unit does not offer 'orphan' cards.

  This conflicts with the SquadPay compliance posture: "SquadPay NEVER holds
  money." If we ever open a Unit depositAccount, we have moved past the
  'pure aggregator' line into 'money transmitter' territory, which requires
  state-by-state MTL licensing.

  Two paths forward:
    A. Use Unit's `creditAccount` product (Unit's credit programs do NOT hold
       customer money — they're a revolving credit line backed by Unit's
       lending partner). This MIGHT preserve our posture but requires:
         • Unit-approved credit program onboarding (several weeks)
         • Lending partner agreement
         • May fail SquadPay's product model since we're not extending credit
           to consumers — we're pooling their money to pay a merchant.
    B. Drop Unit.co for SquadPay's primary issuer slot and keep it as a
       reserved adapter for any future product that legitimately requires
       account holding (e.g., merchant-side payouts to bank).

  Until that decision is made, this adapter:
    • PASSES health_check (sandbox API is reachable)
    • REFUSES to issue_card with a clear error explaining the conflict
    • Stubs the rest, ready to wire once the path is chosen.

Environment:
  UNIT_API_TOKEN  — v2.public Paseto token (sandbox or prod)
  UNIT_ENV        — "sandbox" | "production" (default sandbox)
"""
from __future__ import annotations
import datetime as dt
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from .issuer_base import (
    CardDetails,
    CardHandle,
    CardTransaction,
    FundingResult,
    IssuerAdapter,
    IssuerWebhookEvent,
)

logger = logging.getLogger(__name__)

_SANDBOX_URL = "https://api.s.unit.sh"
_LIVE_URL = "https://api.unit.co"

_COMPLIANCE_CONFLICT = (
    "Unit.co cards require a linked Unit account (deposit or credit). "
    "SquadPay's 'never hold money' policy forbids opening Unit deposit "
    "accounts. A `creditAccount`-based path is theoretically possible but "
    "requires Unit credit-program onboarding + lending partner approval. "
    "Sandbox connection works (health_check passes), but issuing real "
    "squad cards via Unit is intentionally blocked until the founder "
    "signs off on the credit-account path or designates Unit for "
    "merchant-side payouts only."
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _base_url() -> str:
    env = (os.environ.get("UNIT_ENV") or "sandbox").lower()
    return _LIVE_URL if env == "production" else _SANDBOX_URL


def _token() -> str:
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=True)
    t = os.environ.get("UNIT_API_TOKEN")
    if not t:
        raise RuntimeError(
            "UNIT_API_TOKEN not set. Configure via admin Payment Gateways panel "
            "or set in /app/backend/.env before activating Unit."
        )
    return t


async def _get(path: str, timeout: float = 10.0) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.api+json",
    }
    url = f"{_base_url()}{path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers=headers)
    r.raise_for_status()
    return r.json()


class UnitIssuerAdapter(IssuerAdapter):
    slug = "unit"
    display_name = "Unit.co"
    # Per founder spec (June 2025): Unit appears in BOTH the Virtual Card
    # Issuer tab AND the Payout tab. Issuance is blocked at runtime by the
    # NotImplementedError below (compliance conflict re: deposit accounts),
    # so even if an admin activates it, no squad card will be silently
    # mis-issued \u2014 they'll get a clear error.
    supports_apple_wallet = False
    supports_google_wallet = False
    supports_single_use = False
    supports_multi_use = False
    purpose = "both"

    async def health_check(self) -> Dict[str, Any]:
        env = (os.environ.get("UNIT_ENV") or "sandbox").lower()
        if not os.environ.get("UNIT_API_TOKEN"):
            return {"ok": False, "message": "UNIT_API_TOKEN not configured", "latency_ms": 0, "env": env}
        t0 = time.time()
        try:
            # Use a benign list endpoint to validate auth + reach.
            await _get("/applications?page%5Blimit%5D=1")
            return {
                "ok": True,
                "message": "reachable (issue_card disabled — see compliance note)",
                "latency_ms": int((time.time() - t0) * 1000),
                "env": env,
            }
        except httpx.HTTPStatusError as e:
            return {
                "ok": False,
                "message": f"HTTP {e.response.status_code}: {e.response.text[:140]}",
                "latency_ms": int((time.time() - t0) * 1000),
                "env": env,
            }
        except Exception as e:
            return {
                "ok": False,
                "message": f"{type(e).__name__}: {str(e)[:200]}",
                "latency_ms": int((time.time() - t0) * 1000),
                "env": env,
            }

    async def ensure_business_cardholder(self, db) -> str:
        """Return the Unit organization id (cached) — read-only, no account opened.

        We DO NOT create any Unit account here. We only fetch the org id from
        the API token claims for audit/health purposes.
        """
        rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {"key": "integrations"}
        pg = dict(rec.get("payment_gateways") or {})
        issuers = dict(pg.get("issuers") or {})
        cfg = dict(issuers.get("unit") or {})
        cached = cfg.get("org_id")
        if cached:
            return cached
        # Decode org id from the public Paseto token claims (Unit tokens are
        # v2.public Paseto — the payload is base64'd in the middle segment).
        try:
            import base64, json
            token = _token()
            parts = token.split(".")
            if len(parts) >= 3:
                # Unit's Paseto payload is everything after "v2.public." minus
                # the trailing signature bytes. We can't extract it cleanly
                # without their SDK. Fall back to a simple ping that returns
                # org-scoped data.
                pass
        except Exception:
            pass
        # Use the /applications endpoint to fetch our own org context.
        try:
            data = await _get("/applications?page%5Blimit%5D=1")
            included = (data.get("data") or [])
            if included and isinstance(included, list):
                org_id = (included[0].get("relationships", {}).get("org", {}).get("data", {}).get("id")) or "unit-org"
            else:
                org_id = "unit-org"
        except Exception as e:
            raise RuntimeError(f"Unit ensure_business_cardholder failed: {e}")
        cfg["org_id"] = org_id
        cfg["org_id_cached_at"] = _now_iso()
        issuers["unit"] = cfg
        pg["issuers"] = issuers
        await db.app_settings.update_one(
            {"key": "integrations"},
            {"$set": {"payment_gateways": pg}},
            upsert=True,
        )
        return org_id

    async def issue_card(self, db, *, squad_id: str, spend_limit_cents: int, memo: Optional[str] = None) -> CardHandle:
        """REFUSED — see _COMPLIANCE_CONFLICT.

        Issuing a Unit card requires linking it to a Unit account, which
        would violate SquadPay's 'never hold money' invariant. To unblock
        this, the founder must choose one of:
          (a) Approve Unit's creditAccount path (requires lending partner)
          (b) Reserve Unit for merchant-side payouts only and pick a different
              4th issuer for squad cards.
        """
        raise NotImplementedError(_COMPLIANCE_CONFLICT)

    async def fund_card(self, handle: CardHandle, cents: int) -> FundingResult:
        raise NotImplementedError(_COMPLIANCE_CONFLICT)

    async def freeze_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        raise NotImplementedError(_COMPLIANCE_CONFLICT)

    async def close_card(self, handle: CardHandle, reason: str = "squad_settled") -> None:
        raise NotImplementedError(_COMPLIANCE_CONFLICT)

    async def reveal_card_details(self, handle: CardHandle) -> CardDetails:
        raise NotImplementedError(_COMPLIANCE_CONFLICT)

    async def list_transactions(self, handle: CardHandle) -> List[CardTransaction]:
        raise NotImplementedError(_COMPLIANCE_CONFLICT)

    async def verify_webhook(self, body: bytes, headers: Dict[str, str]) -> IssuerWebhookEvent:
        raise NotImplementedError(_COMPLIANCE_CONFLICT)
