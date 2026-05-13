"""Admin ledger query endpoints (June 2025 — Phase 3).

Gated by the `income_fees` module — same scope as the existing Income & Fees
admin page. Read-only.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from ledger import (
    list_entries,
    find_entries_by_txn,
    account_balances,
    ALL_CATEGORIES,
)


def attach_ledger_routes(router: APIRouter, db, get_current_admin):
    from fastapi import Depends as _D
    from admin_modules import require_module

    _gate = require_module("income_fees")

    @router.get("/admin/ledger")
    async def admin_ledger_list(
        bill_id: Optional[str] = Query(None),
        user_id: Optional[str] = Query(None),
        account: Optional[str] = Query(None),
        category: Optional[str] = Query(None),
        kind: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=500),
        skip: int = Query(0, ge=0),
        _admin=_D(get_current_admin),
        _check=_D(_gate),
    ):
        if category and category not in ALL_CATEGORIES:
            raise HTTPException(400, f"Unknown category. Allowed: {', '.join(ALL_CATEGORIES)}")
        return await list_entries(
            db,
            bill_id=bill_id,
            user_id=user_id,
            account=account,
            category=category,
            kind=kind,
            limit=limit,
            skip=skip,
        )

    @router.get("/admin/ledger/summary")
    async def admin_ledger_summary(
        _admin=_D(get_current_admin),
        _check=_D(_gate),
    ):
        balances = await account_balances(db)
        return {"accounts": balances}

    @router.get("/admin/ledger/txn/{txn_id}")
    async def admin_ledger_by_txn(
        txn_id: str,
        _admin=_D(get_current_admin),
        _check=_D(_gate),
    ):
        rows = await find_entries_by_txn(db, txn_id)
        if not rows:
            raise HTTPException(404, f"No ledger entries for txn '{txn_id}'")
        return {"txn_id": txn_id, "entries": rows, "count": len(rows)}
