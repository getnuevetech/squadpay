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

# ---------- Refund / overpayment (Phase H7) ----------
try:
    from routes.refund_routes import make_refund_router
    api_router.include_router(make_refund_router(db))
except Exception as _e:
    print("[startup] refund routes attach failed:", _e)


# ---------- Admin dashboard ----------
from admin_routes import build_admin_router  # noqa: E402
api_router.include_router(build_admin_router(db))


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


# ---------- Mount + middleware ----------
app.include_router(api_router)

# ---------- Admin password reset (Phase H7) — mounted directly on app ----------
try:
    from admin_password_reset import build_password_reset_router
    app.include_router(build_password_reset_router(db))
except Exception as _e:
    print("[startup] admin password reset routes attach failed:", _e)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
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


@app.on_event("shutdown")
async def _on_shutdown():
    client.close()
