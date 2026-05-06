"""Admin Security endpoints (Phase G2 — KMS introspection + key rotation).

Routes (all under /api/admin):
  GET  /security/kms-status   — current key source + fingerprints + warning
  POST /security/kms-reload   — re-read env (after operator changes KMS_MASTER_KEY)
  POST /security/kms-rotate   — re-encrypt every *_enc field in app_settings
                                 with the current primary key (super_admin only)
"""
from fastapi import APIRouter, Depends, Request

from admin import write_audit, require_role
import crypto_kms


def attach_security_routes(router: APIRouter, db, attach_admin):

    @router.get("/security/kms-status")
    async def admin_kms_status(admin=Depends(attach_admin)):
        st = crypto_kms.kms_status()
        # Add a count of encrypted fields currently stored, for the UI banner.
        # (Quick scan of app_settings — single small doc).
        try:
            docs = await db.app_settings.find({}, {"_id": 0}).to_list(length=None)
            enc_count = 0
            for d in docs:
                for v in d.values():
                    if isinstance(v, dict):
                        for k, val in v.items():
                            if isinstance(k, str) and k.endswith("_enc") and val:
                                enc_count += 1
            st["encrypted_field_count"] = enc_count
        except Exception:
            st["encrypted_field_count"] = None
        return st

    @router.post("/security/kms-reload")
    async def admin_kms_reload(
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        before = crypto_kms.kms_status()
        after = crypto_kms.reload_keys()
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.kms_reload",
            target_type="security",
            target_id="kms",
            payload={
                "before": {"source": before["key_source"], "fp": before["primary_fingerprint"]},
                "after": {"source": after["key_source"], "fp": after["primary_fingerprint"]},
            },
            request=request,
        )
        return after

    @router.post("/security/kms-rotate")
    async def admin_kms_rotate(
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin")),
    ):
        # Re-encrypt all *_enc fields in app_settings with the current primary key.
        # Safe to run with KMS_PREVIOUS_KEYS set (MultiFernet decrypts old then re-encrypts new).
        result = await crypto_kms.rotate_all(db)
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.kms_rotate",
            target_type="security",
            target_id="kms",
            payload=result,
            request=request,
        )
        return result
