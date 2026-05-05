"""Admin endpoints for the Referral system (Phase C1).

Mounted onto the admin router by admin_routes.build_admin_router().
"""
import datetime as dt
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field

from admin import write_audit, require_role


class ReferralSettingsIn(BaseModel):
    enabled: bool = False
    referrer_credit: float = Field(0, ge=0, le=10000)
    referee_credit: float = Field(0, ge=0, le=10000)


def attach_referrals_routes(router: APIRouter, db, attach_admin):
    @router.get("/referrals/settings")
    async def get_settings(admin=Depends(attach_admin)):
        rec = await db.app_settings.find_one({"key": "referrals"}, {"_id": 0})
        if not rec:
            rec = {
                "key": "referrals",
                "enabled": False,
                "referrer_credit": 0.0,
                "referee_credit": 0.0,
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            await db.app_settings.insert_one(rec.copy())
        return {
            "enabled": bool(rec.get("enabled")),
            "referrer_credit": float(rec.get("referrer_credit") or 0),
            "referee_credit": float(rec.get("referee_credit") or 0),
            "updated_at": rec.get("updated_at"),
        }

    @router.post("/referrals/settings")
    async def set_settings(
        body: ReferralSettingsIn,
        request: Request,
        admin=Depends(attach_admin),
        _check=Depends(require_role("super_admin", "manager")),
    ):
        update = {
            "key": "referrals",
            "enabled": bool(body.enabled),
            "referrer_credit": round(float(body.referrer_credit), 2),
            "referee_credit": round(float(body.referee_credit), 2),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_by": admin.get("email"),
        }
        await db.app_settings.update_one(
            {"key": "referrals"}, {"$set": update}, upsert=True
        )
        await write_audit(
            db,
            admin_id=admin["id"],
            admin_email=admin["email"],
            action="admin.update_referral_settings",
            target_type="settings",
            target_id="referrals",
            payload={
                "enabled": update["enabled"],
                "referrer_credit": update["referrer_credit"],
                "referee_credit": update["referee_credit"],
            },
            request=request,
        )
        return update

    @router.get("/referrals")
    async def list_referrers(
        request: Request,
        q: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=500),
        skip: int = Query(0, ge=0),
        admin=Depends(attach_admin),
    ):
        """Leaderboard of referrers with counts + conversion."""
        # Aggregate via $group on users referred_by_user_id field
        pipeline: List[dict] = [
            {"$match": {"referred_by_user_id": {"$ne": None}}},
            {
                "$group": {
                    "_id": "$referred_by_user_id",
                    "total": {"$sum": 1},
                    "verified": {"$sum": {"$cond": [{"$eq": ["$verified", True]}, 1, 0]}},
                }
            },
            {"$sort": {"total": -1, "verified": -1}},
        ]
        rows = await db.users.aggregate(pipeline).to_list(length=None)
        # Resolve names
        ids = [r["_id"] for r in rows if r.get("_id")]
        users = await db.users.find(
            {"id": {"$in": ids}},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "referral_code": 1, "is_blocked": 1},
        ).to_list(length=None)
        umap = {u["id"]: u for u in users}
        items = []
        for r in rows:
            u = umap.get(r["_id"], {})
            row = {
                "user_id": r["_id"],
                "name": u.get("name"),
                "phone": u.get("phone"),
                "referral_code": u.get("referral_code"),
                "is_blocked": bool(u.get("is_blocked")),
                "total_referrals": int(r.get("total") or 0),
                "verified_referrals": int(r.get("verified") or 0),
            }
            if q:
                ql = q.lower()
                hay = f"{row['name'] or ''} {row['phone'] or ''} {row['referral_code'] or ''}".lower()
                if ql not in hay:
                    continue
            items.append(row)
        total = len(items)
        items = items[skip : skip + limit]

        # Aggregate stats
        all_users_with_ref = await db.users.count_documents({"referred_by_user_id": {"$ne": None}})
        verified_with_ref = await db.users.count_documents(
            {"referred_by_user_id": {"$ne": None}, "verified": True}
        )
        pending_credits = await db.credits.count_documents({"status": "pending"})
        return {
            "items": items,
            "total": total,
            "skip": skip,
            "limit": limit,
            "stats": {
                "total_referred": all_users_with_ref,
                "verified_referred": verified_with_ref,
                "conversion_rate": round((verified_with_ref / all_users_with_ref * 100) if all_users_with_ref else 0, 1),
                "pending_credits": pending_credits,
            },
        }

    @router.get("/referrals/{user_id}")
    async def referrer_detail(user_id: str, admin=Depends(attach_admin)):
        u = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not u:
            raise HTTPException(404, "User not found")
        referees_cursor = db.users.find(
            {"referred_by_user_id": user_id},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "verified": 1, "created_at": 1, "is_blocked": 1},
        ).sort("created_at", -1)
        referees = await referees_cursor.to_list(length=None)
        # Conversion: referee made at least one group (lead or member, not just signup)
        for r in referees:
            count = await db.groups.count_documents({"members.user_id": r["id"]})
            r["groups_joined"] = int(count)
        referrer = None
        if u.get("referred_by_user_id"):
            ref = await db.users.find_one(
                {"id": u["referred_by_user_id"]},
                {"_id": 0, "id": 1, "name": 1, "referral_code": 1},
            )
            if ref:
                referrer = ref
        pending = await db.credits.count_documents({"user_id": user_id, "status": "pending"})
        return {
            "id": u["id"],
            "name": u.get("name"),
            "phone": u.get("phone"),
            "referral_code": u.get("referral_code"),
            "is_blocked": bool(u.get("is_blocked")),
            "referred_by": referrer,
            "referees": referees,
            "pending_credits": pending,
        }
