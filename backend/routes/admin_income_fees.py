"""
Admin → Income & Fees ledger.

Computes the platform's retained-fee income from existing group documents
in real time (no separate ledger collection — keeps the source of truth
in one place and avoids drift between MongoDB tables).

For each group we expose:
  • transaction_fees_total — sum of p.transaction_fee across all per_user
  • platform_fees_total    — sum of p.platform_fee across all per_user
  • extra_1_total / extra_2_total — sum of p.extra_fees by id
  • total_retained         — items+tax+tip flow to the virtual card;
                              fees are RETAINED by the platform.
  • per-contribution drill-down so the admin can see exactly which payment
    contributed which slice of fees.

This page IS the platform's revenue ledger. The numbers here should
reconcile against Stripe's BalanceTransactions for the same period.
"""
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query


def _safe_iso(v: Any) -> Optional[str]:
    """Coerce common datetime shapes to ISO-8601 string for JSON output."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, str):
        return v
    return None


def _fee_breakdown_for_group(group: Dict[str, Any]) -> Dict[str, float]:
    """Return per-group totals for each fee category (whole-bill)."""
    per_user = group.get("per_user") or []
    transaction = sum(float(p.get("transaction_fee") or 0) for p in per_user)
    platform = sum(float(p.get("platform_fee") or 0) for p in per_user)
    extra_1 = 0.0
    extra_2 = 0.0
    extra_other = 0.0
    for p in per_user:
        for ef in (p.get("extra_fees") or []):
            amt = float(ef.get("amount") or 0)
            fid = str(ef.get("id") or "")
            if fid == "extra_1":
                extra_1 += amt
            elif fid == "extra_2":
                extra_2 += amt
            else:
                extra_other += amt
    total = transaction + platform + extra_1 + extra_2 + extra_other
    return {
        "transaction_fees": round(transaction, 2),
        "platform_fees": round(platform, 2),
        "extra_1": round(extra_1, 2),
        "extra_2": round(extra_2, 2),
        "extra_other": round(extra_other, 2),
        "total_retained": round(total, 2),
    }


def _contribution_rows(group: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Drill-down rows for each contribution. We *attribute* a member's fee
    share proportionally to how much of their personal share they have
    contributed so far.

    contributed_pct = min(1, contribution.amount / member.total_share)
    fee_slice       = member.{transaction_fee, platform_fee, extras} * contributed_pct

    This gives a continuously-updating revenue view even on partially-funded
    bills, and converges to the exact per-member breakdown when the bill
    is fully funded.
    """
    per_user_by_id = {p.get("user_id"): p for p in (group.get("per_user") or [])}
    member_by_id = {m.get("user_id"): m for m in (group.get("members") or [])}

    contributions = list(group.get("contributions") or [])
    rows: List[Dict[str, Any]] = []

    # Track total contributed per user so we can compute proportional shares.
    contrib_so_far: Dict[str, float] = {}
    for c in contributions:
        uid = c.get("user_id")
        amt = float(c.get("amount") or 0)
        pu = per_user_by_id.get(uid) or {}
        share = float(pu.get("total") or 0)
        if share <= 0:
            tx = pl = e1 = e2 = 0.0
        else:
            prev = contrib_so_far.get(uid, 0.0)
            new_total = prev + amt
            prev_pct = min(1.0, prev / share)
            new_pct = min(1.0, new_total / share)
            delta_pct = max(0.0, new_pct - prev_pct)

            # Fee slice attributable to *this* contribution.
            tx = float(pu.get("transaction_fee") or 0) * delta_pct
            pl = float(pu.get("platform_fee") or 0) * delta_pct
            extras = pu.get("extra_fees") or []
            e1 = sum(float(ef.get("amount") or 0) for ef in extras if ef.get("id") == "extra_1") * delta_pct
            e2 = sum(float(ef.get("amount") or 0) for ef in extras if ef.get("id") == "extra_2") * delta_pct
            contrib_so_far[uid] = new_total

        rows.append({
            "user_id": uid,
            "user_name": (member_by_id.get(uid) or {}).get("name") or "Member",
            "amount": round(amt, 2),
            "stripe_pi": c.get("stripe_pi") or c.get("payment_intent_id"),
            "ts": _safe_iso(c.get("ts") or c.get("created_at")),
            "transaction_fee": round(tx, 2),
            "platform_fee": round(pl, 2),
            "extra_1": round(e1, 2),
            "extra_2": round(e2, 2),
            "fee_slice_total": round(tx + pl + e1 + e2, 2),
        })
    return rows


