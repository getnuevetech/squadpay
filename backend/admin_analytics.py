"""Admin analytics aggregations (Phase G5).

GET /api/admin/analytics?range=7d|30d|90d
  → comprehensive analytics payload for the Admin Dashboard

Charts/tables computed:
  - groups_per_day      [{date, count}]
  - gmv_per_day         [{date, amount}]      total bill amounts created
  - aov_per_day         [{date, value}]       avg bill amount
  - signups_per_day     [{date, count, verified_count}]
  - contributions_per_day [{date, amount, count}]
  - top_referrers       [{user_id, name, referral_code, signups, verified_signups}]
  - card_metrics        {total_issued, active, inactive, total_spent}
  - master_account      {balance, entries}
  - funnel              {signups, verified, joined_group, contributed, settled}
  - totals              {users, verified_users, groups, contributions, gmv, gross_processed_30d}
"""
from __future__ import annotations
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Query


def _today_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _date_str(d: dt.date) -> str:
    return d.isoformat()


def _parse_iso_date(s: Optional[str]) -> Optional[dt.date]:
    if not s:
        return None
    try:
        # tolerate full ISO timestamps and bare dates
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).date()
    except Exception:
        try:
            return dt.date.fromisoformat(str(s)[:10])
        except Exception:
            return None


def _empty_series(days: int) -> list[dict]:
    today = _today_utc()
    return [
        {"date": _date_str(today - dt.timedelta(days=i)), "count": 0, "amount": 0.0, "value": 0.0, "verified_count": 0}
        for i in range(days - 1, -1, -1)
    ]


