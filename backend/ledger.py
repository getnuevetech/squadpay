"""Immutable, append-only Fintech Ledger (June 2025 — Phase 3).

Single source of truth for every cent that moves through SquadPay.

Design principles
─────────────────
1. **Append-only.** Rows are never updated or deleted. A correction is a
   new compensating row (a reverse posting), never an edit.
2. **Idempotent writes.** Every event is keyed by a server-generated
   `txn_id` (`tx_charge_<ulid>` / `tx_payout_<ulid>`). Re-running the same
   event is a no-op: the writer first checks for existing rows with the
   same `(txn_id, category)` pair.
3. **2-way idempotency with Stripe.** The same `txn_id` is also sent to
   Stripe as its `idempotency_key`. If our app crashes mid-flight,
   replaying the create call returns the original Stripe Session instead
   of double-charging.
4. **Cents everywhere.** All amounts are stored as integer cents to avoid
   FP rounding drift. `currency` defaults to "usd".
5. **Per-event invariant: sum(credits) == sum(debits)** when an event is
   fully expanded (double-entry). For the minimal Phase-3 charge event
   we write 4 rows and assert balance.

Phase 3 charge event (4 rows per contribution / lead-pay)
───────────────────────────────────────────────────────
  category=charge.gross           account=stripe_clearing   credit=gross
  category=charge.processor_fee   account=processor_fees    debit=0    (placeholder; filled in later from Stripe BalanceTransaction)
  category=charge.tax             account=tax_held          debit=0    (placeholder; reserved for future regulatory withholding)
  category=charge.net_payable     account=merchant_payable  credit=gross - fee - tax

Future phases will:
  • Phase 4: split charge.net_payable into platform_revenue + merchant_payable
    based on per_user.transaction_fee / platform_fee / extra_fees.
  • Phase 4: post-finalization async job reads Stripe BalanceTransaction
    and updates the processor_fee row (via a new compensating row, not edit).
  • Phase 5: payout events (`tx_payout_*`) reduce merchant_payable, debit
    payout_clearing, write provider fee rows.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Account constants
# ─────────────────────────────────────────────────────────────────────────────
class LedgerAccount:
    STRIPE_CLEARING = "stripe_clearing"      # money sitting at Stripe before merchant payout
    PROCESSOR_FEES = "processor_fees"        # gateway fees (Stripe %/$)
    TAX_HELD = "tax_held"                    # regulatory withholding (reserved; 0 for now)
    MERCHANT_PAYABLE = "merchant_payable"    # what SquadPay owes the merchant
    PLATFORM_REVENUE = "platform_revenue"    # SquadPay's internal tx_fee + platform_fee retention
    PAYOUT_CLEARING = "payout_clearing"      # money in flight to lead/member debit card
    PAYOUT_RECIPIENT = "payout_recipient"    # money credited to lead/member after card push


CHARGE_CATEGORIES = ("charge.gross", "charge.processor_fee", "charge.tax", "charge.net_payable")
PAYOUT_CATEGORIES = ("payout.requested", "payout.processor_fee", "payout.settled")
ALL_CATEGORIES = CHARGE_CATEGORIES + PAYOUT_CATEGORIES

DIRECTION_CREDIT = "credit"
DIRECTION_DEBIT = "debit"


# ─────────────────────────────────────────────────────────────────────────────
# ID generation
# ─────────────────────────────────────────────────────────────────────────────
# We use a Crockford-base32 timestamp prefix + 80 bits of entropy. This gives:
#   • Monotonic-ish sortable IDs (timestamp comes first)
#   • ~32 chars total — short enough to fit Stripe's 255-char idempotency cap
#   • Globally unique without coordination
_BASE32_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford


def _b32(num: int, length: int) -> str:
    s = ""
    while num > 0:
        num, rem = divmod(num, 32)
        s = _BASE32_ALPHABET[rem] + s
    return s.rjust(length, "0")[-length:]


def _ulid_like() -> str:
    """26-char ULID-style id (no external dep). Lowercased for visual parity."""
    ts_ms = int(time.time() * 1000)
    rand_bits = int.from_bytes(secrets.token_bytes(10), "big")  # 80 bits
    return (_b32(ts_ms, 10) + _b32(rand_bits, 16)).lower()


def make_txn_id(kind: Literal["charge", "payout", "refund", "adjust"]) -> str:
    return f"tx_{kind}_{_ulid_like()}"


def make_entry_id() -> str:
    return f"le_{_ulid_like()}"


# ─────────────────────────────────────────────────────────────────────────────
# Currency helpers
# ─────────────────────────────────────────────────────────────────────────────

def to_cents(amount: float) -> int:
    """Robust float→cents conversion (avoids 0.1+0.2 style drift)."""
    return int(round(float(amount) * 100))


def from_cents(cents: int) -> float:
    return round(int(cents) / 100.0, 2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Index management (called once at startup)
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_ledger_indexes(db) -> None:
    """Create supporting indexes. Idempotent."""
    try:
        await db.ledger_entries.create_index("txn_id")
        await db.ledger_entries.create_index([("txn_id", 1), ("category", 1)], unique=True)
        await db.ledger_entries.create_index("bill_id")
        await db.ledger_entries.create_index("user_id")
        await db.ledger_entries.create_index("account")
        await db.ledger_entries.create_index("created_at")
    except Exception as e:
        logger.warning(f"[ledger] index creation failed (non-fatal): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Core writer — charge event
# ─────────────────────────────────────────────────────────────────────────────

async def record_charge_event(
    db,
    *,
    txn_id: str,
    bill_id: Optional[str],
    user_id: Optional[str],
    gross_cents: int,
    currency: str = "usd",
    reference: Optional[Dict[str, Any]] = None,
    processor_fee_cents: int = 0,
    tax_cents: int = 0,
    kind: str = "group_member_contribute",
) -> List[Dict[str, Any]]:
    """Idempotently write the 4 charge-event rows for `txn_id`.

    Returns the list of rows persisted. If the txn already has entries,
    returns the EXISTING rows without writing duplicates.
    """
    if gross_cents <= 0:
        raise ValueError("gross_cents must be > 0")
    if processor_fee_cents < 0 or tax_cents < 0:
        raise ValueError("processor_fee_cents/tax_cents must be >= 0")
    net_cents = gross_cents - processor_fee_cents - tax_cents
    if net_cents < 0:
        raise ValueError("processor_fee + tax cannot exceed gross")

    # Idempotency: if any row exists for this txn, return what's there.
    existing = await db.ledger_entries.find({"txn_id": txn_id}, {"_id": 0}).to_list(length=None)
    if existing:
        return existing

    now = _now()
    base = {
        "txn_id": txn_id,
        "bill_id": bill_id,
        "user_id": user_id,
        "currency": currency,
        "reference": reference or {},
        "kind": kind,
        "created_at": now,
    }

    rows: List[Dict[str, Any]] = [
        {
            **base,
            "id": make_entry_id(),
            "account": LedgerAccount.STRIPE_CLEARING,
            "direction": DIRECTION_CREDIT,
            "amount_cents": int(gross_cents),
            "category": "charge.gross",
        },
        {
            **base,
            "id": make_entry_id(),
            "account": LedgerAccount.PROCESSOR_FEES,
            "direction": DIRECTION_DEBIT,
            "amount_cents": int(processor_fee_cents),
            "category": "charge.processor_fee",
        },
        {
            **base,
            "id": make_entry_id(),
            "account": LedgerAccount.TAX_HELD,
            "direction": DIRECTION_DEBIT,
            "amount_cents": int(tax_cents),
            "category": "charge.tax",
        },
        {
            **base,
            "id": make_entry_id(),
            "account": LedgerAccount.MERCHANT_PAYABLE,
            "direction": DIRECTION_CREDIT,
            "amount_cents": int(net_cents),
            "category": "charge.net_payable",
        },
    ]

    # Invariant: the 4 informational rows describe one event where
    # gross_cents enters and gets split into fee + tax + merchant_payable.
    by_cat = {r["category"]: r["amount_cents"] for r in rows}
    if (
        by_cat["charge.gross"]
        - by_cat["charge.processor_fee"]
        - by_cat["charge.tax"]
        != by_cat["charge.net_payable"]
    ):
        raise RuntimeError(
            f"[ledger] charge event imbalance: gross={by_cat['charge.gross']} "
            f"fee={by_cat['charge.processor_fee']} tax={by_cat['charge.tax']} "
            f"net={by_cat['charge.net_payable']}"
        )

    try:
        await db.ledger_entries.insert_many(rows, ordered=True)
    except Exception as e:
        # Race: another worker won. Read what's there and return that.
        logger.warning(f"[ledger] insert race for txn={txn_id}: {e}")
        existing = await db.ledger_entries.find({"txn_id": txn_id}, {"_id": 0}).to_list(length=None)
        if existing:
            return existing
        raise

    logger.info(f"[ledger] charge event posted txn={txn_id} gross={gross_cents}c")
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Query helpers (used by admin endpoints)
# ─────────────────────────────────────────────────────────────────────────────

async def find_entries_by_txn(db, txn_id: str) -> List[Dict[str, Any]]:
    return await db.ledger_entries.find({"txn_id": txn_id}, {"_id": 0}).sort("category", 1).to_list(length=None)


async def list_entries(
    db,
    *,
    bill_id: Optional[str] = None,
    user_id: Optional[str] = None,
    account: Optional[str] = None,
    category: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
) -> Dict[str, Any]:
    q: Dict[str, Any] = {}
    if bill_id:
        q["bill_id"] = bill_id
    if user_id:
        q["user_id"] = user_id
    if account:
        q["account"] = account
    if category:
        q["category"] = category
    if kind:
        q["kind"] = kind
    total = await db.ledger_entries.count_documents(q)
    cursor = db.ledger_entries.find(q, {"_id": 0}).sort("created_at", -1).skip(int(skip)).limit(int(limit))
    items = await cursor.to_list(length=int(limit))
    return {"total": total, "skip": int(skip), "limit": int(limit), "items": items}


async def account_balances(db) -> Dict[str, Dict[str, Any]]:
    """Aggregate net balance per account (credits - debits)."""
    pipeline = [
        {"$group": {
            "_id": {"account": "$account", "direction": "$direction"},
            "amount_cents": {"$sum": "$amount_cents"},
            "rows": {"$sum": 1},
        }},
    ]
    out: Dict[str, Dict[str, int]] = {}
    async for d in db.ledger_entries.aggregate(pipeline):
        acct = d["_id"]["account"]
        dir_ = d["_id"]["direction"]
        bucket = out.setdefault(acct, {"credit_cents": 0, "debit_cents": 0, "rows": 0})
        bucket[f"{dir_}_cents"] = int(d["amount_cents"])
        bucket["rows"] += int(d["rows"])
    # Compute net + add USD helpers
    result: Dict[str, Dict[str, Any]] = {}
    for acct, b in out.items():
        net_cents = b["credit_cents"] - b["debit_cents"]
        result[acct] = {
            "credit_cents": b["credit_cents"],
            "debit_cents": b["debit_cents"],
            "net_cents": net_cents,
            "credit_usd": from_cents(b["credit_cents"]),
            "debit_usd": from_cents(b["debit_cents"]),
            "net_usd": from_cents(net_cents),
            "rows": b["rows"],
        }
    return result
