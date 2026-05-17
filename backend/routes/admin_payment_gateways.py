"""Admin Payment Gateways API — manage virtual card issuer providers.

Single-page admin surface for the issuer adapter system. Lets the admin:
  • See all integrated providers (Stripe / Lithic / Highnote / Unit)
  • View live health for each (auth-validating ping)
  • Enable/disable a provider (sets `enabled` flag in config)
  • Activate exactly ONE provider as the live issuer (mutex)
  • Save provider-specific credentials (encrypted via existing integrations module)

Design rule: only ONE issuer is active at any time. Activating a new one
deactivates the previous active. Provider-specific concerns (KYC, funding,
tokenization) all flow from whichever is currently active — callers don't
need to know which provider is live.
"""
from __future__ import annotations
import datetime as dt
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase

from integrations import encrypt_secret, decrypt_secret, mask_secret
from adapters.issuer_registry import (
    get_active_slug,
    get_issuer_by_slug,
    list_integrated_adapters,
    list_integrated_slugs,
    set_active_slug,
)

logger = logging.getLogger(__name__)


# Map adapter slug -> the .env key its adapter expects for the api key.
# Keeping this here lets us round-trip credentials through the admin UI
# without each adapter having to expose its own config-set route.
_ENV_KEYS: Dict[str, List[str]] = {
    "stripe":   ["STRIPE_API_KEY"],
    "lithic":   ["LITHIC_API_KEY", "LITHIC_ENV", "LITHIC_WEBHOOK_SECRET"],
    "highnote": ["HIGHNOTE_API_KEY", "HIGHNOTE_ORG_ID"],
    "unit":     ["UNIT_API_TOKEN"],
}


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _is_configured(slug: str) -> bool:
    """A provider is 'configured' if its required env keys are non-empty."""
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=True)
    required = _ENV_KEYS.get(slug, [])
    if not required:
        return False
    return bool(os.environ.get(required[0]))


# ---------- request bodies ----------
class ActivateBody(BaseModel):
    slug: str


class ToggleBody(BaseModel):
    slug: str
    enabled: bool


class ConfigureBody(BaseModel):
    slug: str
    credentials: Dict[str, str]


