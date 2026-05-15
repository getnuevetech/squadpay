"""
Admin App-Config route — single source of truth for ALL admin-tunable
runtime settings in SquadPay.

Everything lives in one MongoDB document (`platform_config` collection,
_id = "platform_fees_config") and is mirrored into in-process caches at
startup + on every admin save, so request-path code never has to hit
MongoDB to read a setting.

Sections
────────
• core_fees           — transaction fee % and platform fee $ (formerly hard-coded in core.py)
• extra_fees          — the existing up-to-2 admin-extra fees (preserved as-is)
• wallet              — Apple/Google Wallet push-provisioning master + per-platform toggles
• limits              — min members per bill, min/max bill amount, max items per bill
• otp                 — code length, expiry seconds, max attempts per hour
• card                — spend-cap buffer %, auto-disable hours
• reminders           — cadence hours, bill expiry hours
• ocr                 — provider, model
• brand               — sms sender id, support email, default tip suggestions, currency
• ops                 — maintenance_mode boolean

Each section has a Pydantic model with sensible defaults so the existing
config doc (which only had `fees`) keeps working — missing sections fall
back to defaults.
"""
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

CONFIG_ID = "platform_fees_config"


# ───────────────────── Section schemas ─────────────────────

class CoreFees(BaseModel):
    transaction_fee_pct: float = Field(3.0, ge=0, le=20, description="Percent applied to (Share + Platform + Extras + Insurance) per member — always %, never fixed")
    # June 2025 — Platform fee migrated from a single flat to {type, value}:
    #   type=fixed   → each member pays full $value (NOT divided by N)
    #   type=percent → each member pays value% of (Share or Total/N)
    platform_fee_type: Literal["fixed", "percent"] = Field("fixed", description="Whether platform_fee_value is dollars or percent")
    platform_fee_value: float = Field(0.50, ge=0, le=100, description="Amount or percent depending on platform_fee_type")
    # Insurance — always percent, never fixed. Layered between Extras and Tx Fee.
    insurance_pct: float = Field(1.0, ge=0, le=20, description="Insurance percent applied to (Share + Platform + Extras)")
    # ── Legacy field kept for backwards-compat with older callers/UI ──
    platform_fee_flat: float = Field(0.50, ge=0, le=100, description="DEPRECATED: use platform_fee_type+value. Auto-mirrored from platform_fee_value when type=fixed.")
    # Admin-editable display labels — surfaced everywhere we render these fees
    # (Bill Breakdown card, Income & Fees ledger, receipts, etc.).
    transaction_fee_label: str = Field("Transaction Fee", min_length=1, max_length=40)
    platform_fee_label: str = Field("Platform Fee", min_length=1, max_length=40)
    insurance_label: str = Field("Insurance", min_length=1, max_length=40)


class ExtraFee(BaseModel):
    id: str
    name: str = Field(..., min_length=1, max_length=40)
    type: Literal["percent", "flat"]
    value: float = Field(..., ge=0)
    enabled: bool = False


class Wallet(BaseModel):
    enabled: bool = False
    apple_enabled: bool = True
    google_enabled: bool = True


class Limits(BaseModel):
    min_members_per_bill: int = Field(2, ge=1, le=20)
    min_bill_amount: float = Field(0.0, ge=0)
    max_bill_amount: float = Field(50000.0, ge=0)
    max_items_per_bill: int = Field(200, ge=1, le=1000)


class Otp(BaseModel):
    code_length: int = Field(6, ge=4, le=8)
    expiry_seconds: int = Field(300, ge=60, le=3600)
    max_attempts_per_hour: int = Field(5, ge=1, le=50)


class CardSettings(BaseModel):
    spend_cap_buffer_pct: float = Field(0.0, ge=0, le=25, description="Adds N% headroom to spend cap to absorb POS adjustments")
    auto_disable_hours: int = Field(24, ge=1, le=168)


class Reminders(BaseModel):
    cadence_hours: int = Field(24, ge=1, le=168)
    bill_expiry_hours: int = Field(168, ge=1, le=720)  # 7 days default


class OcrSettings(BaseModel):
    provider: Literal["openai", "anthropic", "gemini"] = "openai"
    model: str = "gpt-4o"


class Brand(BaseModel):
    sms_sender_id: str = Field("SquadPay", max_length=11)
    support_email: str = "support@squadpay.us"
    default_tip_suggestions: List[float] = [15.0, 18.0, 20.0]
    currency: Literal["USD"] = "USD"  # MVP: USD only


class Ops(BaseModel):
    maintenance_mode: bool = False
    maintenance_message: str = "SquadPay is briefly down for maintenance — we'll be right back."


# ───────────────────── Full payload ─────────────────────

class AppConfigPayload(BaseModel):
    core_fees: CoreFees = CoreFees()
    extra_fees: List[ExtraFee] = []
    wallet: Wallet = Wallet()
    limits: Limits = Limits()
    otp: Otp = Otp()
    card: CardSettings = CardSettings()
    reminders: Reminders = Reminders()
    ocr: OcrSettings = OcrSettings()
    brand: Brand = Brand()
    ops: Ops = Ops()


# ───────────────────── In-process caches ─────────────────────

# These are read by request-path code (auth, contribute, OCR, etc.) so
# we don't hit MongoDB on every request.

_APP_CONFIG_CACHE: dict = {}


def get_app_config_cache() -> dict:
    return dict(_APP_CONFIG_CACHE)


def set_app_config_cache(cfg: dict) -> None:
    global _APP_CONFIG_CACHE
    _APP_CONFIG_CACHE = dict(cfg or {})


