"""Admin endpoints for credits + discounts (Phase C2)."""
import datetime as dt
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from admin import write_audit, require_role  # noqa: F401  (kept for back-compat)
from admin_modules import require_module


def _new_id(prefix: str = "cr_") -> str:
    import secrets, string
    alphabet = string.ascii_lowercase + string.digits
    return prefix + "".join(secrets.choice(alphabet) for _ in range(10))


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class GrantCreditIn(BaseModel):
    amount: float = Field(..., gt=0, le=10000)
    note: Optional[str] = None


class DiscountIn(BaseModel):
    type: Literal["flat", "percent"]
    value: float = Field(..., gt=0)
    note: Optional[str] = None


class LeadDiscountIn(BaseModel):
    type: Optional[Literal["flat", "percent"]] = None
    value: Optional[float] = None
    note: Optional[str] = None
    enabled: bool = True


def attach_credits_routes(router: APIRouter, db, attach_admin):
    # ===== USER CREDITS =====

    @router.get("/users/{user_id}/credits")
    async def admin_get_user_credits(user_id: str, admin=Depends(attach_admin)):
        u = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not u:
            raise HTTPException(404, "User not found")
        rows = await db.credits.find(
            {"user_id": user_id}, {"_id": 0}
        ).sort("created_at", -1).limit(200).to_list(length=None)
        balance = 0.0
        for r in rows:
            if r.get("status") == "active":
                balance += float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0)
        return {
            "user_id": user_id,
            "name": u.get("name"),
            "balance": round(max(0.0, balance), 2),
            "items": rows,
            "lead_auto_discount": u.get("lead_auto_discount"),
        }

    @router.post("/users/{user_id}/credits/grant")
    async def admin_grant_credit(
        user_id: str,
        body: GrantCreditIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_module("credit_rules")),
    ):
        u = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not u:
            raise HTTPException(404, "User not found")
        row = {
            "id": _new_id("cr_"),
            "user_id": user_id,
            "amount": round(float(body.amount), 2),
            "consumed_amount": 0.0,
            "kind": "admin_grant",
            "source_user_id": None,
            "status": "active",
            "note": body.note or f"Admin grant by {admin['email']}",
            "created_at": _now(),
            "granted_by": admin["email"],
        }
        await db.credits.insert_one(row.copy())
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.grant_credit",
            target_type="user",
            target_id=user_id,
            payload={"amount": row["amount"], "note": row["note"], "credit_id": row["id"]},
            request=request,
        )
        return row

    @router.post("/users/{user_id}/credits/{credit_id}/revoke")
    async def admin_revoke_credit(
        user_id: str,
        credit_id: str,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_module("credit_rules")),
    ):
        row = await db.credits.find_one({"id": credit_id, "user_id": user_id}, {"_id": 0})
        if not row:
            raise HTTPException(404, "Credit not found")
        if row.get("status") == "revoked":
            return row
        await db.credits.update_one(
            {"id": credit_id},
            {"$set": {"status": "revoked", "revoked_at": _now(), "revoked_by": admin["email"]}},
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.revoke_credit",
            target_type="user",
            target_id=user_id,
            payload={"credit_id": credit_id, "amount": row.get("amount")},
            request=request,
        )
        row = await db.credits.find_one({"id": credit_id}, {"_id": 0})
        return row

    # ===== GROUP DISCOUNT =====

    @router.post("/groups/{group_id}/discount")
    async def admin_set_group_discount(
        group_id: str,
        body: DiscountIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_module("credit_rules")),
    ):
        g = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not g:
            raise HTTPException(404, "Group not found")
        if g.get("status") != "open":
            raise HTTPException(400, "Cannot apply discount to a settled bill")
        original = float(g.get("original_total_amount") or g.get("total_amount") or 0)
        # Compute discount amount
        if body.type == "percent":
            disc_amt = round(original * min(float(body.value), 100) / 100.0, 2)
        else:
            disc_amt = round(min(float(body.value), original), 2)
        new_total = round(max(0.0, original - disc_amt), 2)
        discount = {
            "type": body.type,
            "value": float(body.value),
            "amount": disc_amt,
            "note": body.note,
            "source": "admin",
            "applied_at": _now(),
            "applied_by": admin["email"],
        }
        await db.groups.update_one(
            {"id": group_id},
            {"$set": {
                "discount": discount,
                "total_amount": new_total,
                "original_total_amount": original,
            }},
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.set_group_discount",
            target_type="group",
            target_id=group_id,
            payload={"type": body.type, "value": body.value, "amount": disc_amt, "new_total": new_total},
            request=request,
        )
        return {"discount": discount, "total_amount": new_total, "original_total_amount": original}

    @router.delete("/groups/{group_id}/discount")
    async def admin_clear_group_discount(
        group_id: str,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_module("credit_rules")),
    ):
        g = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not g:
            raise HTTPException(404, "Group not found")
        original = float(g.get("original_total_amount") or g.get("total_amount") or 0)
        await db.groups.update_one(
            {"id": group_id},
            {"$set": {"discount": None, "total_amount": original}},
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.clear_group_discount",
            target_type="group",
            target_id=group_id,
            payload={"restored_total": original, "previous": g.get("discount")},
            request=request,
        )
        return {"discount": None, "total_amount": original}

    # ===== LEAD AUTO-DISCOUNT =====

    @router.post("/users/{user_id}/lead-discount")
    async def admin_set_lead_discount(
        user_id: str,
        body: LeadDiscountIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_module("credit_rules")),
    ):
        u = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not u:
            raise HTTPException(404, "User not found")
        if not body.enabled or not body.type or not body.value or float(body.value) <= 0:
            await db.users.update_one({"id": user_id}, {"$set": {"lead_auto_discount": None}})
            await write_audit(
                db,
                admin_id=admin["id"],
                admin_email=admin["email"],
                action="admin.clear_lead_discount",
                target_type="user",
                target_id=user_id,
                payload={"previous": u.get("lead_auto_discount")},
                request=request,
            )
            return {"lead_auto_discount": None}
        rec = {
            "type": body.type,
            "value": float(body.value),
            "note": body.note,
            "set_at": _now(),
            "set_by": admin["email"],
        }
        await db.users.update_one({"id": user_id}, {"$set": {"lead_auto_discount": rec}})
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.set_lead_discount",
            target_type="user",
            target_id=user_id,
            payload=rec,
            request=request,
        )
        return {"lead_auto_discount": rec}
