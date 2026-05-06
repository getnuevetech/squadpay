"""KMS-backed Fernet for at-rest secret encryption (Phase G2).

Single source of truth for symmetric encryption used across:
  - admin.py            (legacy duplicate — now delegates here)
  - integrations.py     (legacy duplicate — now delegates here)

Key resolution order (highest priority first):
  1. KMS_MASTER_KEY     — required for production. 32 url-safe-base64 bytes (Fernet format).
                          Generate via:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  2. KMS_PREVIOUS_KEYS  — comma-separated list of older keys; used ONLY for decrypt
                          fallback during rotation. New writes always go to the primary.
  3. SECRETS_KEY        — legacy env var (renamed; still accepted for backward-compat).
  4. JWT_SECRET-derived — INSECURE fallback (sha256 of JWT_SECRET, base64-encoded).
                          Logged as a warning at startup. The admin UI surfaces this
                          as a security banner.

Public API:
  encrypt(plain)        -> str   (Fernet token using primary key)
  decrypt(token)        -> str   (tries primary, then legacy keys)
  kms_status(db?)       -> dict  (introspection — used by Admin Security page)
  rotate_all(db)        -> dict  (re-encrypt every *_enc field in app_settings using
                                  the new primary; idempotent; safe to run on a live system)
"""
from __future__ import annotations
import base64
import hashlib
import logging
import os
import time
from typing import List, Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger(__name__)

# Module-level cache (rebuilt on rotation)
_PRIMARY: Optional[Fernet] = None
_MULTI: Optional[MultiFernet] = None
_KEY_SOURCE: str = "uninit"   # "kms_master" | "secrets_key" | "jwt_derived"
_PRIMARY_FP: Optional[str] = None
_LEGACY_FP: List[str] = []


def _fingerprint(key_bytes: bytes) -> str:
    """8-char fingerprint of a Fernet key for logs/UI (does NOT leak the key)."""
    return hashlib.sha256(key_bytes).hexdigest()[:8]


def _derive_from_jwt() -> bytes:
    seed = (os.environ.get("JWT_SECRET") or "dev-jwt-secret").encode("utf-8")
    return base64.urlsafe_b64encode(hashlib.sha256(seed).digest())


def _validate_fernet_key(s: str) -> Optional[bytes]:
    """Returns the key bytes if valid Fernet key, else None."""
    try:
        b = s.encode() if isinstance(s, str) else s
        Fernet(b)
        return b
    except Exception:
        return None


def _build():
    global _PRIMARY, _MULTI, _KEY_SOURCE, _PRIMARY_FP, _LEGACY_FP

    primary_bytes: Optional[bytes] = None
    legacy_bytes: List[bytes] = []
    key_source = "jwt_derived"

    # 1. KMS_MASTER_KEY
    raw = os.environ.get("KMS_MASTER_KEY")
    if raw:
        v = _validate_fernet_key(raw)
        if v:
            primary_bytes = v
            key_source = "kms_master"
        else:
            logger.error("[kms] KMS_MASTER_KEY is set but invalid (must be a Fernet key). Ignoring.")

    # 2. SECRETS_KEY (legacy env var)
    if primary_bytes is None:
        raw2 = os.environ.get("SECRETS_KEY")
        if raw2:
            v2 = _validate_fernet_key(raw2)
            if v2:
                primary_bytes = v2
                key_source = "secrets_key"

    # 3. JWT-derived fallback
    if primary_bytes is None:
        primary_bytes = _derive_from_jwt()
        key_source = "jwt_derived"
        logger.warning(
            "[kms] Using JWT-derived encryption key (INSECURE for production). "
            "Set KMS_MASTER_KEY in .env to a Fernet key."
        )

    # 4. Legacy keys for decrypt fallback (rotation continuity)
    legacy_raw = os.environ.get("KMS_PREVIOUS_KEYS", "").strip()
    if legacy_raw:
        for piece in legacy_raw.split(","):
            piece = piece.strip()
            if not piece:
                continue
            v = _validate_fernet_key(piece)
            if v and v != primary_bytes:
                legacy_bytes.append(v)
            else:
                logger.warning(f"[kms] KMS_PREVIOUS_KEYS entry skipped (invalid or duplicate of primary).")

    # ALWAYS include JWT-derived as a final legacy fallback (so existing data stays
    # readable even after the operator switches to KMS_MASTER_KEY without rotating).
    if key_source != "jwt_derived":
        derived = _derive_from_jwt()
        if derived != primary_bytes and derived not in legacy_bytes:
            legacy_bytes.append(derived)

    _PRIMARY = Fernet(primary_bytes)
    _MULTI = MultiFernet([_PRIMARY, *[Fernet(k) for k in legacy_bytes]])
    _PRIMARY_FP = _fingerprint(primary_bytes)
    _LEGACY_FP = [_fingerprint(k) for k in legacy_bytes]
    _KEY_SOURCE = key_source

    logger.info(
        f"[kms] init source={key_source} primary_fp={_PRIMARY_FP} "
        f"legacy_count={len(legacy_bytes)} legacy_fps={_LEGACY_FP}"
    )