def attach_income_fees_routes(api_router: APIRouter, db, require_admin):
    """Register admin endpoints under /api/admin/income-fees."""
    from admin_modules import require_module
    _gate = require_module("income_fees")

    @api_router.get("/admin/income-fees")
    async def income_fees(
        _admin=Depends(require_admin),
        _check=Depends(_gate),
        # Filter by bill status — defaults to *all* so admins see ongoing income too.
        status: Optional[str] = Query(default=None, description="open | funded | paid | …"),
        # Time window (UTC, ISO-8601). Defaults to no filter.
        since: Optional[str] = Query(default=None),
        until: Optional[str] = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
        skip: int = Query(default=0, ge=0),
    ):
        q: Dict[str, Any] = {}
        if status:
            q["status"] = status
        if since:
            q.setdefault("created_at", {})["$gte"] = since
        if until:
            q.setdefault("created_at", {})["$lte"] = until

        cursor = db.groups.find(q).sort("created_at", -1).skip(skip).limit(limit)
        groups: List[Dict[str, Any]] = []
        agg = {
            "transaction_fees": 0.0,
            "platform_fees": 0.0,
            "extra_1": 0.0,
            "extra_2": 0.0,
            "extra_other": 0.0,
            "total_retained": 0.0,
            "groups_counted": 0,
            "contributions_counted": 0,
            "gross_contributed": 0.0,
        }
        async for g in cursor:
            fees = _fee_breakdown_for_group(g)
            rows = _contribution_rows(g)
            contributed = float((g.get("funding") or {}).get("total_contributed") or 0)
            agg["gross_contributed"] += contributed
            agg["contributions_counted"] += len(rows)
            for k in ("transaction_fees", "platform_fees", "extra_1", "extra_2", "extra_other", "total_retained"):
                agg[k] += fees[k]
            agg["groups_counted"] += 1
            groups.append({
                "id": g.get("id"),
                "title": g.get("title") or g.get("name") or "Bill",
                "status": g.get("status"),
                "created_at": _safe_iso(g.get("created_at")),
                "settled_at": _safe_iso(g.get("paid_at") or g.get("settled_at")),
                "lead_id": g.get("lead_id"),
                "members_count": len(g.get("members") or []),
                "gross_contributed": round(contributed, 2),
                # Tax + tips + item count surfaced for the tabular per-group
                # ledger view. Tax/tips live at the group root (set by
                # itemized split flow), default 0 for fast-split bills.
                "tax": round(float(g.get("tax") or 0), 2),
                "tips": round(float(g.get("tip") or g.get("tips") or 0), 2),
                "total_items": len(g.get("items") or []),
                "fees": fees,
                "contributions": rows,
                "virtual_card_last4": ((g.get("virtual_card") or {}).get("last4")),
            })

        for k in ("transaction_fees", "platform_fees", "extra_1", "extra_2", "extra_other", "total_retained", "gross_contributed"):
            agg[k] = round(agg[k], 2)

        # Cheap time-window aggregates (last 7 / 30 days) for the page header.
        now = datetime.utcnow()
        windows = {"week": now - timedelta(days=7), "month": now - timedelta(days=30)}
        window_totals: Dict[str, float] = {}
        for w_name, w_start in windows.items():
            w_total = 0.0
            async for g in db.groups.find({}):
                ts_raw = g.get("created_at")
                ts = ts_raw if isinstance(ts_raw, datetime) else None
                if not ts:
                    continue
                if ts < w_start:
                    continue
                w_total += _fee_breakdown_for_group(g)["total_retained"]
            window_totals[w_name] = round(w_total, 2)

        return {
            "totals": agg,
            "window_totals": window_totals,
            "groups": groups,
            "skip": skip,
            "limit": limit,
        }

    return income_fees
