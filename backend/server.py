"""SquadPay (formerly SquadPay) — FastAPI entrypoint.

Batch B refactor (post-Phase F2.2): the bulk of route handlers and helpers
have been moved out of this file. This module is now a thin assembler:

  - Loads env / Mongo client / FastAPI app
  - Wires up the route packages under /app/backend/routes
  - Registers the admin router (admin_routes.build_admin_router)
  - Runs startup/shutdown hooks (admin seed, credit migration, reminder loop)

Routes live in:
  routes/auth_routes.py        — /auth/register, /auth/send-otp, /auth/verify-otp, /users/{id}
  routes/groups_routes.py      — /groups, items, /assign, /join, PATCH /groups/{id}
  routes/contribute_routes.py  — /groups/{id}/contribute, /contribute/status/{sid}
  routes/pay_routes.py         — /groups/{id}/pay, /repay, /users/{id}/groups
  routes/misc_routes.py        — /receipt/scan, /, /app-features, /checkout/native-bridge
  routes/* (referrals_credits) — /users/{id}/referrals, /referrals/lookup/{code}, /users/{id}/credits
  payments.py                  — Stripe lead-pay routes (already modularized)
  issuing_reveal.py            — Stripe Issuing PAN reveal routes
  admin_routes.py              — Admin dashboard router
"""
from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---------- DB ----------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# ---------- App ----------
app = FastAPI()

# ---------- Rate limiting (slowapi) ----------
# In-memory limiter keyed off the client IP. For multi-replica deployments swap
# the storage_uri to redis://... — the rest of the code stays identical.
from slowapi import Limiter, _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from slowapi.util import get_remote_address  # noqa: E402
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

api_router = APIRouter(prefix="/api")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


# ---------- Wire user-facing route packages ----------
from routes.auth_routes import attach_auth_routes
from routes.groups_routes import attach_groups_routes
from routes.contribute_routes import attach_contribute_routes
from routes.pay_routes import attach_pay_routes
from routes.misc_routes import attach_referrals_credits_routes, attach_misc_routes
from routes.kyc_routes import attach_kyc_routes

attach_auth_routes(api_router, db)
attach_groups_routes(api_router, db)
attach_contribute_routes(api_router, db)
attach_pay_routes(api_router, db)
attach_referrals_credits_routes(api_router, db)
attach_misc_routes(api_router, db)
attach_kyc_routes(api_router, db)

# ---------- Admin-managed legal pages (Support / Privacy / Terms) ----------
try:
    from routes.legal_routes import attach_legal_routes
    from admin_routes import get_current_admin_factory_sync
    attach_legal_routes(api_router, db, get_current_admin_factory_sync(db))
except Exception as _e:
    print("[startup] legal routes attach failed:", _e)

# ---------- Refund / overpayment (Phase H7) ----------
try:
    from routes.refund_routes import make_refund_router
    api_router.include_router(make_refund_router(db))
except Exception as _e:
    print("[startup] refund routes attach failed:", _e)


# ---------- Account deletion (App Store Guideline 5.1.1(v)) ----------
# IMPORTANT: must be attached BEFORE build_admin_router() so that
# /api/admin/users/deleted is registered before /api/admin/users/{user_id}
# (otherwise FastAPI's router treats "deleted" as a user_id and returns 404).
try:
    from routes.account_deletion_routes import attach_account_deletion_routes
    from admin_routes import get_current_admin_factory_sync as _adm_factory_early
    attach_account_deletion_routes(api_router, db, _adm_factory_early(db))
except Exception as _e:
    print("[startup] account deletion routes attach failed:", _e)


# ---------- Module Registry + RBAC (Batch June 2025) ----------
# Same pre-include placement reasoning — /admin/access/* and /admin/me/modules
# need to register before the legacy admin_router so its catch-all sub-paths
# don't shadow them.
try:
    from admin_modules import attach_module_routes as _attach_module_routes
    _attach_module_routes(api_router, db, _adm_factory_early(db))
except Exception as _e:
    print("[startup] module registry routes attach failed:", _e)


# ---------- Capability Registry (June 2025 — payment/feature on-off switches) ----------
try:
    from app_capabilities import attach_capability_routes as _attach_capability_routes
    _attach_capability_routes(api_router, db, _adm_factory_early(db))
