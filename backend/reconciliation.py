"""Stripe Reconciliation (P1 — Phase G1).

Tracks merchant spend vs. funds collected for each group's virtual card. When
the group is settled (card is disabled / drained), any leftover funds are:

  • If `credit_contributors_enabled` is ON → credited back to each contributor's
    SquadPay wallet, proportional to what they contributed.
  • Else → moved to the "Master Account" ledger (a virtual account owned by the
    business). The master account log is visible in the Admin Dashboard.

Every reconciliation event is logged in `db.reconciliations` with full audit
trail (group, lead, card, amounts, merchant, timestamps).

Triggers:
  AUTO   — on `issuing_transaction.created` webhook, AFTER the transaction is
           recorded (only when the merchant settlement is detected as final
           OR when the card is disabled).
  MANUAL — Admin Dashboard "Reconcile" button (per-group + per-card).

Public API:
  ensure_reconciliation_settings(db)         — seed defaults (idempotent)
  reconcile_group(db, group_id, source)      — run reconciliation for a single group
  list_reconciliations(db, ...)              — for admin listing/filter
  list_master_account(db, ...)               — master account log + balance

Schema additions:
  app_settings.integrations.reconciliation:
      { credit_contributors_enabled: bool, auto_disable_card: bool,
        master_account_id: str, updated_at, updated_by }
  collection: reconciliations
      { id, group_id, group_title, lead_id, lead_name, card_id, source,
        amount_collected, amount_spent, leftover, action,
        master_account_entry_id?, contributor_credits?: [{user_id, name, amount, credit_id}],
        merchant_summary, transactions_count, status, created_at, created_by }
  collection: master_account_ledger
      { id, group_id, group_title, lead_id, lead_name, card_id,
        amount, type ("leftover_in" | "manual_adjust"), reconciliation_id?,
        balance_after, note, created_at, created_by }
"""
from __future__ import annotations
import datetime as dt
import logging
import uuid
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


DEFAULT_RECONCILIATION = {
    "credit_contributors_enabled": False,
    "auto_disable_card": True,
    "master_account_id": "MASTER_SQUADPAY",
    "updated_at": None,
    "updated_by": None,
}


async def ensure_reconciliation_settings(db) -> dict:
    """Seed reconciliation settings inside app_settings.integrations.reconciliation."""
    rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0})
    if not rec:
        rec = {"key": "integrations", "reconciliation": DEFAULT_RECONCILIATION.copy()}
        await db.app_settings.insert_one(rec.copy())
        return rec["reconciliation"]
    if "reconciliation" not in rec or not rec["reconciliation"]:
        await db.app_settings.update_one(
            {"key": "integrations"},
            {"$set": {"reconciliation": DEFAULT_RECONCILIATION.copy()}},
            upsert=True,
        )
        return DEFAULT_RECONCILIATION.copy()
    # Forward-compat: add any missing keys
    cur = rec["reconciliation"]
    patched = False
    for k, v in DEFAULT_RECONCILIATION.items():
        if k not in cur:
            cur[k] = v
            patched = True
    if patched:
        await db.app_settings.update_one(
            {"key": "integrations"}, {"$set": {"reconciliation": cur}}, upsert=True
        )
    return cur


async def get_reconciliation_settings(db) -> dict:
    rec = await db.app_settings.find_one({"key": "integrations"}, {"_id": 0}) or {}
    return rec.get("reconciliation") or DEFAULT_RECONCILIATION.copy()


async def get_master_account_balance(db, master_id: str = "MASTER_SQUADPAY") -> float:
    """Sum of all entries in master_account_ledger for the given master account."""
    cursor = db.master_account_ledger.find(
        {"master_account_id": master_id}, {"_id": 0, "amount": 1}
    )
    rows = await cursor.to_list(length=None)
    return round(sum(float(r.get("amount") or 0) for r in rows), 2)


def _summarize_merchant(transactions: list) -> dict:
    """Pick a representative merchant from the transaction list (most recent)."""
    if not transactions:
        return {"name": None, "category": None, "city": None}
    last = transactions[-1]
    return {
        "name": last.get("merchant_name"),
        "category": last.get("merchant_category"),
        "city": last.get("merchant_city"),
    }