def is_maintenance_mode() -> bool:
    """O(1) check used by request-path guards (e.g. create-bill endpoint).
    Reads the in-process cache populated at startup + every admin save."""
    ops = (_APP_CONFIG_CACHE or {}).get("ops") or {}
    return bool(ops.get("maintenance_mode"))


def maintenance_message() -> str:
    ops = (_APP_CONFIG_CACHE or {}).get("ops") or {}
    return str(
        ops.get("maintenance_message")
        or "SquadPay is briefly down for maintenance — we'll be right back."
    )


# ───────────────────── Load + persist ─────────────────────

DEFAULT_EXTRA_FEES = [
    {"id": "extra_1", "name": "Extra Fee 1", "type": "flat", "value": 0.0, "enabled": False},
    {"id": "extra_2", "name": "Extra Fee 2", "type": "flat", "value": 0.0, "enabled": False},
]


async def load_app_config(db) -> dict:
    """Read the single config doc and return a fully-populated AppConfigPayload as dict.
    Missing sections fall back to defaults so legacy docs (with only `fees`)
    keep working."""
    doc = await db.platform_config.find_one({"_id": CONFIG_ID}) or {}

    # Legacy `fees` array → `extra_fees` (backwards-compat).
    extras_raw = doc.get("extra_fees") or doc.get("fees") or []
    by_id = {e.get("id"): e for e in extras_raw if isinstance(e, dict) and e.get("id")}
    extras: List[dict] = []
    for default in DEFAULT_EXTRA_FEES:
        merged = {**default, **(by_id.get(default["id"]) or {})}
        extras.append({
            "id": merged["id"],
            "name": str(merged.get("name") or default["name"]),
            "type": "percent" if merged.get("type") == "percent" else "flat",
            "value": float(merged.get("value") or 0),
            "enabled": bool(merged.get("enabled")),
        })

    merged_payload = AppConfigPayload(
        core_fees=CoreFees(**(doc.get("core_fees") or {})),
        extra_fees=[ExtraFee(**e) for e in extras],
        wallet=Wallet(**(doc.get("wallet") or {})),
        limits=Limits(**(doc.get("limits") or {})),
        otp=Otp(**(doc.get("otp") or {})),
        card=CardSettings(**(doc.get("card") or {})),
        reminders=Reminders(**(doc.get("reminders") or {})),
        ocr=OcrSettings(**(doc.get("ocr") or {})),
        brand=Brand(**(doc.get("brand") or {})),
        ops=Ops(**(doc.get("ops") or {})),
    )
    return merged_payload.dict()


def attach_app_config_routes(api_router: APIRouter, db, require_admin):
    """Register /api/admin/app-config GET + PUT and return a refresh helper."""
    # Lazy imports to avoid pulling the heavy core graph at module-load time.
    from core import set_extra_fees_cache, set_core_fees_cache  # type: ignore

    async def _refresh_caches():
        cfg = await load_app_config(db)
        set_app_config_cache(cfg)
        set_extra_fees_cache(cfg["extra_fees"])
        # June 2025 — pass new fields (platform fee type/value + insurance).
        # Auto-derive legacy `platform_fee_flat` from `platform_fee_value`
        # when the type is fixed so older callers keep working.
        core_fees = cfg["core_fees"]
        p_type = core_fees.get("platform_fee_type", "fixed")
        p_value = core_fees.get(
            "platform_fee_value",
            core_fees.get("platform_fee_flat", 0.50),
        )
        set_core_fees_cache(
            core_fees["transaction_fee_pct"] / 100.0,
            platform_fee_type=p_type,
            platform_fee_value=p_value,
            insurance_rate=core_fees.get("insurance_pct", 1.0) / 100.0,
        )

    @api_router.get("/admin/app-config")
    async def get_app_config(_admin=Depends(require_admin)):
        cfg = await load_app_config(db)
        # Always refresh the cache when admin reads (cheap, keeps things in sync if DB was edited out-of-band).
        set_app_config_cache(cfg)
        return cfg

    @api_router.put("/admin/app-config")
    async def update_app_config(payload: AppConfigPayload, _admin=Depends(require_admin)):
        # Enforce: extra_fees must use canonical slot IDs (no proliferation of fees beyond the 2 documented slots).
        allowed_ids = {e["id"] for e in DEFAULT_EXTRA_FEES}
        seen = set()
        cleaned_extras: List[dict] = []
        for ef in payload.extra_fees:
            if ef.id not in allowed_ids:
                raise HTTPException(400, f"unknown_extra_slot:{ef.id}")
            if ef.id in seen:
                raise HTTPException(400, f"duplicate_extra_slot:{ef.id}")
            seen.add(ef.id)
            cleaned_extras.append(ef.dict())
        # Backfill missing slots so the admin UI always sees both.
        by_id = {c["id"]: c for c in cleaned_extras}
        for d in DEFAULT_EXTRA_FEES:
            if d["id"] not in by_id:
                cleaned_extras.append(d)

        doc = {
            "core_fees": payload.core_fees.dict(),
            "extra_fees": cleaned_extras,
            "wallet": payload.wallet.dict(),
            "limits": payload.limits.dict(),
            "otp": payload.otp.dict(),
            "card": payload.card.dict(),
            "reminders": payload.reminders.dict(),
            "ocr": payload.ocr.dict(),
            "brand": payload.brand.dict(),
            "ops": payload.ops.dict(),
            # Legacy `fees` mirror — keep so the older /admin/platform-fees
            # endpoint stays consistent with the new bigger schema.
            "fees": cleaned_extras,
        }
        await db.platform_config.update_one(
            {"_id": CONFIG_ID},
            {"$set": doc},
            upsert=True,
        )
        await _refresh_caches()
        return await load_app_config(db)

    return _refresh_caches
