"""Payment Gateway Configuration (June 2025 — Phase 2).

Two independent provider groups:

  • Group A — CHARGE/COLLECTION
      One active provider at a time. Charges members for their contributions.
      Funds settle into Merchant Account A.

  • Group B — FUNDING/WITHDRAWAL (push-to-card)
      One active provider at a time. Real-time payout from our pre-funded
      Merchant Account B to lead/member debit card. Card details never
      stored — collected via provider's hosted iframe one-shot.

Per user direction:
  • Admin DOES NOT register new providers — the catalog below is the only
    set of providers SquadPay supports. To add a 5th provider, write an
    adapter and add a row here (code release).
  • Admin DOES configure each provider's API keys + variables.
  • Only ONE provider in each group is "active" at a time.

This module owns:
  • Static catalog (provider_slug → field schema, fee_label, etc.)
  • db.gateway_config — per-provider stored config (encrypted secrets)
  • Admin endpoints to CRUD config + flip active provider
  • Helper: get_active_gateway_config(group) → returns the live config
"""
from typing import Dict, List, Optional, Literal
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

# Reuse encryption helpers from existing integrations module.
from integrations import encrypt_secret, decrypt_secret, mask_secret  # noqa: E402

# ---------------------------------------------------------------------------
# Static catalog
# ---------------------------------------------------------------------------
# Each provider declares:
#   slug, display_name, group, fields (each: key, label, kind, required, help_text)
#   default_fee_label (reminder string surfaced in admin to update Platform Fees)
# `kind` controls how the admin form renders the field:
#   "secret"  → masked input, encrypted at rest, only "•••• 1234" shown back
#   "public"  → plain text (publishable keys, merchant ids — visible in clear)
#   "select"  → dropdown (uses `options`)