# Build at import
_build()


def encrypt(plain: Optional[str]) -> Optional[str]:
    if plain is None or plain == "":
        return None
    if _PRIMARY is None:
        _build()
    return _PRIMARY.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt(token: Optional[str]) -> Optional[str]:
    if token is None or token == "":
        return None
    if _MULTI is None:
        _build()
    try:
        return _MULTI.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as e:
        logger.warning(f"[kms] decrypt failed (token unreadable with any known key): {e}")
        return None


def is_secure() -> bool:
    """True only if running with a real KMS_MASTER_KEY (or SECRETS_KEY) — i.e.,
    NOT the JWT-derived fallback."""
    return _KEY_SOURCE in ("kms_master", "secrets_key")


# --- Introspection / rotation ---


def kms_status() -> dict:
    return {
        "key_source": _KEY_SOURCE,
        "secure": is_secure(),
        "primary_fingerprint": _PRIMARY_FP,
        "legacy_fingerprints": list(_LEGACY_FP),
        "warning": (
            None if is_secure()
            else "Running with JWT-derived encryption key — INSECURE for production. "
                 "Set KMS_MASTER_KEY in /app/backend/.env to a Fernet key."
        ),
    }


# Field names that hold encrypted secrets in app_settings.integrations.*
# (Discovered dynamically by walking the doc; this is just a doc.)
_ENC_FIELD_SUFFIXES = ("_enc", "_token_enc", "_key_enc")


async def rotate_all(db) -> dict:
    """Walk every encrypted field in `app_settings` and re-encrypt with the
    current primary key. Decrypt uses MultiFernet (primary + legacy), so this
    is safe to run during/after a key change.

    Returns a summary dict { rotated, skipped, failed, fingerprint }.
    """
    started = time.time()
    rotated = 0
    skipped = 0
    failed = 0

    cursor = db.app_settings.find({}, {"_id": 0})
    docs = await cursor.to_list(length=None)

    for doc in docs:
        # find all fields ending in _enc anywhere in the doc (one level deep is enough)
        changed = False
        for top_key, top_val in list(doc.items()):
            if not isinstance(top_val, dict):
                continue
            for k, v in list(top_val.items()):
                if not isinstance(k, str) or not k.endswith("_enc"):
                    continue
                if not v or not isinstance(v, str):
                    continue
                plain = decrypt(v)
                if plain is None:
                    failed += 1
                    continue
                new_token = encrypt(plain)
                if new_token == v:
                    skipped += 1
                    continue
                top_val[k] = new_token
                changed = True
                rotated += 1
        if changed:
            await db.app_settings.update_one(
                {"key": doc.get("key")}, {"$set": doc}
            )

    elapsed_ms = int((time.time() - started) * 1000)
    logger.info(f"[kms] rotation done: rotated={rotated} skipped={skipped} failed={failed} in {elapsed_ms}ms")
    return {
        "rotated": rotated,
        "skipped": skipped,
        "failed": failed,
        "elapsed_ms": elapsed_ms,
        "primary_fingerprint": _PRIMARY_FP,
        "key_source": _KEY_SOURCE,
    }


def reload_keys() -> dict:
    """Re-read env vars and rebuild the cipher. Useful right after admin updates
    KMS_MASTER_KEY (manual env reload still required by operator)."""
    _build()
    return kms_status()
