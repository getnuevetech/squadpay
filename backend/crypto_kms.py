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
    """Walk every encrypted field across all known collections and re-encrypt
    with the current primary key. Decrypt uses MultiFernet (primary + legacy),
    so this is safe to run during/after a key change.

    Scanned collections:
      - app_settings.*                — sms providers, issuing webhook secret
      - app_config (where _id="gateway_configs")
                                       — gateway_config.{slug}.credentials_enc.*
      - users.*                       — payout access_token_enc / refresh_token_enc
                                         (and any other *_enc fields on the user doc)
      - gateway_configs               — top-level credentials_enc dict (newer schema)

    Returns a per-collection summary plus aggregate rotated/skipped/failed.
    """
    started = time.time()
    totals = {"rotated": 0, "skipped": 0, "failed": 0}
    per_collection: dict = {}

    def _rerypt(value):
        """Returns (new_token, status) where status in {'rotated','skipped','failed'}."""
        if not value or not isinstance(value, str):
            return value, "skipped"
        plain = decrypt(value)
        if plain is None:
            return value, "failed"
        new_token = encrypt(plain)
        if new_token == value:
            return value, "skipped"
        return new_token, "rotated"

    async def _walk_dict_enc(coll_name: str, query: dict, key_for_update: dict | None = None):
        """For docs matching `query`, find every *_enc field one or two levels
        deep and re-encrypt in place. Also handles the gateway_config pattern
        where the PARENT field is named `credentials_enc` (and its children
        are unsuffixed, e.g. `secret_key`). `key_for_update` overrides the
        update predicate (defaults to {"_id": doc["_id"]} or
        {"key": doc["key"]} if present). Returns counts for this collection."""
        c = {"rotated": 0, "skipped": 0, "failed": 0}

        def _rotate_in_dict(d: dict) -> bool:
            """Re-encrypt EVERY string value in this dict (used when the parent
            field is itself flagged as _enc)."""
            changed = False
            for k, v in list(d.items()):
                if isinstance(v, str) and v:
                    new_token, status = _rerypt(v)
                    c[status] += 1
                    if status == "rotated":
                        d[k] = new_token
                        changed = True
            return changed

        try:
            cursor = db[coll_name].find(query)
            async for doc in cursor:
                changed = False
                for top_k, top_v in list(doc.items()):
                    if top_k == "_id":
                        continue
                    if isinstance(top_k, str) and top_k.endswith("_enc"):
                        if isinstance(top_v, str):
                            new_token, status = _rerypt(top_v)
                            c[status] += 1
                            if status == "rotated":
                                doc[top_k] = new_token
                                changed = True
                        elif isinstance(top_v, dict):
                            # Parent is `*_enc` → every string child is a secret
                            # (e.g. gateway_config.credentials_enc.secret_key).
                            if _rotate_in_dict(top_v):
                                changed = True
                    elif isinstance(top_v, dict):
                        # walk one more level for nested per-suffix encrypted fields.
                        for k2, v2 in list(top_v.items()):
                            if isinstance(k2, str) and k2.endswith("_enc"):
                                if isinstance(v2, str):
                                    new_token, status = _rerypt(v2)
                                    c[status] += 1
                                    if status == "rotated":
                                        top_v[k2] = new_token
                                        changed = True
                                elif isinstance(v2, dict):
                                    if _rotate_in_dict(v2):
                                        changed = True
                            elif isinstance(v2, dict):
                                for k3, v3 in list(v2.items()):
                                    if isinstance(k3, str) and k3.endswith("_enc"):
                                        if isinstance(v3, str):
                                            new_token, status = _rerypt(v3)
                                            c[status] += 1
                                            if status == "rotated":
                                                v2[k3] = new_token
                                                changed = True
                if changed:
                    pred = key_for_update or (
                        {"_id": doc["_id"]} if "_id" in doc
                        else {"key": doc.get("key")} if doc.get("key")
                        else {"id": doc.get("id")} if doc.get("id")
                        else None
                    )
                    if pred:
                        update_doc = {k: v for k, v in doc.items() if k != "_id"}
                        await db[coll_name].update_one(pred, {"$set": update_doc})
        except Exception as e:  # pylint: disable=broad-except
            logger.warning(f"[kms] rotate scan failed for {coll_name}: {e}")
        per_collection[coll_name] = c
        for k in totals:
            totals[k] += c[k]

    # ── 1. app_settings (sms providers, issuing config)
    await _walk_dict_enc("app_settings", {})

    # ── 2. gateway_config (SquadPay schema — singular, single collection)
    await _walk_dict_enc("gateway_config", {})

    # ── 3. gateway_configs (legacy plural variant — harmless if absent)
    await _walk_dict_enc("gateway_configs", {})

    # ── 4. app_config (legacy / future single-doc-style configs)
    await _walk_dict_enc("app_config", {})

    # ── 5. users — only docs that actually have any *_enc fields.
    await _walk_dict_enc("users", {
        "$or": [
            {"access_token_enc": {"$exists": True, "$ne": None}},
            {"refresh_token_enc": {"$exists": True, "$ne": None}},
            {"stripe_connect": {"$exists": True}},
        ],
    })

    # ── 6. issuing config (separate single-doc collection on some deployments)
    await _walk_dict_enc("issuing", {})

    # ── 7. connect_user_accounts (Stripe Connect tokens for payouts)
    await _walk_dict_enc("connect_user_accounts", {})

    # ── 8. astra_user_tokens / payout_user_cards (Astra payout integration)
    await _walk_dict_enc("astra_user_tokens", {})
    await _walk_dict_enc("payout_user_cards", {})

    elapsed_ms = int((time.time() - started) * 1000)
    logger.info(
        f"[kms] rotation done: rotated={totals['rotated']} skipped={totals['skipped']} "
        f"failed={totals['failed']} in {elapsed_ms}ms per_collection={per_collection}"
    )
    return {
        **totals,
        "elapsed_ms": elapsed_ms,
        "primary_fingerprint": _PRIMARY_FP,
        "key_source": _KEY_SOURCE,
        "per_collection": per_collection,
    }


def reload_keys() -> dict:
    """Re-read env vars and rebuild the cipher. Useful right after admin updates
    KMS_MASTER_KEY (manual env reload still required by operator)."""
    _build()
    return kms_status()