GATEWAY_PROVIDERS: List[Dict] = [
    # ─────────── Group A — CHARGE/COLLECTION ───────────
    {
        "slug": "stripe",
        "display_name": "Stripe",
        "group": "charge",
        "icon_hint": "stripe",
        "default_fee_label": "2.9% + $0.30 per transaction",
        "regions": ["US", "CA", "UK", "EU", "AU"],
        "fields": [
            {"key": "publishable_key", "label": "Publishable key",  "kind": "public", "required": True,
             "help_text": "pk_test_… or pk_live_… — public client key."},
            {"key": "secret_key",      "label": "Secret key",       "kind": "secret", "required": True,
             "help_text": "sk_test_… or sk_live_… — keep this private."},
            {"key": "webhook_secret",  "label": "Webhook secret",   "kind": "secret", "required": True,
             "help_text": "whsec_… — used to verify incoming webhook signatures."},
            {"key": "environment",     "label": "Environment",      "kind": "select", "required": True,
             "options": ["test", "live"]},
        ],
        "status": "production",   # stripe is live for SquadPay
    },
    {
        "slug": "square",
        "display_name": "Square",
        "group": "charge",
        "icon_hint": "square",
        "default_fee_label": "2.6% + $0.10 per transaction",
        "regions": ["US", "CA", "UK", "JP", "AU"],
        "fields": [
            {"key": "application_id",  "label": "Application ID",   "kind": "public", "required": True,
             "help_text": "Square Application ID from the developer dashboard."},
            {"key": "access_token",    "label": "Access token",     "kind": "secret", "required": True,
             "help_text": "OAuth access token or sandbox token."},
            {"key": "location_id",     "label": "Location ID",      "kind": "public", "required": True,
             "help_text": "Square Location to deposit funds to."},
            {"key": "webhook_signature_key", "label": "Webhook signature key", "kind": "secret", "required": True,
             "help_text": "From Square dashboard → Webhooks → Add signature key."},
            {"key": "environment",     "label": "Environment",      "kind": "select", "required": True,
             "options": ["sandbox", "production"]},
        ],
        "status": "scaffold",
    },
    {
        "slug": "adyen",
        "display_name": "Adyen",
        "group": "charge",
        "icon_hint": "adyen",
        "default_fee_label": "2.5% (negotiable, varies by region/card)",
        "regions": ["US", "EU", "UK", "AU", "global"],
        "fields": [
            {"key": "merchant_account", "label": "Merchant account",  "kind": "public", "required": True,
             "help_text": "Adyen merchant account name."},
            {"key": "api_key",          "label": "API key",           "kind": "secret", "required": True},
            {"key": "client_key",       "label": "Client key",        "kind": "public", "required": True,
             "help_text": "Client-side key used by Drop-in / Components."},
            {"key": "hmac_key",         "label": "HMAC key",          "kind": "secret", "required": True,
             "help_text": "Webhook signature verification key."},
            {"key": "environment",      "label": "Environment",       "kind": "select", "required": True,
             "options": ["test", "live"]},
        ],
        "status": "scaffold",
    },
    {
        "slug": "flutterwave",
        "display_name": "Flutterwave",
        "group": "charge",
        "icon_hint": "flutterwave",
        "default_fee_label": "1.4% local / 3.8% international",
        "regions": ["NG", "KE", "GH", "ZA", "Africa"],
        "fields": [
            {"key": "public_key",      "label": "Public key",        "kind": "public", "required": True,
             "help_text": "FLWPUBK_… visible on the client."},
            {"key": "secret_key",      "label": "Secret key",        "kind": "secret", "required": True,
             "help_text": "FLWSECK_… — server-side only."},
            {"key": "encryption_key",  "label": "Encryption key",    "kind": "secret", "required": True,
             "help_text": "FLWSECK_…_ENCK — used for direct charge requests."},
            {"key": "webhook_secret_hash", "label": "Webhook secret hash", "kind": "secret", "required": True,
             "help_text": "Set via Flutterwave dashboard → Settings → Webhooks."},
            {"key": "environment",     "label": "Environment",       "kind": "select", "required": True,
             "options": ["test", "live"]},
        ],
        "status": "scaffold",
    },

    # ─────────── Group B — FUNDING / WITHDRAWAL (push-to-card) ───────────
    {
        "slug": "astra",
        "display_name": "Astra",
        "group": "payout",
        "icon_hint": "astra",
        "default_fee_label": "1.0–1.5% per push-to-card payout (Visa Direct partner)",
        "regions": ["US"],
        "fields": [
            {"key": "api_key",         "label": "API key",           "kind": "secret", "required": True,
             "help_text": "Astra API key from app.astra.finance/developers."},
            {"key": "client_secret",   "label": "Client secret",     "kind": "secret", "required": True},
            {"key": "webhook_secret",  "label": "Webhook secret",    "kind": "secret", "required": True},
            {"key": "environment",     "label": "Environment",       "kind": "select", "required": True,
             "options": ["sandbox", "production"]},
        ],
        "status": "scaffold",
    },
    {
        "slug": "branch",
        "display_name": "Branch",
        "group": "payout",
        "icon_hint": "branch",
        "default_fee_label": "Per-payout pricing (Visa Direct / Mastercard Send)",
        "regions": ["US"],
        "fields": [
            {"key": "api_key",        "label": "API key",            "kind": "secret", "required": True},
            {"key": "organization_id","label": "Organization ID",    "kind": "public", "required": True},
            {"key": "webhook_secret", "label": "Webhook secret",     "kind": "secret", "required": True},
            {"key": "environment",    "label": "Environment",        "kind": "select", "required": True,
             "options": ["sandbox", "production"]},
        ],
        "status": "scaffold",
    },
    {
        "slug": "wise",
        "display_name": "Wise (formerly TransferWise)",
        "group": "payout",
        "icon_hint": "wise",
        "default_fee_label": "Mid-market FX + small per-transfer fee",
        "regions": ["global"],
        "fields": [
            {"key": "api_token",      "label": "API token",          "kind": "secret", "required": True},
            {"key": "profile_id",     "label": "Profile ID",         "kind": "public", "required": True},
            {"key": "webhook_secret", "label": "Webhook secret",     "kind": "secret", "required": True},
            {"key": "environment",    "label": "Environment",        "kind": "select", "required": True,
             "options": ["sandbox", "live"]},
        ],
        "status": "scaffold",
    },
]

CHARGE_PROVIDERS = [p for p in GATEWAY_PROVIDERS if p["group"] == "charge"]
PAYOUT_PROVIDERS = [p for p in GATEWAY_PROVIDERS if p["group"] == "payout"]
PROVIDER_BY_SLUG = {p["slug"]: p for p in GATEWAY_PROVIDERS}


# ---------------------------------------------------------------------------
# Cache: which provider is active per group
# ---------------------------------------------------------------------------
_ACTIVE_BY_GROUP: Dict[str, Optional[str]] = {"charge": None, "payout": None}


async def load_active_gateway_cache(db) -> None:
    global _ACTIVE_BY_GROUP
    docs = await db.gateway_config.find(
        {"is_active": True},
        {"_id": 0, "group": 1, "provider_slug": 1},
    ).to_list(length=None)
    out = {"charge": None, "payout": None}
    for d in docs:
        out[d["group"]] = d["provider_slug"]
    _ACTIVE_BY_GROUP = out