async def reconcile_group(
    db,
    group_id: str,
    source: str = "auto",
    actor_email: Optional[str] = None,
) -> dict:
    """Run reconciliation for a single group. Idempotent.

    Returns the reconciliation record that was created (or the existing one if
    a final reconciliation has already been recorded).
    """
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise ValueError(f"Group {group_id} not found")

    settings = await get_reconciliation_settings(db)
    vc = group.get("virtual_card") or {}
    card_id = vc.get("stripe_card_id")
    if not card_id:
        raise ValueError("Group has no Stripe Issuing card — nothing to reconcile.")

    # --- Compute amounts
    contributions = group.get("contributions") or []
    amount_collected = round(sum(float(c.get("amount") or 0) for c in contributions), 2)
    amount_spent = round(float(vc.get("spent") or 0.0), 2)
    leftover = round(max(0.0, amount_collected - amount_spent), 2)

    # --- Idempotency: if already finalized for this group, return existing
    existing_final = await db.reconciliations.find_one(
        {"group_id": group_id, "status": "finalized"}, {"_id": 0}
    )
    if existing_final:
        return existing_final

    lead = await db.users.find_one({"id": group.get("lead_id")}, {"_id": 0}) if group.get("lead_id") else None

    # --- Build reconciliation record (status: pending until action completes)
    rec_id = _new_id("rcn_")
    rec = {
        "id": rec_id,
        "group_id": group_id,
        "group_title": group.get("title") or "Group Bill",
        "lead_id": group.get("lead_id"),
        "lead_name": (lead or {}).get("name"),
        "lead_phone": (lead or {}).get("phone"),
        "card_id": card_id,
        "source": source,                           # auto | manual
        "amount_collected": amount_collected,
        "amount_spent": amount_spent,
        "leftover": leftover,
        "action": None,                             # set below
        "master_account_entry_id": None,
        "contributor_credits": [],
        "merchant_summary": _summarize_merchant(vc.get("transactions") or []),
        "transactions_count": len(vc.get("transactions") or []),
        "status": "pending",
        "created_at": _now(),
        "created_by": actor_email or "system",
    }

    # --- No leftover (or tiny rounding noise) → just log a "no_leftover" record
    if leftover < 0.01:
        rec["action"] = "no_leftover"
        rec["status"] = "finalized"
        await db.reconciliations.insert_one(rec.copy())
        return rec

    # --- Decide action
    credit_mode = bool(settings.get("credit_contributors_enabled"))
    if credit_mode:
        rec["action"] = "credit_contributors"
        # Distribute leftover proportionally by contribution amount
        total = amount_collected
        contrib_credits = []
        running = 0.0
        # Aggregate contributions by user_id (one credit row per user)
        per_user: dict = {}
        for c in contributions:
            uid = c.get("user_id")
            if not uid:
                continue
            per_user[uid] = round(per_user.get(uid, 0.0) + float(c.get("amount") or 0), 2)

        items = list(per_user.items())
        for idx, (uid, paid) in enumerate(items):
            share = round(leftover * (paid / total), 2) if total > 0 else 0.0
            # Last contributor takes the rounding remainder
            if idx == len(items) - 1:
                share = round(leftover - running, 2)
            running = round(running + share, 2)
            if share <= 0.001:
                continue
            user = await db.users.find_one({"id": uid}, {"_id": 0, "name": 1})
            credit_id = _new_id("cr_")
            await db.credits.insert_one({
                "id": credit_id,
                "user_id": uid,
                "amount": share,
                "consumed_amount": 0.0,
                "kind": "reconciliation_refund",
                "status": "active",
                "note": f"Refund of leftover from group '{rec['group_title']}'.",
                "source_group_id": group_id,
                "source_reconciliation_id": rec_id,
                "created_at": _now(),
            })
            contrib_credits.append({
                "user_id": uid,
                "name": (user or {}).get("name"),
                "amount": share,
                "credit_id": credit_id,
            })
        rec["contributor_credits"] = contrib_credits
    else:
        rec["action"] = "moved_to_master"
        master_id = settings.get("master_account_id") or "MASTER_SQUADPAY"
        prev_balance = await get_master_account_balance(db, master_id)
        new_balance = round(prev_balance + leftover, 2)
        ledger_id = _new_id("mae_")
        await db.master_account_ledger.insert_one({
            "id": ledger_id,
            "master_account_id": master_id,
            "type": "leftover_in",
            "group_id": group_id,
            "group_title": rec["group_title"],
            "lead_id": rec["lead_id"],
            "lead_name": rec["lead_name"],
            "card_id": card_id,
            "amount": leftover,
            "balance_after": new_balance,
            "reconciliation_id": rec_id,
            "note": f"Leftover from group '{rec['group_title']}'",
            "created_at": _now(),
            "created_by": actor_email or "system",
        })
        rec["master_account_entry_id"] = ledger_id
        rec["master_balance_after"] = new_balance

    rec["status"] = "finalized"
    await db.reconciliations.insert_one(rec.copy())

    # --- Auto-disable card if enabled (after reconciliation)
    if settings.get("auto_disable_card", True) and vc.get("status") == "active":
        try:
            from issuing import disable_group_card
            await disable_group_card(db, group_id)
        except Exception as e:
            logger.warning(f"[reconcile] auto-disable card failed for {group_id}: {e}")

    return rec