except Exception as _e:
    print("[startup] capability routes attach failed:", _e)


# ---------- Payment Gateway Configuration (June 2025 Phase 2) ----------
try:
    from gateway_config import attach_gateway_routes as _attach_gateway_routes
    _attach_gateway_routes(api_router, db, _adm_factory_early(db))
except Exception as _e:
    print("[startup] gateway routes attach failed:", _e)


# ---------- Admin dashboard ----------
from admin_routes import build_admin_router  # noqa: E402
api_router.include_router(build_admin_router(db))

# ---------- Admin: configurable platform fees ----------
try:
    from routes.admin_platform_fees import attach_platform_fees_routes
    from admin_routes import get_current_admin_factory_sync as _adm_factory
    _refresh_platform_fees = attach_platform_fees_routes(api_router, db, _adm_factory(db))

    @app.on_event("startup")
    async def _load_platform_fees_cache():
        try:
            await _refresh_platform_fees()
        except Exception as _e:
            print("[startup] platform fees initial load failed:", _e)
except Exception as _e:
    print("[startup] admin platform fees attach failed:", _e)


# ---------- Admin: full app-config (core fees, wallet, limits, otp, etc.) ----------
# Single source of truth for ALL admin-tunable runtime settings. Reads
# /api/admin/app-config, writes /api/admin/app-config. Mirrors changes
# into in-process caches via the returned refresh helper.
try:
    from routes.admin_app_config import attach_app_config_routes
    _refresh_app_config = attach_app_config_routes(api_router, db, _adm_factory(db))

    @app.on_event("startup")
    async def _load_app_config_cache():
        try:
            await _refresh_app_config()
            print("[startup] app-config cache loaded")
        except Exception as _e:
            print("[startup] app-config initial load failed:", _e)
except Exception as _e:
    print("[startup] admin app-config attach failed:", _e)


# ---------- Admin: Income & Fees ledger (Batch B) ----------
try:
    from routes.admin_income_fees import attach_income_fees_routes
    attach_income_fees_routes(api_router, db, _adm_factory(db))
except Exception as _e:
    print("[startup] admin income-fees attach failed:", _e)


# ---------- Admin: Master Account + Master Virtual Card (Batch C) ----------
try:
    from routes.admin_master_account import attach_master_account_routes
    attach_master_account_routes(api_router, db, _adm_factory(db))
except Exception as _e:
    print("[startup] admin master-account attach failed:", _e)


# ---------- Admin: Notification Center (Batch June 2025) ----------
try:
    from routes.admin_notifications import attach_admin_notifications_routes
    attach_admin_notifications_routes(api_router, db, _adm_factory(db))
except Exception as _e:
    print("[startup] admin notifications attach failed:", _e)


# ---------- Admin: Bulk SMS broadcaster (Batch June 2025) ----------
try:
    from routes.admin_bulk_sms import attach_bulk_sms_routes
    attach_bulk_sms_routes(api_router, db, _adm_factory(db))
except Exception as _e:
    print("[startup] admin bulk-sms attach failed:", _e)


# ---------- Admin: Credit Rules engine (Batch June 2025) ----------
try:
    from routes.admin_credit_rules import attach_credit_rules_routes
    attach_credit_rules_routes(api_router, db, _adm_factory(db))
except Exception as _e:
    print("[startup] admin credit-rules attach failed:", _e)


# ---------- Contact Us + Customer Service (Batch June 2025) ----------
try:
    from routes.contact_routes import attach_contact_routes
    attach_contact_routes(api_router, db, _adm_factory(db))
except Exception as _e:
    print("[startup] contact routes attach failed:", _e)


# ---------- Admin: Full-content search (Batch June 2025) ----------
try:
    from routes.admin_search import attach_admin_search_routes
    attach_admin_search_routes(api_router, db, _adm_factory(db))
except Exception as _e:
    print("[startup] admin search attach failed:", _e)


# ---------- Account deletion (App Store Guideline 5.1.1(v)) ----------
try:
    from routes.account_deletion_routes import attach_account_deletion_routes
    attach_account_deletion_routes(api_router, db, _adm_factory(db))
except Exception as _e:
    print("[startup] account deletion routes attach failed:", _e)