def attach_analytics_routes(router: APIRouter, db, attach_admin):

    @router.get("/analytics")
    async def admin_analytics(
        range_param: str = Query("30d", alias="range"),
        admin=Depends(attach_admin),
    ):
        # Note: param aliased so frontend can send ?range=30d while we avoid
        # shadowing Python's built-in `range()` inside the handler.
        days = 30
        rng = range_param
        if rng.endswith("d"):
            try:
                days = max(1, min(180, int(rng[:-1])))
            except Exception:
                days = 30

        today = _today_utc()
        start = today - dt.timedelta(days=days - 1)
        start_iso = dt.datetime.combine(start, dt.time.min, tzinfo=dt.timezone.utc).isoformat()

        # ---- groups_per_day + gmv_per_day + aov_per_day
        groups_cursor = db.groups.find(
            {"created_at": {"$gte": start_iso}},
            {"_id": 0, "id": 1, "total_amount": 1, "created_at": 1, "lead_id": 1, "contributions": 1, "virtual_card": 1, "status": 1, "members": 1},
        )
        groups_in_range = await groups_cursor.to_list(length=None)

        groups_buckets: dict = {}
        for g in groups_in_range:
            d = _parse_iso_date(g.get("created_at"))
            if not d or d < start or d > today:
                continue
            key = _date_str(d)
            entry = groups_buckets.setdefault(key, {"count": 0, "gmv": 0.0})
            entry["count"] += 1
            entry["gmv"] += float(g.get("total_amount") or 0)

        groups_per_day = []
        gmv_per_day = []
        aov_per_day = []
        for i in range(days - 1, -1, -1):
            d = today - dt.timedelta(days=i)
            key = _date_str(d)
            b = groups_buckets.get(key, {"count": 0, "gmv": 0.0})
            groups_per_day.append({"date": key, "count": b["count"]})
            gmv_per_day.append({"date": key, "amount": round(b["gmv"], 2)})
            aov = round(b["gmv"] / b["count"], 2) if b["count"] > 0 else 0.0
            aov_per_day.append({"date": key, "value": aov})

        # ---- signups_per_day
        users_cursor = db.users.find(
            {"created_at": {"$gte": start_iso}},
            {"_id": 0, "id": 1, "created_at": 1, "verified": 1, "referred_by_user_id": 1},
        )
        users_in_range = await users_cursor.to_list(length=None)
        users_buckets: dict = {}
        for u in users_in_range:
            d = _parse_iso_date(u.get("created_at"))
            if not d or d < start or d > today:
                continue
            key = _date_str(d)
            entry = users_buckets.setdefault(key, {"count": 0, "verified_count": 0})
            entry["count"] += 1
            if u.get("verified"):
                entry["verified_count"] += 1
        signups_per_day = []
        for i in range(days - 1, -1, -1):
            d = today - dt.timedelta(days=i)
            key = _date_str(d)
            b = users_buckets.get(key, {"count": 0, "verified_count": 0})
            signups_per_day.append({"date": key, "count": b["count"], "verified_count": b["verified_count"]})

        # ---- contributions_per_day (across ALL groups, but contributions made within range)
        contrib_buckets: dict = {}
        all_groups_for_contribs = await db.groups.find(
            {}, {"_id": 0, "contributions": 1}
        ).to_list(length=None)
        for g in all_groups_for_contribs:
            for c in g.get("contributions") or []:
                d = _parse_iso_date(c.get("at"))
                if not d or d < start or d > today:
                    continue
                key = _date_str(d)
                entry = contrib_buckets.setdefault(key, {"amount": 0.0, "count": 0})
                entry["amount"] += float(c.get("amount") or 0)
                entry["count"] += 1
        contributions_per_day = []
        for i in range(days - 1, -1, -1):
            d = today - dt.timedelta(days=i)
            key = _date_str(d)
            b = contrib_buckets.get(key, {"amount": 0.0, "count": 0})
            contributions_per_day.append({"date": key, "amount": round(b["amount"], 2), "count": b["count"]})

        # ---- top referrers (all-time)
        pipeline = [
            {"$match": {"referred_by_user_id": {"$ne": None}}},
            {"$group": {
                "_id": "$referred_by_user_id",
                "signups": {"$sum": 1},
                "verified_signups": {"$sum": {"$cond": [{"$eq": ["$verified", True]}, 1, 0]}},
            }},
            {"$sort": {"signups": -1}},
            {"$limit": 10},
        ]
        top_raw = await db.users.aggregate(pipeline).to_list(length=10)
        top_user_ids = [r["_id"] for r in top_raw]
        ref_users = {}
        if top_user_ids:
            cursor = db.users.find(
                {"id": {"$in": top_user_ids}},
                {"_id": 0, "id": 1, "name": 1, "referral_code": 1},
            )
            for u in await cursor.to_list(length=None):
                ref_users[u["id"]] = u
        top_referrers = []
        for r in top_raw:
            u = ref_users.get(r["_id"]) or {}
            top_referrers.append({
                "user_id": r["_id"],
                "name": u.get("name") or "—",
                "referral_code": u.get("referral_code"),
                "signups": r["signups"],
                "verified_signups": r["verified_signups"],
            })

        # ---- card metrics (all-time across all groups)
        cards_cursor = db.groups.find(
            {"virtual_card.stripe_card_id": {"$exists": True, "$ne": None}},
            {"_id": 0, "id": 1, "virtual_card": 1, "total_amount": 1},
        )
        cards = await cards_cursor.to_list(length=None)
        total_issued = len(cards)
        active = sum(1 for c in cards if (c.get("virtual_card") or {}).get("status") == "active")
        inactive = sum(1 for c in cards if (c.get("virtual_card") or {}).get("status") == "inactive")
        total_spent = round(
            sum(float((c.get("virtual_card") or {}).get("spent") or 0) for c in cards),
            2,
        )
        card_metrics = {
            "total_issued": total_issued,
            "active": active,
            "inactive": inactive,
            "total_spent": total_spent,
        }

        # ---- master account balance (Phase G1)
        try:
            from reconciliation import get_master_account_balance
            master_balance = await get_master_account_balance(db)
        except Exception:
            master_balance = 0.0
        master_entries = await db.master_account_ledger.count_documents({})

        # ---- conversion funnel (all-time)
        all_users = await db.users.count_documents({})
        verified_users = await db.users.count_documents({"verified": True})
        users_with_groups = await db.groups.distinct("members.user_id")
        joined_group = len(users_with_groups)
        # users with at least 1 contribution
        contrib_users = set()
        for g in all_groups_for_contribs:
            for c in g.get("contributions") or []:
                if c.get("user_id"):
                    contrib_users.add(c["user_id"])
        contributed = len(contrib_users)
        # settled groups (status closed/paid+fully spent)
        settled_groups = await db.groups.count_documents({"status": {"$in": ["closed", "paid"]}})
        funnel = {
            "signups": all_users,
            "verified": verified_users,
            "joined_group": joined_group,
            "contributed": contributed,
            "settled_groups": settled_groups,
        }

        # ---- totals
        all_groups_count = await db.groups.count_documents({})
        all_groups_gmv_pipeline = [
            {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}},
        ]
        gmv_total_doc = await db.groups.aggregate(all_groups_gmv_pipeline).to_list(length=1)
        gmv_total = round(float(gmv_total_doc[0]["total"]) if gmv_total_doc else 0.0, 2)

        contributions_count = sum(len(g.get("contributions") or []) for g in all_groups_for_contribs)
        gross_processed_range = round(sum(c["amount"] for c in contributions_per_day), 2)

        totals = {
            "users": all_users,
            "verified_users": verified_users,
            "groups": all_groups_count,
            "groups_in_range": sum(b["count"] for b in groups_per_day),
            "contributions": contributions_count,
            "gmv": gmv_total,
            "gmv_in_range": round(sum(b["amount"] for b in gmv_per_day), 2),
            "gross_processed_in_range": gross_processed_range,
            "signups_in_range": sum(b["count"] for b in signups_per_day),
            "verified_in_range": sum(b["verified_count"] for b in signups_per_day),
        }

        return {
            "range_days": days,
            "start_date": _date_str(start),
            "end_date": _date_str(today),
            "groups_per_day": groups_per_day,
            "gmv_per_day": gmv_per_day,
            "aov_per_day": aov_per_day,
            "signups_per_day": signups_per_day,
            "contributions_per_day": contributions_per_day,
            "top_referrers": top_referrers,
            "card_metrics": card_metrics,
            "master_account": {"balance": master_balance, "entries": master_entries},
            "funnel": funnel,
            "totals": totals,
        }
