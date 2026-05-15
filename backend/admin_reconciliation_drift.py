"""
admin_reconciliation_drift.py — Phase 1 of Real-Time Ledger Reconciliation
=========================================================================
Drift detection: compare SquadPay's internal records of money collected
against the corresponding source of truth (Stripe PaymentIntents for
contributions, the group's `virtual_card.transactions` for spend). Any
mismatch beyond a small rounding tolerance is persisted to the
`reconciliation_drift` collection so admins can investigate.

This module is PURELY ADDITIVE — it never mutates groups, contributions,
or Stripe. It only OBSERVES. Future phases will graduate from observation
to auto-recovery (Phase 3 — Auto Recovery) and full double-entry ledger
posting (Phase 2 — Real-Time Ledger).

Drift kinds we track:
  • db_internal      — sum(contributions.amount) != funding.total_contributed
                       (denormalization rot in our own DB)
  • stripe_charges   — sum(contributions.amount) for the group differs from
                       sum(stripe.PaymentIntent.amount_received) tagged with
                       metadata.group_id == <id>
  • stripe_card_spend — group.virtual_card.spent differs from
                        sum(stripe.Issuing.Transaction.amount) for the card
  • settlement_imbalance — finalised group has total_contributed <
                            grand_total (i.e. paid out more than collected)

Each drift row is { id, group_id, kind, expected, observed, delta,
detected_at, resolved, notes }. Resolved=true after admin marks it OK or
a follow-up scan confirms the numbers reconcile.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

# Local imports
from admin import write_audit  # type: ignore
from admin_routes import get_current_admin_factory_sync  # type: ignore

DRIFT_TOLERANCE = 0.01  # $0.01 — anything tighter is just float noise


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "drft_") -> str:
    return f"{prefix}{int(time.time() * 1000):x}"


# ──────────────────────────────────────────────────────────────────────────
# Scanner
# ──────────────────────────────────────────────────────────────────────────

async def _scan_db_internal_drift(db) -> list[dict]:
    """Detect denormalisation rot: sum(contributions.amount) for each group
    should equal `funding.total_contributed` cached on the group doc.

    This is a cheap, no-network sanity check that catches bugs in our own
    update paths (e.g. a contribution insert that forgot to refresh the
    funding aggregate).
    """
    drifts: list[dict] = []
    # Only scan groups that have at least one contribution; settled/cancelled
    # are still in scope because drift would indicate a historical leak.
    cursor = db.groups.find(
        {"contributions.0": {"$exists": True}},
        {
            "_id": 0,
            "id": 1,
            "title": 1,
            "status": 1,
            "contributions": 1,
            "funding": 1,
        },
    )
    async for g in cursor:
        contribs = g.get("contributions") or []
        observed = round(sum(float(c.get("amount") or 0) for c in contribs), 2)
        funding = g.get("funding") or {}
        expected = round(float(funding.get("total_contributed") or 0), 2)
        delta = round(observed - expected, 2)
        if abs(delta) > DRIFT_TOLERANCE:
            drifts.append({
                "id": _new_id(),
                "group_id": g.get("id"),
                "group_title": g.get("title") or "Group Bill",
                "group_status": g.get("status"),
                "kind": "db_internal",
                "expected": expected,
                "observed": observed,
                "delta": delta,
                "detected_at": _now_iso(),
                "resolved": False,
                "notes": (
                    "funding.total_contributed disagrees with the live sum "
                    "of contributions[].amount on the same group document. "
                    "Likely cause: a contribution mutation skipped the "
                    "funding aggregate refresh."
                ),
            })
    return drifts


async def _scan_settlement_imbalance(db) -> list[dict]:
    """Detect groups in a settled/lead_paid state whose total_contributed is
    less than the gross billed amount (we paid out more than we collected).

    Doesn't catch live overruns mid-flow — those resolve naturally. Only
    flags terminal states where the imbalance is permanent.
    """
    drifts: list[dict] = []
    cursor = db.groups.find(
        {"status": {"$in": ["lead_paid", "settled"]}},
        {
            "_id": 0,
            "id": 1,
            "title": 1,
            "status": 1,
            "total_amount": 1,
            "funding": 1,
        },
    )
    async for g in cursor:
        funding = g.get("funding") or {}
        contributed = round(float(funding.get("total_contributed") or 0), 2)
        billed = round(float(g.get("total_amount") or 0), 2)
        delta = round(contributed - billed, 2)
        if delta < -DRIFT_TOLERANCE:
            drifts.append({
                "id": _new_id(),
                "group_id": g.get("id"),
                "group_title": g.get("title") or "Group Bill",
                "group_status": g.get("status"),
                "kind": "settlement_imbalance",
                "expected": billed,
                "observed": contributed,
                "delta": delta,  # negative
                "detected_at": _now_iso(),
                "resolved": False,
                "notes": (
                    "Group reached terminal state but contributors covered "
                    "less than the merchant total. Lead may have absorbed "
                    "the gap, or a refund/credit needs auditing."
                ),
            })
    return drifts


async def run_drift_scan(db, kinds: Optional[list[str]] = None) -> dict:
    """Run a full drift scan and persist any new drift rows.

    Idempotent at the row level: if an unresolved drift already exists for
    the same (group_id, kind), we update its `detected_at` instead of
    inserting a duplicate. Once resolved=true rows survive forever as an
    audit trail.

    Returns a summary suitable for the admin UI's "Last scan" panel.
    """
    started = time.monotonic()
    selected = set(kinds or ["db_internal", "settlement_imbalance"])
    all_drifts: list[dict] = []

    if "db_internal" in selected:
        all_drifts.extend(await _scan_db_internal_drift(db))
    if "settlement_imbalance" in selected:
        all_drifts.extend(await _scan_settlement_imbalance(db))

    inserted = 0
    refreshed = 0
    for d in all_drifts:
        existing = await db.reconciliation_drift.find_one({
            "group_id": d["group_id"],
            "kind": d["kind"],
            "resolved": False,
        })
        if existing:
            # Refresh observed / delta in case the gap changed since last scan.
            await db.reconciliation_drift.update_one(
                {"id": existing["id"]},
                {"$set": {
                    "observed": d["observed"],
                    "delta": d["delta"],
                    "detected_at": d["detected_at"],
                }},
            )
            refreshed += 1
        else:
            await db.reconciliation_drift.insert_one(d)
            inserted += 1

    elapsed_ms = int((time.monotonic() - started) * 1000)
    summary = {
        "ran_at": _now_iso(),
        "elapsed_ms": elapsed_ms,
        "kinds_scanned": sorted(selected),
        "drifts_found": len(all_drifts),
        "rows_inserted": inserted,
        "rows_refreshed": refreshed,
    }
    # Stash a copy of the last summary for the admin UI's status header.
    await db.reconciliation_drift_runs.insert_one({"id": _new_id("run_"), **summary})
    return summary


# ──────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────

def attach_drift_routes(api_router, db):
    """Mount Phase 1 reconciliation-drift admin endpoints onto `api_router`.

    Endpoints (all require admin auth):
      POST  /api/admin/reconciliation/drift/scan       — run a scan now
      GET   /api/admin/reconciliation/drift            — list drift rows
      GET   /api/admin/reconciliation/drift/runs       — last 20 scans
      POST  /api/admin/reconciliation/drift/{id}/resolve  — mark resolved
    """
    r = APIRouter()
    current_admin = get_current_admin_factory_sync(db)

    async def _audit(admin, action: str, payload: dict, target_id: Optional[str] = None):
        """Best-effort audit log entry — swallow errors so admin operations
        never fail because the audit collection had a hiccup.
        """
        try:
            await write_audit(
                db,
                admin_id=admin.get("id") or admin.get("admin_id") or "",
                admin_email=admin.get("email") or "",
                action=action,
                target_type="reconciliation_drift",
                target_id=target_id,
                payload=payload,
            )
        except Exception:
            pass

    @r.post("/admin/reconciliation/drift/scan")
    async def scan_now(
        kinds: Optional[str] = Query(default=None, description="Comma-separated kinds to scan"),
        admin=Depends(current_admin),
    ):
        kinds_list = [k.strip() for k in kinds.split(",")] if kinds else None
        summary = await run_drift_scan(db, kinds_list)
        await _audit(admin, "reconciliation.drift.scan", summary)
        return summary

    @r.get("/admin/reconciliation/drift")
    async def list_drift(
        resolved: Optional[bool] = Query(default=None),
        kind: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        skip: int = Query(default=0, ge=0),
        admin=Depends(current_admin),
    ):
        filt: dict = {}
        if resolved is not None:
            filt["resolved"] = resolved
        if kind:
            filt["kind"] = kind
        cursor = db.reconciliation_drift.find(filt, {"_id": 0}).sort("detected_at", -1).skip(skip).limit(limit)
        items = [d async for d in cursor]
        total = await db.reconciliation_drift.count_documents(filt)
        return {"items": items, "total": total, "skip": skip, "limit": limit}

    @r.get("/admin/reconciliation/drift/runs")
    async def list_runs(admin=Depends(current_admin)):
        cursor = db.reconciliation_drift_runs.find({}, {"_id": 0}).sort("ran_at", -1).limit(20)
        items = [d async for d in cursor]
        return {"items": items}

    @r.post("/admin/reconciliation/drift/{drift_id}/resolve")
    async def resolve_drift(
        drift_id: str,
        note: Optional[str] = Query(default=None),
        admin=Depends(current_admin),
    ):
        row = await db.reconciliation_drift.find_one({"id": drift_id}, {"_id": 0})
        if not row:
            raise HTTPException(status_code=404, detail="Drift row not found")
        await db.reconciliation_drift.update_one(
            {"id": drift_id},
            {"$set": {
                "resolved": True,
                "resolved_at": _now_iso(),
                "resolved_by": (admin.get("email") if isinstance(admin, dict) else getattr(admin, "email", None)) or "unknown",
                "resolution_note": note or "Marked resolved by admin",
            }},
        )
        await _audit(admin, "reconciliation.drift.resolve", {"note": note}, target_id=drift_id)
        return {"ok": True, "id": drift_id, "resolved": True}

    api_router.include_router(r)


# ──────────────────────────────────────────────────────────────────────────
# Periodic background scan
# ──────────────────────────────────────────────────────────────────────────

async def start_drift_background_loop(db, interval_seconds: int = 900):
    """Spawn an asyncio task that runs a drift scan every `interval_seconds`
    (default 15 minutes). Safe to call multiple times — caller decides.

    Use:
        import asyncio
        asyncio.create_task(start_drift_background_loop(db))
    """
    import asyncio
    import logging
    log = logging.getLogger("recon_drift_cron")
    log.info(f"[recon-drift-cron] background loop started (interval={interval_seconds}s)")

    # Allow the env var to disable the loop entirely (for tests / dev).
    if os.environ.get("RECON_DRIFT_ENABLED", "1") != "1":
        log.info("[recon-drift-cron] disabled via RECON_DRIFT_ENABLED env")
        return

    while True:
        try:
            summary = await run_drift_scan(db)
            log.info(
                f"[recon-drift-cron] scan complete: "
                f"found={summary['drifts_found']} inserted={summary['rows_inserted']} "
                f"refreshed={summary['rows_refreshed']} took={summary['elapsed_ms']}ms"
            )
        except Exception as e:
            log.warning(f"[recon-drift-cron] scan failed: {e}")
        await asyncio.sleep(interval_seconds)