async def seed_default_active_gateways(db) -> None:
    """Idempotent — pin Stripe as the default active charge provider so existing
    code keeps working. Payout group starts INACTIVE; admin must configure
    Astra (or similar) before any payout flow becomes live."""
    now = datetime.now(timezone.utc).isoformat()

    # Create a config row for Stripe (charge) if none exists.
    stripe_cfg = await db.gateway_config.find_one(
        {"group": "charge", "provider_slug": "stripe"}, {"_id": 0},
    )
    if not stripe_cfg:
        await db.gateway_config.insert_one({
            "id": "gc_stripe_charge",
            "group": "charge",
            "provider_slug": "stripe",
            "credentials_enc": {},  # admin will fill keys via UI (or via legacy /admin/integrations endpoint)
            "settings": {
                "fee_label_override": None,  # null → use catalog default
                "currency": "USD",
            },
            "is_active": True,  # Stripe is THE charge gateway today
            "created_at": now,
            "updated_at": now,
        })

    await load_active_gateway_cache(db)


def get_active_provider(group: Literal["charge", "payout"]) -> Optional[str]:
    """Returns the slug of the active provider in the given group, or None."""
    return _ACTIVE_BY_GROUP.get(group)


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class GatewayCredentialsUpdate(BaseModel):
    # Free-form bag — each provider has its own field set per catalog.
    # Keys present in `credentials` map to GATEWAY_PROVIDERS[slug].fields[].key.
    credentials: Dict[str, str] = Field(default_factory=dict)
    # Public (non-secret) settings such as currency, fee_label_override.
    settings: Optional[Dict[str, Optional[str]]] = None


