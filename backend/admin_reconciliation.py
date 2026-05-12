"""Admin endpoints for Reconciliation (Phase G1).

Routes (all under /api/admin):
  GET  /reconciliations                     — list events with filters
  GET  /reconciliations/{rec_id}            — detail
  POST /groups/{group_id}/reconcile          — manual reconcile trigger (super_admin/manager)
  POST /groups/{group_id}/disable-card       — manual card disable (already in admin_routes)
  GET  /master-account                      — master account ledger + balance
  GET  /reconciliation-settings             — current settings
  POST /reconciliation-settings             — update toggle (credit_contributors_enabled, auto_disable_card)
"""
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from admin import write_audit, require_role
from admin_modules import require_module
from reconciliation import (
    ensure_reconciliation_settings,
    get_reconciliation_settings,
    list_master_account,
    list_reconciliations,
    get_reconciliation_detail,
    reconcile_group,
)


class ReconciliationSettingsIn(BaseModel):
    credit_contributors_enabled: Optional[bool] = None
    auto_disable_card: Optional[bool] = None


def attach_reconciliation_routes(router: APIRouter, db, attach_admin):

    @router.get("/reconciliations")
    async def admin_list_reconciliations(
        q: Optional[str] = None,
        action: Optional[Literal["credit_contributors", "moved_to_master", "no_leftover"]] = None,
        limit: int = 50,
        skip: int = 0,
        admin=Depends(attach_admin),
    ):
        return await list_reconciliations(db, q=q, action=action, limit=limit, skip=skip)

    @router.get("/reconciliations/{rec_id}")
    async def admin_get_reconciliation(rec_id: str, admin=Depends(attach_admin)):
        rec = await get_reconciliation_detail(db, rec_id)
        if not rec:
            raise HTTPException(404, "Reconciliation not found")
        return rec

    @router.post("/groups/{group_id}/reconcile")
    async def admin_manual_reconcile(
        group_id: str,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_module("reconciliations")),
    ):
        try:
            rec = await reconcile_group(db, group_id, source="manual", actor_email=admin["email"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.reconcile_group",
            target_type="group",
            target_id=group_id,
            payload={
                "reconciliation_id": rec.get("id"),
                "action": rec.get("action"),
                "leftover": rec.get("leftover"),
                "amount_collected": rec.get("amount_collected"),
                "amount_spent": rec.get("amount_spent"),
            },
            request=request,
        )
        return rec

    @router.get("/master-account")
    async def admin_master_account(
        limit: int = 100,
        skip: int = 0,
        admin=Depends(attach_admin),
    ):
        return await list_master_account(db, limit=limit, skip=skip)

    @router.get("/reconciliation-settings")
    async def admin_get_reconciliation_settings(admin=Depends(attach_admin)):
        await ensure_reconciliation_settings(db)
        return await get_reconciliation_settings(db)

    @router.post("/reconciliation-settings")
    async def admin_set_reconciliation_settings(
        body: ReconciliationSettingsIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_module("reconciliations")),
    ):
        await ensure_reconciliation_settings(db)
        cur = await get_reconciliation_settings(db)
        new = dict(cur)
        if body.credit_contributors_enabled is not None:
            new["credit_contributors_enabled"] = bool(body.credit_contributors_enabled)
        if body.auto_disable_card is not None:
            new["auto_disable_card"] = bool(body.auto_disable_card)
        import datetime as _dt
        new["updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        new["updated_by"] = admin["email"]
        await db.app_settings.update_one(
            {"key": "integrations"}, {"$set": {"reconciliation": new}}, upsert=True
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.update_reconciliation_settings",
            target_type="settings",
            target_id="integrations.reconciliation",
            payload=new,
            request=request,
        )
        return new
