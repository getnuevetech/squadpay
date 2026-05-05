"""Admin auth, RBAC + audit logging.

Designed for long-term: separate Admin collection, JWT auth, role-based access
control, immutable audit log, encryption helper for secrets.
"""
import os
import time
import uuid
import datetime as dt
from typing import Optional, List, Literal

import jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_ctx.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _pwd_ctx.verify(password, hashed)
    except Exception:
        return False


# Symmetric key for storing third-party API secrets (Stripe/Twilio API keys etc).
# Falls back to a derived key from JWT_SECRET if SECRETS_KEY missing.
def _resolve_fernet_key() -> bytes:
    key = os.environ.get("SECRETS_KEY")
    if key:
        return key.encode() if isinstance(key, str) else key
    # Derive a 32-byte key from JWT_SECRET (urlsafe base64 of sha256)
    import hashlib, base64
    seed = (os.environ.get("JWT_SECRET") or "dev-jwt-secret").encode()
    return base64.urlsafe_b64encode(hashlib.sha256(seed).digest())


_fernet = Fernet(_resolve_fernet_key())


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet.decrypt(token.encode()).decode()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-jwt-secret-CHANGE-ME-in-prod")
JWT_ALG = "HS256"
JWT_TTL_SECONDS = int(os.environ.get("ADMIN_JWT_TTL", "28800"))  # 8 hours


def create_access_token(admin_id: str, role: str) -> str:
    payload = {
        "sub": admin_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_TTL_SECONDS,
        "type": "admin",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired — please sign in again")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid auth token")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

Role = Literal["super_admin", "manager", "support"]
ROLE_HIERARCHY = {"super_admin": 3, "manager": 2, "support": 1}


class AdminLoginIn(BaseModel):
    email: str
    password: str


class AdminCreateIn(BaseModel):
    email: str
    password: str = Field(min_length=8)
    name: str
    role: Role = "support"


class AdminOut(BaseModel):
    id: str
    email: str
    name: str
    role: Role
    is_active: bool
    last_login_at: Optional[str] = None
    created_at: str


class AdminAuthResponse(BaseModel):
    token: str
    admin: AdminOut


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

security = HTTPBearer(auto_error=False)


async def get_current_admin_factory(db):
    """Returns a FastAPI dependency that yields the current admin doc.

    Wraps in factory because db is created in the main module after env load.
    """

    async def _dep(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    ):
        token: Optional[str] = None
        if credentials and credentials.scheme.lower() == "bearer":
            token = credentials.credentials
        if not token:
            # also accept ?token= param for convenience in browser-only views
            token = request.query_params.get("token")
        if not token:
            raise HTTPException(401, "Admin auth required")
        payload = decode_token(token)
        admin = await db.admins.find_one({"id": payload["sub"]}, {"_id": 0})
        if not admin or not admin.get("is_active", True):
            raise HTTPException(401, "Account inactive or not found")
        return admin

    return _dep


def require_role(*roles: Role):
    """Decorator-like dependency. Usage in route: ``Depends(require_role('super_admin','manager'))``.

    The route MUST also depend on get_current_admin to populate the admin into request.state.
    """

    allowed = set(roles)

    def _check(request: Request):
        admin = getattr(request.state, "admin", None)
        if not admin:
            raise HTTPException(401, "Admin auth required")
        if admin["role"] not in allowed:
            raise HTTPException(403, f"Requires one of roles: {','.join(sorted(allowed))}")
        return admin

    return _check


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

AUDIT_ACTIONS_DESTRUCTIVE = {
    "admin.delete_user",
    "admin.delete_group",
    "admin.block_user",
    "admin.unblock_user",
    "admin.block_group",
    "admin.unblock_group",
    "admin.adjust_contribution",
    "admin.override_status",
    "admin.toggle_provider",
    "admin.update_provider_secret",
    "admin.create_admin",
    "admin.delete_admin",
    "admin.update_referral_settings",
    "admin.grant_credit",
    "admin.revoke_credit",
    "admin.set_group_discount",
    "admin.clear_group_discount",
    "admin.set_lead_discount",
    "admin.clear_lead_discount",
}


async def write_audit(
    db,
    *,
    admin_id: str,
    admin_email: str,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    payload: Optional[dict] = None,
    request: Optional[Request] = None,
):
    rec = {
        "id": "al_" + uuid.uuid4().hex[:12],
        "admin_id": admin_id,
        "admin_email": admin_email,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "payload": payload or {},
        "ip": (request.client.host if request and request.client else None),
        "destructive": action in AUDIT_ACTIONS_DESTRUCTIVE,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    await db.audit_log.insert_one(rec)
    return rec


# ---------------------------------------------------------------------------
# Bootstrap: seed first super-admin from env on startup
# ---------------------------------------------------------------------------

async def ensure_seed_admin(db):
    email = os.environ.get("ADMIN_EMAIL", "[email protected]").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")
    name = os.environ.get("ADMIN_NAME", "Super Admin")
    existing = await db.admins.find_one({"email": email}, {"_id": 0})
    if existing:
        return existing
    rec = {
        "id": "ad_" + uuid.uuid4().hex[:10],
        "email": email,
        "password_hash": hash_password(password),
        "name": name,
        "role": "super_admin",
        "is_active": True,
        "last_login_at": None,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    await db.admins.insert_one(rec)
    return rec