class ActivateProviderIn(BaseModel):
    provider_slug: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_config(cfg: Dict) -> Dict:
    """Mask all encrypted credential values for safe transport to UI."""
    slug = cfg.get("provider_slug")
    catalog = PROVIDER_BY_SLUG.get(slug, {})
    creds_out: Dict[str, Dict] = {}
    creds_in = cfg.get("credentials_enc") or {}
    for field in catalog.get("fields", []):
        key = field["key"]
        kind = field["kind"]
        if kind == "secret":
            enc = creds_in.get(key)
            creds_out[key] = {
                "kind": "secret",
                "set": bool(enc),
                "masked": mask_secret(decrypt_secret(enc)) if enc else None,
            }
        else:
            creds_out[key] = {
                "kind": kind,
                "value": creds_in.get(key),  # plain
            }
    return {
        "id": cfg.get("id"),
        "group": cfg.get("group"),
        "provider_slug": slug,
        "is_active": bool(cfg.get("is_active")),
        "settings": cfg.get("settings") or {},
        "credentials": creds_out,
        "updated_at": cfg.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def attach_gateway_routes(router: APIRouter, db, get_current_admin):
    from fastapi import Depends as _D
    from admin_modules import require_module

    _integrations_gate = require_module("integrations")  # same module gate as other integrations

    @router.get("/admin/gateways/catalog")
    async def gateways_catalog(_=_D(get_current_admin), __=_D(_integrations_gate)):
        """Static catalog — provider list + field schemas. Frontend renders
        the admin form from this."""
        return {
            "charge_providers": CHARGE_PROVIDERS,
            "payout_providers": PAYOUT_PROVIDERS,
            "active": dict(_ACTIVE_BY_GROUP),
        }

    @router.get("/admin/gateways")
    async def gateways_state(_=_D(get_current_admin), __=_D(_integrations_gate)):
        """All stored configs (with masked secrets)."""
        cursor = db.gateway_config.find({}, {"_id": 0})
        docs = await cursor.to_list(length=200)
        return {
            "items": [_serialize_config(d) for d in docs],
            "active": dict(_ACTIVE_BY_GROUP),
        }

    @router.put("/admin/gateways/{group}/{slug}")
    async def update_gateway_credentials(
        group: str,
        slug: str,
        body: GatewayCredentialsUpdate,
        request: Request,
        admin=_D(get_current_admin),
        _check=_D(_integrations_gate),
    ):
        if group not in ("charge", "payout"):
            raise HTTPException(400, "group must be charge or payout")
        catalog = PROVIDER_BY_SLUG.get(slug)
        if not catalog or catalog["group"] != group:
            raise HTTPException(404, f"Unknown provider '{slug}' in group '{group}'")

        # Validate provided credential keys against catalog
        allowed = {f["key"]: f for f in catalog["fields"]}
        bad = [k for k in body.credentials.keys() if k not in allowed]
        if bad:
            raise HTTPException(400, f"Unknown field(s): {','.join(bad)}")

        existing = await db.gateway_config.find_one(
            {"group": group, "provider_slug": slug}, {"_id": 0},
        ) or {
            "id": f"gc_{slug}_{group}",
            "group": group,
            "provider_slug": slug,
            "credentials_enc": {},
            "settings": {},
            "is_active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        creds = dict(existing.get("credentials_enc") or {})
        for k, v in body.credentials.items():
            if v is None or v == "":
                # Empty string → clear this field
                creds.pop(k, None)
                continue
            field_def = allowed[k]
            if field_def["kind"] == "secret":
                creds[k] = encrypt_secret(v.strip())
            elif field_def["kind"] == "select":
                if field_def.get("options") and v not in field_def["options"]:
                    raise HTTPException(400, f"Invalid value for {k}: {v}")
                creds[k] = v.strip()
            else:
                creds[k] = v.strip()

        settings = dict(existing.get("settings") or {})
        if body.settings:
            for k, v in body.settings.items():
                settings[k] = v

        update = {
            "credentials_enc": creds,
            "settings": settings,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        await db.gateway_config.update_one(
            {"id": existing["id"]},
            {"$set": update, "$setOnInsert": {
                "id": existing["id"],
                "group": group,
                "provider_slug": slug,
                "is_active": bool(existing.get("is_active")),
                "created_at": existing.get("created_at"),
            }},
            upsert=True,
        )

        try:
            from admin import write_audit
            await write_audit(
                db, admin_id=admin["id"], admin_email=admin["email"],
                action="admin.gateway_credentials_updated",
                target_type="gateway", target_id=existing["id"],
                payload={"group": group, "slug": slug, "fields": list(body.credentials.keys())},
                request=request,
            )
        except Exception:
            pass

        cfg = await db.gateway_config.find_one({"id": existing["id"]}, {"_id": 0})
        return _serialize_config(cfg)

    @router.post("/admin/gateways/{group}/activate")
    async def activate_provider(
        group: str,
        body: ActivateProviderIn,
        request: Request,
        admin=_D(get_current_admin),
        _check=_D(_integrations_gate),
    ):
        if group not in ("charge", "payout"):
            raise HTTPException(400, "group must be charge or payout")
        catalog = PROVIDER_BY_SLUG.get(body.provider_slug)
        if not catalog or catalog["group"] != group:
            raise HTTPException(400, f"Provider '{body.provider_slug}' not in group '{group}'")

        # Guardrail: refuse to activate a provider whose adapter is not yet
        # implemented in code. Admin can SAVE credentials for it (preparing for
        # future release), but flipping the active switch on a scaffold would
        # break live charges silently.
        if catalog.get("status") != "production":
            raise HTTPException(
                400,
                f"{catalog['display_name']} adapter is not yet implemented in code. "
                "Credentials are saved, but activation will only be available once "
                "the adapter ships in a future release.",
            )

        # Ensure provider's required fields are filled before activation
        cfg = await db.gateway_config.find_one(
            {"group": group, "provider_slug": body.provider_slug}, {"_id": 0},
        )
        missing = []
        creds = (cfg or {}).get("credentials_enc") or {}
        for f in catalog["fields"]:
            if f.get("required") and not creds.get(f["key"]):
                missing.append(f["label"])
        if missing:
            raise HTTPException(
                400,
                f"Cannot activate '{body.provider_slug}' — missing required field(s): {', '.join(missing)}.",
            )

        now = datetime.now(timezone.utc).isoformat()

        # Atomically deactivate everyone else in the group, activate the chosen one.
        await db.gateway_config.update_many(
            {"group": group, "provider_slug": {"$ne": body.provider_slug}},
            {"$set": {"is_active": False, "updated_at": now}},
        )
        await db.gateway_config.update_one(
            {"group": group, "provider_slug": body.provider_slug},
            {"$set": {"is_active": True, "updated_at": now}},
            upsert=False,
        )

        await load_active_gateway_cache(db)

        try:
            from admin import write_audit
            await write_audit(
                db, admin_id=admin["id"], admin_email=admin["email"],
                action="admin.gateway_activated",
                target_type="gateway", target_id=f"gc_{body.provider_slug}_{group}",
                payload={"group": group, "slug": body.provider_slug},
                request=request,
            )
        except Exception:
            pass

        return {"ok": True, "group": group, "active": body.provider_slug}