# ---------- Stripe payment routes (Phase E) ----------
try:
    from payments import attach_payment_routes
    attach_payment_routes(api_router, db)
except Exception as _e:
    print("[startup] payment routes attach failed:", _e)


# ---------- Stripe Issuing PAN reveal + spend webhook (Phase F2) ----------
try:
    from issuing_reveal import attach_reveal_routes
    attach_reveal_routes(api_router, db)
except Exception as _e:
    print("[startup] reveal routes attach failed:", _e)


# ---------- Apple/Google Wallet push provisioning (scaffold) ----------
# Endpoint returns 202 with `pending_psp_approval` until PNO/PSP approvals
# land. The frontend uses it to render a graceful "Coming Soon" CTA.
try:
    from routes.wallet_routes import router as _wallet_router
    # mount at app level since wallet_routes already declares prefix="/api"
    app.include_router(_wallet_router)
except Exception as _e:
    print("[startup] wallet routes attach failed:", _e)


# ---------- Mount + middleware ----------
app.include_router(api_router)

# ---------- Admin password reset (Phase H7) — mounted directly on app ----------
try:
    from admin_password_reset import build_password_reset_router
    app.include_router(build_password_reset_router(db))
except Exception as _e:
    print("[startup] admin password reset routes attach failed:", _e)

# ---------- Admin recovery (gated by ADMIN_RECOVERY_TOKEN env) ----------
# Disabled by default: every endpoint returns 503 unless the env var is set.
# See /app/backend/scripts/README.md for the full activation flow.
try:
    from recovery_routes import build_recovery_router
    app.include_router(build_recovery_router(db))
except Exception as _e:
    print("[startup] admin recovery routes attach failed:", _e)

# CORS — When `allow_credentials=True`, the spec forbids `allow_origins=["*"]`.
# Browsers silently reject cross-origin responses with that combo (manifests as
# "Failed to fetch" client-side). We use an explicit allowlist plus a regex
# for Vercel preview deploys / Emergent preview hosts.
_default_origins = [
    "https://squadpay.us",
    "https://www.squadpay.us",
    "http://localhost:3000",
    "http://localhost:8081",
    "https://joint-pay-1.preview.emergentagent.com",
]
_extra = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
_allowed_origins = list(dict.fromkeys(_default_origins + _extra))

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"^https://([a-z0-9-]+\.)*(vercel\.app|preview\.emergentagent\.com)$",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Lifecycle ----------
@app.on_event("startup")
async def _on_startup():
    # Seed the super-admin account from ADMIN_EMAIL/ADMIN_PASSWORD env (idempotent)
    try:
        from admin import ensure_seed_admin
        await ensure_seed_admin(db)
    except Exception as e:
        print("[startup] seed admin failed:", e)
    # Phase C2 migration: flip leftover pending credits to active (idempotent)
    try:
        from core import _activate_pending_credits
        await _activate_pending_credits(db)
    except Exception as e:
        print("[startup] activate credits failed:", e)
    # Phase D: start reminder background loop
    try:
        from reminders import start_reminder_loop
        start_reminder_loop(db, interval_seconds=900)
    except Exception as e:
        print("[startup] reminder loop failed:", e)
    # Phase G1: seed reconciliation defaults (idempotent)
    try:
        from reconciliation import ensure_reconciliation_settings
        await ensure_reconciliation_settings(db)
    except Exception as e:
        print("[startup] reconciliation settings failed:", e)

    # June 2025: seed RBAC roles + warm the in-memory roles cache.
    try:
        from admin_modules import seed_system_roles
        await seed_system_roles(db)
    except Exception as e:
        print("[startup] seed roles failed:", e)

    # June 2025: seed capability registry (virtual_card on/off, lead_debit_card etc.)
    try:
        from app_capabilities import seed_capabilities
        await seed_capabilities(db)
    except Exception as e:
        print("[startup] seed capabilities failed:", e)

    # June 2025 (Phase 2): warm the active-gateway cache + pin Stripe charge
    try:
        from gateway_config import seed_default_active_gateways
        await seed_default_active_gateways(db)
    except Exception as e:
        print("[startup] seed gateways failed:", e)


@app.on_event("shutdown")
async def _on_shutdown():
    client.close()