def attach_payment_gateways_routes(api_router: APIRouter, db, admin_dep):
    """Attach payment gateway management routes.

    `admin_dep` is the dependency from admin_routes.get_current_admin_factory_sync(db).
    Mirrors the pattern used by admin_logos / admin_module_routes etc.
    """

    @api_router.get("/admin/payment-gateways")
    async def list_gateways(admin=Depends(admin_dep)):
        rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {}
        pg = dict(rec.get("payment_gateways") or {})
        pg.setdefault("active_issuer", "stripe")
        pg.setdefault("issuers", {})
        active = pg.get("active_issuer")
        issuers_cfg = pg.get("issuers") or {}
        out: List[Dict[str, Any]] = []
        for adapter in list_integrated_adapters():
            cfg = dict(issuers_cfg.get(adapter.slug) or {})
            configured = _is_configured(adapter.slug)
            try:
                health = await adapter.health_check()
            except Exception as e:
                health = {"ok": False, "message": str(e)[:200], "latency_ms": 0, "env": "error"}
            out.append({
                "slug": adapter.slug,
                "display_name": adapter.display_name,
                "active": adapter.slug == active,
                "enabled": bool(cfg.get("enabled", configured)),
                "configured": configured,
                "capabilities": {
                    "apple_wallet": adapter.supports_apple_wallet,
                    "google_wallet": adapter.supports_google_wallet,
                    "single_use": adapter.supports_single_use,
                    "multi_use": adapter.supports_multi_use,
                },
                "health": health,
                "env_keys": _ENV_KEYS.get(adapter.slug, []),
                "updated_by": cfg.get("updated_by"),
                "updated_at": cfg.get("updated_at"),
            })
        return {
            "active_issuer": active,
            "active_changed_by": pg.get("active_issuer_changed_by"),
            "active_changed_at": pg.get("active_issuer_changed_at"),
            "providers": out,
        }

    @api_router.post("/admin/payment-gateways/activate")
    async def activate(body: ActivateBody, admin=Depends(admin_dep)):
        if body.slug not in list_integrated_slugs():
            raise HTTPException(400, f"Provider {body.slug!r} is not integrated in this build")
        if not _is_configured(body.slug):
            raise HTTPException(400, f"Provider {body.slug!r} has no credentials configured. Set credentials first.")
        adapter = await get_issuer_by_slug(body.slug)
        health = await adapter.health_check()
        if not health.get("ok"):
            raise HTTPException(400, f"Provider {body.slug!r} health check failed: {health.get('message')}")
        actor = (admin.get("username") if isinstance(admin, dict) else getattr(admin, "username", "admin")) or "admin"
        pg = await set_active_slug(db, body.slug, changed_by=actor)
        logger.info(f"[admin] payment-gateway activated: {body.slug} by {actor}")
        return {"ok": True, "active_issuer": pg["active_issuer"]}

    @api_router.post("/admin/payment-gateways/toggle")
    async def toggle(body: ToggleBody, admin=Depends(admin_dep)):
        if body.slug not in list_integrated_slugs():
            raise HTTPException(400, f"Provider {body.slug!r} is not integrated")
        actor = (admin.get("username") if isinstance(admin, dict) else getattr(admin, "username", "admin")) or "admin"
        rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {"key": "integrations"}
        pg = dict(rec.get("payment_gateways") or {})
        issuers = dict(pg.get("issuers") or {})
        slot = dict(issuers.get(body.slug) or {})
        if pg.get("active_issuer") == body.slug and not body.enabled:
            raise HTTPException(400, f"Cannot disable {body.slug!r} — it is the active issuer. Activate another provider first.")
        slot["enabled"] = bool(body.enabled)
        slot["updated_by"] = actor
        slot["updated_at"] = _now_iso()
        issuers[body.slug] = slot
        pg["issuers"] = issuers
        await db.app_settings.update_one(
            {"key": "integrations"},
            {"$set": {"payment_gateways": pg}},
            upsert=True,
        )
        return {"ok": True}

    @api_router.post("/admin/payment-gateways/configure")
    async def configure(body: ConfigureBody, admin=Depends(admin_dep)):
        if body.slug not in list_integrated_slugs():
            raise HTTPException(400, f"Provider {body.slug!r} is not integrated")
        allowed = set(_ENV_KEYS.get(body.slug, []))
        bad = [k for k in body.credentials.keys() if k not in allowed]
        if bad:
            raise HTTPException(400, f"Unknown credential keys for {body.slug!r}: {bad}")
        env_path = "/app/backend/.env"
        try:
            with open(env_path, "r") as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        existing_keys = {}
        for i, ln in enumerate(lines):
            if "=" in ln and not ln.lstrip().startswith("#"):
                k = ln.split("=", 1)[0].strip()
                existing_keys[k] = i
        for k, v in body.credentials.items():
            line = f"{k}={v}\n"
            if k in existing_keys:
                lines[existing_keys[k]] = line
            else:
                lines.append(line)
        with open(env_path, "w") as f:
            f.writelines(lines)
        actor = (admin.get("username") if isinstance(admin, dict) else getattr(admin, "username", "admin")) or "admin"
        rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {"key": "integrations"}
        pg = dict(rec.get("payment_gateways") or {})
        issuers = dict(pg.get("issuers") or {})
        slot = dict(issuers.get(body.slug) or {})
        for k, v in body.credentials.items():
            if k.endswith("_ENV"):
                slot[k] = v
            else:
                slot[f"{k}_enc"] = encrypt_secret(v)
        slot["updated_by"] = actor
        slot["updated_at"] = _now_iso()
        issuers[body.slug] = slot
        pg["issuers"] = issuers
        await db.app_settings.update_one(
            {"key": "integrations"},
            {"$set": {"payment_gateways": pg}},
            upsert=True,
        )
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env", override=True)
        adapter = await get_issuer_by_slug(body.slug)
        health = await adapter.health_check()
        return {"ok": True, "health": health}

    @api_router.get("/admin/payment-gateways/{slug}/health")
    async def health(slug: str, admin=Depends(admin_dep)):
        if slug not in list_integrated_slugs():
            raise HTTPException(404, f"Provider {slug!r} not integrated")
        adapter = await get_issuer_by_slug(slug)
        return await adapter.health_check()