async def maybe_auto_reconcile(db, group_id: str) -> Optional[dict]:
    """Called after every issuing transaction. Reconciles only when the group
    appears to be fully settled (spent ≥ collected − 0.01 OR card already disabled).

    Returns the reconciliation record if one was created, else None.
    """
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        return None
    vc = group.get("virtual_card") or {}
    if not vc.get("stripe_card_id"):
        return None
    contributions = group.get("contributions") or []
    collected = sum(float(c.get("amount") or 0) for c in contributions)
    spent = float(vc.get("spent") or 0.0)
    card_status = vc.get("status")

    # Trigger when card is inactive OR spent has caught up (within 1 cent) to collected.
    if card_status != "inactive" and spent + 0.01 < collected:
        return None  # still active, more spend may come

    # Already finalized?
    existing = await db.reconciliations.find_one(
        {"group_id": group_id, "status": "finalized"}, {"_id": 0}
    )
    if existing:
        return None

    try:
        return await reconcile_group(db, group_id, source="auto", actor_email="system")
    except Exception as e:
        logger.warning(f"[reconcile] auto reconcile failed for {group_id}: {e}")
        return None


async def list_reconciliations(
    db, *, q: Optional[str] = None, action: Optional[str] = None,
    limit: int = 50, skip: int = 0,
) -> dict:
    flt: dict = {}
    if action:
        flt["action"] = action
    if q:
        flt["$or"] = [
            {"group_title": {"$regex": q, "$options": "i"}},
            {"lead_name": {"$regex": q, "$options": "i"}},
            {"card_id": {"$regex": q, "$options": "i"}},
            {"group_id": {"$regex": q, "$options": "i"}},
        ]
    total = await db.reconciliations.count_documents(flt)
    cursor = db.reconciliations.find(flt, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
    items = await cursor.to_list(length=limit)
    return {"items": items, "total": total, "skip": skip, "limit": limit}


async def get_reconciliation_detail(db, rec_id: str) -> Optional[dict]:
    return await db.reconciliations.find_one({"id": rec_id}, {"_id": 0})


async def list_master_account(
    db, *, master_id: str = "MASTER_SQUADPAY", limit: int = 50, skip: int = 0,
) -> dict:
    flt = {"master_account_id": master_id}
    total = await db.master_account_ledger.count_documents(flt)
    cursor = db.master_account_ledger.find(flt, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
    items = await cursor.to_list(length=limit)
    balance = await get_master_account_balance(db, master_id)
    return {"items": items, "total": total, "balance": balance, "skip": skip, "limit": limit}
